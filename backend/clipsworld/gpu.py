"""NVIDIA GPU support for Whisper.

faster-whisper needs CUDA 12 cuBLAS + cuDNN 9 DLLs on Windows. They are ~1 GB, so instead of
shipping them in the installer, Clipsworld downloads them once (the "GPU pack") from the
official NVIDIA wheels on PyPI and keeps them in %APPDATA%/Clipsworld/gpu.
"""
import json
import os
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


def install_pack(job):
    if not IS_WIN:
        raise RuntimeError("The GPU pack is only needed on Windows.")
    d = gpu_dir()
    tmp = d / "_download"
    tmp.mkdir(exist_ok=True)
    wheels = [(_pick_wheel(p, pre), p) for p, pre in PACKAGES]
    total = sum(w["size"] for w, _ in wheels) or 1
    done = 0
    for w, name in wheels:
        dest = tmp / w["filename"]
        job.update(stage=f"Downloading {name} ({w['size'] // (1024 * 1024)} MB)…")
        with urllib.request.urlopen(w["url"], timeout=60) as r, open(dest, "wb") as out:
            while True:
                chunk = r.read(1024 * 512)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                job.update(progress=0.95 * done / total)
        job.update(stage=f"Unpacking {name}…")
        with zipfile.ZipFile(dest) as z:
            for member in z.namelist():
                if member.lower().endswith(".dll") and "/bin/" in member.replace("\\", "/"):
                    target = d / Path(member).name
                    with z.open(member) as src, open(target, "wb") as out:
                        out.write(src.read())
        dest.unlink(missing_ok=True)
    missing = [n for n in REQUIRED if not (d / n).exists()]
    if missing:
        raise RuntimeError("GPU pack is incomplete, missing: " + ", ".join(missing))
    activate()
    return {"installed": True}
