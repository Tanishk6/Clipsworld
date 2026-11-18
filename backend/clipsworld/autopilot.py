"""Autopilot: turns the video links you give it into finished Shorts and posts them on a schedule.

Loop (runs in the background while Clipsworld is open, every 20 s):
  1. Keep a buffer of finished clips (posts per day x days ahead). When it runs low, take the best unused
     clip from an analysed video, or analyse the next video link in the queue.
  2. Produce a clip: Claude plans effects + writes title/description/hashtags, then the clip is edited with
     HyperFrames (motion graphics). If HyperFrames fails, the normal Clipsworld editor renders it.
  3. Finished clips wait in Review (when approval is on) until you approve them.
  4. Approved clips get the next free time slot and are uploaded to YouTube right away as *scheduled*
     videos (YouTube publishes them at the slot time, even if this PC is off by then).
"""
import json
import threading
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import projects, render, youtube
from . import settings as settings_mod
from .paths import data_dir

STYLE_ROTATION = ["hormozi", "beast", "comic", "gaming", "meme", "punch", "bebas", "neon"]
WAITING = ("producing", "review", "approved", "uploading")
_lock = threading.RLock()
_worker = {"thread": None, "stage": "", "progress": 0.0, "item": None, "kind": None}
_stop = threading.Event()
_loop = None


# ------------------------------------------------------------------ state

def _file() -> Path:
    return data_dir() / "autopilot.json"


def _load() -> dict:
    f = _file()
    st = {}
    if f.exists():
        try:
            st = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            st = {}
    st.setdefault("sources", [])
    st.setdefault("items", [])
    st.setdefault("log", [])
    st.setdefault("style_i", 0)
    return st


def _save(st: dict):
    tmp = _file().with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_file())


def _log(st: dict, msg: str):
    st["log"].append({"t": int(time.time()), "msg": msg})
    st["log"] = st["log"][-200:]


def _item(st, iid):
    for it in st["items"]:
        if it["id"] == iid:
            return it
    raise KeyError(f"Autopilot item {iid} not found")


def _source(st, sid):
    for s in st["sources"]:
        if s["id"] == sid:
            return s
    raise KeyError(f"Video {sid} not found")


def state() -> dict:
    with _lock:
        st = _load()
    s = settings_mod.load()
    w = {k: _worker[k] for k in ("stage", "progress", "item", "kind")}
    w["busy"] = bool(_worker["thread"] and _worker["thread"].is_alive())
    counts = {}
    for it in st["items"]:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    return {"enabled": bool(s.get("ap_enabled")), "worker": w, "counts": counts,
            "sources": st["sources"][::-1], "items": sorted(st["items"], key=_sort_key),
            "log": st["log"][-60:][::-1], "youtube": youtube.status(), "slots": slot_times(s),
            "next_slots": [x.isoformat() for x in upcoming_slots(st, s, 5)]}


def _sort_key(it):
    order = {"review": 0, "producing": 1, "approved": 2, "uploading": 3, "scheduled": 4, "failed": 5,
             "uploaded": 6, "rejected": 7}
    return (order.get(it["status"], 9), it.get("publish_at") or "", -it.get("created", 0))


# ------------------------------------------------------------------ sources

def add_sources(urls: list) -> dict:
    added = []
    with _lock:
        st = _load()
        known = {s["url"] for s in st["sources"]}
        for u in urls:
            u = str(u).strip()
            if not u.lower().startswith(("http://", "https://")) or u in known:
                continue
            src = {"id": uuid.uuid4().hex[:8], "url": u, "added": int(time.time()), "status": "queued",
                   "title": "", "project_id": None, "error": None, "used": []}
            st["sources"].append(src)
            known.add(u)
            added.append(src)
        if added:
            _log(st, f"Added {len(added)} video link(s).")
        _save(st)
    return {"added": len(added)}


def remove_source(sid: str):
    with _lock:
        st = _load()
        st["sources"] = [s for s in st["sources"] if s["id"] != sid]
        _save(st)


def retry_source(sid: str):
    with _lock:
        st = _load()
        s = _source(st, sid)
        s.update(status="queued", error=None)
        _save(st)


# ------------------------------------------------------------------ schedule

def slot_times(s: dict) -> list:
    times = [t for t in (s.get("ap_times") or []) if _parse_hm(t)]
    n = max(1, min(12, int(s.get("ap_per_day") or 5)))
    times = sorted(times, key=lambda t: _parse_hm(t))[:n]
    return times or ["12:00"]


def _parse_hm(t: str):
    try:
        h, m = str(t).split(":")
        h, m = int(h), int(m)
        if 0 <= h < 24 and 0 <= m < 60:
            return (h, m)
    except (ValueError, AttributeError):
        pass
    return None


def _taken(st) -> set:
    return {it["publish_at"] for it in st["items"]
            if it.get("publish_at") and it["status"] in ("approved", "uploading", "scheduled", "uploaded")}


def upcoming_slots(st, s, count: int, now: datetime | None = None) -> list:
    """Next free slots as aware UTC datetimes (slots are in this PC's local time)."""
    now = (now or datetime.now().astimezone())
    taken = _taken(st)
    out = []
    day = now.date()
    for _ in range(60):
        for t in slot_times(s):
            h, m = _parse_hm(t)
            local = datetime(day.year, day.month, day.day, h, m).astimezone()
            if local < now + timedelta(minutes=20):
                continue
            iso = local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if iso not in taken:
                out.append(local.astimezone(timezone.utc))
                if len(out) >= count:
                    return out
        day = day + timedelta(days=1)
    return out


def _assign_slot(st, s, it):
    nxt = upcoming_slots(st, s, 1)
    it["publish_at"] = nxt[0].strftime("%Y-%m-%dT%H:%M:%SZ") if nxt else None


# ------------------------------------------------------------------ review actions

def approve(iid: str, patch: dict | None = None) -> dict:
    with _lock:
        st = _load()
        it = _item(st, iid)
        if it["status"] not in ("review", "failed", "rejected"):
            raise ValueError("This clip can't be approved right now.")
        _apply_meta(it, patch or {})
        it.update(status="approved", error=None, attempts=0, next_try=0)
        if patch and patch.get("publish_at"):
            it["publish_at"] = str(patch["publish_at"])
        else:
            it["publish_at"] = None
            _assign_slot(st, settings_mod.load(), it)
        _log(st, f"Approved “{it['title']}”.")
        _save(st)
        return it


def _apply_meta(it, patch):
    if "title" in patch:
        it["title"] = str(patch["title"]).strip()[:100] or it["title"]
    if "description" in patch:
        it["description"] = str(patch["description"])[:4900]
    if "tags" in patch:
        tags = patch["tags"] if isinstance(patch["tags"], list) else str(patch["tags"]).replace(",", " ").split()
        it["tags"] = [str(t).strip() for t in tags if str(t).strip()][:30]


def edit_item(iid: str, patch: dict) -> dict:
    with _lock:
        st = _load()
        it = _item(st, iid)
        _apply_meta(it, patch)
        if patch.get("publish_at") and it["status"] in ("approved",):
            it["publish_at"] = str(patch["publish_at"])
        _save(st)
        return it


def reject(iid: str) -> dict:
    with _lock:
        st = _load()
        it = _item(st, iid)
        if it["status"] in ("uploading", "scheduled", "uploaded"):
            raise ValueError("This clip is already on YouTube.")
        it.update(status="rejected", publish_at=None)
        _log(st, f"Rejected “{it['title']}”.")
        _save(st)
        return it


def delete_item(iid: str):
    with _lock:
        st = _load()
        it = _item(st, iid)
        if it["status"] in ("producing", "uploading"):
            raise ValueError("Wait until this clip finishes.")
        st["items"] = [x for x in st["items"] if x["id"] != iid]
        _save(st)
    p = Path(it.get("video_path") or "")
    if p.name.startswith("ap_") and p.exists():
        p.unlink(missing_ok=True)


def retry_item(iid: str) -> dict:
    with _lock:
        st = _load()
        it = _item(st, iid)
        if it["status"] == "failed" and it.get("video_id") is None and it.get("video_path") and Path(it["video_path"]).exists():
            it.update(status="approved", attempts=0, next_try=0, error=None)
            if not it.get("publish_at") or _past(it["publish_at"]):
                it["publish_at"] = None
                _assign_slot(st, settings_mod.load(), it)
        elif it["status"] in ("failed", "rejected", "render_failed"):
            it.update(status="queued_again", error=None)
        _save(st)
        return it


def _ts(iso: str) -> float:
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def _past(iso: str) -> bool:
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) < datetime.now(timezone.utc) + timedelta(minutes=10)
    except ValueError:
        return True


# ------------------------------------------------------------------ worker

class _Progress:
    def __init__(self, base=0.0, span=1.0):
        self.base, self.span = base, span

    def update(self, progress=None, stage=None):
        if _stop.is_set():
            raise RuntimeError("Autopilot was stopped.")
        if progress is not None:
            _worker["progress"] = round(self.base + self.span * max(0.0, min(1.0, float(progress))), 4)
        if stage is not None:
            _worker["stage"] = stage


def _run(kind, fn, *args):
    def go():
        _worker.update(kind=kind, progress=0.0)
        try:
            fn(*args)
        except Exception:
            traceback.print_exc()
        finally:
            _worker.update(stage="", progress=0.0, item=None, kind=None)
    t = threading.Thread(target=go, daemon=True, name=f"autopilot-{kind}")
    _worker["thread"] = t
    t.start()


def busy() -> bool:
    return bool(_worker["thread"] and _worker["thread"].is_alive())


def tick(force: bool = False):
    """One scheduler step. Starts at most one background task."""
    s = settings_mod.load()
    if busy() or not (s.get("ap_enabled") or force):
        return None
    with _lock:
        st = _load()
        now = time.time()
        # 1) uploads first (they're quick and time-sensitive)
        if youtube.status()["connected"]:
            for it in sorted(st["items"], key=lambda x: x.get("publish_at") or ""):
                if it["status"] == "approved" and now >= it.get("next_try", 0):
                    public = (s.get("ap_privacy") or "public") == "public"
                    if not it.get("publish_at") or (public and _past(it["publish_at"])):
                        it["publish_at"] = None
                        _assign_slot(st, s, it)
                    if not public and it.get("publish_at") and _ts(it["publish_at"]) > now + 60:
                        continue  # not scheduled on YouTube: upload when the slot arrives
                    it["status"] = "uploading"
                    _save(st)
                    _run("upload", _upload, it["id"])
                    return "upload"
        # 2) regenerate items the user asked to redo
        for it in st["items"]:
            if it["status"] == "queued_again":
                it["status"] = "producing"
                _save(st)
                _run("produce", _produce, it["id"])
                return "produce"
        # 3) keep the buffer full
        per_day = len(slot_times(s))
        target = per_day * max(1, int(s.get("ap_buffer_days") or 2))
        ready = sum(1 for it in st["items"] if it["status"] in WAITING)
        if ready >= target:
            return None
        cand = _next_candidate(st, s)
        if cand:
            src, clip = cand
            it = {"id": uuid.uuid4().hex[:8], "source_id": src["id"], "project_id": src["project_id"],
                  "clip_id": clip["id"], "status": "producing", "created": int(now), "title": clip.get("title", ""),
                  "description": "", "tags": [], "publish_at": None, "video_id": None, "video_path": None,
                  "engine": None, "error": None, "attempts": 0, "next_try": 0, "score": clip.get("score", 0),
                  "style": STYLE_ROTATION[st["style_i"] % len(STYLE_ROTATION)]}
            st["style_i"] += 1
            src["used"].append(clip["id"])
            st["items"].append(it)
            _save(st)
            _run("produce", _produce, it["id"])
            return "produce"
        for src in st["sources"]:
            if src["status"] == "queued":
                src["status"] = "analysing"
                _save(st)
                _run("analyse", _analyse, src["id"])
                return "analyse"
    return None


def _next_candidate(st, s):
    min_score = int(s.get("ap_min_score") or 0)
    per_video = int(s.get("ap_clips_per_video") or 6)
    best = None
    for src in st["sources"]:
        if src["status"] not in ("ready", "empty") or not src.get("project_id") or len(src["used"]) >= per_video:
            continue
        try:
            p = projects.load(src["project_id"])
        except Exception:
            src["status"] = "error"
            src["error"] = "The project for this video was deleted."
            continue
        for c in p.get("clips", []):
            if c["id"] in src["used"] or c.get("score", 0) < min_score:
                continue
            if best is None or c.get("score", 0) > best[1].get("score", 0):
                best = (src, c)
        if best:  # finish one video before moving to the next (keeps order of your links)
            return best
    return best


def _analyse(sid: str):
    with _lock:
        st = _load()
        src = _source(st, sid)
        url = src["url"]
        pid = src.get("project_id")
    _worker.update(item=sid, stage="Downloading video…")
    try:
        if not pid:
            pid = projects.create(url)["id"]
            with _lock:
                st = _load()
                _source(st, sid)["project_id"] = pid
                _save(st)
        projects.analyze(_Progress(), pid)
        p = projects.load(pid)
        with _lock:
            st = _load()
            src = _source(st, sid)
            src.update(status="ready" if p.get("clips") else "empty", title=p.get("name", ""),
                       clips=len(p.get("clips", [])), error=None if p.get("clips") else "No good moments found.")
            _log(st, f"Analysed “{p.get('name', url)}”: {len(p.get('clips', []))} clips found.")
            _save(st)
    except Exception as e:
        with _lock:
            st = _load()
            src = _source(st, sid)
            src.update(status="error", error=str(e)[:300])
            _log(st, f"Couldn't analyse {url}: {e}")
            _save(st)


def _produce(iid: str):
    from . import hyperframes
    s = settings_mod.load()
    with _lock:
        st = _load()
        it = _item(st, iid)
    _worker.update(item=iid)
    pid, cid = it["project_id"], it["clip_id"]
    try:
        prog = _Progress(0.0, 0.15)
        # captions: Hinglish by default, rotate the caption style for variety
        p = projects.load(pid)
        c = projects._defaults(projects.get_clip(p, cid))
        prog.update(0.05, "Styling captions…")
        if c["captions"].get("style") != it.get("style"):
            projects.update_clip(pid, cid, {"captions": {"style": it.get("style") or "hormozi"}})
        prog.update(0.2, "Planning effects…")
        try:
            projects.auto_edit(prog, pid, cid)
        except Exception:
            pass
        prog.update(0.6, "Writing title and hashtags…")
        lang = s.get("caption_language", "hinglish")
        try:
            projects.gen_metadata(prog, pid, cid, lang if lang != "original" else "hinglish")
        except Exception:
            pass
        p = projects.load(pid)
        c = projects._defaults(projects.get_clip(p, cid))
        out_dir = Path(s["output_dir"]) / "Autopilot"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"ap_{iid}_{render.safe_name(c.get('title', 'clip'))}.mp4"
        engine, err = None, None
        if (s.get("ap_engine") or "hyperframes") == "hyperframes":
            try:
                hyperframes.edit_clip(_Progress(0.15, 0.85), p, c, s, out)
                engine = "hyperframes"
            except Exception as e:  # fall back to the normal editor
                err = str(e)[:300]
                if "needs your Claude" not in err and "not installed" not in err:
                    traceback.print_exc()
        if not engine:
            _worker["stage"] = "Rendering with the Clipsworld editor…"
            render.export_clip(_Progress(0.15 if err is None else 0.5, 0.85 if err is None else 0.5), p, c, s,
                               out_override=out)
            engine = "clipsworld"
        meta = c.get("meta") or {}
        tags = [t.lstrip("#") for t in (meta.get("hashtags") or []) if t]
        desc = meta.get("description") or c.get("hook") or ""
        hashtags = " ".join("#" + t for t in tags[:8])
        if hashtags and hashtags not in desc:
            desc = f"{desc}\n\n{hashtags}"
        if p.get("credit") and p["credit"] not in desc:
            desc += f"\n\nCredit: {p['credit']}"
        with _lock:
            st = _load()
            it = _item(st, iid)
            it.update(video_path=str(out), engine=engine, engine_note=err,
                      title=(meta.get("title") or c.get("title") or "Clip")[:100], description=desc[:4900],
                      tags=tags[:30], thumb=f"{projects.pdir(pid)}/thumb_{cid}.jpg", duration=round(c["end"] - c["start"], 1))
            if s.get("ap_approval", True):
                it["status"] = "review"
                _log(st, f"Ready for review: “{it['title']}” ({engine}).")
            else:
                it.update(status="approved", attempts=0, next_try=0)
                _assign_slot(st, s, it)
                _log(st, f"Made “{it['title']}” ({engine}), scheduled automatically.")
            _save(st)
    except Exception as e:
        traceback.print_exc()
        with _lock:
            st = _load()
            it = _item(st, iid)
            it.update(status="render_failed", error=str(e)[:300])
            _log(st, f"Couldn't make a clip: {e}")
            _save(st)


def _upload(iid: str):
    s = settings_mod.load()
    with _lock:
        st = _load()
        it = _item(st, iid)
    _worker.update(item=iid, stage=f"Uploading “{it['title']}” to YouTube…")
    try:
        path = Path(it.get("video_path") or "")
        if not path.exists():
            raise youtube.YTError("The clip file is missing (was it moved or deleted?).")
        title = it["title"]
        if "#shorts" not in title.lower() and len(title) <= 90:
            title = f"{title} #shorts"
        privacy = s.get("ap_privacy") or "public"
        schedule = it.get("publish_at") if privacy == "public" else None
        vid = youtube.upload(str(path), title, it.get("description", ""), it.get("tags", []),
                             privacy=privacy, publish_at=schedule,
                             progress=lambda x: _worker.update(progress=round(x, 3)))
        info = {}
        try:
            info = youtube.video_status(vid)
        except Exception:
            pass
        with _lock:
            st = _load()
            it = _item(st, iid)
            it.update(status="scheduled" if schedule else "uploaded", video_id=vid, error=None,
                      uploaded_at=int(time.time()), yt_privacy=info.get("privacyStatus"))
            locked = info.get("privacyStatus") == "private" and not info.get("publishAt") and \
                (s.get("ap_privacy") or "public") != "private"
            if locked:
                it["note"] = "YouTube kept this video private: your Google project needs the YouTube audit (see Setup)."
            _log(st, f"Uploaded “{it['title']}” → youtu.be/{vid}" + (f" (goes live {schedule})" if schedule else f" ({privacy})"))
            _save(st)
    except Exception as e:
        msg = str(e)
        with _lock:
            st = _load()
            it = _item(st, iid)
            it["attempts"] = it.get("attempts", 0) + 1
            quota = "quota" in msg.lower() or "limit" in msg.lower()
            wait = 6 * 3600 if quota else 600 * it["attempts"]
            if it["attempts"] >= 5:
                it.update(status="failed", error=msg[:300])
            else:
                it.update(status="approved", error=msg[:300], next_try=time.time() + wait)
            _log(st, f"Upload failed for “{it['title']}”: {msg[:160]}")
            _save(st)


# ------------------------------------------------------------------ loop

def start_loop():
    global _loop
    if _loop and _loop.is_alive():
        return
    with _lock:  # anything stuck from a crash goes back to its previous step
        st = _load()
        for it in st["items"]:
            if it["status"] == "producing":
                it["status"] = "queued_again"
            elif it["status"] == "uploading":
                it["status"] = "approved"
        for src in st["sources"]:
            if src["status"] == "analysing":
                src["status"] = "queued"
        _save(st)

    def loop():
        while not _stop.wait(20):
            try:
                tick()
            except Exception:
                traceback.print_exc()
    _loop = threading.Thread(target=loop, daemon=True, name="autopilot-loop")
    _loop.start()


def run_now() -> str | None:
    return tick(force=True)
