"""NVIDIA GPU support for Whisper.

faster-whisper needs CUDA 12 cuBLAS + cuDNN 9 DLLs on Windows. They are ~1 GB, so instead of
shipping them in the installer, Clipsworld downloads them once (the "GPU pack") from the
official NVIDIA wheels on PyPI and keeps them in %APPDATA%/Clipsworld/gpu.
"""
import hashlib
import json
import os
import shutil
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from .paths import IS_WIN, gpu_dir

PACKAGES = [
    ("nvidia-cublas-cu12", "12."),
    ("nvidia-cudnn-cu12", "9."),
    ("nvidia-cuda-nvrtc-cu12", "12."),
]
REQUIRED = ["cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll", "cudnn_ops64_9.dll"]

_added = False


def activate():
    """Make the GPU pack DLLs findable. Call before loading Whisper."""
    global _added
    if _added or not IS_WIN:
        return
    d = gpu_dir()
    if any(d.glob("*.dll")):
        os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
        try:
            os.add_dll_directory(str(d))
        except (AttributeError, OSError):
            pass
        _added = True


def pack_installed() -> bool:
    if not IS_WIN:
        return False
    d = gpu_dir()
    return all((d / n).exists() for n in REQUIRED)


def cuda_device_count() -> int:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count()
    except Exception:
        return 0


def status() -> dict:
    return {
        "platform_supported": IS_WIN,
        "nvidia_gpus": cuda_device_count(),
        "pack_installed": pack_installed(),
    }


def _pick_wheel(pkg: str, major_prefix: str) -> dict:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{pkg}/json", timeout=30) as r:
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


_install_lock = threading.Lock()


def _download(job, url: str, dest: Path, size: int, sha256: str, label: str, done_before: int, total: int):
    """Resumable download with retries and checksum, so a dropped connection doesn't break the pack."""
    for attempt in range(8):
        have = dest.stat().st_size if dest.exists() else 0
        if have > size:
            dest.unlink()
            have = 0
        if have < size:
            req = urllib.request.Request(url, headers={"User-Agent": "Clipsworld/1.0",
                                                       **({"Range": f"bytes={have}-"} if have else {})})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    if have and r.status != 206:  # server ignored the range: start over
                        have = 0
                    with open(dest, "ab" if have else "wb") as out:
                        while True:
                            chunk = r.read(1024 * 512)
                            if not chunk:
                                break
                            out.write(chunk)
                            have += len(chunk)
                            job.update(progress=0.95 * (done_before + have) / total,
                                       stage=f"Downloading {label}… {have // 1048576} / {size // 1048576} MB")
            except Exception as e:  # noqa: BLE001
                job.update(stage=f"Connection dropped, retrying ({attempt + 1})… {e.__class__.__name__}")
                time.sleep(min(20, 2 + attempt * 3))
                continue
        if dest.stat().st_size == size:
            job.update(stage=f"Checking {label}…")
            h = hashlib.sha256()
            with open(dest, "rb") as f:
                for block in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(block)
            if not sha256 or h.hexdigest() == sha256:
                return
            dest.unlink()  # corrupted: download again
        time.sleep(2)
    raise RuntimeError(f"Couldn't download {label} — check your internet connection and try again.")


def install_pack(job):
    if not IS_WIN:
        raise RuntimeError("The GPU pack is only needed on Windows.")
    if not _install_lock.acquire(blocking=False):
        raise RuntimeError("The GPU pack is already downloading.")
    try:
        d = gpu_dir()
        tmp = d / "_download"
        tmp.mkdir(parents=True, exist_ok=True)
        job.update(stage="Finding NVIDIA files…")
        wheels = [(_pick_wheel(p, pre), p) for p, pre in PACKAGES]
        total = sum(w["size"] for w, _ in wheels) or 1
        done = 0
        for w, name in wheels:
            dest = tmp / w["filename"]
            _download(job, w["url"], dest, w["size"], (w.get("digests") or {}).get("sha256", ""), name, done, total)
            done += w["size"]
            job.update(progress=0.95 * done / total, stage=f"Unpacking {name}…")
            if not zipfile.is_zipfile(dest):
                dest.unlink(missing_ok=True)
                raise RuntimeError(f"{name} download was damaged. Press the button again to retry.")
            with zipfile.ZipFile(dest) as z:
                for member in z.namelist():
                    if member.lower().endswith(".dll") and "/bin/" in member.replace("\\", "/"):
                        with z.open(member) as src, open(d / Path(member).name, "wb") as out:
                            shutil.copyfileobj(src, out, 1024 * 1024)
            dest.unlink(missing_ok=True)
        missing = [n for n in REQUIRED if not (d / n).exists()]
        if missing:
            raise RuntimeError("GPU pack is incomplete, missing: " + ", ".join(missing))
        activate()
        return {"installed": True}
    finally:
        _install_lock.release()
