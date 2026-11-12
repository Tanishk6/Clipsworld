"""Projects: one imported video, its transcript, and its clips."""
import json
import shutil
import threading
import time
import uuid
from pathlib import Path

from . import ai, captions, highlights, media, render, transcribe, ytdl
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


def list_all() -> list:
    out = []
    for d in projects_dir().iterdir():
        try:
            out.append(summary(load(d.name)))
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
        if need_preview and not (d / "preview.mp4").exists():
            _set(p, stage="Making a preview copy…")
            media.make_preview(p["source_path"], d / "preview.mp4", info["duration"],
                               lambda x: job.update(progress=0.92 + 0.08 * x, stage="Making a preview copy…"))
        _set(p, status="ready", stage="Ready", error=None)
        return {"project_id": pid, "clips": len(p["clips"])}
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
    clips = keep + [new_clip(p, c) for c in found
                    if all(c["end"] <= k["start"] or c["start"] >= k["end"] for k in keep)]
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
    rebuild_cues(p, clip)
    text = " ".join(q["text"] for q in clip["captions"]["cues"])
    if text and len(captions.DEVANAGARI.findall(text)) > len(text) * 0.3:
        clip["captions"]["style"] = "pop"  # Hindi script: start with a Hindi-friendly font
        rebuild_cues(p, clip)
    return clip


def rebuild_cues(p: dict, clip: dict):
    st = captions.STYLES.get(clip["captions"].get("style", "pop"), captions.STYLES["pop"])
    segs = (p.get("transcript") or {}).get("segments", [])
    clip["captions"]["cues"] = captions.build_cues(segs, clip["start"], clip["end"], st["words"])
    clip["captions"]["language"] = "original"


def _thumb(p, clip):
    t = pdir(p["id"]) / f"thumb_{clip['id']}.jpg"
    media.thumbnail(p["source_path"], (clip["start"] + clip["end"]) / 2, t, width=360)


def get_clip(p, cid):
    for c in p["clips"]:
        if c["id"] == cid:
            return c
    raise KeyError(cid)


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
        for k in ("title", "hook", "pinned"):
            if k in patch:
                c[k] = patch[k]
        if "layout" in patch:
            c["layout"].update(patch["layout"])
        if "captions" in patch:
            cap = dict(patch["captions"])
            if "cues" in cap:
                cap["cues"] = [captions.respread_words(dict(q)) if q.get("edited") else q for q in cap["cues"]]
            old_style = c["captions"].get("style")
            c["captions"].update(cap)
            if "style" in cap and cap["style"] != old_style and c["captions"].get("language") == "original" \
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
    p = load(pid)
    c = get_clip(p, cid)
    if target == "original":
        update = {"captions": {"language": "original"}}
        rebuild_cues(p, c)
        save(p)
        return update_clip(pid, cid, update)
    if c["captions"].get("language") != "original":
        rebuild_cues(p, c)  # always translate from the original words
    cues = c["captions"]["cues"]
    lines = ai.translate_lines(job, [q["text"] for q in cues], target, s)
    for q, t in zip(cues, lines):
        q["text"] = t.strip() or q["text"]
        captions.respread_words(q)
    c["captions"]["language"] = target
    if c.get("hook"):
        c["hook"] = ai.translate_lines(None, [c["hook"]], target, s)[0]
    save(p)
    return c


def export(job, pid, cids: list):
    s = settings_mod.load()
    results = []
    for i, cid in enumerate(cids):
        p = load(pid)
        c = get_clip(p, cid)
        res = render.export_clip(job, p, c, s, (i / len(cids), (i + 1) / len(cids)))
        with _lock(pid):
            p = load(pid)
            get_clip(p, cid).setdefault("exports", []).append(res)
            save(p)
        results.append(res)
    return {"files": results}


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
