"""FFmpeg helpers: probing, audio extraction, loudness analysis, running encodes."""
import json
import subprocess
import wave
from pathlib import Path

import numpy as np

from .paths import IS_WIN, tool

NO_WINDOW = 0x08000000 if IS_WIN else 0


def _run(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", creationflags=NO_WINDOW, **kw)


def probe(path: str) -> dict:
    r = _run([tool("ffprobe"), "-v", "error", "-print_format", "json",
              "-show_format", "-show_streams", path])
    if r.returncode != 0:
        raise RuntimeError(f"Can't read this video: {r.stderr.strip()[-300:]}")
    info = json.loads(r.stdout)
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not a:
        raise RuntimeError("This video has no audio track, so Clipsworld can't find clips in it.")
    dur = float(info.get("format", {}).get("duration") or (v or a).get("duration") or 0)
    fps = 30.0
    if v and v.get("avg_frame_rate", "0/0") != "0/0":
        n, d = v["avg_frame_rate"].split("/")
        fps = float(n) / float(d) if float(d) else 30.0
    return {
        "duration": dur,
        "width": int(v["width"]) if v else 0,
        "height": int(v["height"]) if v else 0,
        "fps": round(fps, 3),
        "has_video": v is not None,
        "vcodec": (v or {}).get("codec_name", ""),
    }


_FF_MAJOR = None


def ffmpeg_major() -> int:
    global _FF_MAJOR
    if _FF_MAJOR is None:
        r = _run([tool("ffmpeg"), "-hide_banner", "-version"])
        import re as _re
        m = _re.search(r"ffmpeg version (?:n)?(\d+)\.", r.stdout)
        _FF_MAJOR = int(m.group(1)) if m else 99  # git/master builds are new
    return _FF_MAJOR


def filter_script_args(path: str) -> list:
    """-filter_complex from a file (new syntax on FFmpeg 7+, old option on 6)."""
    return ["-/filter_complex", path] if ffmpeg_major() >= 7 else ["-filter_complex_script", path]


def run_ffmpeg(args: list, duration: float, on_progress=None, cwd=None):
    """Run ffmpeg, reporting 0..1 progress from its -progress output."""
    cmd = [tool("ffmpeg"), "-hide_banner", "-y", "-nostats", "-progress", "pipe:1"] + args
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace", creationflags=NO_WINDOW, cwd=cwd)
    err_tail = []

    import threading

    def read_err():
        for line in p.stderr:
            err_tail.append(line)
            if len(err_tail) > 40:
                err_tail.pop(0)

    t = threading.Thread(target=read_err, daemon=True)
    t.start()
    try:
        for line in p.stdout:
            if line.startswith("out_time_us=") and duration > 0 and on_progress:
                try:
                    us = int(line.split("=", 1)[1])
                    on_progress(min(1.0, us / 1e6 / duration))
                except ValueError:
                    pass
    except BaseException:
        p.kill()
        raise
    p.wait()
    t.join(timeout=2)
    if p.returncode != 0:
        raise RuntimeError("FFmpeg failed: " + "".join(err_tail)[-800:])


def extract_audio(src: str, dst: Path, duration: float, on_progress=None):
    run_ffmpeg(["-i", src, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)],
               duration, on_progress)


def loudness_curve(wav_path: Path, hop: float = 0.25) -> list:
    """Loudness (dBFS) every `hop` seconds. Used for the waveform and highlight finder."""
    with wave.open(str(wav_path), "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        step = int(sr * hop)
        out = []
        while True:
            frames = w.readframes(step * 240)  # read ~1 minute at a time
            if not frames:
                break
            x = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            m = len(x) // step
            if m == 0:
                break
            blocks = x[: m * step].reshape(m, step)
            rms = np.sqrt(np.mean(blocks ** 2, axis=1) + 1e-12)
            out.extend((20 * np.log10(rms)).round(2).tolist())
        _ = n
    return out


def thumbnail(src: str, at: float, dst: Path, width: int = 480):
    r = _run([tool("ffmpeg"), "-hide_banner", "-y", "-ss", f"{max(0, at):.2f}", "-i", src,
              "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", str(dst)])
    return r.returncode == 0 and dst.exists()


def make_preview(src: str, dst: Path, duration: float, on_progress=None):
    """Small browser-friendly H.264 copy, used when the source can't play in the app."""
    run_ffmpeg(["-i", src, "-vf", "scale=-2:'min(540,ih)'", "-c:v", "libx264", "-preset", "ultrafast",
                "-crf", "30", "-tune", "fastdecode", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(dst)],
               duration, on_progress)
