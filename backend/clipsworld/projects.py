"""Projects: one imported video, its transcript, and its clips."""
import json
import shutil
import threading
import time
import uuid
from pathlib import Path

from . import ai, captions, effects as fx, highlights, media, originality, render, transcribe, ytdl
from . import settings as settings_mod
from .paths import projects_dir

_locks: dict = {}
PLAYABLE_EXT = {".mp4", ".m4v", ".mov", ".webm"}
PLAYABLE_CODECS = {"h264", "vp8", "vp9", "av1"}


def _lock(pid):
    return _locks.setdefault(pid, threading.RLock())


def pdir(pid: str) -> Path:
    return projects_dir() / pid


def load(pid: str) -> dict:
    f = pdir(pid) / "project.json"
    if not f.exists():
        raise KeyError(pid)
    return json.loads(f.read_text(encoding="utf-8"))


def save(p: dict):
    with _lock(p["id"]):
        p["updated"] = int(time.time())
        f = pdir(p["id"]) / "project.json"
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
        tmp.replace(f)


def summary(p: dict) -> dict:
    return {k: p.get(k) for k in ("id", "name", "created", "updated", "status", "stage", "error",
                                  "source_kind", "info", "warning")} | {
        "clip_count": len(p.get("clips", [])),
        "export_count": sum(len(c.get("exports", [])) for c in p.get("clips", [])),
        "thumb": bool(p.get("cover")),
    }


_summary_cache: dict = {}


def list_all() -> list:
    out = []
    for d in projects_dir().iterdir():
        f = d / "project.json"
        try:
            m = f.stat().st_mtime
            hit = _summary_cache.get(d.name)
            if not hit or hit[0] != m:
                hit = (m, summary(load(d.name)))
                _summary_cache[d.name] = hit
            out.append(hit[1])
        except Exception:
            continue
    return sorted(out, key=lambda p: -(p.get("updated") or 0))


def public(p: dict) -> dict:
    """Full project for the UI, without the big transcript word lists."""
    q = dict(p)
    tr = p.get("transcript")
    if tr:
        q["transcript"] = {k: v for k, v in tr.items() if k != "segments"}
        q["transcript"]["segments"] = [{"start": s["start"], "end": s["end"], "text": s["text"]}
                                       for s in tr["segments"]]
    q.pop("loudness", None)
    for c in q.get("clips", []):
        _defaults(c)
    return q


def create(source: str, name: str | None = None) -> dict:
    pid = uuid.uuid4().hex[:10]
    d = pdir(pid)
    d.mkdir(parents=True)
    is_url = source.strip().lower().startswith(("http://", "https://"))
    p = {
        "id": pid, "name": name or ("New video" if is_url else Path(source).stem),
        "created": int(time.time()), "status": "queued", "stage": "Waiting…",
        "source_kind": "url" if is_url else "file",
        "source_url": source.strip() if is_url else None,
        "source_path": None if is_url else source,
        "clips": [],
    }
    save(p)
    return p


def delete(pid: str):
    shutil.rmtree(pdir(pid), ignore_errors=True)


# ---------------------------------------------------------------- pipeline

def _set(p, **kw):
    p.update(kw)
    save(p)


def analyze(job, pid: str, from_stage: str = "start"):
    s = settings_mod.load()
    p = load(pid)
    d = pdir(pid)
    try:
        if from_stage == "start":
            if p["source_kind"] == "url" and not (p.get("source_path") and Path(p["source_path"]).exists()):
                _set(p, status="working", stage="Downloading video…")
                res = ytdl.download(job, p["source_url"], d)
                _set(p, source_path=res["path"], name=res["title"][:80], uploader=res["uploader"])
            src = p["source_path"]
            if not Path(src).exists():
                raise RuntimeError(f"Video file not found: {src}")
            job.update(progress=0.0, stage="Reading video…")
            info = media.probe(src)
            _set(p, info=info, status="working", stage="Extracting audio…")
            wav = d / "audio.wav"
            media.extract_audio(src, wav, info["duration"], lambda x: job.update(progress=0.05 * x, stage="Extracting audio…"))
            job.update(progress=0.06, stage="Measuring loudness…")
            loud = media.loudness_curve(wav)
            cover = d / "cover.jpg"
            media.thumbnail(src, min(info["duration"] * 0.1, 30), cover)
            _set(p, loudness=loud, cover=cover.exists())

            class Sub:  # map transcription progress into 8%..80%
                def update(self, progress=None, stage=None):
                    job.update(None if progress is None else 0.08 + 0.72 * progress, stage)

            _set(p, stage="Transcribing…")
            tr = transcribe.transcribe(Sub(), str(wav), info["duration"], s)
            _set(p, transcript=tr)
        find_clips(job, p, s, base=0.8 if from_stage == "start" else 0.0)
        p = load(pid)
        info = p["info"]
        need_preview = (Path(p["source_path"]).suffix.lower() not in PLAYABLE_EXT
                        or info.get("vcodec") not in PLAYABLE_CODECS)
        has_preview = (d / "preview.mp4").exists()
        # the project is usable right away; the playable preview copy is made after
        _set(p, status="ready", stage="Ready", error=None,
             preview_state="making" if need_preview and not has_preview else ("ready" if has_preview else "not_needed"))
        if need_preview and not has_preview:
            tmp = d / "preview.tmp.mp4"
            try:
                media.make_preview(p["source_path"], tmp, info["duration"],
                                   lambda x: job.update(progress=0.92 + 0.08 * x, stage="Making a playable preview…"))
                tmp.replace(d / "preview.mp4")
                p = load(pid)
                _set(p, preview_state="ready")
            except Exception:
                tmp.unlink(missing_ok=True)
                p = load(pid)
                _set(p, preview_state="failed")
        return {"project_id": pid, "clips": len(load(pid)["clips"])}
    except Exception as e:
        p = load(pid)
        _set(p, status="error", stage="Failed", error=str(e))
        raise


def find_clips(job, p: dict, s: dict, base: float = 0.0):
    tr = p.get("transcript")
    if not tr:
        raise RuntimeError("Transcribe the video first.")
    segs, loud, dur = tr["segments"], p.get("loudness") or [], p["info"]["duration"]
    warning = None
    span = 1.0 - base
    if not segs:
        found = []
        warning = "No speech was found in this video."
    elif s.get("claude_api_key"):
        class Sub:
            def update(self, progress=None, stage=None):
                job.update(None if progress is None else base + span * 0.9 * progress, stage)
        try:
            found = ai.find_clips(Sub(), segs, loud, dur, s)
        except ai.AIError as e:
            warning = f"Claude couldn't pick clips ({e}). Used the free offline finder instead."
            found = highlights.local_clips(segs, loud, dur, s)
    else:
        job.update(stage="Finding the best moments (offline)…")
        found = highlights.local_clips(segs, loud, dur, s)
        warning = "Tip: add your Claude API key in Settings for much smarter clip picks."
    p = load(p["id"])
    keep = [c for c in p.get("clips", []) if c.get("pinned") or c.get("exports")]
    for k in keep:  # transcript may be new: refresh their captions too
        _defaults(k)
        if not any(q.get("edited") for q in k["captions"].get("cues", [])):
            rebuild_cues(p, k)
    fresh = [c for c in found if all(c["end"] <= k["start"] or c["start"] >= k["end"] for k in keep)]
    lang = s.get("caption_language", "hinglish")
    made = []
    for i, c in enumerate(fresh):
        if s.get("claude_api_key") and lang != "original":
            job.update(stage=f"Writing {'Hinglish' if lang == 'hinglish' else lang.upper()} captions… {i + 1}/{len(fresh)}")
        made.append(new_clip(p, c))
    clips = keep + made
    for i, c in enumerate(clips):
        job.update(progress=base + span * (0.9 + 0.1 * i / max(1, len(clips))), stage="Making thumbnails…")
        _thumb(p, c)
    _set(p, clips=clips, warning=warning)


def new_clip(p: dict, c: dict) -> dict:
    clip = {
        "id": uuid.uuid4().hex[:6], "start": c["start"], "end": c["end"],
        "title": c.get("title") or "Highlight", "hook": c.get("hook", ""),
        "reason": c.get("reason", ""), "category": c.get("category", "funny"),
        "score": c.get("score", 50), "source": c.get("source", "manual"),
        "layout": {"format": "short", "mode": "blur", "crop_x": 0.5, "zoom": 1.0},
        "captions": {"enabled": True, "style": "hormozi", "position": "bottom", "uppercase": None,
                     "show_hook": bool(c.get("hook")), "language": "original", "cues": []},
        "exports": [],
    }
    _defaults(clip)
    s = settings_mod.load()
    target = s.get("caption_language", "hinglish") if s.get("claude_api_key") else "original"
    rebuild_cues(p, clip, translate=False)
    text = " ".join(q["text"] for q in clip["captions"]["cues"])
    hindi = bool(text) and len(captions.DEVANAGARI.findall(text)) > len(text) * 0.3
    if hindi and target in ("original", "hi"):
        clip["captions"]["style"] = "pop"  # Hindi script: start with a Hindi-friendly font
    clip["captions"]["language"] = target
    rebuild_cues(p, clip)
    return clip


def _defaults(c: dict) -> dict:
    c.setdefault("effects", [])
    c.setdefault("meta", {})
    a = c.setdefault("audio", {})
    a.setdefault("orig_volume", 1.0)
    a.setdefault("vo_volume", 1.0)
    a.setdefault("duck", True)
    a.setdefault("sfx_volume", 1.0)
    a.setdefault("vo_file", None)
    a.setdefault("vo_has_video", False)
    b = a.setdefault("bubble", {})
    b.setdefault("show", True)
    b.setdefault("pos", "top-right")
    b.setdefault("size", 0.34)
    c.setdefault("layout", {}).setdefault("cam", {"x": 0.70, "y": 0.0, "w": 0.30, "h": 0.30})
    c["layout"].setdefault("split", 0.42)
    c["captions"].setdefault("replay_captions", True)
    return c


def _clean_effect(e: dict, L: float) -> dict | None:
    kind = e.get("type")
    if kind not in fx.TYPES:
        return None
    try:
        t = float(e.get("t", 0))
    except (TypeError, ValueError):
        return None
    if not (0 <= t <= L):
        return None
    params = {k: v for k, v in e.items() if k not in ("type", "t", "id")}
    for k in ("dur", "scale", "speed", "strength", "volume", "zoom", "fx", "fy"):
        if k in params:
            try:
                params[k] = float(params[k])
            except (TypeError, ValueError):
                params.pop(k)
    if "sfx" in params and params["sfx"] and not fx.sfx_path(str(params["sfx"])):
        params["sfx"] = None
    out = fx.new_effect(kind, t, **params)
    if e.get("id"):
        out["id"] = str(e["id"])[:12]
    return out


def rebuild_cues(p: dict, clip: dict, translate: bool = True, job=None):
    """Make captions again from the speech, then (if chosen) translate them, e.g. to Hinglish."""
    st = captions.STYLES.get(clip["captions"].get("style", "pop"), captions.STYLES["pop"])
    segs = (p.get("transcript") or {}).get("segments", [])
    clip["captions"]["cues"] = captions.build_cues(segs, clip["start"], clip["end"], st["words"])
    want = clip["captions"].get("language") or "original"
    clip["captions"]["language"] = "original"
    if translate and want != "original":
        apply_translation(clip, want, settings_mod.load(), job)


def apply_translation(clip: dict, target: str, s: dict, job=None) -> bool:
    """Translate the clip's caption lines (and a Hindi hook) with Claude. Returns False if not possible."""
    if target == "original" or not s.get("claude_api_key"):
        return False
    cues = clip["captions"]["cues"]
    hook = clip.get("hook") or ""
    hook_needs = bool(hook) and (target != "hi" and bool(captions.DEVANAGARI.search(hook)) or target == "hi")
    lines = [q["text"] for q in cues] + ([hook] if hook_needs else [])
    if lines:
        try:
            ctx = " · ".join(x for x in (clip.get("title"), clip.get("reason")) if x)
            out = ai.translate_lines(job, lines, target, s, context=ctx[:200])
        except ai.AIError:
            return False
        for q, t in zip(cues, out):
            q["text"] = t.strip() or q["text"]
            captions.respread_words(q)
        if hook_needs:
            clip["hook"] = out[-1].strip() or hook
    clip["captions"]["language"] = target
    return True


def _thumb(p, clip):
    t = pdir(p["id"]) / f"thumb_{clip['id']}.jpg"
    media.thumbnail(p["source_path"], (clip["start"] + clip["end"]) / 2, t, width=360)


class ClipNotFound(KeyError):
    def __str__(self):
        return "This clip no longer exists (the clip list was updated). The list has been refreshed — pick the clip again."


def get_clip(p, cid):
    for c in p["clips"]:
        if c["id"] == cid:
            return c
    raise ClipNotFound(cid)


def analyze_running(pid) -> bool:
    from . import jobs
    return any(j["project_id"] == pid and j["kind"] == "analyze" and j["status"] == "running" for j in jobs.all_jobs())


def update_clip(pid, cid, patch: dict) -> dict:
    with _lock(pid):
        p = load(pid)
        c = get_clip(p, cid)
        dur = p["info"]["duration"]
        retime = False
        for k in ("start", "end"):
            if k in patch:
                v = round(min(dur, max(0.0, float(patch[k]))), 3)
                retime = retime or v != c[k]
                c[k] = v
        if c["end"] - c["start"] < 1:
            c["end"] = min(dur, c["start"] + 1)
        _defaults(c)
        for k in ("title", "hook", "pinned"):
            if k in patch:
                c[k] = patch[k]
        if "layout" in patch:
            lay = dict(patch["layout"])
            if "cam" in lay:
                c["layout"]["cam"] = {**c["layout"].get("cam", {}), **lay.pop("cam")}
            c["layout"].update(lay)
        if "effects" in patch:
            L = c["end"] - c["start"]
            c["effects"] = sorted([x for x in (_clean_effect(e, L) for e in patch["effects"] or []) if x],
                                  key=lambda e: e["t"])
        if "audio" in patch:
            au = dict(patch["audio"])
            au.pop("vo_file", None)
            au.pop("vo_has_video", None)
            if "bubble" in au:
                c["audio"]["bubble"].update(au.pop("bubble"))
            c["audio"].update(au)
        if "meta" in patch:
            c["meta"].update(patch["meta"])
        if "captions" in patch:
            cap = dict(patch["captions"])
            if "cues" in cap:
                cap["cues"] = [captions.respread_words(dict(q)) if q.get("edited") else q for q in cap["cues"]]
            old_style = c["captions"].get("style")
            c["captions"].update(cap)
            if "style" in cap and cap["style"] != old_style \
                    and not any(q.get("edited") for q in c["captions"]["cues"]):
                rebuild_cues(p, c)
        if retime:
            rebuild_cues(p, c)
            _thumb(p, c)
        save(p)
        return c


def add_clip(pid, start, end) -> dict:
    with _lock(pid):
        p = load(pid)
        segs = (p.get("transcript") or {}).get("segments", [])
        c = new_clip(p, {"start": start, "end": end,
                         "title": highlights._title_from(highlights.text_between(segs, start, end)),
                         "source": "manual", "score": 50})
        c["pinned"] = True
        p["clips"].insert(0, c)
        _thumb(p, c)
        save(p)
        return c


def delete_clip(pid, cid):
    with _lock(pid):
        p = load(pid)
        p["clips"] = [c for c in p["clips"] if c["id"] != cid]
        save(p)


def translate_clip(job, pid, cid, target):
    s = settings_mod.load()
    if target != "original" and not s.get("claude_api_key"):
        raise ai.AIError("Add your Claude API key in Settings to translate captions.")
    with _lock(pid):
        p = load(pid)
        c = _defaults(get_clip(p, cid))
        c["captions"]["language"] = "original"
        rebuild_cues(p, c, translate=False)  # always translate from the original words
        if target != "original":
            if not apply_translation(c, target, s, job):
                raise ai.AIError("Claude couldn't translate the captions right now. Try again in a moment.")
        save(p)
        return c


def export(job, pid, cids: list):
    s = settings_mod.load()
    results = []
    for i, cid in enumerate(cids):
        p = load(pid)
        c = _defaults(get_clip(p, cid))
        if not (c.get("meta") or {}).get("title"):
            try:
                gen_metadata(job, pid, cid, c["captions"].get("language", "original"))
                p = load(pid)
                c = _defaults(get_clip(p, cid))
            except Exception:
                pass
        res = render.export_clip(job, p, c, s, (i / len(cids), (i + 1) / len(cids)))
        with _lock(pid):
            p = load(pid)
            get_clip(p, cid).setdefault("exports", []).append(res)
            save(p)
        results.append(res)
    return {"files": results}


def update_project(pid, patch: dict) -> dict:
    with _lock(pid):
        p = load(pid)
        for k in ("name", "credit"):
            if k in patch:
                p[k] = str(patch[k])[:120]
        save(p)
        return p


def preview(job, pid, cid):
    s = settings_mod.load()
    p = load(pid)
    c = _defaults(get_clip(p, cid))
    out = pdir(pid) / f"preview_{cid}.mp4"
    res = render.export_clip(job, p, c, s, preview=True, preview_path=out)
    res["version"] = int(time.time())
    return res


def save_voiceover(pid, cid, data: bytes, ext: str, has_video: bool) -> dict:
    with _lock(pid):
        p = load(pid)
        c = _defaults(get_clip(p, cid))
        old = c["audio"].get("vo_file")
        ext = ext if ext in ("webm", "mp4", "m4a", "mp3", "wav", "ogg", "mkv", "mov") else "webm"
        f = pdir(pid) / f"vo_{cid}_{int(time.time())}.{ext}"
        f.write_bytes(data)
        if old and Path(old).exists() and Path(old).parent == pdir(pid):
            Path(old).unlink(missing_ok=True)
        c["audio"]["vo_file"] = str(f)
        c["audio"]["vo_has_video"] = bool(has_video)
        save(p)
        return c


def import_voiceover(pid, cid, path: str) -> dict:
    src = Path(path)
    if not src.exists():
        raise RuntimeError("File not found")
    has_video = False
    try:
        has_video = media.probe(str(src)).get("has_video", False) if src.suffix.lower() not in (".mp3", ".wav", ".m4a", ".ogg") else False
    except Exception:
        pass
    return save_voiceover(pid, cid, src.read_bytes(), src.suffix.lstrip(".").lower(), has_video)


def delete_voiceover(pid, cid) -> dict:
    with _lock(pid):
        p = load(pid)
        c = _defaults(get_clip(p, cid))
        old = c["audio"].get("vo_file")
        if old and Path(old).parent == pdir(pid):
            Path(old).unlink(missing_ok=True)
        c["audio"]["vo_file"] = None
        c["audio"]["vo_has_video"] = False
        save(p)
        return c


def auto_edit(job, pid, cid):
    s = settings_mod.load()
    p = load(pid)
    c = _defaults(get_clip(p, cid))
    L = c["end"] - c["start"]
    segs = (p.get("transcript") or {}).get("segments", [])
    loud = p.get("loudness") or []
    local = fx.auto_edit_local(c, loud, 0.25, segs, float(s.get("max_clip_sec", 60)))
    effects, note = local, "offline"
    if s.get("claude_api_key"):
        job.update(progress=0.2, stage="Claude is planning the edit…")
        peaks = sorted({round(e["t"], 1) for e in local if e["type"] in ("zoom", "shake")})
        try:
            raw = ai.auto_edit(segs, c, peaks, s, [x["id"] for x in fx.sfx_list() if x["source"] == "builtin"])
            got = [x for x in (_clean_effect(e, L) for e in raw) if x]
            if got:
                effects, note = got, "claude"
        except ai.AIError as e:
            note = f"offline ({e})"
    with _lock(pid):
        p = load(pid)
        c = _defaults(get_clip(p, cid))
        c["effects"] = sorted(effects, key=lambda e: e["t"])
        save(p)
    return {"clip": c, "source": note}


CAT_TAGS = {"funny": ["#funny", "#comedy"], "shock": ["#omg", "#unexpected"], "hype": ["#epic", "#clutch"],
            "panic": ["#scary", "#horror"], "rage": ["#rage"], "skill": ["#skills", "#pro"],
            "wholesome": ["#wholesome"], "story": ["#story"], "laugh": ["#funny"], "banter": ["#funny"]}


def gen_metadata(job, pid, cid, language="original"):
    s = settings_mod.load()
    p = load(pid)
    c = _defaults(get_clip(p, cid))
    text = " ".join(q["text"] for q in c["captions"].get("cues", []))
    credit = p.get("credit", "")
    if s.get("claude_api_key"):
        job.update(progress=0.3, stage="Writing title and hashtags…")
        lang = language if language != "original" else ("hinglish" if captions.DEVANAGARI.search(text) else "en")
        meta = ai.metadata(c, text, lang, credit, s)
    else:
        tags = ["#shorts", "#gaming"] + CAT_TAGS.get(c.get("category", ""), [])
        if captions.DEVANAGARI.search(text):
            tags.append("#hindi")
        desc = (c.get("hook") or c["title"])
        if credit:
            desc += f"\n\nCredit: {credit}"
        meta = {"title": c["title"][:70], "description": desc, "hashtags": tags}
    with _lock(pid):
        p = load(pid)
        c = _defaults(get_clip(p, cid))
        c["meta"] = meta
        save(p)
    return {"clip": c}


def originality_check(pid, cid) -> dict:
    p = load(pid)
    c = _defaults(get_clip(p, cid))
    recent = []
    for proj in list_all()[:10]:
        try:
            q = load(proj["id"])
        except Exception:
            continue
        for x in q.get("clips", []):
            if x.get("exports") and x["id"] != cid:
                recent.append((x.get("captions", {}).get("style"),
                               tuple(sorted({e["type"] for e in x.get("effects", [])}))))
    return originality.check(p, c, recent[-8:])


def all_exports() -> list:
    out = []
    for proj in list_all():
        p = load(proj["id"])
        for c in p.get("clips", []):
            for e in c.get("exports", []):
                if Path(e["path"]).exists():
                    out.append(e | {"project_id": p["id"], "project": p["name"], "clip_id": c["id"],
                                    "title": c["title"]})
    return sorted(out, key=lambda e: -e.get("at", 0))
