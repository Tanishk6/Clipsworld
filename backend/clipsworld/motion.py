"""Motion graphics component library for HyperFrames edits.

Claude doesn't write raw animation code: it picks and times polished, pre-built components (hook titles,
meme stamps, comic bursts, emoji pops, punch zooms, shakes, flashes, speed lines, arrows...). This module
turns that plan into HTML + CSS + GSAP for HyperFrames, and picks / times the sound effects so each sound's
hit lands exactly on its moment.
"""
import html as htmlmod
import math

from . import effects as fx

COLORS = {"yellow": "#FFE600", "white": "#FFFFFF", "red": "#FF2D2D", "green": "#3DFF6E", "cyan": "#2DE2FF",
          "orange": "#FF8A00", "pink": "#FF4FD8", "purple": "#9B5CFF"}
FONTS = ["Luckiest Guy", "Bangers", "Anton", "Lilita One", "Montserrat Black", "Archivo Black", "Bebas Neue"]
HOOK_STYLES = ["box", "stamp", "slide", "glitch"]
POP_STYLES = ["stamp", "burst", "slide", "bounce", "glitch"]
TYPES = ["punch", "shake", "flash", "pop", "emoji", "speedlines", "vignette", "arrow", "label", "sfx"]

DEFAULT_SFX = {"punch": "whoosh-fast-medium", "shake": "boom-hit-strong", "flash": "impact-medium-hard",
               "pop": "pop-large-in", "emoji": "pop-small-in", "speedlines": "whoosh-medium-hard",
               "vignette": "bass-rumble-short", "arrow": "swish-medium", "label": "pop-small-in"}
HOOK_SFX = {"box": "whoosh-fast-hard", "stamp": "cinematic-slam-big", "slide": "zip-in-hard", "glitch": "digital-glitch-clear"}

SYSTEM = """You are the motion designer of a top Indian YouTube Shorts channel (gaming / funny clips, Hinglish
audience). You plan the motion graphics for one clip using a library of polished, pre-built components.
The base video and word-by-word captions already exist (captions sit around {cap_pct}% of the height - keep
text components away from there). You see a few frames of the framed clip (same layout as the final video).

Canvas {w}x{h}, clip length {d:.2f}s. Times are seconds from the clip start. Positions x,y are 0..1 of the
canvas (0,0 = top-left). Keep text inside x 0.06..0.84 (YouTube buttons cover the right edge).

Components (events):
- punch: fast punch-in zoom on the video. t, dur (hold 0.4-1.5), scale (1.15-1.6), x, y (zoom focus), ease ("snap"|"smooth")
- shake: camera shake for hits/screams/explosions. t, dur (0.25-0.8), strength (1-3)
- flash: white flash frame on a hard hit or cut. t
- pop: meme text pop. t, dur (0.8-2), text (1-3 words, Roman Hinglish/English, CAPS, e.g. "BHAI KYA?!", "NO WAY",
  "SKILL ISSUE", "BHAAGO!!"), style ("stamp"|"burst"|"slide"|"bounce"|"glitch"), color, y ("top"|"upper"|"middle")
- emoji: emoji reaction. t, dur (0.8-2), emoji (1-2 emojis like 😂 💀 😱 🔥 🤯 😭 👀), x, y, size ("s"|"m"|"l"), motion ("pop"|"float"|"spin")
- speedlines: anime speed lines for hype/rush moments. t, dur (0.6-2)
- vignette: pulsing red vignette for panic/danger. t, dur (1-3)
- arrow: red arrow + circle pointing at something in the frame. t, dur (1-2.5), x, y (the target)
- label: small tag naming who/what ("ME:", "MY FRIEND:", "1 HP"). t, dur (1-3), text, x, y
- sfx: sound only. t
Every event may set "sfx" (an id from the sound list) and "volume" (0.3-1.2); leave sfx empty for a good
default, or "none" for silence. Sounds are timed so their hit lands exactly at t.

Hook (first 2-3 s): text (2-6 words, Roman script, the curiosity hook), style ("box"|"stamp"|"slide"|"glitch"), color.

How great editors do it:
- 6-14 events total. A punch zoom (often + shake/flash) on every real punchline, scream, kill or fail.
- 2-4 text pops/emojis on the funniest lines - never on boring lines, never two at once.
- Vary components and sounds; build up before a big moment (riser into it) and hit hard on it.
- Silence is fine during setup; the edit should follow the energy of the speech.
- Never cover the captions; never put text over a face you can see.

Sounds (id, length, what it is):
{sfx}"""

_ev = {"type": "object", "required": ["type", "t"], "properties": {
    "type": {"type": "string", "enum": TYPES}, "t": {"type": "number"}, "dur": {"type": "number"},
    "scale": {"type": "number"}, "x": {"type": "number"}, "y": {"type": ["number", "string"]},
    "ease": {"type": "string"}, "strength": {"type": "number"}, "text": {"type": "string"},
    "style": {"type": "string"}, "color": {"type": "string"}, "emoji": {"type": "string"},
    "size": {"type": "string"}, "motion": {"type": "string"}, "sfx": {"type": "string"},
    "volume": {"type": "number"}}}
SCHEMA = {"type": "object", "required": ["hook", "events"], "properties": {
    "hook": {"type": "object", "required": ["text"], "properties": {
        "text": {"type": "string"}, "style": {"type": "string", "enum": HOOK_STYLES},
        "color": {"type": "string", "enum": list(COLORS)}, "font": {"type": "string", "enum": FONTS}}},
    "events": {"type": "array", "items": _ev},
    "font": {"type": "string", "enum": FONTS},
    "progress_bar": {"type": "boolean"}}}


def _num(v, lo, hi, default):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v)) if math.isfinite(v) else default


def _txt(s, limit):
    s = " ".join(str(s or "").split())
    return htmlmod.escape(s.upper()[:limit])


def _color(c, default="yellow"):
    if isinstance(c, str) and c.startswith("#") and len(c) in (4, 7):
        return c
    return COLORS.get(str(c or "").lower(), COLORS[default])


def normalize(plan: dict, dur: float) -> dict:
    """Clamp and clean Claude's plan so the composition is always valid."""
    plan = plan if isinstance(plan, dict) else {}
    hook = plan.get("hook") if isinstance(plan.get("hook"), dict) else {}
    out = {"hook": {"text": str(hook.get("text") or "")[:60],
                    "style": hook.get("style") if hook.get("style") in HOOK_STYLES else "box",
                    "color": hook.get("color") if hook.get("color") in COLORS else "yellow",
                    "font": hook.get("font") if hook.get("font") in FONTS else None},
           "font": plan.get("font") if plan.get("font") in FONTS else "Luckiest Guy",
           "progress_bar": plan.get("progress_bar", True) is not False, "events": []}
    evs = [e for e in (plan.get("events") or []) if isinstance(e, dict) and e.get("type") in TYPES]
    evs.sort(key=lambda e: _num(e.get("t"), 0, dur, 0))
    busy_until = {}  # the same kind of overlay never overlaps itself (a pop can sit with an emoji)
    for e in evs[:18]:
        t = _num(e.get("t"), 0.0, max(0.0, dur - 0.25), 0.0)
        typ = e["type"]
        d = {"punch": (0.3, 1.8, 0.8), "shake": (0.2, 1.0, 0.5), "pop": (0.6, 2.5, 1.3), "emoji": (0.6, 2.5, 1.3),
             "speedlines": (0.4, 2.5, 1.0), "vignette": (0.6, 3.5, 1.6), "arrow": (0.8, 3.0, 1.8),
             "label": (0.8, 4.0, 2.0)}.get(typ, (0.1, 0.4, 0.25))
        ev = {"type": typ, "t": round(t, 3), "dur": round(min(_num(e.get("dur"), *d), dur - t), 3)}
        if typ in ("pop", "emoji", "label", "arrow"):
            if t < busy_until.get(typ, -9.0) + 0.2:
                continue
            busy_until[typ] = t + ev["dur"]
        if typ == "punch":
            ev.update(scale=_num(e.get("scale"), 1.08, 1.7, 1.3), x=_num(e.get("x"), 0, 1, 0.5),
                      y=_num(e.get("y"), 0, 1, 0.45), ease="smooth" if e.get("ease") == "smooth" else "snap")
        elif typ == "shake":
            ev["strength"] = _num(e.get("strength"), 0.5, 3, 1.5)
        elif typ == "pop":
            ev.update(text=_txt(e.get("text") or "BRUH", 24), style=e.get("style") if e.get("style") in POP_STYLES else "stamp",
                      color=_color(e.get("color")), y={"top": 0.14, "upper": 0.24, "middle": 0.40}.get(
                          e.get("y") if isinstance(e.get("y"), str) else "", _num(e.get("y"), 0.1, 0.5, 0.24)))
        elif typ == "emoji":
            emo = "".join(ch for ch in str(e.get("emoji") or "😂") if not ch.isascii())[:4] or "😂"
            ev.update(emoji=emo, x=_num(e.get("x"), 0.1, 0.8, 0.7), y=_num(e.get("y"), 0.1, 0.55, 0.3),
                      size=e.get("size") if e.get("size") in ("s", "m", "l") else "m",
                      motion=e.get("motion") if e.get("motion") in ("pop", "float", "spin") else "pop")
        elif typ == "arrow":
            ev.update(x=_num(e.get("x"), 0.1, 0.85, 0.5), y=_num(e.get("y"), 0.15, 0.75, 0.45))
        elif typ == "label":
            ev.update(text=_txt(e.get("text") or "ME:", 18), x=_num(e.get("x"), 0.05, 0.7, 0.08),
                      y=_num(e.get("y"), 0.1, 0.6, 0.2))
        sfx = str(e.get("sfx") or "").strip()
        if sfx.lower() in ("none", "no", "-"):
            sfx = ""
        elif not sfx or not fx.sfx_path(sfx):
            sfx = DEFAULT_SFX.get(typ, "") if typ != "sfx" else ""
        ev["sfx"] = sfx
        ev["volume"] = _num(e.get("volume"), 0.0, 1.5, 0.85)
        out["events"].append(ev)
    return out


# ------------------------------------------------------------------ rendering

def _text_css(font, size, color, stroke):
    return (f"font-family:'{font}','Luckiest Guy',sans-serif;font-size:{size}px;color:{color};line-height:1.02;"
            f'-webkit-text-stroke:{stroke}px #000;paint-order:stroke fill;'
            f'text-shadow:0 {stroke}px 0 #000,0 {stroke * 2}px {stroke * 3}px rgba(0,0,0,.45);')


def render(plan: dict, w: int, h: int, dur: float, master_volume: float = 1.0) -> dict:
    """Returns {"css", "html", "js", "sounds": [{path, t, dur, volume}]}."""
    k = min(w, h) / 1080
    font = plan.get("font") or "Luckiest Guy"
    css, html, js, sounds = [], [], [], []

    def sound(sid, t, vol=0.85):
        p = fx.sfx_path(sid)
        if not p:
            return
        start = max(0.0, t - fx.sfx_sync(sid))
        length = float(fx.catalog().get(fx.ALIASES.get(sid, sid), {}).get("duration") or 2.0)
        if start < dur - 0.05:
            sounds.append({"path": str(p), "t": round(start, 3), "dur": round(min(length + 0.05, dur - start), 3),
                           "volume": round(max(0.0, min(2.0, vol * master_volume)), 3)})

    css.append(f""".mg {{ position:absolute; z-index:24; pointer-events:none; }}
.mgt {{ position:absolute; left:0; right:0; text-align:center; transform-origin:50% 50%; z-index:26; }}
.mgt span {{ display:inline-block; }}""")

    # progress bar
    if plan.get("progress_bar", True):
        html.append(f'<div id="pbar" class="clip mg" data-start="0" data-duration="{dur:.3f}" '
                    f'style="left:0;top:0;height:{int(12 * k)}px;width:{w}px;background:linear-gradient(90deg,#7c5cff,#ff4fd8,#ffe600);transform-origin:0 50%;z-index:40"></div>')
        js.append(f'tl.fromTo("#pbar",{{scaleX:0}},{{scaleX:1,duration:{dur:.3f},ease:"none"}},0);')

    # hook
    hk = plan.get("hook") or {}
    if hk.get("text"):
        hd = min(2.8, max(1.2, dur * 0.3))
        col = _color(hk.get("color"))
        hfont = hk.get("font") or font
        text = _txt(hk["text"], 60)
        size = int((118 if len(text) < 18 else 96 if len(text) < 30 else 80) * k)
        top = int(h * 0.11)
        style = hk.get("style", "box")
        if style == "box":
            html.append(f'<div id="hook" class="clip mgt" data-start="0" data-duration="{hd:.3f}" style="top:{top}px;padding:0 {int(70 * k)}px">'
                        f'<span style="background:{col};color:#111;font-family:\'{hfont}\';font-size:{size}px;line-height:1.08;'
                        f'padding:{int(14 * k)}px {int(30 * k)}px;border-radius:{int(22 * k)}px;box-shadow:0 {int(14 * k)}px 0 #000,0 {int(24 * k)}px {int(40 * k)}px rgba(0,0,0,.5);'
                        f'border:{int(6 * k)}px solid #000">{text}</span></div>')
            js.append('tl.fromTo("#hook",{y:-260,rotation:-6,opacity:0},{y:0,rotation:-2,opacity:1,duration:0.42,ease:"back.out(1.8)"},0.05);')
        elif style == "stamp":
            html.append(f'<div id="hook" class="clip mgt" data-start="0" data-duration="{hd:.3f}" style="top:{top}px;padding:0 {int(60 * k)}px;{_text_css(hfont, int(size * 1.1), col, max(6, int(size / 11)))}">{text}</div>')
            js.append('tl.fromTo("#hook",{scale:3.2,rotation:-12,opacity:0},{scale:1,rotation:-4,opacity:1,duration:0.22,ease:"power4.in"},0.05);'
                      'tl.to("#hook",{x:14,duration:0.04,repeat:5,yoyo:true},0.27);tl.set("#hook",{x:0},0.5);')
        elif style == "slide":
            words = text.split(" ")
            a, b = " ".join(words[:max(1, len(words) // 2)]), " ".join(words[max(1, len(words) // 2):])
            html.append(f'<div id="hook" class="clip mgt" data-start="0" data-duration="{hd:.3f}" style="top:{top}px;{_text_css(hfont, size, col, max(6, int(size / 11)))}">'
                        f'<div id="hookA">{a}</div><div id="hookB" style="color:#fff">{b}</div></div>')
            js.append('tl.from("#hookA",{x:-1200,skewX:20,duration:0.35,ease:"expo.out"},0.05);'
                      'tl.from("#hookB",{x:1200,skewX:-20,duration:0.35,ease:"expo.out"},0.18);')
        else:  # glitch
            st = _text_css(hfont, size, col, max(6, int(size / 11)))
            html.append(f'<div id="hook" class="clip mgt" data-start="0" data-duration="{hd:.3f}" style="top:{top}px;padding:0 {int(60 * k)}px">'
                        f'<div id="hookR" style="position:absolute;left:0;right:0;opacity:.8;{st}color:#ff004c;-webkit-text-stroke:0">{text}</div>'
                        f'<div id="hookC" style="position:absolute;left:0;right:0;opacity:.8;{st}color:#00f0ff;-webkit-text-stroke:0">{text}</div>'
                        f'<div style="position:relative;{st}">{text}</div></div>')
            js.append('tl.from("#hook",{opacity:0,duration:0.06},0.05);')
            for i, (dx, dy) in enumerate([(14, -6), (-18, 4), (10, 8), (-6, -4), (0, 0)]):
                tt = 0.05 + i * 0.06
                js.append(f'tl.set("#hookR",{{x:{dx},y:{dy}}},{tt:.2f});tl.set("#hookC",{{x:{-dx},y:{-dy}}},{tt:.2f});')
        js.append(f'tl.to("#hook",{{y:-80,opacity:0,scale:0.9,duration:0.25,ease:"power2.in"}},{hd - 0.27:.3f});')
        sound(HOOK_SFX.get(style, "whoosh-fast-hard"), 0.12, 0.8)

    # events
    for i, e in enumerate(plan.get("events") or []):
        t, d, typ = e["t"], e["dur"], e["type"]
        eid = f"e{i}"
        if typ == "punch":
            ox, oy = e["x"] * 100, e["y"] * 100
            inn = 0.1 if e["ease"] == "snap" else 0.35
            js.append(f'tl.set("#base",{{transformOrigin:"{ox:.0f}% {oy:.0f}%"}},{t:.3f});'
                      f'tl.to("#base",{{scale:{e["scale"]:.3f},duration:{inn},ease:"{"expo.out" if e["ease"] == "snap" else "power2.out"}"}},{t:.3f});'
                      f'tl.to("#base",{{scale:1,duration:0.3,ease:"power2.inOut"}},{t + max(inn, d):.3f});')
        elif typ == "shake":
            amp = int(18 * e["strength"] * k)
            n = max(3, int(d / 0.045))
            for j in range(n):
                tt = t + j * d / n
                fall = 1 - j / n
                dx = amp * fall * (1 if j % 2 == 0 else -1)
                dy = amp * 0.6 * fall * (1 if (j // 2) % 2 == 0 else -1)
                js.append(f'tl.set("#base",{{x:{dx:.1f},y:{dy:.1f},rotation:{(dx / amp if amp else 0) * 0.8:.2f}}},{tt:.3f});')
            js.append(f'tl.set("#base",{{x:0,y:0,rotation:0}},{t + d:.3f});')
        elif typ == "flash":
            html.append(f'<div id="{eid}" class="clip mg" data-start="{t:.3f}" data-duration="0.28" style="inset:0;background:#fff;z-index:45"></div>')
            js.append(f'tl.fromTo("#{eid}",{{opacity:0.9}},{{opacity:0,duration:0.26,ease:"power2.out"}},{t:.3f});')
        elif typ == "pop":
            size = int((150 if len(e["text"]) <= 8 else 120 if len(e["text"]) <= 14 else 96) * k)
            top = int(h * e["y"])
            stroke = max(7, int(size / 10))
            st = e["style"]
            if st == "burst":
                pts = []
                for j in range(24):
                    r = 1.0 if j % 2 == 0 else 0.72
                    a = j * math.pi / 12
                    pts.append(f"{50 + 50 * r * math.cos(a):.1f},{50 + 42 * r * math.sin(a):.1f}")
                html.append(f'<div id="{eid}" class="clip mgt" data-start="{t:.3f}" data-duration="{d:.3f}" style="top:{top - int(60 * k)}px;height:{int(size * 2.2)}px">'
                            f'<svg id="{eid}b" viewBox="0 0 100 100" preserveAspectRatio="none" style="position:absolute;left:12%;width:76%;height:100%">'
                            f'<polygon points="{" ".join(pts)}" fill="{e["color"]}" stroke="#000" stroke-width="2.2"/></svg>'
                            f'<div style="position:relative;top:{int(size * 0.55)}px;{_text_css(font, size, "#fff", stroke)}">{e["text"]}</div></div>')
                js.append(f'tl.fromTo("#{eid}",{{scale:0,rotation:-20}},{{scale:1,rotation:-4,duration:0.32,ease:"elastic.out(1,0.55)"}},{t:.3f});'
                          f'tl.to("#{eid}b",{{rotation:12,duration:{d:.3f},ease:"none"}},{t:.3f});')
            elif st == "slide":
                html.append(f'<div id="{eid}" class="clip mgt" data-start="{t:.3f}" data-duration="{d:.3f}" style="top:{top}px">'
                            f'<span style="background:{e["color"]};padding:{int(10 * k)}px {int(34 * k)}px;transform:skewX(-10deg);'
                            f'border:{int(6 * k)}px solid #000;box-shadow:{int(12 * k)}px {int(12 * k)}px 0 #000;{_text_css(font, int(size * 0.85), "#111", 0)}-webkit-text-stroke:0;text-shadow:none">{e["text"]}</span></div>')
                js.append(f'tl.fromTo("#{eid}",{{x:-1300}},{{x:0,duration:0.26,ease:"expo.out"}},{t:.3f});')
            elif st == "bounce":
                html.append(f'<div id="{eid}" class="clip mgt" data-start="{t:.3f}" data-duration="{d:.3f}" style="top:{top}px;{_text_css(font, size, e["color"], stroke)}">{e["text"]}</div>')
                js.append(f'tl.fromTo("#{eid}",{{y:-700,scaleY:1.3}},{{y:0,scaleY:1,duration:0.55,ease:"bounce.out"}},{t:.3f});')
            elif st == "glitch":
                tc = _text_css(font, size, e["color"], stroke)
                html.append(f'<div id="{eid}" class="clip mgt" data-start="{t:.3f}" data-duration="{d:.3f}" style="top:{top}px">'
                            f'<div id="{eid}r" style="position:absolute;left:0;right:0;{tc}color:#ff004c;-webkit-text-stroke:0;opacity:.85">{e["text"]}</div>'
                            f'<div id="{eid}c" style="position:absolute;left:0;right:0;{tc}color:#00f0ff;-webkit-text-stroke:0;opacity:.85">{e["text"]}</div>'
                            f'<div style="position:relative;{tc}">{e["text"]}</div></div>')
                for j, (dx, dy) in enumerate([(16, -6), (-20, 5), (12, 8), (-8, -4), (0, 0)]):
                    tt = t + j * 0.05
                    js.append(f'tl.set("#{eid}r",{{x:{dx},y:{dy}}},{tt:.3f});tl.set("#{eid}c",{{x:{-dx},y:{-dy}}},{tt:.3f});')
            else:  # stamp
                html.append(f'<div id="{eid}" class="clip mgt" data-start="{t:.3f}" data-duration="{d:.3f}" style="top:{top}px;{_text_css(font, size, e["color"], stroke)}">{e["text"]}</div>')
                js.append(f'tl.fromTo("#{eid}",{{scale:2.8,rotation:-16,opacity:0}},{{scale:1,rotation:-6,opacity:1,duration:0.16,ease:"power4.in"}},{t:.3f});'
                          f'tl.to("#{eid}",{{scale:1.06,duration:0.5,ease:"sine.inOut",yoyo:true,repeat:1}},{t + 0.2:.3f});')
            js.append(f'tl.to("#{eid}",{{scale:0.4,opacity:0,duration:0.14,ease:"power2.in"}},{t + d - 0.15:.3f});')
        elif typ == "emoji":
            size = int({"s": 110, "m": 170, "l": 250}[e["size"]] * k)
            x, y = int(e["x"] * w - size / 2), int(e["y"] * h - size / 2)
            html.append(f'<div id="{eid}" class="clip mg" data-start="{t:.3f}" data-duration="{d:.3f}" style="left:{x}px;top:{y}px;font-size:{size}px;line-height:1;'
                        f'font-family:\'Segoe UI Emoji\',\'Apple Color Emoji\',\'Noto Color Emoji\',sans-serif;filter:drop-shadow(0 {int(10 * k)}px {int(12 * k)}px rgba(0,0,0,.5));z-index:27">{e["emoji"]}</div>')
            if e["motion"] == "float":
                js.append(f'tl.fromTo("#{eid}",{{y:60,opacity:0,scale:0.6}},{{y:0,opacity:1,scale:1,duration:0.25,ease:"back.out(2)"}},{t:.3f});'
                          f'tl.to("#{eid}",{{y:-160,rotation:12,duration:{d:.3f},ease:"none"}},{t:.3f});')
            elif e["motion"] == "spin":
                js.append(f'tl.fromTo("#{eid}",{{scale:0,rotation:-360}},{{scale:1,rotation:0,duration:0.45,ease:"back.out(1.6)"}},{t:.3f});')
            else:
                js.append(f'tl.fromTo("#{eid}",{{scale:0,rotation:-25}},{{scale:1,rotation:8,duration:0.3,ease:"elastic.out(1.1,0.5)"}},{t:.3f});'
                          f'tl.to("#{eid}",{{y:-14,duration:0.3,yoyo:true,repeat:{max(1, int(d / 0.3) - 1)},ease:"sine.inOut"}},{t + 0.3:.3f});')
            js.append(f'tl.to("#{eid}",{{scale:0,opacity:0,duration:0.14}},{t + d - 0.15:.3f});')
        elif typ == "speedlines":
            lines = []
            for j in range(36):
                a = j * 2 * math.pi / 36 + (0.05 if j % 3 == 0 else 0)
                r0 = 0.42 + 0.12 * ((j * 7) % 5) / 5
                x1, y1 = 50 + 50 * r0 * math.cos(a), 50 + 50 * r0 * math.sin(a)
                x2, y2 = 50 + 80 * math.cos(a), 50 + 80 * math.sin(a)
                lines.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#fff" stroke-width="{0.35 + (j % 3) * 0.25:.2f}"/>')
            html.append(f'<svg id="{eid}" class="clip mg" data-start="{t:.3f}" data-duration="{d:.3f}" viewBox="0 0 100 100" preserveAspectRatio="none" '
                        f'style="left:0;top:0;width:{w}px;height:{h}px;z-index:22;opacity:.75">{"".join(lines)}</svg>')
            js.append(f'tl.fromTo("#{eid}",{{opacity:0,scale:1.25}},{{opacity:0.8,scale:1,duration:0.15}},{t:.3f});')
            for j in range(int(d / 0.1)):
                js.append(f'tl.set("#{eid}",{{rotation:{(-1.5 if j % 2 else 1.5)}}},{t + 0.15 + j * 0.1:.3f});')
            js.append(f'tl.to("#{eid}",{{opacity:0,duration:0.15}},{t + d - 0.15:.3f});')
        elif typ == "vignette":
            html.append(f'<div id="{eid}" class="clip mg" data-start="{t:.3f}" data-duration="{d:.3f}" style="inset:0;z-index:21;'
                        f'background:radial-gradient(ellipse at center, rgba(0,0,0,0) 45%, rgba(170,0,0,.75) 100%)"></div>')
            js.append(f'tl.fromTo("#{eid}",{{opacity:0}},{{opacity:1,duration:0.25,yoyo:true,repeat:{max(1, int(d / 0.25) - 1)},ease:"sine.inOut"}},{t:.3f});')
        elif typ == "arrow":
            cx, cy = e["x"] * w, e["y"] * h
            r = int(85 * k)
            left = cx > w / 2
            ax = cx - r * 2.8 if left else cx + r * 2.8
            ay = cy + r * 2.0
            ang = math.atan2(cy - ay, cx - ax)
            ex, ey = cx - math.cos(ang) * (r + 14 * k), cy - math.sin(ang) * (r + 14 * k)
            hl = 70 * k
            p1 = (ex + math.cos(ang + math.pi - 0.45) * hl, ey + math.sin(ang + math.pi - 0.45) * hl)
            p2 = (ex + math.cos(ang + math.pi + 0.45) * hl, ey + math.sin(ang + math.pi + 0.45) * hl)
            sw = int(22 * k)
            html.append(f'<div id="{eid}" class="clip mg" data-start="{t:.3f}" data-duration="{d:.3f}" style="left:0;top:0;width:{w}px;height:{h}px;z-index:28">'
                        f'<div id="{eid}c" style="position:absolute;left:{cx - r:.0f}px;top:{cy - r:.0f}px;width:{2 * r}px;height:{2 * r}px;border-radius:50%;'
                        f'border:{int(12 * k)}px solid #ff1e1e;box-shadow:0 0 0 {int(5 * k)}px #000,inset 0 0 0 {int(4 * k)}px #000"></div>'
                        f'<svg style="position:absolute;left:0;top:0" width="{w}" height="{h}" viewBox="0 0 {w} {h}"><g id="{eid}a">'
                        f'<line x1="{ax:.0f}" y1="{ay:.0f}" x2="{ex:.0f}" y2="{ey:.0f}" stroke="#000" stroke-width="{sw + 10}" stroke-linecap="round"/>'
                        f'<polygon points="{ex:.0f},{ey:.0f} {p1[0]:.0f},{p1[1]:.0f} {p2[0]:.0f},{p2[1]:.0f}" fill="#ff1e1e" stroke="#000" stroke-width="8" stroke-linejoin="round"/>'
                        f'<line x1="{ax:.0f}" y1="{ay:.0f}" x2="{ex:.0f}" y2="{ey:.0f}" stroke="#ff1e1e" stroke-width="{sw}" stroke-linecap="round"/>'
                        f'</g></svg></div>')
            js.append(f'tl.fromTo("#{eid}c",{{scale:0}},{{scale:1,duration:0.3,ease:"back.out(2.5)"}},{t:.3f});'
                      f'tl.fromTo("#{eid}a",{{scale:0,svgOrigin:"{ax:.0f} {ay:.0f}"}},{{scale:1,svgOrigin:"{ax:.0f} {ay:.0f}",duration:0.25,ease:"back.out(1.5)"}},{t + 0.1:.3f});'
                      f'tl.to("#{eid}c",{{scale:1.12,duration:0.25,yoyo:true,repeat:{max(1, int(d / 0.25) - 2)}}},{t + 0.35:.3f});')
        elif typ == "label":
            ev.update(text=_txt(e.get("text") or "ME:", 18), x=_num(e.get("x"), 0.05, 0.7, 0.08),
                      y=_num(e.get("y"), 0.1, 0.6, 0.2))
        sfx = str(e.get("sfx") or "").strip()
        if sfx.lower() in ("none", "no", "-"):
            sfx = ""
        elif not sfx or not fx.sfx_path(sfx):
            sfx = DEFAULT_SFX.get(typ, "") if typ != "sfx" else ""
        ev["sfx"] = sfx
        ev["volume"] = _num(e.get("volume"), 0.0, 1.5, 0.85)
        out["events"].append(ev)
    return out


# ------------------------------------------------------------------ rendering

def _text_css(font, size, color, stroke):
    return (f"font-family:'{font}','Luckiest Guy',sans-serif;font-size:{size}px;color:{color};line-height:1.02;"
            f'-webkit-text-stroke:{stroke}px #000;paint-order:stroke fill;'
            f'text-shadow:0 {stroke}px 0 #000,0 {stroke * 2}px {stroke * 3}px rgba(0,0,0,.45);')


def render(plan: dict, w: int, h: int, dur: float, master_volume: float = 1.0) -> dict:
    """Returns {"css", "html", "js", "sounds": [{path, t, dur, volume}]}."""
    k = min(w, h) / 1080
    font = plan.get("font") or "Luckiest Guy"
    css, html, js, sounds = [], [], [], []

    def sound(sid, t, vol=0.85):
        p = fx.sfx_path(sid)
        if not p:
            return
        start = max(0.0, t - fx.sfx_sync(sid))
        length = float(fx.catalog().get(fx.ALIASES.get(sid, sid), {}).get("duration") or 2.0)
        if start < dur - 0.05:
            sounds.append({"path": str(p), "t": round(start, 3), "dur": round(min(length + 0.05, dur - start), 3),
                           "volume": round(max(0.0, min(2.0, vol * master_volume)), 3)})

    css.append(f""".mg {{ position:absolute; z-index:24; pointer-events:none; }}
.mgt {{ position:absolute; left:0; right:0; text-align:center; transform-origin:50% 50%; z-index:26; }}
.mgt span {{ display:inline-block; }}""")

    # progress bar
    if plan.get("progress_bar", True):
        html.append(f'<div id="pbar" class="clip mg" data-start="0" data-duration="{dur:.3f}" '
                    f'style="left:0;top:0;height:{int(12 * k)}px;width:{w}px;background:linear-gradient(90deg,#7c5cff,#ff4fd8,#ffe600);transform-origin:0 50%;z-index:40"></div>')
        js.append(f'tl.fromTo("#pbar",{{scaleX:0}},{{scaleX:1,duration:{dur:.3f},ease:"none"}},0);')

    # hook
    hk = plan.get("hook") or {}
    if hk.get("text"):
        hd = min(2.8, max(1.2, dur * 0.3))
        col = _color(hk.get("color"))
        hfont = hk.get("font") or font
        text = _txt(hk["text"], 60)
        size = int((118 if len(text) < 18 else 96 if len(text) < 30 else 80) * k)
        top = int(h * 0.11)
        style = hk.get("style", "box")
        if style == "box":
            html.append(f'<div id="hook" class="clip mgt" data-start="0" data-duration="{hd:.3f}" style="top:{top}px;padding:0 {int(70 * k)}px">'
                        f'<span style="background:{col};color:#111;font-family:\'{hfont}\';font-size:{size}px;line-height:1.08;'
                        f'padding:{int(14 * k)}px {int(30 * k)}px;border-radius:{int(22 * k)}px;box-shadow:0 {int(14 * k)}px 0 #000,0 {int(24 * k)}px {int(40 * k)}px rgba(0,0,0,.5);'
                        f'border:{int(6 * k)}px solid #000">{text}</span></div>')
            js.append('tl.fromTo("#hook",{y:-260,rotation:-6,opacity:0},{y:0,rotation:-2,opacity:1,duration:0.42,ease:"back.out(1.8)"},0.05);')
        elif style == "stamp":
            html.append(f'<div id="hook" class="clip mgt" data-start="0" data-duration="{hd:.3f}" style="top:{top}px;padding:0 {int(60 * k)}px;{_text_css(hfont, int(size * 1.1), col, max(6, int(size / 11)))}">{text}</div>')
            js.append('tl.fromTo("#hook",{scale:3.2,rotation:-12,opacity:0},{scale:1,rotation:-4,opacity:1,duration:0.22,ease:"power4.in"},0.05);'
                      'tl.to("#hook",{x:14,duration:0.04,repeat:5,yoyo:true},0.27);tl.set("#hook",{x:0},0.5);')
        elif style == "slide":
            words = text.split(" ")
            a, b = " ".join(words[:max(1, len(words) // 2)]), " ".join(words[max(1, len(words) // 2):])
            html.append(f'<div id="hook" class="clip mgt" data-start="0" data-duration="{hd:.3f}" style="top:{top}px;{_text_css(hfont, size, col, max(6, int(size / 11)))}">'
                        f'<div id="hookA">{a}</div><div id="hookB" style="color:#fff">{b}</div></div>')
            js.append('tl.from("#hookA",{x:-1200,skewX:20,duration:0.35,ease:"expo.out"},0.05);'
                      'tl.from("#hookB",{x:1200,skewX:-20,duration:0.35,ease:"expo.out"},0.18);')
        else:  # glitch
            st = _text_css(hfont, size, col, max(6, int(size / 11)))
            html.append(f'<div id="hook" class="clip mgt" data-start="0" data-duration="{hd:.3f}" style="top:{top}px;padding:0 {int(60 * k)}px">'
                        f'<div id="hookR" style="position:absolute;left:0;right:0;opacity:.8;{st}color:#ff004c;-webkit-text-stroke:0">{text}</div>'
                        f'<div id="hookC" style="position:absolute;left:0;right:0;opacity:.8;{st}color:#00f0ff;-webkit-text-stroke:0">{text}</div>'
                        f'<div style="position:relative;{st}">{text}</div></div>')
            js.append('tl.from("#hook",{opacity:0,duration:0.06},0.05);')
            for i, (dx, dy) in enumerate([(14, -6), (-18, 4), (10, 8), (-6, -4), (0, 0)]):
                tt = 0.05 + i * 0.06
                js.append(f'tl.set("#hookR",{{x:{dx},y:{dy}}},{tt:.2f});tl.set("#hookC",{{x:{-dx},y:{-dy}}},{tt:.2f});')
        js.append(f'tl.to("#hook",{{y:-80,opacity:0,scale:0.9,duration:0.25,ease:"power2.in"}},{hd - 0.27:.3f});')
        sound(HOOK_SFX.get(style, "whoosh-fast-hard"), 0.12, 0.8)

    # events
    for i, e in enumerate(plan.get("events") or []):
        t, d, typ = e["t"], e["dur"], e["type"]
        eid = f"e{i}"
        if typ == "punch":
            ox, oy = e["x"] * 100, e["y"] * 100
            inn = 0.1 if e["ease"] == "snap" else 0.35
            js.append(f'tl.set("#base",{{transformOrigin:"{ox:.0f}% {oy:.0f}%"}},{t:.3f});'
                      f'tl.to("#base",{{scale:{e["scale"]:.3f},duration:{inn},ease:"{"expo.out" if e["ease"] == "snap" else "power2.out"}"}},{t:.3f});'
                      f'tl.to("#base",{{scale:1,duration:0.3,ease:"power2.inOut"}},{t + max(inn, d):.3f});')
        elif typ == "shake":
            amp = int(18 * e["strength"] * k)
            n = max(3, int(d / 0.045))
            for j in range(n):
                tt = t + j * d / n
                fall = 1 - j / n
                dx = amp * fall * (1 if j % 2 == 0 else -1)
                dy = amp * 0.6 * fall * (1 if (j // 2) % 2 == 0 else -1)
                js.append(f'tl.set("#base",{{x:{dx:.1f},y:{dy:.1f},rotation:{(dx / amp if amp else 0) * 0.8:.2f}}},{tt:.3f});')
            js.append(f'tl.set("#base",{{x:0,y:0,rotation:0}},{t + d:.3f});')
        elif typ == "flash":
            html.append(f'<div id="{eid}" class="clip mg" data-start="{t:.3f}" data-duration="0.28" style="inset:0;background:#fff;z-index:45"></div>')
            js.append(f'tl.fromTo("#{eid}",{{opacity:0.9}},{{opacity:0,duration:0.26,ease:"power2.out"}},{t:.3f});')
        elif typ == "pop":
            size = int((150 if len(e["text"]) <= 8 else 120 if len(e["text"]) <= 14 else 96) * k)
            top = int(h * e["y"])
            stroke = max(7, int(size / 10))
            st = e["style"]
            if st == "burst":
                pts = []
                for j in range(24):
                    r = 1.0 if j % 2 == 0 else 0.72
                    a = j * math.pi / 12
                    pts.append(f"{50 + 50 * r * math.cos(a):.1f},{50 + 42 * r * math.sin(a):.1f}")
                html.append(f'<div id="{eid}" class="clip mgt" data-start="{t:.3f}" data-duration="{d:.3f}" style="top:{top - int(60 * k)}px;height:{int(size * 2.2)}px">'
                            f'<svg id="{eid}b" viewBox="0 0 100 100" preserveAspectRatio="none" style="position:absolute;left:12%;width:76%;height:100%">'
                            f'<polygon points="{" ".join(pts)}" fill="{e["color"]}" stroke="#000" stroke-width="2.2"/></svg>'
                            f'<div style="position:relative;top:{int(size * 0.55)}px;{_text_css(font, size, "#fff", stroke)}">{e["text"]}</div></div>')
                js.append(f'tl.fromTo("#{eid}",{{scale:0,rotation:-20}},{{scale:1,rotation:-4,duration:0.32,ease:"elastic.out(1,0.55)"}},{t:.3f});'
                          f'tl.to("#{eid}b",{{rotation:12,duration:{d:.3f},ease:"none"}},{t:.3f});')
            elif st == "slide":
                html.append(f'<div id="{eid}" class="clip mgt" data-start="{t:.3f}" data-duration="{d:.3f}" style="top:{top}px">'
                            f'<span style="background:{e["color"]};padding:{int(10 * k)}px {int(34 * k)}px;transform:skewX(-10deg);'
                            f'border:{int(6 * k)}px solid #000;box-shadow:{int(12 * k)}px {int(12 * k)}px 0 #000;{_text_css(font, int(size * 0.85), "#111", 0)}-webkit-text-stroke:0;text-shadow:none">{e["text"]}</span></div>')
                js.append(f'tl.fromTo("#{eid}",{{x:-1300}},{{x:0,duration:0.26,ease:"expo.out"}},{t:.3f});')
            elif st == "bounce":
                html.append(f'<div id="{eid}" class="clip mgt" data-start="{t:.3f}" data-duration="{d:.3f}" style="top:{top}px;{_text_css(font, size, e["color"], stroke)}">{e["text"]}</div>')
                js.append(f'tl.fromTo("#{eid}",{{y:-700,scaleY:1.3}},{{y:0,scaleY:1,duration:0.55,ease:"bounce.out"}},{t:.3f});')
            elif st == "glitch":
                tc = _text_css(font, size, e["color"], stroke)
                html.append(f'<div id="{eid}" class="clip mgt" data-start="{t:.3f}" data-duration="{d:.3f}" style="top:{top}px">'
                            f'<div id="{eid}r" style="position:absolute;left:0;right:0;{tc}color:#ff004c;-webkit-text-stroke:0;opacity:.85">{e["text"]}</div>'
                            f'<div id="{eid}c" style="position:absolute;left:0;right:0;{tc}color:#00f0ff;-webkit-text-stroke:0;opacity:.85">{e["text"]}</div>'
                            f'<div style="position:relative;{tc}">{e["text"]}</div></div>')
                for j, (dx, dy) in enumerate([(16, -6), (-20, 5), (12, 8), (-8, -4), (0, 0)]):
                    tt = t + j * 0.05
                    js.append(f'tl.set("#{eid}r",{{x:{dx},y:{dy}}},{tt:.3f});tl.set("#{eid}c",{{x:{-dx},y:{-dy}}},{tt:.3f});')
            else:  # stamp
                html.append(f'<div id="{eid}" class="clip mgt" data-start="{t:.3f}" data-duration="{d:.3f}" style="top:{top}px;{_text_css(font, size, e["color"], stroke)}">{e["text"]}</div>')
                js.append(f'tl.fromTo("#{eid}",{{scale:2.8,rotation:-16,opacity:0}},{{scale:1,rotation:-6,opacity:1,duration:0.16,ease:"power4.in"}},{t:.3f});'
                          f'tl.to("#{eid}",{{scale:1.06,duration:0.5,ease:"sine.inOut",yoyo:true,repeat:1}},{t + 0.2:.3f});')
            js.append(f'tl.to("#{eid}",{{scale:0.4,opacity:0,duration:0.14,ease:"power2.in"}},{t + d - 0.15:.3f});')
        elif typ == "emoji":
            size = int({"s": 110, "m": 170, "l": 250}[e["size"]] * k)
            x, y = int(e["x"] * w - size / 2), int(e["y"] * h - size / 2)
            html.append(f'<div id="{eid}" class="clip mg" data-start="{t:.3f}" data-duration="{d:.3f}" style="left:{x}px;top:{y}px;font-size:{size}px;line-height:1;'
                        f'font-family:\'Segoe UI Emoji\',\'Apple Color Emoji\',\'Noto Color Emoji\',sans-serif;filter:drop-shadow(0 {int(10 * k)}px {int(12 * k)}px rgba(0,0,0,.5));z-index:27">{e["emoji"]}</div>')
            if e["motion"] == "float":
                js.append(f'tl.fromTo("#{eid}",{{y:60,opacity:0,scale:0.6}},{{y:0,opacity:1,scale:1,duration:0.25,ease:"back.out(2)"}},{t:.3f});'
                          f'tl.to("#{eid}",{{y:-160,rotation:12,duration:{d:.3f},ease:"none"}},{t:.3f});')
            elif e["motion"] == "spin":
                js.append(f'tl.fromTo("#{eid}",{{scale:0,rotation:-360}},{{scale:1,rotation:0,duration:0.45,ease:"back.out(1.6)"}},{t:.3f});')
            else:
                js.append(f'tl.fromTo("#{eid}",{{scale:0,rotation:-25}},{{scale:1,rotation:8,duration:0.3,ease:"elastic.out(1.1,0.5)"}},{t:.3f});'
                          f'tl.to("#{eid}",{{y:-14,duration:0.3,yoyo:true,repeat:{max(1, int(d / 0.3) - 1)},ease:"sine.inOut"}},{t + 0.3:.3f});')
            js.append(f'tl.to("#{eid}",{{scale:0,opacity:0,duration:0.14}},{t + d - 0.15:.3f});')
        elif typ == "speedlines":
            lines = []
            for j in range(36):
                a = j * 2 * math.pi / 36 + (0.05 if j % 3 == 0 else 0)
                r0 = 0.42 + 0.12 * ((j * 7) % 5) / 5
                x1, y1 = 50 + 50 * r0 * math.cos(a), 50 + 50 * r0 * math.sin(a)
                x2, y2 = 50 + 80 * math.cos(a), 50 + 80 * math.sin(a)
                lines.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#fff" stroke-width="{0.35 + (j % 3) * 0.25:.2f}"/>')
            html.append(f'<svg id="{eid}" class="clip mg" data-start="{t:.3f}" data-duration="{d:.3f}" viewBox="0 0 100 100" preserveAspectRatio="none" '
                        f'style="left:0;top:0;width:{w}px;height:{h}px;z-index:22;opacity:.75">{"".join(lines)}</svg>')
            js.append(f'tl.fromTo("#{eid}",{{opacity:0,scale:1.25}},{{opacity:0.8,scale:1,duration:0.15}},{t:.3f});')
            for j in range(int(d / 0.1)):
                js.append(f'tl.set("#{eid}",{{rotation:{(-1.5 if j % 2 else 1.5)}}},{t + 0.15 + j * 0.1:.3f});')
            js.append(f'tl.to("#{eid}",{{opacity:0,duration:0.15}},{t + d - 0.15:.3f});')
        elif typ == "vignette":
            html.append(f'<div id="{eid}" class="clip mg" data-start="{t:.3f}" data-duration="{d:.3f}" style="inset:0;z-index:21;'
                        f'background:radial-gradient(ellipse at center, rgba(0,0,0,0) 45%, rgba(170,0,0,.75) 100%)"></div>')
            js.append(f'tl.fromTo("#{eid}",{{opacity:0}},{{opacity:1,duration:0.25,yoyo:true,repeat:{max(1, int(d / 0.25) - 1)},ease:"sine.inOut"}},{t:.3f});')
        elif typ == "arrow":
            cx, cy = e["x"] * w, e["y"] * h
            r = int(85 * k)
            left = cx > w / 2
            ax = cx - r * 2.8 if left else cx + r * 2.8
            ay = cy + r * 2.0
            ang = math.degrees(math.atan2(cy - ay, cx - ax))
            length = math.hypot(cx - ax, cy - ay) - r - 10
            html.append(f'<div id="{eid}" class="clip mg" data-start="{t:.3f}" data-duration="{d:.3f}" style="left:0;top:0;width:{w}px;height:{h}px;z-index:28">'
                        f'<div id="{eid}c" style="position:absolute;left:{cx - r:.0f}px;top:{cy - r:.0f}px;width:{2 * r}px;height:{2 * r}px;border-radius:50%;'
                        f'border:{int(12 * k)}px solid #ff1e1e;box-shadow:0 0 0 {int(5 * k)}px #000,inset 0 0 0 {int(4 * k)}px #000"></div>'
                        f'<div id="{eid}a" style="position:absolute;left:{ax:.0f}px;top:{ay:.0f}px;width:{length:.0f}px;height:{int(22 * k)}px;transform-origin:0 50%;'
                        f'transform:rotate({ang:.1f}deg);background:#ff1e1e;border:{int(4 * k)}px solid #000;border-radius:{int(10 * k)}px"></div></div>')
            js.append(f'tl.fromTo("#{eid}c",{{scale:0}},{{scale:1,duration:0.3,ease:"back.out(2.5)"}},{t:.3f});'
                      f'tl.fromTo("#{eid}a",{{scaleX:0}},{{scaleX:1,duration:0.22,ease:"power3.out"}},{t + 0.12:.3f});'
                      f'tl.to("#{eid}c",{{scale:1.12,duration:0.25,yoyo:true,repeat:{max(1, int(d / 0.25) - 2)}}},{t + 0.35:.3f});')
        elif typ == "label":
            size = int(64 * k)
            html.append(f'<div id="{eid}" class="clip mg" data-start="{t:.3f}" data-duration="{d:.3f}" style="left:{int(e["x"] * w)}px;top:{int(e["y"] * h)}px;z-index:27;'
                        f'background:#fff;color:#111;font-family:\'Archivo Black\';font-size:{size}px;padding:{int(6 * k)}px {int(20 * k)}px;'
                        f'border:{int(5 * k)}px solid #000;border-radius:{int(14 * k)}px;box-shadow:{int(8 * k)}px {int(8 * k)}px 0 #000;transform:rotate(-3deg)">{e["text"]}</div>')
            js.append(f'tl.fromTo("#{eid}",{{x:-500,opacity:0}},{{x:0,opacity:1,duration:0.25,ease:"back.out(1.6)"}},{t:.3f});')
        if e.get("sfx"):
            sound(e["sfx"], t + (0.05 if typ == "punch" else 0), e.get("volume", 0.85))
    return {"css": "\n".join(css), "html": "\n".join(html), "js": "\n".join(js), "sounds": sounds}
