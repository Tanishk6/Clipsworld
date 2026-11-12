"""NVIDIA GPU support for Whisper.

faster-whisper needs CUDA 12 cuBLAS + cuDNN 9 DLLs on Windows. They are ~1 GB, so instead of
shipping them in the installer, Clipsworld downloads them once (the "GPU pack") from the
official NVIDIA wheels on PyPI and keeps them in %APPDATA%/Clipsworld/gpu.
"""
import os

from .paths import IS_WIN, gpu_dir

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


def install_pack(job=None):
    """Start (or resume) the GPU pack download in the background."""
    from . import downloads
    return downloads.start("gpu")
