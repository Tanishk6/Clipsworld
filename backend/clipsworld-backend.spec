# PyInstaller build of the Clipsworld engine (run from the backend/ folder).
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ["faster_whisper", "ctranslate2", "onnxruntime", "av", "tokenizers",
            "huggingface_hub", "yt_dlp", "anthropic", "uvicorn", "fastapi", "starlette"]:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["server.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["clipsworld", "clipsworld.ai", "clipsworld.captions", "clipsworld.gpu",
                                   "clipsworld.highlights", "clipsworld.jobs", "clipsworld.media",
                                   "clipsworld.paths", "clipsworld.projects", "clipsworld.render",
                                   "clipsworld.settings", "clipsworld.transcribe", "clipsworld.ytdl"],
    excludes=["tkinter", "matplotlib", "torch", "tensorflow", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="clipsworld-backend",
          console=True, upx=False, icon="../app/build/icon.ico")
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="clipsworld-backend")
