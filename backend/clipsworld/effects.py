"""Clip effects: zoom/shake punch-ins, freeze frames, slow-mo replays, text pops and sound effects.

All effect times are stored relative to the clip start, on the *source* timeline. Freeze frames
and replays insert extra time, so this module builds the output timeline (segments) and maps
source times to output times for captions, zooms, texts and sounds.
"""
import uuid
from pathlib import Path

import numpy as np

from .paths import data_dir, resources_dir

TYPES = ("zoom", "shake", "freeze", "replay", "text", "sfx")

DEFAULTS = {
    "zoom": {"dur": 0.9, "scale": 1.3, "ease": "snap", "fx": 0.5, "fy": 0.45, "sfx": "whoosh"},
    "shake": {"dur": 0.6, "strength": 1.0, "sfx": "boom"},
    "freeze": {"dur": 1.2, "text": "WAIT WHAT?!", "zoom": 1.12, "sfx": "record_scratch"},
    "replay": {"dur": 2.5, "speed": 0.6, "label": "REPLAY", "sfx": "rewind"},
    "text": {"dur": 1.4, "text": "BRUH", "position": "middle", "color": "#FFE600", "sfx": "pop"},
    "sfx": {"dur": 0.0, "sfx": "boom", "volume": 0.85},
}

TEXT_IDEAS = {
    "shock": "WAIT WHAT?!", "laugh": "LMAO", "loud": "BRUH", "hype": "LET'S GOOO",
    "panic": "BHAAGOOO!!", "banter": "BHAI KYA?!",
}


def new_effect(kind: str, t: float, **params) -> dict:
    e = {"id": uuid.uuid4().hex[:6], "type": kind, "t": round(float(t), 2), "volume": 0.85}
    e.update(DEFAULTS[kind])
    e.update({k: v for k, v in params.items() if v is not None})
    return e


# --------------------------------------------------------------- sound library

def sfx_dirs():
    user = data_dir() / "sfx"
    user.mkdir(parents=True, exist_ok=True)
    return [("builtin", resources_dir() / "sfx"), ("user", user)]


def sfx_list() -> list:
    out = []
    for src, d in sfx_dirs():
        if not d.exists():
            continue
        for f in sorted(d.iterdir()):
            if f.suffix.lower() in (".wav", ".mp3", ".ogg", ".m4a", ".flac"):
                out.append({"id": f.stem if src == "builtin" else f"user:{f.name}",
                            "name": f.stem.replace("_", " ").title(), "source": src})
    return out


def sfx_path(sfx_id: str) -> Path | None:
    if not sfx_id:
        return None
    if sfx_id.startswith("user:"):
        p = data_dir() / "sfx" / Path(sfx_id[5:]).name
        return p if p.exists() else None
    for ext in (".wav", ".mp3", ".ogg"):
        p = resources_dir() / "sfx" / (Path(sfx_id).name + ext)
        if p.exists():
            return p
    return None


# --------------------------------------------------------------- timeline

def build_timeline(length: float, effects: list) -> list:
    """Segments in output order: {kind, a, b, speed, out_a, out_b, effect}."""
    inserts = []
    for e in effects:
        if e["type"] == "freeze":
            t = min(max(0.05, e["t"]), length - 0.05)
            inserts.append((t, 0, {"kind": "freeze", "a": t, "b": t, "speed": 1.0,
                                   "dur": max(0.3, float(e.get("dur", 1.2))), "effect": e}))
        elif e["type"] == "replay":
            end = min(max(0.3, e["t"]), length)
            start = max(0.0, end - max(0.5, float(e.get("dur", 2.5))))
            speed = min(1.0, max(0.5, float(e.get("speed", 0.6))))
            inserts.append((end, 1, {"kind": "replay", "a": start, "b": end, "speed": speed,
                                     "dur": (end - start) / speed, "effect": e}))
    inserts.sort(key=lambda x: (x[0], x[1]))
    segs, cur = [], 0.0
    for pos, _, seg in inserts:
        if pos > cur + 0.01:
            segs.append({"kind": "normal", "a": cur, "b": pos, "speed": 1.0, "dur": pos - cur})
            cur = pos
        segs.append(seg)
    if length > cur + 0.01:
        segs.append({"kind": "normal", "a": cur, "b": length, "speed": 1.0, "dur": length - cur})
    o = 0.0
    for s in segs:
        s["out_a"], s["out_b"] = o, o + s["dur"]
        o += s["dur"]
    return segs


def total_duration(segs) -> float:
    return segs[-1]["out_b"] if segs else 0.0


def map_time(segs, t: float) -> float:
    """Source-relative time → output time (first normal occurrence)."""
    for s in segs:
        if s["kind"] == "normal" and s["a"] - 1e-6 <= t <= s["b"] + 1e-6:
            return s["out_a"] + (t - s["a"])
    # inside nothing (shouldn't happen): clamp
    return min(t, total_duration(segs))


def map_cues(segs, cues: list, clip_start: float, replay_captions: bool = True) -> list:
    """Caption cues (source absolute times) → output-relative times (incl. repeats in replays)."""
    out = []
    normals = [s for s in segs if s["kind"] == "normal"]

    def seg_of(t):
        for i, s in enumerate(normals):
            if s["a"] - 1e-6 <= t <= s["b"] + 1e-6:
                return i
        return -1

    for q in cues:
        a, b = q["start"] - clip_start, q["end"] - clip_start
        words = q.get("words") or []
        # split the cue where a freeze/replay was inserted, so captions never overlap the insert
        groups = {}
        for w in words:
            groups.setdefault(seg_of(max(a, min(b, (w["start"] + w["end"]) / 2 - clip_start))), []).append(w)
        if not groups:
            groups = {seg_of(a): []}
        keys = sorted(k for k in groups if k >= 0)
        for n_g, gi in enumerate(keys):
            ws = groups[gi]
            s = normals[gi]
            ga = a if n_g == 0 or not ws else ws[0]["start"] - clip_start
            gb = b if n_g == len(keys) - 1 or not ws else ws[-1]["end"] - clip_start
            ga, gb = min(s["b"], max(s["a"], ga)), min(s["b"], max(s["a"], gb))
            m = dict(q)
            if ws and len(groups) > 1:
                m["text"] = " ".join(w["word"] for w in ws)
            m["start"], m["end"] = map_time(segs, ga), map_time(segs, gb)
            m["words"] = [dict(w, start=map_time(segs, min(s["b"], max(s["a"], w["start"] - clip_start))),
                               end=map_time(segs, min(s["b"], max(s["a"], w["end"] - clip_start)))) for w in ws]
            if m["end"] > m["start"] + 0.02:
                out.append(m)
        if not replay_captions:
            continue
        for s in segs:
            if s["kind"] != "replay" or b <= s["a"] or a >= s["b"]:
                continue
            f = lambda x, s=s: s["out_a"] + (min(max(x, s["a"]), s["b"]) - s["a"]) / s["speed"]  # noqa: E731
            inside = [w for w in words if s["a"] - 0.05 <= (w["start"] + w["end"]) / 2 - clip_start <= s["b"] + 0.05]
            if words and not inside:
                continue
            r = dict(q)
            if inside and len(inside) != len(words):
                r["text"] = " ".join(w["word"] for w in inside)
            ra = inside[0]["start"] - clip_start if inside and inside[0] is not words[0] else a
            rb = inside[-1]["end"] - clip_start if inside and inside[-1] is not words[-1] else b
            r["start"], r["end"] = f(ra), f(rb)
            r["words"] = [dict(w, start=f(w["start"] - clip_start), end=f(w["end"] - clip_start)) for w in inside]
            if r["end"] > r["start"] + 0.02:
                out.append(r)
    out.sort(key=lambda x: x["start"])
    return out


# --------------------------------------------------------------- ffmpeg pieces

def segments_filter(segs, fps: float, src_v="0:v", src_a="0:a", has_audio=True) -> tuple:
    """Return (filter text, video label, audio label) that cuts/loops/slows the clip."""
    n = len(segs)
    parts = [f"[{src_v}]split={n}" + "".join(f"[sv{i}]" for i in range(n)) if n > 1 else f"[{src_v}]null[sv0]"]
    if has_audio:
        parts.append(f"[{src_a}]asplit={n}" + "".join(f"[sa{i}]" for i in range(n)) if n > 1 else f"[{src_a}]anull[sa0]")
    fmt = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
    for i, s in enumerate(segs):
        a, b = s["a"], s["b"]
        if s["kind"] == "freeze":
            parts.append(f"[sv{i}]trim=start={a:.3f}:end={a + 0.5:.3f},setpts=PTS-STARTPTS,"
                         f"loop=loop=-1:size=1:start=0,setpts=N/({fps:.4f}*TB),trim=duration={s['dur']:.3f}[v{i}]")
            if has_audio:
                parts.append(f"[sa{i}]atrim=start=0:end=0.01,anullsink")
            parts.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={s['dur']:.3f},{fmt}[a{i}]")
        else:
            sp = s["speed"]
            vpts = "setpts=PTS-STARTPTS" + (f",setpts=PTS/{sp:.4f}" if sp != 1 else "")
            parts.append(f"[sv{i}]trim=start={a:.3f}:end={b:.3f},{vpts}[v{i}]")
            if has_audio:
                apts = "asetpts=PTS-STARTPTS" + (f",atempo={sp:.4f}" if sp != 1 else "")
                parts.append(f"[sa{i}]atrim=start={a:.3f}:end={b:.3f},{apts},{fmt}[a{i}]")
            else:
                parts.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={s['dur']:.3f},{fmt}[a{i}]")
    if n > 1:
        parts.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vcat][acat]")
    else:
        parts.append("[v0]null[vcat]")
        parts.append("[a0]anull[acat]")
    return ";".join(parts), "vcat", "acat"


def zoom_filter(segs, effects, out_w, out_h, fps) -> str | None:
    """Per-frame zoom (punch-in / smooth) and camera shake, on the output timeline."""
    zs, xs, ys = [], [], []
    for e in effects:
        t0 = map_time(segs, e["t"])
        if e["type"] == "zoom":
            d = max(0.1, float(e.get("dur", 0.9)))
            sc = min(2.5, max(1.02, float(e.get("scale", 1.3)))) - 1
            ramp = 0.18 if e.get("ease") == "smooth" else 0.04
            env = f"min(1,max(0,(t-{t0:.3f})/{ramp}))*min(1,max(0,({t0 + d:.3f}-t)/{ramp}))"
            zs.append(f"{sc:.3f}*{env}")
        elif e["type"] == "shake":
            d = max(0.1, float(e.get("dur", 0.6)))
            k = float(e.get("strength", 1.0))
            env = f"between(t,{t0:.3f},{t0 + d:.3f})*max(0,1-(t-{t0:.3f})/{d:.3f})"
            zs.append(f"0.08*{env}")
            xs.append(f"{18 * k:.1f}*sin(t*71)*{env}")
            ys.append(f"{14 * k:.1f}*sin(t*53+1.3)*{env}")
        elif e["type"] == "freeze" and float(e.get("zoom", 1.0)) > 1.0:
            s = next((x for x in segs if x.get("effect") is e), None)
            if s:
                z = float(e["zoom"]) - 1
                env = f"between(t,{s['out_a']:.3f},{s['out_b']:.3f})*min(1,(t-{s['out_a']:.3f})/0.25)"
                zs.append(f"{z:.3f}*{env}")
    if not zs:
        return None
    Z = "(1+" + "+".join(zs) + ")"
    fx = next((float(e.get("fx", 0.5)) for e in effects if e["type"] == "zoom"), 0.5)
    fy = next((float(e.get("fy", 0.45)) for e in effects if e["type"] == "zoom"), 0.45)
    X = f"(iw-{out_w})*{fx:.3f}" + ("+" + "+".join(xs) if xs else "")
    Y = f"(ih-{out_h})*{fy:.3f}" + ("+" + "+".join(ys) if ys else "")
    return (f"scale=w='trunc({out_w}*{Z}/2)*2':h='trunc({out_h}*{Z}/2)*2':eval=frame:flags=bicubic,"
            f"crop={out_w}:{out_h}:x='max(0,min(iw-{out_w},{X}))':y='max(0,min(ih-{out_h},{Y}))'")


def text_events(segs, effects, avoid: str = "") -> list:
    """Extra on-screen texts for the ASS file (output timeline). `avoid` = caption position."""
    ev = []

    def place(pos):
        return ("top" if avoid != "top" else "middle") if pos == avoid else pos
    for e in effects:
        if e["type"] == "text" and e.get("text", "").strip():
            t0 = map_time(segs, e["t"])
            ev.append({"start": t0, "end": t0 + float(e.get("dur", 1.4)), "text": e["text"].strip(),
                       "kind": "pop", "position": place(e.get("position", "middle")), "color": e.get("color", "#FFE600")})
        elif e["type"] == "freeze":
            s = next((x for x in segs if x.get("effect") is e), None)
            if s and e.get("text", "").strip():
                ev.append({"start": s["out_a"], "end": s["out_b"], "text": e["text"].strip(), "kind": "pop",
                           "position": place("middle"), "color": e.get("color", "#FFFFFF")})
        elif e["type"] == "replay":
            s = next((x for x in segs if x.get("effect") is e), None)
            if s and e.get("label", "").strip():
                ev.append({"start": s["out_a"], "end": s["out_b"], "text": e["label"].strip(), "kind": "badge"})
    return ev


def sound_events(segs, effects, master: float = 1.0) -> list:
    out = []
    for e in effects:
        p = sfx_path(e.get("sfx", ""))
        if not p:
            continue
        if e["type"] in ("freeze", "replay"):
            s = next((x for x in segs if x.get("effect") is e), None)
            t0 = s["out_a"] if s else map_time(segs, e["t"])
        else:
            t0 = map_time(segs, e["t"])
        vol = float(e.get("volume", 0.85) if e.get("volume") is not None else 0.85) * max(0.0, float(master))
        if vol > 0.001:
            out.append({"path": str(p), "t": max(0.0, t0), "volume": vol})
    return out


# --------------------------------------------------------------- auto edit (offline)

def auto_edit_local(clip: dict, loud: list, hop: float, segments: list, max_len: float) -> list:
    """Add punch-in zooms on the loudest reactions, a freeze or replay on the best moment."""
    from .highlights import _text_hits, excitement
    s0, s1 = clip["start"], clip["end"]
    L = s1 - s0
    z = excitement(loud)
    i0, i1 = int(s0 / hop), int(s1 / hop)
    win = z[i0:i1] if len(z) else np.zeros(0)
    effects = []
    peaks = []
    if len(win) >= 3:
        sm = np.convolve(win, np.ones(3) / 3, mode="same")
        order = np.argsort(-sm)
        for idx in order:
            t = idx * hop
            if sm[idx] < 1.0 or len(peaks) >= 3:
                break
            if all(abs(t - p) > 3.0 for p, _ in peaks) and 0.6 < t < L - 0.4:
                peaks.append((t, float(sm[idx])))
    for k, (t, strength) in enumerate(sorted(peaks, key=lambda x: -x[1])):
        if k == 0:
            effects.append(new_effect("zoom", t - 0.15, scale=1.35, dur=1.0, sfx="boom"))
            effects.append(new_effect("shake", t - 0.05, dur=0.5, sfx=""))
        else:
            effects.append(new_effect("zoom", t - 0.1, scale=1.22, dur=0.8, ease="smooth", sfx="whoosh"))
    # reaction words → text pop
    best_kind, best_t = None, None
    for s in segments:
        if s["end"] < s0 or s["start"] > s1:
            continue
        sc, kinds, _ = _text_hits(s["text"])
        if sc >= 2 and kinds:
            k = sorted(kinds, key=lambda x: ["shock", "laugh", "panic", "hype", "banter"].index(x)
                       if x in ["shock", "laugh", "panic", "hype", "banter"] else 9)[0]
            best_kind, best_t = k, (s["start"] + s["end"]) / 2 - s0
            break
    if best_kind:
        while any(abs(best_t - e["t"]) < 0.7 for e in effects):
            best_t += 0.8
    if best_kind and 0.3 < best_t < L - 0.5:
        effects.append(new_effect("text", best_t, text=TEXT_IDEAS.get(best_kind, "BRUH"), sfx="pop"))
    # replay the biggest moment if there is room
    if peaks:
        t, _ = max(peaks, key=lambda x: x[1])
        end = min(L, t + 0.8)
        if end - 2.2 > 0 and L + 2.2 / 0.6 <= max_len + 6:
            effects.append(new_effect("replay", end, dur=2.2, speed=0.6))
    effects.sort(key=lambda e: e["t"])
    return effects
