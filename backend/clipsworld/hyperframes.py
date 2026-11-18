"""HyperFrames editing (HeyGen's open-source "HTML → video" renderer).

For each clip:
  1. Clipsworld renders the framed base video (layout + audio + voice bubble, no captions).
  2. Clipsworld writes word-synced animated captions as HTML/GSAP (reliable, exact timing).
  3. Claude designs the motion graphics on top: hook title, text/emoji pops, punch-in zooms and
     shakes on the punchlines, accents and sound effects.
  4. The HyperFrames CLI renders it to MP4 on this PC.

The "Motion graphics pack" (Node.js + HyperFrames + Chrome headless shell) downloads once.
"""
import html as htmlmod
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

from . import ai, captions, effects as fx, media
from .paths import IS_WIN, data_dir, fonts_dir

HF_VERSION = "0.9.65"
GSAP_VERSION = "3.15.0"
UA = {"User-Agent": "Clipsworld/1.6"}


def pack_dir() -> Path:
    p = data_dir() / "hyperframes"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ------------------------------------------------------------------ tools

def tools() -> dict:
    d = pack_dir()
    if IS_WIN:
        node = next(iter(sorted(d.glob("node-*/node.exe"))), None)
        npm = next(iter(sorted(d.glob("node-*/node_modules/npm/bin/npm-cli.js"))), None)
        chrome = next(iter(sorted(d.glob("chrome-headless-shell*/**/chrome-headless-shell.exe"))), None)
    else:
        node = shutil.which("node")
        npm = shutil.which("npm")
        chrome = os.environ.get("CLIPSWORLD_CHROME") or shutil.which("google-chrome") or shutil.which("chromium")
    hf = d / "app" / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"
    gsap = d / "app" / "node_modules" / "gsap" / "dist" / "gsap.min.js"
    return {"node": str(node) if node else None, "npm": str(npm) if npm else None,
            "chrome": str(chrome) if chrome else None,
            "hf": str(hf) if hf.exists() else None, "gsap": str(gsap) if gsap.exists() else None}


def ready() -> bool:
    t = tools()
    return all(t[k] for k in ("node", "chrome", "hf", "gsap"))


def _head_size(url: str) -> int:
    req = urllib.request.Request(url, method="HEAD", headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return int(r.headers.get("Content-Length") or 0)


def pack_files() -> list:
    """Files for the downloads manager (Windows): Node.js and Chrome headless shell."""
    d = pack_dir() / "_download"
    d.mkdir(parents=True, exist_ok=True)
    man = d / "manifest.json"
    if man.exists():
        try:
            return json.loads(man.read_text(encoding="utf-8"))
        except Exception:
            pass
    files = []
    if IS_WIN:
        with urllib.request.urlopen(urllib.request.Request("https://nodejs.org/dist/index.json", headers=UA), timeout=30) as r:
            versions = json.load(r)
        v = next(x["version"] for x in versions if x["version"].startswith("v22.") and "win-x64-zip" in x.get("files", []))
        url = f"https://nodejs.org/dist/{v}/node-{v}-win-x64.zip"
        sha = ""
        try:
            with urllib.request.urlopen(urllib.request.Request(f"https://nodejs.org/dist/{v}/SHASUMS256.txt", headers=UA), timeout=30) as r:
                for line in r.read().decode().splitlines():
                    if line.endswith(f"node-{v}-win-x64.zip"):
                        sha = line.split()[0]
        except Exception:
            pass
        files.append({"name": "Node.js", "url": url, "size": _head_size(url), "sha256": sha, "dest": str(d / f"node-{v}.zip")})
        with urllib.request.urlopen(urllib.request.Request(
                "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json",
                headers=UA), timeout=30) as r:
            cft = json.load(r)
        dl = next(x["url"] for x in cft["channels"]["Stable"]["downloads"]["chrome-headless-shell"] if x["platform"] == "win64")
        files.append({"name": "Chrome renderer", "url": dl, "size": _head_size(dl), "sha256": "",
                      "dest": str(d / "chrome-headless-shell.zip")})
    man.write_text(json.dumps(files), encoding="utf-8")
    return files


def pack_finish(task):
    """Unzip Node + Chrome, then install HyperFrames + GSAP with npm."""
    d = pack_dir()
    for f in task.files:
        p = Path(f["dest"])
        task.stage = f"Unpacking {f['name']}…"
        if not zipfile.is_zipfile(p):
            p.unlink(missing_ok=True)
            raise RuntimeError(f"{f['name']} was damaged. Press Retry to download it again.")
        with zipfile.ZipFile(p) as z:
            z.extractall(d)
    t = tools()
    if not t["node"] or not t["npm"]:
        raise RuntimeError("Node.js is missing from the motion graphics pack.")
    task.stage = "Installing HyperFrames…"
    app = d / "app"
    app.mkdir(exist_ok=True)
    (app / "package.json").write_text('{"name":"clipsworld-hf","private":true}', encoding="utf-8")
    cmd = ([t["node"], t["npm"]] if t["npm"].endswith(".js") else [t["npm"]]) + [
        "install", f"hyperframes@{HF_VERSION}", f"gsap@{GSAP_VERSION}", "--no-audit", "--no-fund", "--loglevel=error"]
    r = subprocess.run(cmd, cwd=str(app), capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=media.NO_WINDOW, env=_env())
    if r.returncode != 0 or not tools()["hf"]:
        raise RuntimeError("Installing HyperFrames failed: " + (r.stderr or r.stdout)[-500:])
    for f in task.files:
        Path(f["dest"]).unlink(missing_ok=True)
    (d / "_download" / "manifest.json").unlink(missing_ok=True)


def _env() -> dict:
    e = dict(os.environ)
    t = tools()
    if t["node"]:
        e["PATH"] = str(Path(t["node"]).parent) + os.pathsep + e.get("PATH", "")
    e.update({"HYPERFRAMES_NO_TELEMETRY": "1", "DO_NOT_TRACK": "1", "HYPERFRAMES_SKIP_SKILLS": "1",
              "HYPERFRAMES_RENDER_LOCK": "off", "NO_UPDATE_NOTIFIER": "1"})
    try:
        e["HYPERFRAMES_FFMPEG_PATH"] = media.tool("ffmpeg")
        e["HYPERFRAMES_FFPROBE_PATH"] = media.tool("ffprobe")
    except FileNotFoundError:
        pass
    if t["chrome"]:
        e["PRODUCER_HEADLESS_SHELL_PATH"] = t["chrome"]
    return e


# ------------------------------------------------------------------ composition

SYSTEM = """You are the motion designer of a top Indian YouTube Shorts channel. You add motion graphics
to a clip with HyperFrames (HTML + CSS + GSAP rendered to video). The base video and the captions
already exist; you add everything that makes it feel professionally edited.

Contract (follow exactly, or the render breaks):
- Canvas {w}x{h}px, duration {d:.2f}s. The base video is <video id="base"> filling the frame; never add
  another video and never change its src. You MAY animate #base (scale / x / y / rotation) for punch-in
  zooms and shakes, always returning to scale 1, x 0, y 0.
- Every element you add must be inside the root and have class="clip", data-start (seconds) and
  data-duration (seconds), and position:absolute styling. z-index: overlays 20-40 (captions use 30).
- Animate ONLY with the provided paused GSAP timeline `tl` using absolute times:
  tl.to(selector, {{...}}, time) / tl.from / tl.fromTo / tl.set. No other timelines, no setTimeout,
  no Math.random, no Date, no network, no external images or fonts.
- Fonts you can use (font-family names): {fonts}.
- Keep text inside the safe area: x 60..{safe_r}px, y 160..{safe_b}px (YouTube buttons cover the right
  edge and the bottom). Captions sit around y {cap_y}px - don't cover them.

What to make:
1. Hook title in the first ~2.5 s (use the given hook text, big, bold, animated in and out).
2. 3-6 punch-in zooms or shakes on #base at the loudest / funniest moments (fast in ~0.12s, hold, ease back).
3. 2-5 text or emoji pops at punchlines (short Hinglish/English meme words, emojis are fine), with a
   playful entrance and exit.
4. Optional accents: a thin animated progress bar at the very top, highlight shapes, arrows.
5. Sound effects that land exactly on your pops and zooms (pick ids from: {sfx}).
Vary the look - don't make every clip identical. Stay tasteful: the clip must stay watchable.

Return with the answer tool:
- css: CSS rules for your elements (ids/classes you created)
- html: your overlay elements only (no <html>/<body>/<script>)
- js: JavaScript statements that use `tl`
- sounds: list of {{sfx, t, volume}}"""

SCHEMA = {"type": "object", "required": ["css", "html", "js"], "properties": {
    "css": {"type": "string"}, "html": {"type": "string"}, "js": {"type": "string"},
    "sounds": {"type": "array", "items": {"type": "object", "required": ["sfx", "t"], "properties": {
        "sfx": {"type": "string"}, "t": {"type": "number"}, "volume": {"type": "number"}}}}}}


def _font_faces(work: Path) -> tuple:
    css, names = [], []
    for family, file in captions.FONT_FILES.items():
        src = fonts_dir() / file
        if src.exists():
            (work / "fonts").mkdir(exist_ok=True)
            shutil.copy(src, work / "fonts" / file)
            css.append(f'@font-face {{ font-family: "{family}"; src: url("fonts/{file}"); font-display: block; }}')
            names.append(family)
    return "\n".join(css), names


def caption_layer(cues: list, clip_start: float, dur: float, style: dict, w: int, h: int, upper: bool) -> tuple:
    """Word-synced animated captions (HTML, CSS, JS)."""
    k = h / 1920
    size = int(style["size"] * k)
    cap_y = int(h * 0.66)
    stroke = max(2, int(style["bord"] * k * 1.6))
    css = f""".cap {{ position:absolute; left:{int(70 * k)}px; right:{int(140 * k)}px; top:{cap_y}px; z-index:30;
  text-align:center; font-family:"{style['font']}","Mukta ExtraBold",sans-serif; font-size:{size}px; line-height:1.08;
  color:{style['color']}; -webkit-text-stroke:{stroke}px {style['outline']}; paint-order:stroke fill;
  text-shadow:0 {int(6 * k)}px {int(10 * k)}px rgba(0,0,0,.45); transform-origin:50% 50%; }}
.cap .w {{ display:inline-block; margin:0 0.14em; transform-origin:50% 70%; }}
.cap.deva {{ font-family:"Mukta ExtraBold",sans-serif; font-size:{int(88 * k)}px; }}"""
    if style.get("box"):
        css += f"\n.cap .w {{ background:#141414; padding:0 {int(10 * k)}px; border-radius:{int(10 * k)}px; -webkit-text-stroke:0; }}"
    html_parts, js = [], []
    active = style.get("active") or style.get("karaoke") or "#FFE600"
    for i, q in enumerate(cues):
        a = max(0.0, q["start"] - clip_start)
        b = min(dur, q["end"] - clip_start)
        if b <= a + 0.05:
            continue
        words = q.get("words") or captions.respread_words(dict(q))["words"]
        deva = bool(captions.DEVANAGARI.search(q["text"]))
        spans = "".join(f'<span class="w" id="c{i}w{j}">{htmlmod.escape(x["word"].upper() if upper and not deva else x["word"])}</span>'
                        for j, x in enumerate(words))
        html_parts.append(f'<div id="c{i}" class="clip cap{" deva" if deva else ""}" data-start="{a:.3f}" '
                          f'data-duration="{b - a:.3f}" data-track-index="3">{spans}</div>')
        js.append(f'tl.from("#c{i}", {{scale:0.78, opacity:0, duration:0.12, ease:"back.out(2.5)"}}, {a:.3f});')
        for j, x in enumerate(words):
            ws = max(a, x["start"] - clip_start)
            we = min(b, (words[j + 1]["start"] - clip_start) if j + 1 < len(words) else b)
            js.append(f'tl.set("#c{i}w{j}", {{color:"{active}", scale:{style.get("active_scale", 112) / 100:.2f}}}, {ws:.3f});')
            if j + 1 < len(words):
                js.append(f'tl.set("#c{i}w{j}", {{color:"{style["color"]}", scale:1}}, {we:.3f});')
    return css, "\n".join(html_parts), "\n".join(js), cap_y


def build_index(work: Path, w: int, h: int, dur: float, fonts_css: str, cap: tuple, design: dict, sounds: list) -> str:
    cap_css, cap_html, cap_js, _ = cap
    audio = "\n".join(
        f'<audio id="s{i}" class="clip" src="sfx/{Path(s["path"]).name}" data-start="{s["t"]:.3f}" '
        f'data-duration="{s["dur"]:.3f}" data-volume="{s["volume"]:.2f}" data-track-index="6"></audio>'
        for i, s in enumerate(sounds))
    return f"""<!doctype html>
<html lang="hi" data-resolution="{'portrait' if h > w else 'landscape' if w > h else 'square'}">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width={w}, height={h}" />
<script src="gsap.min.js"></script>
<style>
{fonts_css}
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ width:{w}px; height:{h}px; overflow:hidden; background:#000; }}
#base {{ position:absolute; inset:0; width:100%; height:100%; object-fit:cover; transform-origin:50% 45%; z-index:1; }}
{cap_css}
/* motion design */
{design.get("css", "")}
</style>
</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{dur:.3f}" data-width="{w}" data-height="{h}">
<video id="base" class="clip" src="base.mp4" playsinline data-start="0" data-duration="{dur:.3f}" data-track-index="0" data-has-audio="true"></video>
{cap_html}
{design.get("html", "")}
{audio}
</div>
<script>
window.__timelines = window.__timelines || {{}};
const tl = gsap.timeline({{ paused: true }});
{cap_js}
try {{
{design.get("js", "")}
}} catch (e) {{ console.error("design error", e); }}
window.__timelines["main"] = tl;
</script>
</body>
</html>
"""


def _run_hf(args: list, cwd: Path, timeout: int = 1800, on_line=None):
    t = tools()
    p = subprocess.Popen([t["node"], t["hf"], *args], cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace", creationflags=media.NO_WINDOW, env=_env())
    out = []
    start = time.time()
    for line in p.stdout:
        out.append(line)
        if on_line:
            on_line(line)
        if time.time() - start > timeout:
            p.kill()
            raise RuntimeError("HyperFrames took too long.")
    p.wait()
    return p.returncode, "".join(out)


def edit_clip(job, project: dict, clip: dict, settings: dict, out_path: Path, progress_range=(0.0, 1.0)) -> dict:
    """Render one clip with HyperFrames. Raises on failure (the caller falls back to the normal editor)."""
    from . import render  # local import: render imports effects
    if not ready():
        raise RuntimeError("The motion graphics pack is not installed yet.")
    test_design = os.environ.get("CLIPSWORLD_HF_TEST_DESIGN")  # automated tests only: skip Claude
    if not settings.get("claude_api_key") and not test_design:
        raise RuntimeError("HyperFrames editing needs your Claude API key.")
    a, b = progress_range
    span = b - a
    fmt = (clip.get("layout") or {}).get("format", "short")
    w, h = render.FORMATS.get(fmt, render.FORMATS["short"])
    start, end = float(clip["start"]), float(clip["end"])
    dur = end - start
    work = Path(tempfile.mkdtemp(prefix="cw_hf_"))
    try:
        # 1) base video: framing + audio + voice bubble, no captions or effects
        job.update(progress=a, stage="HyperFrames: preparing the base video…")
        base_clip = json.loads(json.dumps(clip))
        base_clip["effects"] = []
        base_clip.setdefault("captions", {})["enabled"] = False
        base_clip["captions"]["show_hook"] = False
        render.export_clip(job, project, base_clip, settings, (a, a + span * 0.25), out_override=work / "base.mp4",
                           keyframes=True)
        shutil.copy(tools()["gsap"], work / "gsap.min.js")
        fonts_css, font_names = _font_faces(work)

        # 2) captions
        st = captions.STYLES.get(clip["captions"].get("style", "hormozi"), captions.STYLES["hormozi"])
        upper = st["upper"] if clip["captions"].get("uppercase") is None else clip["captions"]["uppercase"]
        cues = (clip["captions"].get("cues") or []) if clip["captions"].get("enabled", True) else []
        cap = caption_layer(cues, start, dur, st, w, h, upper)

        # 3) Claude designs the motion graphics
        job.update(progress=a + span * 0.3, stage="HyperFrames: Claude is designing the motion graphics…")
        from .highlights import excitement
        loud = project.get("loudness") or []
        z = excitement(loud)
        i0, i1 = int(start / 0.25), int(end / 0.25)
        peaks = sorted(range(max(0, i0), min(len(z), i1)), key=lambda i: -z[i])[:6] if len(z) else []
        peak_txt = ", ".join(f"{i * 0.25 - start:.1f}s" for i in sorted(peaks)) or "none"
        lines = [f"[{max(0, q['start'] - start):.1f}-{min(dur, q['end'] - start):.1f}] {q['text']}" for q in cues]
        sfx_ids = [s["id"] for s in fx.sfx_list() if s["source"] == "builtin"]
        system = SYSTEM.format(w=w, h=h, d=dur, fonts=", ".join(font_names), safe_r=int(w * 0.84),
                               safe_b=int(h * 0.80), cap_y=cap[3], sfx=", ".join(sfx_ids))
        user = (f"Clip title: {clip.get('title', '')}\nHook text: {clip.get('hook') or clip.get('title', '')}\n"
                f"Category: {clip.get('category', '')}\nLoudest moments (seconds): {peak_txt}\n"
                f"Captions (seconds):\n" + "\n".join(lines))
        model = settings.get("ap_hf_model") or "claude-sonnet-5-5"
        if test_design:
            design = json.loads(Path(test_design).read_text(encoding="utf-8"))
        else:
            design = ai._ask_json(settings["claude_api_key"], model, system, user, SCHEMA, "hyperframes", max_tokens=12000)

        # 4) sounds
        sounds = []
        (work / "sfx").mkdir()
        for s in ai._as_list(design.get("sounds")):
            if not isinstance(s, dict):
                continue
            p = fx.sfx_path(str(s.get("sfx", "")))
            try:
                t = float(s.get("t", 0))
            except (TypeError, ValueError):
                continue
            if not p or not (0 <= t < dur):
                continue
            shutil.copy(p, work / "sfx" / p.name)
            vol = float(s.get("volume") or 0.8) * float((clip.get("audio") or {}).get("sfx_volume", 1.0))
            sounds.append({"path": str(p), "t": t, "dur": min(3.0, dur - t), "volume": max(0.0, min(2.0, vol))})

        index = build_index(work, w, h, dur, fonts_css, cap, design, sounds)
        (work / "index.html").write_text(index, encoding="utf-8")
        (work / "hyperframes.json").write_text('{"name":"clipsworld-clip"}', encoding="utf-8")

        # 5) lint; let Claude fix errors once
        code, out = _run_hf(["lint", ".", "--json"], work, timeout=180)
        errs = _lint_errors(out)
        if errs and test_design:
            raise RuntimeError("HyperFrames lint: " + "; ".join(errs[:5]))
        if errs:
            job.update(stage="HyperFrames: fixing the design…")
            fix_user = user + "\n\nYour previous answer had these HyperFrames errors, fix them:\n" + "\n".join(errs[:15]) + \
                "\n\nPrevious answer:\n" + json.dumps({k: design.get(k) for k in ("css", "html", "js")}, ensure_ascii=False)[:20000]
            design = ai._ask_json(settings["claude_api_key"], model, system, fix_user, SCHEMA, "hyperframes_fix", max_tokens=12000)
            index = build_index(work, w, h, dur, fonts_css, cap, design, sounds)
            (work / "index.html").write_text(index, encoding="utf-8")

        # 6) render
        job.update(progress=a + span * 0.45, stage="HyperFrames: rendering…")
        t0 = time.time()
        est = max(20.0, dur * 4)

        def tick(_line):
            job.update(progress=a + span * (0.45 + 0.5 * min(1.0, (time.time() - t0) / est)))

        code, out = _run_hf(["render", ".", "-o", str(out_path), "--quality", "looks", "--fps", "30", "--quiet"],
                            work, on_line=tick)
        if code != 0 or not out_path.exists() or out_path.stat().st_size < 10000:
            raise RuntimeError("HyperFrames render failed: " + out[-600:])
        job.update(progress=b)
        return {"path": str(out_path), "duration": round(dur, 2), "engine": "hyperframes",
                "sounds": len(sounds)}
    finally:
        if os.environ.get("CLIPSWORLD_KEEP_HF") != "1":
            shutil.rmtree(work, ignore_errors=True)


def _lint_errors(out: str) -> list:
    try:
        start = out.find("{")
        data = json.loads(out[start:]) if start >= 0 else {}
    except Exception:
        return []
    found = []

    def walk(x):
        if isinstance(x, dict):
            sev = str(x.get("severity", x.get("level", ""))).lower()
            if sev == "error" and (x.get("message") or x.get("code")):
                msg = f"{x.get('code') or x.get('rule') or ''}: {x.get('message', '')}".strip(": ")
                if x.get("fixHint"):
                    msg += f" (fix: {x['fixHint']})"
                found.append(msg)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(data)
    return found
