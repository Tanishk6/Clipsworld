"""User settings, saved as JSON in the Clipsworld data folder."""
import json
import threading

from .paths import data_dir, default_output_dir

DEFAULTS = {
    "claude_api_key": "",
    "claude_model": "claude-haiku-5-5",
    "whisper_model": "large-v3-turbo",   # tiny, base, small, medium, large-v3-turbo
    "device": "auto",                    # auto, cuda, cpu
    "language": "mixed",                 # mixed (Hindi+English), auto, hi, en
    "encoder": "auto",                   # auto, nvenc, x264
    "output_dir": "",
    "max_clips": 12,
    "min_clip_sec": 15,
    "max_clip_sec": 60,
}

_lock = threading.Lock()


def _file():
    return data_dir() / "settings.json"


def load() -> dict:
    with _lock:
        s = dict(DEFAULTS)
        f = _file()
        if f.exists():
            try:
                s.update(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                pass
        if not s.get("output_dir"):
            s["output_dir"] = str(default_output_dir())
        return s


def save(update: dict) -> dict:
    current = load()
    for k, v in update.items():
        if k in DEFAULTS:
            current[k] = v
    with _lock:
        _file().write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


def public(s: dict) -> dict:
    """Settings safe to send to the UI (API key masked)."""
    out = dict(s)
    key = out.pop("claude_api_key", "")
    out["has_api_key"] = bool(key)
    out["api_key_hint"] = (key[:10] + "…" + key[-4:]) if len(key) > 16 else ""
    return out
