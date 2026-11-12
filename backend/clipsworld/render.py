"""Render a clip to a finished MP4 (9:16 Short or 16:9) with burned-in captions."""
import re
import shutil
import tempfile
import time
from pathlib import Path

from . import captions, gpu, media
from .paths import IS_WIN, fonts_dir

FORMATS = {"short": (1080, 1920), "landscape": (1920, 1080), "square": (1080, 1080)}


def safe_name(s: str, limit: int = 60) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", s).strip().strip(".")
    s = re.sub(r"\s+", " ", s)
    return (s[:limit].strip() or "clip")


def video_filter(info: dict, layout: dict, out_w: int, out_h: int) -> str:
    mode = layout.get("mode", "blur")
    x = min(1.0, max(0.0, float(layout.get("crop_x", 0.5))))
    zoom = min(3.0, max(1.0, float(layout.get("zoom", 1.0))))
    target_ratio = out_w / out_h
    src_ratio = (info["width"] / info["height"]) if info.get("height") else target_ratio
    if mode == "crop" or (abs(src_ratio - target_ratio) < 0.02):
        cw = f"min(iw,ih*{target_ratio:.5f})/{zoom}"
        ch = f"min(ih,iw/{target_ratio:.5f})/{zoom}"
        v = (f"[0:v]crop=w='{cw}':h='{ch}':x='(iw-ow)*{x:.4f}':y='(ih-oh)/2',"
             f"scale={out_w}:{out_h}:flags=lanczos")
    elif mode == "fit":
        v = (f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:flags=lanczos,"
             f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:color=black")
    else:  # blur: sharp video in the middle, blurred copy filling the background
        fg_w = int(out_w * zoom)
        v = (f"[0:v]split=2[a][b];"
             f"[a]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},"
             f"boxblur=luma_radius=28:luma_power=2:chroma_radius=10,eq=brightness=-0.07:saturation=1.15[bg];"
             f"[b]scale='min({fg_w},iw*{out_h}/ih)':-2:flags=lanczos[fg];"
             f"[bg][fg]overlay=(W-w)/2:(H-h)/2")
    return v + ",setsar=1"


def _encoder_args(name: str) -> list:
    if name == "nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]


def export_clip(job, project: dict, clip: dict, settings: dict, progress_range=(0.0, 1.0)) -> dict:
    info = project["info"]
    fmt = clip.get("layout", {}).get("format", "short")
    out_w, out_h = FORMATS.get(fmt, FORMATS["short"])
    start, end = float(clip["start"]), float(clip["end"])
    dur = max(0.5, end - start)
    cap = clip.get("captions", {})

    out_dir = Path(settings.get("output_dir")) / safe_name(project.get("name", "Clipsworld"), 50)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = safe_name(clip.get("title") or "clip")
    out_path = out_dir / f"{base} [{clip['id']}].mp4"

    work = Path(tempfile.mkdtemp(prefix="cw_"))
    try:
        vf = video_filter(info, clip.get("layout", {}), out_w, out_h)
        if cap.get("enabled", True) and (cap.get("cues") or (cap.get("show_hook") and clip.get("hook"))):
            ass = captions.build_ass(
                cap.get("cues") or [], start, end, cap.get("style", "pop"), cap.get("position", "bottom"),
                cap.get("uppercase"), clip.get("hook", "") if cap.get("show_hook") else "",
                width=out_w, height=out_h)
            (work / "captions.ass").write_text(ass, encoding="utf-8")
            fonts = work / "fonts"
            fonts.mkdir()
            if fonts_dir().exists():
                for f in fonts_dir().glob("*.[ot]tf"):
                    shutil.copy(f, fonts / f.name)
            vf += ",subtitles=captions.ass:fontsdir=fonts"
        vf += ",format=yuv420p[v]"

        enc = settings.get("encoder", "auto")
        order = ["x264"]
        if enc == "nvenc" or (enc == "auto" and IS_WIN and gpu.cuda_device_count() > 0):
            order = ["nvenc", "x264"]
        a, b = progress_range
        last_err = None
        for e in order:
            try:
                job.update(stage=f"Rendering “{clip.get('title', 'clip')[:40]}” ({'GPU' if e == 'nvenc' else 'CPU'})…")
                media.run_ffmpeg(
                    ["-ss", f"{start:.3f}", "-i", project["source_path"], "-t", f"{dur:.3f}",
                     "-filter_complex", vf, "-map", "[v]", "-map", "0:a:0?", *_encoder_args(e),
                     "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart",
                     str(out_path)],
                    dur, lambda p: job.update(progress=a + (b - a) * p), cwd=str(work))
                last_err = None
                break
            except RuntimeError as err:
                last_err = err
                if e == "nvenc":
                    job.update(stage="GPU encoder not available, using CPU…")
        if last_err:
            raise last_err
        thumb = out_path.with_suffix(".jpg")
        media.thumbnail(str(out_path), min(1.0, dur / 3), thumb, width=540)
        return {"path": str(out_path), "thumb": str(thumb) if thumb.exists() else None,
                "format": fmt, "duration": round(dur, 2), "at": int(time.time())}
    finally:
        shutil.rmtree(work, ignore_errors=True)
