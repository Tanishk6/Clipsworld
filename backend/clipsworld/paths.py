"""Where Clipsworld keeps its data and finds its bundled tools."""
import os
import shutil
import sys
from pathlib import Path

IS_WIN = sys.platform == "win32"


def data_dir() -> Path:
    env = os.environ.get("CLIPSWORLD_DATA")
    if env:
        p = Path(env)
    elif IS_WIN:
        p = Path(os.environ.get("APPDATA", str(Path.home()))) / "Clipsworld"
    else:
        p = Path.home() / ".clipsworld"
    p.mkdir(parents=True, exist_ok=True)
    return p


def projects_dir() -> Path:
    p = data_dir() / "projects"
    p.mkdir(parents=True, exist_ok=True)
    return p


def models_dir() -> Path:
    p = data_dir() / "models"
    p.mkdir(parents=True, exist_ok=True)
    return p


def gpu_dir() -> Path:
    p = data_dir() / "gpu"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_output_dir() -> Path:
    p = Path.home() / "Videos" / "Clipsworld"
    p.mkdir(parents=True, exist_ok=True)
    return p


def resources_dir() -> Path:
    env = os.environ.get("CLIPSWORLD_RESOURCES")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        # PyInstaller build lives in <app>/resources/backend/
        return Path(sys.executable).resolve().parent.parent
    return Path(__file__).resolve().parents[2] / "resources"


def fonts_dir() -> Path:
    return resources_dir() / "fonts"


def tool(name: str) -> str:
    """Find ffmpeg / ffprobe: bundled copy first, then PATH."""
    exe = name + (".exe" if IS_WIN else "")
    bundled = resources_dir() / "ffmpeg" / exe
    if bundled.exists():
        return str(bundled)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(f"{name} not found. Reinstall Clipsworld or put {name} in PATH.")
