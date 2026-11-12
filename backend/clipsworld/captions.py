"""Caption building (word timing → short on-screen lines) and ASS subtitle styles."""
import re

PLAY_W, PLAY_H = 1080, 1920
DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def _c(hex_rgb: str, alpha: int = 0) -> str:
    """#RRGGBB → ASS &HAABBGGRR"""
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


# Font files bundled in resources/fonts (family name -> file). All OFL / Apache licensed.
FONT_FILES = {
    "Montserrat Black": "Montserrat-Black.ttf",
    "Montserrat ExtraBold": "Montserrat-ExtraBold.ttf",
    "Poppins ExtraBold": "Poppins-ExtraBold.ttf",
    "Mukta ExtraBold": "Mukta-ExtraBold.ttf",
    "Anton": "Anton-Regular.ttf",
    "Bebas Neue": "BebasNeue-Regular.ttf",
    "Bangers": "Bangers-Regular.ttf",
    "Luckiest Guy": "LuckiestGuy-Regular.ttf",
    "Archivo Black": "ArchivoBlack-Regular.ttf",
    "Lilita One": "LilitaOne-Regular.ttf",
    "Press Start 2P": "PressStart2P-Regular.ttf",
}
# Fonts that can draw Hindi (Devanagari). Other fonts fall back to Mukta for Hindi lines.
DEVA_FONTS = {"Mukta ExtraBold", "Poppins ExtraBold"}
HINDI_FALLBACK = "Mukta ExtraBold"

# Each style: font, size, colors, outline, words per caption, active-word effect.
# Presets follow the caption looks trending on Shorts/TikTok/Reels.
STYLES = {
    "hormozi": {"label": "Hormozi Bold", "font": "Montserrat Black", "size": 92, "color": "#FFFFFF",
                "outline": "#000000", "bord": 7, "shadow": 6, "words": 3, "active": "#F7C204",
                "active_scale": 108, "upper": True, "pop": True},
    "beast": {"label": "Beast Mode", "font": "Luckiest Guy", "size": 100, "color": "#FFFFFF",
              "outline": "#000000", "bord": 10, "shadow": 3, "words": 2, "active": "#FFE600",
              "active_scale": 118, "upper": True, "pop": True},
    "pop": {"label": "Pop Highlight", "font": "Mukta ExtraBold", "size": 92, "color": "#FFFFFF",
            "outline": "#000000", "bord": 9, "shadow": 2, "words": 3, "active": "#FFE600",
            "active_scale": 115, "upper": False, "pop": True},
    "bebas": {"label": "Bebas Impact", "font": "Bebas Neue", "size": 136, "color": "#FFFFFF",
              "outline": "#000000", "bord": 7, "shadow": 3, "words": 3, "active": "#02FB23",
              "active_scale": 110, "upper": True, "pop": True},
    "meme": {"label": "Bold Meme", "font": "Anton", "size": 104, "color": "#FFFFFF",
             "outline": "#000000", "bord": 10, "shadow": 0, "words": 2, "active": None,
             "active_scale": 100, "upper": True, "pop": True},
    "comic": {"label": "Comic Pop", "font": "Bangers", "size": 116, "color": "#FFE600",
              "outline": "#000000", "bord": 9, "shadow": 4, "words": 2, "active": "#FF3B3B",
              "active_scale": 115, "upper": True, "pop": True},
    "gaming": {"label": "Gaming Bubble", "font": "Lilita One", "size": 100, "color": "#FFFFFF",
               "outline": "#4B1D96", "bord": 10, "shadow": 3, "words": 3, "active": "#FF4FD8",
               "active_scale": 112, "upper": False, "pop": True},
    "pixel": {"label": "Pixel Gamer", "font": "Press Start 2P", "size": 54, "color": "#FFFFFF",
              "outline": "#000000", "bord": 8, "shadow": 4, "words": 3, "active": "#55FF55",
              "active_scale": 110, "upper": True, "pop": True},
    "punch": {"label": "Punch Clean", "font": "Archivo Black", "size": 84, "color": "#FFFFFF",
              "outline": "#111111", "bord": 7, "shadow": 2, "words": 3, "active": "#00E5FF",
              "active_scale": 110, "upper": False, "pop": True},
    "neon": {"label": "Neon Glow", "font": "Poppins ExtraBold", "size": 84, "color": "#3CF2FF",
             "outline": "#0B1D6B", "bord": 6, "shadow": 0, "words": 3, "active": "#FF3DF2",
             "active_scale": 110, "upper": False, "pop": True, "blur": 3},
    "clean": {"label": "Clean Box", "font": "Poppins ExtraBold", "size": 66, "color": "#FFFFFF",
              "outline": "#000000", "bord": 0, "shadow": 0, "words": 5, "active": "#7CFF6B",
              "active_scale": 100, "upper": False, "pop": False, "box": True},
    "karaoke": {"label": "Karaoke Fill", "font": "Mukta ExtraBold", "size": 88, "color": "#FFD23F",
                "outline": "#2B0A3D", "bord": 8, "shadow": 2, "words": 4, "active": None,
                "active_scale": 100, "upper": False, "pop": False, "karaoke": "#FFFFFF"},
}
for _st in STYLES.values():
    _st["deva"] = _st["font"] in DEVA_FONTS

POSITIONS = {"bottom": (2, 420), "middle": (5, 0), "top": (8, 330)}


def build_cues(segments: list, start: float, end: float, words_per_cue: int = 3, max_chars: int = 24) -> list:
    """Group transcript words inside [start, end] into short caption cues (source timeline)."""
    words = []
    for s in segments:
        if s["end"] < start or s["start"] > end:
            continue
        ws = s.get("words") or []
        if not ws and s["text"].strip():
            # no word timing: spread words evenly over the segment
            toks = s["text"].split()
            d = (s["end"] - s["start"]) / max(1, len(toks))
            ws = [{"start": s["start"] + i * d, "end": s["start"] + (i + 1) * d, "word": t}
                  for i, t in enumerate(toks)]
        for w in ws:
            if w["end"] > start and w["start"] < end:
                words.append({"start": max(start, w["start"]), "end": min(end, w["end"]), "word": w["word"]})
    cues, cur = [], []

    def flush():
        if cur:
            cues.append({"start": round(cur[0]["start"], 3), "end": round(cur[-1]["end"], 3),
                         "text": " ".join(w["word"] for w in cur),
                         "words": [dict(w) for w in cur]})
            cur.clear()

    for w in words:
        if cur:
            gap = w["start"] - cur[-1]["end"]
            chars = sum(len(x["word"]) + 1 for x in cur) + len(w["word"])
            if len(cur) >= words_per_cue or gap > 0.6 or chars > max_chars or re.search(r"[.!?।,]$", cur[-1]["word"]):
                flush()
        cur.append(w)
    flush()
    # stretch each cue to the next one so captions don't flicker off
    for a, b in zip(cues, cues[1:]):
        if 0 < b["start"] - a["end"] < 0.35:
            a["end"] = b["start"]
    return cues


def respread_words(cue: dict) -> dict:
    """After editing/translating text, spread new words across the cue time."""
    toks = cue["text"].split()
    d = (cue["end"] - cue["start"]) / max(1, len(toks))
    cue["words"] = [{"start": round(cue["start"] + i * d, 3), "end": round(cue["start"] + (i + 1) * d, 3), "word": t}
                    for i, t in enumerate(toks)]
    return cue


def _ts(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return text.replace("\\", "⧵").replace("{", "(").replace("}", ")").replace("\n", " ")


def build_ass(cues: list, clip_start: float, clip_end: float, style_id: str = "hormozi",
              position: str = "bottom", uppercase: bool | None = None, hook: str = "",
              hook_seconds: float = 3.0, width: int = PLAY_W, height: int = PLAY_H,
              extra: list | None = None) -> str:
    st = STYLES.get(style_id, STYLES["hormozi"])
    align, margin_v = POSITIONS.get(position, POSITIONS["bottom"])
    scale = height / PLAY_H
    upper = st["upper"] if uppercase is None else uppercase
    font_size = int(st["size"] * scale)
    border_style = 3 if st.get("box") else 1
    back = _c("#000000", 0x60) if st.get("box") else _c("#000000", 0x80)
    outline_col = _c("#141414") if st.get("box") else _c(st["outline"])
    bord = 14 * scale if st.get("box") else st["bord"] * scale
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "YCbCr Matrix: TV.709", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{st['font']},{font_size},{_c(st['color'])},{_c(st.get('karaoke') or st['color'])},"
        f"{outline_col},{back},0,0,0,0,100,100,1,0,{border_style},{bord:.1f},{st['shadow'] * scale:.1f},"
        f"{align},{int(70 * scale)},{int(70 * scale)},{int(margin_v * scale)},1",
        f"Style: CapHi,{HINDI_FALLBACK},{int(88 * scale)},{_c(st['color'])},{_c(st.get('karaoke') or st['color'])},"
        f"{outline_col},{back},0,0,0,0,100,100,1,0,{border_style},{bord:.1f},{st['shadow'] * scale:.1f},"
        f"{align},{int(70 * scale)},{int(70 * scale)},{int(margin_v * scale)},1",
        f"Style: Hook,Mukta ExtraBold,{int(64 * scale)},{_c('#111111')},{_c('#111111')},{_c('#FFE600')},"
        f"{_c('#FFE600')},0,0,0,0,100,100,0,0,3,{18 * scale:.1f},0,8,{int(90 * scale)},{int(90 * scale)},"
        f"{int(250 * scale)},1",
        f"Style: Pop,Luckiest Guy,{int(118 * scale)},{_c('#FFE600')},{_c('#FFE600')},{_c('#000000')},"
        f"{_c('#000000', 0x60)},0,0,0,0,100,100,2,0,1,{10 * scale:.1f},{5 * scale:.1f},5,{int(60 * scale)},"
        f"{int(60 * scale)},0,1",
        f"Style: Badge,Montserrat Black,{int(48 * scale)},{_c('#FFFFFF')},{_c('#FFFFFF')},{_c('#FF2D55')},"
        f"{_c('#FF2D55')},0,0,0,0,100,100,3,0,3,{14 * scale:.1f},0,7,{int(60 * scale)},{int(60 * scale)},"
        f"{int(170 * scale)},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for ev in extra or []:
        a, b = ev["start"], ev["end"]
        if b <= a:
            continue
        txt = _esc(ev["text"])
        if ev.get("kind") == "badge":
            lines.append(f"Dialogue: 3,{_ts(a)},{_ts(b)},Badge,,0,0,0,,{{\\fad(100,100)}}\u25B6 {txt}")
            continue
        pos = {"top": (width / 2, height * 0.24), "middle": (width / 2, height * 0.44),
               "bottom": (width / 2, height * 0.70)}.get(ev.get("position", "middle"), (width / 2, height * 0.44))
        style = "CapHi" if DEVANAGARI.search(txt) else "Pop"
        col = _c(ev.get("color", "#FFE600"))
        lines.append(f"Dialogue: 3,{_ts(a)},{_ts(b)},{style},,0,0,0,,{{\\an5\\pos({pos[0]:.0f},{pos[1]:.0f})"
                     f"\\c{col}\\frz-4\\fscx40\\fscy40\\t(0,120,\\fscx118\\fscy118)"
                     f"\\t(120,220,\\fscx100\\fscy100)\\fad(0,150)}}{txt}")
    blur = f"\\blur{st['blur']}" if st.get("blur") else ""
    if hook.strip():
        h = _esc(hook.strip())
        lines.append(f"Dialogue: 1,{_ts(0)},{_ts(min(hook_seconds, clip_end - clip_start))},Hook,,0,0,0,,"
                     f"{{\\fad(120,200)\\fscx80\\fscy80\\t(0,150,\\fscx100\\fscy100)}}{h}")
    for cue in cues:
        cs, ce = cue["start"] - clip_start, cue["end"] - clip_start
        if ce <= 0 or cs >= clip_end - clip_start:
            continue
        cs = max(0.0, cs)
        words = cue.get("words") or respread_words(dict(cue))["words"]
        toks = [_esc(w["word"].upper() if upper else w["word"]) for w in words]
        if not toks:
            continue
        style_name = "CapHi" if (not st["deva"] and DEVANAGARI.search(cue["text"])) else "Cap"
        pop = "{\\fscx82\\fscy82\\t(0,90,\\fscx100\\fscy100)}" if st.get("pop") else ""
        if st.get("karaoke"):
            parts = []
            for w, tok in zip(words, toks):
                dur_cs = max(1, int(round((w["end"] - w["start"]) * 100)))
                parts.append(f"{{\\kf{dur_cs}}}{tok}")
            lines.append(f"Dialogue: 0,{_ts(cs)},{_ts(ce)},{style_name},,0,0,0,,{{{blur}}}" + " ".join(parts))
            continue
        if not st.get("active"):
            lines.append(f"Dialogue: 0,{_ts(cs)},{_ts(ce)},{style_name},,0,0,0,,{pop}{{{blur}}}" + " ".join(toks))
            continue
        for k, w in enumerate(words):
            ws = cs if k == 0 else max(cs, w["start"] - clip_start)
            we = ce if k == len(words) - 1 else max(ws + 0.01, words[k + 1]["start"] - clip_start)
            if we <= ws:
                continue
            hi = (f"{{\\c{_c(st['active'])}\\fscx{st['active_scale']}\\fscy{st['active_scale']}}}"
                  f"{toks[k]}{{\\c{_c(st['color'])}\\fscx100\\fscy100}}")
            text = " ".join(hi if i == k else t for i, t in enumerate(toks))
            lead = pop if k == 0 else ""
            lines.append(f"Dialogue: 0,{_ts(ws)},{_ts(we)},{style_name},,0,0,0,,{lead}{{{blur}}}{text}")
    return "\n".join(lines) + "\n"
