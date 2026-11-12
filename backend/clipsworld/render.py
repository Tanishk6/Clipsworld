"""Render a clip to a finished MP4 (9:16 Short, 1:1 or 16:9) with effects, captions,
voiceover / facecam bubble and sound effects."""
import re
import shutil
import tempfile
import time
from pathlib import Path

from . import captions, effects as fx, gpu, media
from .paths import IS_WIN, fonts_dir

FORMATS = {"short": (1080, 1920), "landscape": (1920, 1080), "square": (1080, 1080)}
BUBBLE_POS = ("top-right", "top-left", "bottom-right", "bottom-left", "middle-right", "middle-left")


def safe_name(s: str, limit: int = 60) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", s).strip().strip(".")
    s = re.sub(r"\s+", " ", s)
    return (s[:limit].strip() or "clip")


def video_filter(info: dict, layout: dict, out_w: int, out_h: int, src: str = "0:v") -> str:
    """Fit the source into the output frame. Returns a filter chain starting at [src]."""
    mode = layout.get("mode", "blur")
    x = min(1.0, max(0.0, float(layout.get("crop_x", 0.5))))
    zoom = min(3.0, max(1.0, float(layout.get("zoom", 1.0))))
    target_ratio = out_w / out_h
    src_ratio = (info["width"] / info["height"]) if info.get("height") else target_ratio
    if mode == "split":
        cam = layout.get("cam") or {"x": 0.70, "y": 0.0, "w": 0.30, "h": 0.30}
        cx, cy = min(0.95, max(0.0, float(cam["x"]))), min(0.95, max(0.0, float(cam["y"])))
        cw, ch = min(1 - cx, max(0.05, float(cam["w"]))), min(1 - cy, max(0.05, float(cam["h"])))
        top_h = int(out_h * min(0.6, max(0.25, float(layout.get("split", 0.42)))) // 2 * 2)
        bot_h = out_h - top_h
        bot_ratio = out_w / bot_h
        return (f"[{src}]split=2[gp][cm];"
                f"[cm]crop=w=iw*{cw:.4f}:h=ih*{ch:.4f}:x=iw*{cx:.4f}:y=ih*{cy:.4f},"
                f"scale={out_w}:{top_h}:force_original_aspect_ratio=increase:flags=lanczos,crop={out_w}:{top_h}[top];"
                f"[gp]crop=w='min(iw,ih*{bot_ratio:.5f})/{zoom}':h='min(ih,iw/{bot_ratio:.5f})/{zoom}':"
                f"x='(iw-ow)*{x:.4f}':y='(ih-oh)/2',scale={out_w}:{bot_h}:flags=lanczos[bot];"
                f"[top][bot]vstack=inputs=2,setsar=1")
    if mode == "crop" or abs(src_ratio - target_ratio) < 0.02:
        cw = f"min(iw,ih*{target_ratio:.5f})/{zoom}"
        ch = f"min(ih,iw/{target_ratio:.5f})/{zoom}"
        v = (f"[{src}]crop=w='{cw}':h='{ch}':x='(iw-ow)*{x:.4f}':y='(ih-oh)/2',"
             f"scale={out_w}:{out_h}:flags=lanczos")
    elif mode == "fit":
        v = (f"[{src}]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:flags=lanczos,"
             f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:color=black")
    else:  # blur: sharp video in the middle, blurred copy filling the background
        fg_w = int(out_w * zoom) // 2 * 2
        v = (f"[{src}]split=2[bga][bgb];"
             f"[bga]scale={out_w // 4}:{out_h // 4}:force_original_aspect_ratio=increase,crop={out_w // 4}:{out_h // 4},"
             f"boxblur=luma_radius=8:luma_power=2:chroma_radius=4,eq=brightness=-0.07:saturation=1.15,"
             f"scale={out_w}:{out_h}[bg];"
             f"[bgb]scale='min({fg_w},iw*{out_h}/ih)':-2:flags=lanczos[fg];"
             f"[bg][fg]overlay=(W-w)/2:(H-h)/2")
    return v + ",setsar=1"


def _encoder_args(name: str, preview: bool) -> list:
    if preview:
        return ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "30"]
    if name == "nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]


def _make_bubble_assets(work: Path, size: int):
    """Circle mask + gradient ring PNGs for the facecam bubble."""
    r = size / 2
    media._run([media.tool("ffmpeg"), "-hide_banner", "-y", "-f", "lavfi", "-i",
                f"color=c=black:s={size}x{size}:d=1,format=gray,"
                f"geq=lum='255*clip(({r - 1}-hypot(X-{r},Y-{r}))/1.5,0,1)'",
                "-frames:v", "1", str(work / "mask.png")])
    R = r + 8
    S = int(R * 2)
    media._run([media.tool("ffmpeg"), "-hide_banner", "-y", "-f", "lavfi", "-i",
                f"color=c=black:s={S}x{S}:d=1,format=rgba,"
                f"geq=r='124+131*X/W':g='92-13*X/W':b='255-39*Y/H':"
                f"a='255*clip(({R - 1}-hypot(X-{R},Y-{R}))/1.5,0,1)'",
                "-frames:v", "1", str(work / "ring.png")])


def plan_output(clip: dict):
    L = max(0.5, float(clip["end"]) - float(clip["start"]))
    effs = [e for e in clip.get("effects", []) if e.get("type") in fx.TYPES and 0 <= float(e.get("t", 0)) <= L]
    segs = fx.build_timeline(L, effs)
    return L, effs, segs, fx.total_duration(segs)


def export_clip(job, project: dict, clip: dict, settings: dict, progress_range=(0.0, 1.0),
                preview: bool = False, preview_path: Path | None = None) -> dict:
    info = project["info"]
    fps = min(60.0, float(info.get("fps") or 30.0))
    lay = clip.get("layout", {})
    fmt = lay.get("format", "short")
    out_w, out_h = FORMATS.get(fmt, FORMATS["short"])
    if preview:
        out_w, out_h = out_w // 2 // 2 * 2, out_h // 2 // 2 * 2
    start = float(clip["start"])
    L, effs, segs, total = plan_output(clip)
    cap = clip.get("captions", {})
    aud = clip.get("audio", {}) or {}

    if preview:
        out_path = preview_path
    else:
        from .paths import default_output_dir
        base = Path(settings.get("output_dir") or default_output_dir())
        out_dir = base / safe_name(project.get("name", "Clipsworld"), 50)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            out_dir = default_output_dir() / safe_name(project.get("name", "Clipsworld"), 50)
            out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{safe_name(clip.get('title') or 'clip')} [{clip['id']}].mp4"

    work = Path(tempfile.mkdtemp(prefix="cw_"))
    try:
        inputs = ["-ss", f"{start:.3f}", "-t", f"{L + 0.6:.3f}", "-i", project["source_path"]]
        n_in = 1
        parts = []
        seg_f, vlab, alab = fx.segments_filter(segs, fps)
        parts.append(seg_f)
        parts.append(video_filter(info, lay, out_w, out_h, src=f"{vlab}").replace(f"[{vlab}]", f"[{vlab}]fps={fps:.4f},", 1)
                     + "[vl]")
        cur = "vl"
        z = fx.zoom_filter(segs, effs, out_w, out_h, fps)
        if z:
            parts.append(f"[{cur}]{z}[vz]")
            cur = "vz"

        # voiceover / facecam reaction
        vo = aud.get("vo_file")
        vo_ok = bool(vo) and Path(vo).exists()
        vo_idx = None
        if vo_ok:
            inputs += ["-i", vo]
            vo_idx = n_in
            n_in += 1
            bub = aud.get("bubble", {}) or {}
            if aud.get("vo_has_video") and bub.get("show", True):
                size = int(out_w * min(0.6, max(0.15, float(bub.get("size", 0.34))))) // 2 * 2
                _make_bubble_assets(work, size)
                inputs += ["-loop", "1", "-i", str(work / "mask.png"), "-loop", "1", "-i", str(work / "ring.png")]
                m_idx, r_idx = n_in, n_in + 1
                n_in += 2
                margin = int(out_w * 0.045)
                pos = bub.get("pos", "top-right")
                bx = f"W-w-{margin}" if pos.endswith("right") else f"{margin}"
                by = {"top": f"{int(out_h * 0.14)}", "bottom": f"H-h-{int(out_h * 0.24)}",
                      "middle": "(H-h)/2"}[pos.split("-")[0]]
                parts.append(f"[{vo_idx}:v]setpts=PTS-STARTPTS,scale={size}:{size}:force_original_aspect_ratio=increase,"
                             f"crop={size}:{size},format=yuva420p[cam]")
                parts.append(f"[{m_idx}:v]format=gray,scale={size}:{size}[mk]")
                parts.append("[cam][mk]alphamerge[bub]")
                parts.append(f"[{cur}][{r_idx}:v]overlay=x='{bx}-8':y='{by}-8':shortest=1:format=auto[vr]")
                parts.append(f"[vr][bub]overlay=x='{bx}':y='{by}':eof_action=pass:format=auto[vb]")
                cur = "vb"

        # captions + text pops + replay badge
        cues = fx.map_cues(segs, cap.get("cues") or [], start, cap.get("replay_captions", True)) \
            if cap.get("enabled", True) else []
        extra = fx.text_events(segs, effs, cap.get("position", "bottom") if cues else "")
        hook = clip.get("hook", "") if cap.get("show_hook") else ""
        if cues or extra or hook:
            ass = captions.build_ass(cues, 0.0, total, cap.get("style", "hormozi"), cap.get("position", "bottom"),
                                     cap.get("uppercase"), hook, width=out_w, height=out_h, extra=extra)
            (work / "captions.ass").write_text(ass, encoding="utf-8")
            fonts = work / "fonts"
            fonts.mkdir()
            if fonts_dir().exists():
                for f in fonts_dir().glob("*.[ot]tf"):
                    shutil.copy(f, fonts / f.name)
            parts.append(f"[{cur}]subtitles=captions.ass:fontsdir=fonts[vs]")
            cur = "vs"
        parts.append(f"[{cur}]format=yuv420p[v]")

        # audio: original + voiceover (with ducking) + sound effects
        afmt = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
        orig_v = float(aud.get("orig_volume", 1.0))
        parts.append(f"[{alab}]volume={orig_v:.3f}[ab]")
        mix = ["ab"]
        if vo_ok:
            parts.append(f"[{vo_idx}:a]asetpts=PTS-STARTPTS,{afmt},volume={float(aud.get('vo_volume', 1.0)):.3f}[vo]")
            if aud.get("duck", True):
                parts.append("[vo]asplit=2[vo1][vo2]")
                parts.append("[ab][vo1]sidechaincompress=threshold=0.02:ratio=6:attack=15:release=350[abd]")
                mix = ["abd", "vo2"]
            else:
                mix.append("vo")
        for k, s in enumerate(fx.sound_events(segs, effs)):
            inputs += ["-i", s["path"]]
            ms = int(s["t"] * 1000)
            parts.append(f"[{n_in}:a]{afmt},volume={s['volume']:.3f},adelay={ms}|{ms}[sx{k}]")
            mix.append(f"sx{k}")
            n_in += 1
        if len(mix) > 1:
            parts.append("".join(f"[{m}]" for m in mix) +
                         f"amix=inputs={len(mix)}:duration=first:dropout_transition=0:normalize=0,"
                         f"alimiter=limit=0.95:level=disabled[a]")
        else:
            parts.append(f"[{mix[0]}]anull[a]")

        graph = ";\n".join(parts)
        (work / "graph.txt").write_text(graph, encoding="utf-8")

        enc = settings.get("encoder", "auto")
        order = ["x264"]
        if not preview and (enc == "nvenc" or (enc == "auto" and IS_WIN and gpu.cuda_device_count() > 0)):
            order = ["nvenc", "x264"]
        a, b = progress_range
        last_err = None
        for e in order:
            try:
                label = "preview" if preview else f"“{clip.get('title', 'clip')[:40]}”"
                job.update(stage=f"Rendering {label} ({'GPU' if e == 'nvenc' else 'CPU'})…")
                media.run_ffmpeg(
                    inputs + media.filter_script_args("graph.txt") + ["-map", "[v]", "-map", "[a]",
                              "-t", f"{total:.3f}", "-r", f"{fps:.4f}", *_encoder_args(e, preview),
                              "-c:a", "aac", "-b:a", "96k" if preview else "192k", "-ar", "48000",
                              "-movflags", "+faststart", str(out_path)],
                    total, lambda p: job.update(progress=a + (b - a) * p), cwd=str(work))
                last_err = None
                break
            except RuntimeError as err:
                last_err = err
                if e == "nvenc":
                    job.update(stage="GPU encoder not available, using CPU…")
        if last_err:
            raise last_err
        if preview:
            return {"path": str(out_path), "duration": round(total, 2)}
        thumb = out_path.with_suffix(".jpg")
        media.thumbnail(str(out_path), min(1.0, total / 3), thumb, width=540)
        meta = clip.get("meta") or {}
        if meta:
            txt = out_path.with_suffix(".txt")
            tags = " ".join(meta.get("hashtags", []))
            txt.write_text(f"TITLE:\n{meta.get('title', clip.get('title', ''))}\n\nDESCRIPTION:\n"
                           f"{meta.get('description', '')}\n\nHASHTAGS:\n{tags}\n", encoding="utf-8")
        return {"path": str(out_path), "thumb": str(thumb) if thumb.exists() else None,
                "format": fmt, "duration": round(total, 2), "at": int(time.time())}
    finally:
        shutil.rmtree(work, ignore_errors=True)
