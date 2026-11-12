"""Background downloads with pause / resume / retry / checksum.

Used for the NVIDIA GPU pack and the Whisper speech models. Partial files stay on disk, so a
download continues where it stopped — after a pause, a dropped connection or an app restart.
"""
import hashlib
import json
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from .paths import IS_WIN, gpu_dir, models_dir

UA = {"User-Agent": "Clipsworld/1.1"}
WHISPER_REPOS = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "large-v3": "Systran/faster-whisper-large-v3",
}
MODEL_FILES = {"config.json", "model.bin", "tokenizer.json", "vocabulary.json", "vocabulary.txt",
               "preprocessor_config.json"}

_tasks: dict = {}
_lock = threading.Lock()


class Paused(Exception):
    pass


class Task:
    def __init__(self, key: str, label: str):
        self.key = key
        self.label = label
        self.state = "idle"      # idle, preparing, downloading, paused, done, error
        self.files = []          # [{name, url, dest, size, sha256}]
        self.done_bytes = 0
        self.total_bytes = 0
        self.speed = 0.0
        self.stage = ""
        self.error = None
        self.pause_flag = False
        self.thread = None

    def to_dict(self):
        return {"key": self.key, "label": self.label, "state": self.state, "done_bytes": self.done_bytes,
                "total_bytes": self.total_bytes, "speed": round(self.speed), "stage": self.stage,
                "error": self.error,
                "progress": round(self.done_bytes / self.total_bytes, 4) if self.total_bytes else 0}


# ------------------------------------------------------------------ task definitions

def _model_dir(name: str) -> Path:
    return models_dir() / f"whisper-{name}"


def model_ready(name: str) -> bool:
    d = _model_dir(name)
    man = d / "manifest.json"
    if not man.exists():
        return False
    try:
        files = json.loads(man.read_text(encoding="utf-8"))
    except Exception:
        return False
    return all((d / f["name"]).exists() and (d / f["name"]).stat().st_size == f["size"] for f in files)


def model_path(name: str) -> Path:
    return _model_dir(name)


def _model_files(name: str) -> list:
    d = _model_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    man = d / "manifest.json"
    if man.exists():
        try:
            files = json.loads(man.read_text(encoding="utf-8"))
            if files:
                return [dict(f, dest=str(d / f["name"])) for f in files]
        except Exception:
            pass
    repo = WHISPER_REPOS.get(name)
    if not repo:
        raise RuntimeError(f"Unknown speech model: {name}")
    with urllib.request.urlopen(urllib.request.Request(
            f"https://huggingface.co/api/models/{repo}?blobs=true", headers=UA), timeout=30) as r:
        info = json.load(r)
    real = info.get("id", repo)
    files = []
    for s in info.get("siblings", []):
        if s["rfilename"] in MODEL_FILES:
            files.append({"name": s["rfilename"], "size": int(s.get("size") or 0),
                          "sha256": (s.get("lfs") or {}).get("sha256", ""),
                          "url": f"https://huggingface.co/{real}/resolve/main/{s['rfilename']}"})
    if not any(f["name"] == "model.bin" for f in files):
        raise RuntimeError("Speech model files not found online.")
    man.write_text(json.dumps(files), encoding="utf-8")
    return [dict(f, dest=str(d / f["name"])) for f in files]


GPU_PACKAGES = [("nvidia-cublas-cu12", "12."), ("nvidia-cudnn-cu12", "9."), ("nvidia-cuda-nvrtc-cu12", "12.")]


def _pick_wheel(pkg: str, major_prefix: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(f"https://pypi.org/pypi/{pkg}/json", headers=UA),
                                timeout=30) as r:
        data = json.load(r)

    def ver_key(v):
        return [int(p) if p.isdigit() else 0 for p in v.split(".")]

    for v in sorted(data["releases"], key=ver_key, reverse=True):
        if not v.startswith(major_prefix) or any(c.isalpha() for c in v.replace(".", "")):
            continue
        for f in data["releases"][v]:
            if f["filename"].endswith("win_amd64.whl"):
                return f
    raise RuntimeError(f"No Windows download found for {pkg}")


def _gpu_files() -> list:
    tmp = gpu_dir() / "_download"
    tmp.mkdir(parents=True, exist_ok=True)
    man = tmp / "manifest.json"
    if man.exists():
        try:
            return json.loads(man.read_text(encoding="utf-8"))
        except Exception:
            pass
    files = []
    for pkg, pre in GPU_PACKAGES:
        w = _pick_wheel(pkg, pre)
        files.append({"name": pkg, "url": w["url"], "size": w["size"],
                      "sha256": (w.get("digests") or {}).get("sha256", ""), "dest": str(tmp / w["filename"])})
    man.write_text(json.dumps(files), encoding="utf-8")
    return files


def _gpu_finish(task: Task):
    from . import gpu
    d = gpu_dir()
    for f in task.files:
        p = Path(f["dest"])
        task.stage = f"Unpacking {f['name']}…"
        if not zipfile.is_zipfile(p):
            p.unlink(missing_ok=True)
            raise RuntimeError(f"{f['name']} was damaged. Press Resume to download it again.")
        with zipfile.ZipFile(p) as z:
            for member in z.namelist():
                if member.lower().endswith(".dll") and "/bin/" in member.replace("\\", "/"):
                    with z.open(member) as src, open(d / Path(member).name, "wb") as out:
                        while True:
                            b = src.read(1024 * 1024)
                            if not b:
                                break
                            out.write(b)
    missing = [n for n in gpu.REQUIRED if not (d / n).exists()]
    if missing:
        raise RuntimeError("GPU pack is incomplete, missing: " + ", ".join(missing))
    for f in task.files:
        Path(f["dest"]).unlink(missing_ok=True)
    (gpu_dir() / "_download" / "manifest.json").unlink(missing_ok=True)
    gpu.activate()


def _definition(key: str):
    if key == "gpu":
        if not IS_WIN:
            raise RuntimeError("The GPU pack is only needed on Windows.")
        return "NVIDIA GPU pack", _gpu_files, _gpu_finish
    if key.startswith("model:"):
        name = key.split(":", 1)[1]
        return f"Speech model ({name})", lambda: _model_files(name), None
    raise KeyError(key)


def is_done(key: str) -> bool:
    if key == "gpu":
        from . import gpu
        return gpu.pack_installed()
    if key.startswith("model:"):
        return model_ready(key.split(":", 1)[1])
    return False


# ------------------------------------------------------------------ engine

def _part_size(f) -> int:
    p = Path(f["dest"])
    if p.exists():
        return p.stat().st_size
    part = Path(f["dest"] + ".part")
    return part.stat().st_size if part.exists() else 0


def _download_file(task: Task, f: dict, base: int):
    dest = Path(f["dest"])
    part = Path(f["dest"] + ".part")
    size = int(f["size"])
    if dest.exists() and dest.stat().st_size == size:
        return
    for attempt in range(10):
        have = part.stat().st_size if part.exists() else 0
        if have > size:
            part.unlink()
            have = 0
        if have < size:
            headers = dict(UA)
            if have:
                headers["Range"] = f"bytes={have}-"
            try:
                with urllib.request.urlopen(urllib.request.Request(f["url"], headers=headers), timeout=60) as r:
                    if have and r.status != 206:
                        have = 0
                    t0, b0 = time.time(), have
                    with open(part, "ab" if have else "wb") as out:
                        while True:
                            if task.pause_flag:
                                raise Paused()
                            chunk = r.read(1024 * 256)
                            if not chunk:
                                break
                            out.write(chunk)
                            have += len(chunk)
                            task.done_bytes = base + have
                            dt = time.time() - t0
                            if dt > 1:
                                task.speed = (have - b0) / dt
                            task.stage = f"Downloading {f['name']}"
            except Paused:
                raise
            except Exception as e:  # noqa: BLE001
                task.stage = f"Connection problem, retrying ({attempt + 1}/10)… {e.__class__.__name__}"
                for _ in range(int(min(20, 2 + attempt * 3) * 4)):
                    if task.pause_flag:
                        raise Paused()
                    time.sleep(0.25)
                continue
        if part.exists() and part.stat().st_size == size:
            if f.get("sha256"):
                task.stage = f"Checking {f['name']}…"
                h = hashlib.sha256()
                with open(part, "rb") as fh:
                    for block in iter(lambda: fh.read(1024 * 1024), b""):
                        h.update(block)
                if h.hexdigest() != f["sha256"]:
                    part.unlink()
                    task.stage = f"{f['name']} was damaged, downloading again…"
                    continue
            part.replace(dest)
            return
    raise RuntimeError(f"Couldn't download {f['name']}. Check your internet and press Resume.")


def _run(task: Task, finish):
    try:
        task.state = "downloading"
        base = 0
        for f in task.files:
            _download_file(task, f, base)
            base += int(f["size"])
            task.done_bytes = base
        if finish:
            task.state = "preparing"
            finish(task)
        task.state = "done"
        task.stage = "Ready"
        task.done_bytes = task.total_bytes
    except Paused:
        task.state = "paused"
        task.stage = "Paused"
        task.speed = 0
    except Exception as e:  # noqa: BLE001
        task.state = "error"
        task.error = str(e)
        task.stage = "Failed"
        task.speed = 0


def _get(key: str) -> Task:
    with _lock:
        t = _tasks.get(key)
        if not t:
            label, _, _ = _definition(key)
            t = Task(key, label)
            _tasks[key] = t
        return t


def status(key: str) -> dict:
    t = _get(key)
    if t.state in ("idle", "error", "paused") and is_done(key):
        t.state = "done"
    if t.state in ("idle", "paused") and not t.total_bytes:
        # show how much is already on disk from an earlier session
        try:
            label, files_fn, _ = _definition(key)
            man_known = (key == "gpu" and (gpu_dir() / "_download" / "manifest.json").exists()) or \
                        (key.startswith("model:") and (_model_dir(key[6:]) / "manifest.json").exists())
            if man_known:
                files = files_fn()
                t.total_bytes = sum(int(f["size"]) for f in files)
                t.done_bytes = sum(min(int(f["size"]), _part_size(f)) for f in files)
                if t.done_bytes and t.state == "idle":
                    t.state = "paused"
                    t.stage = "Paused"
        except Exception:
            pass
    return t.to_dict()


def start(key: str) -> dict:
    t = _get(key)
    if is_done(key):
        t.state = "done"
        return t.to_dict()
    if t.state in ("downloading", "preparing") and t.thread and t.thread.is_alive():
        return t.to_dict()
    label, files_fn, finish = _definition(key)
    t.pause_flag = False
    t.error = None
    t.state = "downloading"
    t.stage = "Starting…"

    def go():
        try:
            t.files = files_fn()
            t.total_bytes = sum(int(f["size"]) for f in t.files)
            t.done_bytes = sum(min(int(f["size"]), _part_size(f)) for f in t.files)
        except Exception as e:  # noqa: BLE001
            t.state = "error"
            t.error = f"Couldn't reach the download server: {e}"
            t.stage = "Failed"
            return
        _run(t, finish)

    t.thread = threading.Thread(target=go, daemon=True)
    t.thread.start()
    return t.to_dict()


def pause(key: str) -> dict:
    t = _get(key)
    if t.state == "downloading":
        t.pause_flag = True
    return t.to_dict()


def all_status(model_name: str) -> list:
    keys = ["gpu"] if IS_WIN else []
    keys.append(f"model:{model_name}")
    keys += [k for k in list(_tasks) if k not in keys and _tasks[k].state in ("downloading", "paused", "preparing")]
    out = []
    for k in keys:
        try:
            out.append(status(k))
        except Exception:
            pass
    return out


def wait_for(key: str, job, stage_prefix: str):
    """Block a job until the download is done (shows progress; respects pause)."""
    if is_done(key):
        return
    start(key)
    while True:
        t = _get(key)
        if t.state == "done":
            return
        if t.state == "error":
            raise RuntimeError(t.error or "Download failed")
        mb = f"{t.done_bytes // 1048576} / {t.total_bytes // 1048576} MB" if t.total_bytes else ""
        if t.state == "paused":
            job.update(stage=f"{stage_prefix} paused at {mb} — press Resume in Settings to continue")
        else:
            sp = f" · {t.speed / 1048576:.1f} MB/s" if t.speed else ""
            job.update(stage=f"{stage_prefix}… {mb}{sp} (first time only)")
        time.sleep(0.7)
