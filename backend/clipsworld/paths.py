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


def _windows_videos_folder() -> Path | None:
    """The real Videos folder (it may be moved to OneDrive or another drive)."""
    if not IS_WIN:
        return None
    try:
        import ctypes
        import uuid
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        folder_id = GUID.from_buffer_copy(uuid.UUID("{18989B1D-99B5-455B-841C-AB7C74E4DDFC}").bytes_le)
        out = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(out)) == 0:
            path = out.value
            ctypes.windll.ole32.CoTaskMemFree(out)
            return Path(path) if path else None
    except Exception:
        pass
    return None


_OUTPUT_DIR = None


def default_output_dir() -> Path:
    """First folder we can actually create: Videos\\Clipsworld, then a few safe fallbacks."""
    global _OUTPUT_DIR
    if _OUTPUT_DIR:
        return _OUTPUT_DIR
    home = Path.home()
    candidates = [_windows_videos_folder(), home / "Videos", home / "OneDrive" / "Videos",
                  home / "Documents", data_dir()]
    for base in candidates:
        if not base:
            continue
        p = base / "Clipsworld" if base != data_dir() else base / "exports"
        try:
            p.mkdir(parents=True, exist_ok=True)
            _OUTPUT_DIR = p
            return p
        except OSError:
            continue
    _OUTPUT_DIR = data_dir()
    return _OUTPUT_DIR


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
