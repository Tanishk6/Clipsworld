"""Clipsworld backend: a local HTTP API used by the desktop UI."""
import argparse
import os
import sys
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clipsworld import ai, captions, gpu, jobs, projects  # noqa: E402
from clipsworld import settings as settings_mod  # noqa: E402
from clipsworld.paths import resources_dir  # noqa: E402

VERSION = "1.6.0"
app = FastAPI(title="Clipsworld", version=VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(projects.ClipNotFound)
async def _clip_missing(_request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=404, content={"detail": str(exc)})


def _project(pid):
    try:
        return projects.load(pid)
    except KeyError:
        raise HTTPException(404, "Project not found")


@app.get("/health")
def health():
    return {"ok": True, "version": VERSION, "resources": str(resources_dir())}


# ------------------------------------------------------------ settings
@app.get("/settings")
def get_settings():
    return settings_mod.public(settings_mod.load())


@app.get("/styles")
def styles():
    return {"styles": captions.STYLES, "positions": list(captions.POSITIONS), "fonts": captions.FONT_FILES}


@app.put("/settings")
def put_settings(body: dict = Body(...)):
    if "claude_api_key" in body and body["claude_api_key"] is None:
        body.pop("claude_api_key")
    return settings_mod.public(settings_mod.save(body))


@app.post("/settings/test-key")
def test_key(body: dict = Body(default={})):
    s = settings_mod.load()
    key = body.get("claude_api_key") or s.get("claude_api_key")
    model = body.get("claude_model") or s.get("claude_model")
    try:
        return ai.test_key(key, model)
    except ai.AIError as e:
        return {"ok": False, "error": str(e)}


@app.get("/gpu")
def gpu_status():
    return gpu.status()


@app.post("/gpu/install")
def gpu_install():
    return gpu.install_pack()


@app.get("/downloads")
def downloads_list():
    from clipsworld import downloads
    return downloads.all_status(settings_mod.load().get("whisper_model", "large-v3-turbo"))


@app.post("/downloads/{key}/start")
def download_start(key: str):
    from clipsworld import downloads
    try:
        return downloads.start(key)
    except (KeyError, RuntimeError) as e:
        raise HTTPException(400, str(e))


@app.post("/downloads/{key}/pause")
def download_pause(key: str):
    from clipsworld import downloads
    try:
        return downloads.pause(key)
    except KeyError as e:
        raise HTTPException(400, str(e))


# ------------------------------------------------------------ projects
@app.get("/projects")
def list_projects():
    return projects.list_all()


@app.post("/projects")
def create_project(body: dict = Body(...)):
    src = (body.get("source") or "").strip()
    if not src:
        raise HTTPException(400, "Choose a video file or paste a link.")
    if not src.lower().startswith(("http://", "https://")) and not Path(src).exists():
        raise HTTPException(400, f"File not found: {src}")
    p = projects.create(src, body.get("name"))
    job = jobs.start("analyze", p["id"], projects.analyze, p["id"])
    return {"project": projects.public(p), "job": job.to_dict()}


@app.get("/projects/{pid}")
def get_project(pid: str):
    return projects.public(_project(pid))


@app.delete("/projects/{pid}")
def delete_project(pid: str):
    projects.delete(pid)
    return {"ok": True}


@app.post("/projects/{pid}/analyze")
def reanalyze(pid: str, body: dict = Body(default={})):
    p = _project(pid)
    if projects.analyze_running(pid):
        raise HTTPException(409, "Clipsworld is already working on this video. Wait for it to finish.")
    stage = body.get("from", "clips" if p.get("transcript") else "start")
    job = jobs.start("analyze", pid, projects.analyze, pid, "start" if stage == "start" else "clips")
    return job.to_dict()


@app.get("/projects/{pid}/media")
def media_file(pid: str):
    p = _project(pid)
    prev = projects.pdir(pid) / "preview.mp4"
    path = prev if prev.exists() else Path(p.get("source_path") or "")
    if not path.exists():
        raise HTTPException(404, "Video not ready")
    return FileResponse(path)


@app.get("/projects/{pid}/cover")
def cover(pid: str):
    f = projects.pdir(pid) / "cover.jpg"
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, headers={"Cache-Control": "max-age=60"})


@app.get("/projects/{pid}/thumb/{cid}")
def thumb(pid: str, cid: str):
    f = projects.pdir(pid) / f"thumb_{cid}.jpg"
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, headers={"Cache-Control": "no-cache"})


@app.get("/projects/{pid}/waveform")
def waveform(pid: str, points: int = 1200):
    p = _project(pid)
    loud = p.get("loudness") or []
    if not loud:
        return {"hop": 0.25, "values": []}
    n = max(1, len(loud) // max(1, points))
    vals = [max(loud[i:i + n]) for i in range(0, len(loud), n)]
    return {"hop": 0.25 * n, "values": [round(min(1.0, max(0.0, (v + 60) / 60)), 3) for v in vals]}


# ------------------------------------------------------------ clips
@app.post("/projects/{pid}/clips")
def add_clip(pid: str, body: dict = Body(...)):
    _project(pid)
    return projects.add_clip(pid, float(body["start"]), float(body["end"]))


@app.put("/projects/{pid}/clips/{cid}")
def update_clip(pid: str, cid: str, body: dict = Body(...)):
    try:
        return projects.update_clip(pid, cid, body)
    except KeyError:
        raise HTTPException(404, "Clip not found")


@app.delete("/projects/{pid}/clips/{cid}")
def delete_clip(pid: str, cid: str):
    projects.delete_clip(pid, cid)
    return {"ok": True}


@app.post("/projects/{pid}/clips/{cid}/captions/rebuild")
def rebuild(pid: str, cid: str):
    p = _project(pid)
    c = projects.get_clip(p, cid)
    projects.rebuild_cues(p, c)
    projects.save(p)
    return c


@app.post("/projects/{pid}/clips/{cid}/translate")
def translate(pid: str, cid: str, body: dict = Body(...)):
    projects.get_clip(_project(pid), cid)
    return jobs.start("translate", pid, projects.translate_clip, pid, cid, body.get("target", "en")).to_dict()


@app.post("/projects/{pid}/export")
def export(pid: str, body: dict = Body(...)):
    p = _project(pid)
    ids = body.get("clip_ids") or [c["id"] for c in p["clips"]]
    for cid in ids:
        projects.get_clip(p, cid)
    if not ids:
        raise HTTPException(400, "No clips to export.")
    return jobs.start("export", pid, projects.export, pid, ids).to_dict()


@app.put("/projects/{pid}")
def update_project(pid: str, body: dict = Body(...)):
    _project(pid)
    return projects.public(projects.update_project(pid, body))


@app.get("/projects/{pid}/frame")
def frame(pid: str, t: float = 0.0):
    p = _project(pid)
    f = projects.pdir(pid) / "frame.jpg"
    from clipsworld import media
    media.thumbnail(p["source_path"], t, f, width=960)
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, headers={"Cache-Control": "no-cache"})


@app.post("/projects/{pid}/clips/{cid}/preview")
def clip_preview(pid: str, cid: str):
    projects.get_clip(_project(pid), cid)
    return jobs.start("preview", pid, projects.preview, pid, cid).to_dict()


@app.post("/projects/{pid}/clips/{cid}/auto-edit")
def clip_auto_edit(pid: str, cid: str):
    projects.get_clip(_project(pid), cid)
    return jobs.start("auto_edit", pid, projects.auto_edit, pid, cid).to_dict()


@app.post("/projects/{pid}/clips/{cid}/metadata")
def clip_metadata(pid: str, cid: str, body: dict = Body(default={})):
    projects.get_clip(_project(pid), cid)
    return jobs.start("metadata", pid, projects.gen_metadata, pid, cid, body.get("language", "original")).to_dict()


@app.get("/projects/{pid}/clips/{cid}/originality")
def clip_originality(pid: str, cid: str):
    _project(pid)
    try:
        return projects.originality_check(pid, cid)
    except KeyError:
        raise HTTPException(404, "Clip not found")


@app.post("/projects/{pid}/clips/{cid}/voiceover")
async def upload_voiceover(pid: str, cid: str, request: Request, ext: str = "webm", video: int = 0):
    _project(pid)
    data = await request.body()
    if len(data) < 1000:
        raise HTTPException(400, "Recording is empty.")
    return projects.save_voiceover(pid, cid, data, ext, bool(video))


@app.post("/projects/{pid}/clips/{cid}/voiceover/import")
def import_voiceover(pid: str, cid: str, body: dict = Body(...)):
    _project(pid)
    try:
        return projects.import_voiceover(pid, cid, body.get("path", ""))
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@app.delete("/projects/{pid}/clips/{cid}/voiceover")
def delete_voiceover(pid: str, cid: str):
    _project(pid)
    return projects.delete_voiceover(pid, cid)


@app.get("/sfx")
def sfx_list():
    from clipsworld import effects as fx
    return fx.sfx_list()


@app.get("/sfx/{sfx_id}")
def sfx_file(sfx_id: str):
    from clipsworld import effects as fx
    p = fx.sfx_path(sfx_id)
    if not p:
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "max-age=86400"})


@app.get("/effects/defaults")
def effect_defaults():
    from clipsworld import effects as fx, originality
    return {"defaults": fx.DEFAULTS, "types": fx.TYPES, "rules": originality.RULES}


@app.get("/exports")
def exports():
    return projects.all_exports()


@app.get("/fonts/{name}")
def font(name: str):
    from clipsworld.paths import fonts_dir
    f = fonts_dir() / Path(name).name
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, headers={"Cache-Control": "max-age=86400"})


@app.get("/file")
def any_file(path: str):
    """Serve an exported clip or thumbnail for preview in the app."""
    f = Path(path)
    if not f.exists() or f.suffix.lower() not in {".mp4", ".jpg", ".webm", ".m4a", ".mp3", ".wav", ".mkv", ".mov", ".ogg"}:
        raise HTTPException(404)
    return FileResponse(f)


# ------------------------------------------------------------ jobs
@app.get("/jobs")
def list_jobs():
    return jobs.all_jobs()


@app.get("/jobs/{jid}")
def get_job(jid: str):
    j = jobs.get(jid)
    if not j:
        raise HTTPException(404, "Job not found")
    return j.to_dict()


@app.post("/jobs/{jid}/cancel")
def cancel_job(jid: str):
    return {"ok": jobs.cancel(jid)}


# ------------------------------------------------------------ YouTube
@app.get("/youtube/status")
def yt_status():
    from clipsworld import youtube
    return youtube.status()


@app.put("/youtube/client")
def yt_client(body: dict = Body(...)):
    from clipsworld import youtube
    try:
        youtube.set_client(str(body.get("client_id", "")), str(body.get("client_secret", "")))
    except youtube.YTError as e:
        raise HTTPException(400, str(e))
    return youtube.status()


@app.post("/youtube/connect")
def yt_connect(request: Request):
    from clipsworld import youtube
    try:
        return {"url": youtube.auth_url(f"http://127.0.0.1:{request.url.port}/youtube/callback")}
    except youtube.YTError as e:
        raise HTTPException(400, str(e))


@app.get("/youtube/callback")
def yt_callback(code: str = "", state: str = "", error: str = ""):
    from fastapi.responses import HTMLResponse
    from clipsworld import youtube
    ok, msg = False, error or "Google didn't send a sign-in code."
    if code:
        try:
            ch = (youtube.handle_callback(code, state) or {}).get("channel") or {}
            ok, msg = True, f"Connected to {ch.get('title') or 'your YouTube channel'}."
        except youtube.YTError as e:
            msg = str(e)
    color = "#3ddc84" if ok else "#ff5c7a"
    import html as h
    return HTMLResponse(f"""<!doctype html><meta charset=utf-8><title>Clipsworld</title>
<body style="background:#0d0d14;color:#eee;font:16px system-ui;display:grid;place-items:center;height:100vh;margin:0">
<div style="text-align:center"><div style="font-size:42px;color:{color}">{'✓' if ok else '✕'}</div>
<h2>{h.escape(msg)}</h2><p style="opacity:.7">You can close this tab and go back to Clipsworld.</p></div></body>""")


@app.post("/youtube/disconnect")
def yt_disconnect():
    from clipsworld import youtube
    youtube.disconnect()
    return youtube.status()


# ------------------------------------------------------------ Autopilot
@app.get("/autopilot")
def ap_state():
    from clipsworld import autopilot
    return autopilot.state()


@app.post("/autopilot/sources")
def ap_add(body: dict = Body(...)):
    from clipsworld import autopilot
    urls = body.get("urls") or []
    if isinstance(urls, str):
        urls = urls.split()
    return autopilot.add_sources(urls)


@app.delete("/autopilot/sources/{sid}")
def ap_remove(sid: str):
    from clipsworld import autopilot
    autopilot.remove_source(sid)
    return {"ok": True}


@app.post("/autopilot/sources/{sid}/retry")
def ap_retry_source(sid: str):
    from clipsworld import autopilot
    try:
        autopilot.retry_source(sid)
    except KeyError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


def _ap_call(fn, *a):
    try:
        return fn(*a)
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'\""))
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.post("/autopilot/items/{iid}/approve")
def ap_approve(iid: str, body: dict = Body(default={})):
    from clipsworld import autopilot
    return _ap_call(autopilot.approve, iid, body)


@app.put("/autopilot/items/{iid}")
def ap_edit(iid: str, body: dict = Body(...)):
    from clipsworld import autopilot
    return _ap_call(autopilot.edit_item, iid, body)


@app.post("/autopilot/items/{iid}/reject")
def ap_reject(iid: str):
    from clipsworld import autopilot
    return _ap_call(autopilot.reject, iid)


@app.post("/autopilot/items/{iid}/retry")
def ap_retry(iid: str):
    from clipsworld import autopilot
    return _ap_call(autopilot.retry_item, iid)


@app.delete("/autopilot/items/{iid}")
def ap_delete(iid: str):
    from clipsworld import autopilot
    _ap_call(autopilot.delete_item, iid)
    return {"ok": True}


@app.post("/autopilot/run")
def ap_run():
    from clipsworld import autopilot
    return {"started": autopilot.run_now(), "busy": autopilot.busy()}


@app.on_event("startup")
def _start_autopilot():
    if os.environ.get("CLIPSWORLD_NO_AUTOPILOT") == "1":
        return
    from clipsworld import autopilot
    autopilot.start_loop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("CLIPSWORLD_PORT", 8765)))
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    import uvicorn
    print(f"CLIPSWORLD_READY port={a.port}", flush=True)
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
