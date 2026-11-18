"""Thumbnail maker: Claude looks at the best frames of a clip, picks one and writes the text; Clipsworld
designs the thumbnail (zoomed subject, huge outlined headline, highlight circle + arrow, banner).

Shorts thumbnails are shown in different shapes (vertical shelf, ~3:2 in search, 16:9 elsewhere), so the
vertical design keeps everything important inside the middle band and survives any of those crops.
"""
import io
import json
import math
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import ai, captions, media
from .paths import fonts_dir

COLORS = {"yellow": "#FFE600", "white": "#FFFFFF", "red": "#FF2D2D", "green": "#3DFF6E", "cyan": "#2DE2FF",
          "orange": "#FF8A00", "pink": "#FF4FD8"}
FONTS = ["Luckiest Guy", "Anton", "Bangers", "Bebas Neue", "Montserrat Black", "Lilita One", "Archivo Black"]

SYSTEM = """You design YouTube Shorts thumbnails for an Indian gaming/funny clips channel (Hinglish audience).
You get several frames from one clip plus its captions. Pick the single frame with the clearest, most
expressive or most surprising moment (big reaction, explosion, clutch, funny face, something weird).
Then write the thumbnail text:
- headline: 2-4 words, MAX 22 characters, Roman script only (Hinglish or English, never Devanagari), punchy,
  curiosity or shock (e.g. "YE KYA HUA?!", "1 HP CLUTCH", "BHAI NAHI!"). No emojis.
  Don't repeat the video title word for word. No clickbait lies.
- subline: optional 1-3 words for a small banner ("LAST SECOND", "100% REAL") or empty.
- focus_x/focus_y (0..1 in the chosen frame) = the subject to zoom on; zoom 1.0-1.8.
- circle: the exact spot (0..1 frame coords) to highlight with a red circle, or null if nothing specific.
- color/font: pick what pops against this frame."""

SCHEMA = {"type": "object", "required": ["frame", "headline", "focus_x", "focus_y", "zoom", "color", "font"],
          "properties": {
              "frame": {"type": "integer"}, "headline": {"type": "string"}, "subline": {"type": "string"},
              "focus_x": {"type": "number"}, "focus_y": {"type": "number"}, "zoom": {"type": "number"},
              "circle": {"type": ["object", "null"], "properties": {"x": {"type": "number"}, "y": {"type": "number"}}},
              "color": {"type": "string", "enum": list(COLORS)}, "font": {"type": "string", "enum": FONTS},
              "reason": {"type": "string"}}}


# ------------------------------------------------------------------ frames

def _frame(src: str, t: float, width: int = 1280) -> Image.Image:
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "f.jpg"
        r = subprocess.run([media.tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{max(0.0, t):.3f}",
                            "-i", src, "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "2", str(out)],
                           capture_output=True, creationflags=media.NO_WINDOW)
        if r.returncode != 0 or not out.exists():
            raise RuntimeError("Couldn't read a frame for the thumbnail.")
        return Image.open(out).convert("RGB")


def candidate_times(project: dict, clip: dict, n: int = 6) -> list:
    """Source-video times: loudest moments of the clip first, then evenly spaced ones."""
    start, end = float(clip["start"]), float(clip["end"])
    loud = project.get("loudness") or []
    picks = []
    if loud:
        idx = sorted(range(int(start / 0.25), min(len(loud), int(end / 0.25))), key=lambda i: -loud[i])
        for i in idx:
            t = i * 0.25
            if start + 0.3 < t < end - 0.2 and all(abs(t - p) > 1.5 for p in picks):
                picks.append(t)
            if len(picks) >= n - 2:
                break
    k = 1
    while len(picks) < n:
        t = start + (end - start) * k / (n + 1)
        if all(abs(t - p) > 0.8 for p in picks):
            picks.append(t)
        k += 1
        if k > 4 * n:
            break
    return sorted(picks)[:n]


def _jpeg(img: Image.Image, width: int = 640) -> bytes:
    im = img.copy()
    im.thumbnail((width, width))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=80)
    return b.getvalue()


# ------------------------------------------------------------------ design

def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    f = captions.FONT_FILES.get(name) or captions.FONT_FILES["Luckiest Guy"]
    return ImageFont.truetype(str(fonts_dir() / f), size)


def _clean_text(s: str, limit: int) -> str:
    s = "".join(ch for ch in str(s or "") if ord(ch) < 0x2000 or ch in "’‘“”…").strip()
    s = " ".join(s.split())
    return s.upper()[:limit]


def _fit_lines(draw, text, font_name, max_w, max_size, min_size=70, max_lines=2):
    words = text.split()
    for size in range(max_size, min_size - 1, -6):
        f = _font(font_name, size)
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if draw.textlength(test, font=f) <= max_w or not cur:
                cur = test
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        if len(lines) <= max_lines and all(draw.textlength(ln, font=f) <= max_w for ln in lines):
            return f, lines, size
    f = _font(font_name, min_size)
    return f, [text], min_size


def _text_block(canvas: Image.Image, text: str, font_name: str, color: str, center_x: int, top: int,
                max_w: int, max_size: int, rotate: float = -3.0) -> int:
    """Huge outlined headline with a drop shadow. Returns the block's bottom y."""
    probe = ImageDraw.Draw(canvas)
    f, lines, size = _fit_lines(probe, text, font_name, max_w, max_size)
    stroke = max(6, size // 11)
    line_h = int(size * 1.02)
    w = int(max(probe.textlength(ln, font=f) for ln in lines)) + stroke * 4 + 40
    h = line_h * len(lines) + stroke * 4 + 40
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d, sd = ImageDraw.Draw(layer), ImageDraw.Draw(shadow)
    for i, ln in enumerate(lines):
        lw = d.textlength(ln, font=f)
        x, y = (w - lw) / 2, 20 + stroke + i * line_h
        sd.text((x + 8, y + 12), ln, font=f, fill=(0, 0, 0, 200), stroke_width=stroke, stroke_fill=(0, 0, 0, 200))
        d.text((x, y), ln, font=f, fill=color, stroke_width=stroke, stroke_fill="#000000")
    shadow = shadow.filter(ImageFilter.GaussianBlur(6))
    shadow.alpha_composite(layer)
    block = shadow.rotate(rotate, resample=Image.BICUBIC, expand=True)
    canvas.alpha_composite(block, (int(center_x - block.width / 2), int(top)))
    return int(top + block.height)


def _banner(canvas: Image.Image, text: str, center_x: int, y: int, size: int = 64):
    f = _font("Anton", size)
    d = ImageDraw.Draw(canvas)
    tw = d.textlength(text, font=f)
    pad = size // 2
    box = Image.new("RGBA", (int(tw + pad * 2), int(size * 1.45)), (0, 0, 0, 0))
    bd = ImageDraw.Draw(box)
    bd.rounded_rectangle([0, 0, box.width - 1, box.height - 1], radius=size // 4, fill="#E8132B")
    bd.text((pad, size * 0.12), text, font=f, fill="#FFFFFF")
    box = box.rotate(2, resample=Image.BICUBIC, expand=True)
    canvas.alpha_composite(box, (int(center_x - box.width / 2), int(y)))


def _circle_arrow(canvas: Image.Image, cx: int, cy: int, r: int, from_left: bool):
    d = ImageDraw.Draw(canvas)
    for k, (col, wdt) in enumerate((("#000000", 22), ("#FF1E1E", 13))):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col, width=wdt)
    # arrow from the side toward the circle
    sx = cx - r * 2.6 if from_left else cx + r * 2.6
    sy = cy + r * 1.9
    ang = math.atan2(cy - sy, cx - sx)
    ex, ey = cx - math.cos(ang) * (r + 18), cy - math.sin(ang) * (r + 18)
    for col, wdt in (("#000000", 30), ("#FF1E1E", 18)):
        d.line([sx, sy, ex, ey], fill=col, width=wdt)
        hl = 60 if col == "#000000" else 48
        for side in (-1, 1):
            a = ang + math.pi - side * 0.5
            d.line([ex, ey, ex + math.cos(a) * hl, ey + math.sin(a) * hl], fill=col, width=wdt)


def compose(frame: Image.Image, design: dict, size=(1080, 1920), crop_x: float = 0.5) -> Image.Image:
    W, H = size
    fw, fh = frame.size
    color = COLORS.get(design.get("color"), COLORS["yellow"])
    font = design.get("font") if design.get("font") in FONTS else "Luckiest Guy"
    headline = _clean_text(design.get("headline") or "", 26)
    if not headline or captions.DEVANAGARI.search(headline):
        headline = "WAIT FOR IT!"
    subline = _clean_text(design.get("subline") or "", 18)
    if captions.DEVANAGARI.search(subline):
        subline = ""
    zoom = max(1.0, min(1.8, float(design.get("zoom") or 1.2)))
    fx = min(1.0, max(0.0, float(design.get("focus_x", 0.5))))
    fy = min(1.0, max(0.0, float(design.get("focus_y", 0.5))))
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))

    # background: the frame, covered + blurred + darkened
    sc = max(W / fw, H / fh)
    bg = frame.resize((int(fw * sc) + 1, int(fh * sc) + 1), Image.BICUBIC)
    bx = int((bg.width - W) * crop_x)
    bg = bg.crop((bx, (bg.height - H) // 2, bx + W, (bg.height - H) // 2 + H)).filter(ImageFilter.GaussianBlur(28))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), 0.45)
    canvas.paste(bg, (0, 0))

    vertical = H > W
    # main panel: zoomed on the subject, inside the crop-safe middle band
    pw = W if vertical else W
    ph = int(H * 0.56) if vertical else H
    target_ratio = pw / ph
    cw = fw / zoom
    ch = cw / target_ratio
    if ch > fh:
        ch = fh
        cw = ch * target_ratio
    cx0 = min(max(fx * fw - cw / 2, 0), fw - cw)
    cy0 = min(max(fy * fh - ch / 2, 0), fh - ch)
    panel = frame.crop((int(cx0), int(cy0), int(cx0 + cw), int(cy0 + ch))).resize((pw, ph), Image.LANCZOS)
    py = (H - ph) // 2 if vertical else 0
    if vertical:
        glow = Image.new("RGBA", (W, ph + 40), (0, 0, 0, 0))
        ImageDraw.Draw(glow).rectangle([0, 10, W, ph + 30], fill=color)
        canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(14)), (0, py - 20))
    canvas.paste(panel, (0, py))

    # highlight circle + arrow
    circ = design.get("circle")
    if isinstance(circ, dict) and "x" in circ and "y" in circ:
        px = (float(circ["x"]) * fw - cx0) / cw * pw
        pyy = (float(circ["y"]) * fh - cy0) / ch * ph + py
        if 40 < px < pw - 40 and py + 40 < pyy < py + ph - 40:
            _circle_arrow(canvas, int(px), int(pyy), int(min(pw, ph) * 0.11), from_left=px > pw / 2)

    # headline + banner
    if vertical:
        top = py - int(H * 0.07)
        bottom = _text_block(canvas, headline, font, color, W // 2, top, int(W * 0.92), 200)
        if subline:
            _banner(canvas, subline, W // 2, max(bottom - 10, py + ph - 140), 70)
    else:
        bottom = _text_block(canvas, headline, font, color, int(W * 0.5), int(H * 0.04), int(W * 0.9), 150, rotate=-2)
        if subline:
            _banner(canvas, subline, W // 2, H - 130, 56)
    return canvas.convert("RGB")


def save_jpeg(img: Image.Image, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    for q in (92, 85, 75, 65):
        img.save(path, "JPEG", quality=q, optimize=True)
        if path.stat().st_size < 1_900_000:  # YouTube limit is 2 MB
            return


# ------------------------------------------------------------------ main

def make(project: dict, clip: dict, settings: dict, out_path: Path, override: dict | None = None,
         remake: bool = True, previous: dict | None = None, progress=None) -> dict:
    """Make (or re-make) a thumbnail. Returns {"path", "design"}.
    remake=False + previous design: keep frame and layout, only apply text/colour changes from override."""
    src = project.get("source_path")
    if not src or not Path(src).exists():
        raise RuntimeError("The source video is missing.")
    fmt = (clip.get("layout") or {}).get("format", "short")
    size = (1080, 1920) if fmt == "short" else (1280, 720)
    crop_x = float((clip.get("layout") or {}).get("crop_x", 0.5))
    if previous and not remake:
        design = dict(previous)
        design.update({k: v for k, v in (override or {}).items() if v is not None})
        frame = _frame(src, float(design["t"]))
    else:
        times = candidate_times(project, clip)
        progress and progress(0.2, "Picking the best frame…")
        frames = [_frame(src, t) for t in times]
        design = None
        if settings.get("claude_api_key"):
            cues = (clip.get("captions") or {}).get("cues") or []
            text = "\n".join(f"[{max(0, q['start'] - clip['start']):.1f}s] {q['text']}" for q in cues)[:3000]
            rel = ", ".join("%.1fs" % (t - clip["start"]) for t in times)
            user = (f"Video title: {(clip.get('meta') or {}).get('title') or clip.get('title', '')}\n"
                    f"Hook: {clip.get('hook', '')}\nFrames are images 0-{len(frames) - 1} "
                    f"(times in clip: {rel}).\n"
                    f"Captions:\n{text}\n"
                    + (f"\nThe creator asked: {json.dumps(override, ensure_ascii=False)}" if override else ""))
            progress and progress(0.5, "Claude is designing the thumbnail…")
            try:
                design = ai._ask_json(settings["claude_api_key"], settings.get("ap_hf_model") or "claude-sonnet-5-5",
                                      SYSTEM, user, SCHEMA, "thumbnail", max_tokens=1500,
                                      images=[_jpeg(f) for f in frames])
            except ai.AIError:
                design = None
        if not design:  # offline: loudest frame + hook words (Latin text only: thumbnail fonts can't draw Hindi)
            words = (clip.get("hook") or clip.get("title") or "").split()
            if not words or captions.DEVANAGARI.search(" ".join(words)):
                words = ["WAIT", "FOR", "IT!"]
            design = {"frame": 0, "headline": " ".join(words[:3]), "focus_x": 0.5, "focus_y": 0.45, "zoom": 1.25,
                      "color": "yellow", "font": "Luckiest Guy", "circle": None, "subline": "", "offline": True}
        i = int(design.get("frame") or 0)
        i = i if 0 <= i < len(frames) else 0
        design["t"] = times[i]
        if override:
            design.update({k: v for k, v in override.items() if v is not None})
        frame = frames[i]
    progress and progress(0.85, "Drawing the thumbnail…")
    img = compose(frame, design, size, crop_x)
    out_path = Path(out_path)
    save_jpeg(img, out_path)
    return {"path": str(out_path), "design": design}
