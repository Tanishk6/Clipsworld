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

VERSION = "1.2.0"
app = FastAPI(title="Clipsworld", version=VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


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
    _project(pid)
    return jobs.start("translate", pid, projects.translate_clip, pid, cid, body.get("target", "en")).to_dict()


@app.post("/projects/{pid}/export")
def export(pid: str, body: dict = Body(...)):
    p = _project(pid)
    ids = body.get("clip_ids") or [c["id"] for c in p["clips"]]
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
    _project(pid)
    return jobs.start("preview", pid, projects.preview, pid, cid).to_dict()


@app.post("/projects/{pid}/clips/{cid}/auto-edit")
def clip_auto_edit(pid: str, cid: str):
    _project(pid)
    return jobs.start("auto_edit", pid, projects.auto_edit, pid, cid).to_dict()


@app.post("/projects/{pid}/clips/{cid}/metadata")
def clip_metadata(pid: str, cid: str, body: dict = Body(default={})):
    _project(pid)
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
