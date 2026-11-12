"""Find funny / interesting moments without AI: loudness spikes + reaction words.

This is the free, offline finder. When a Claude API key is set, ai.find_clips() uses these
moments as hints and lets Claude choose the final clips.
"""
import re

import numpy as np

HOP = 0.25  # seconds per loudness sample

KEYWORDS = {
    "laugh": (3.0, ["haha", "hehe", "lol", "lmao", "rofl", "😂", "🤣", "[laughter]", "(laughs)",
                    "*laughs*", "हाहा", "हा हा", "हाहाहा"]),
    "shock": (2.0, ["oh my god", "omg", "no way", "what the", "wtf", "holy", "oh no", "bruh",
                    "are you serious", "kya baat", "oh teri", "o teri", "bhagwan", "hey bhagwan",
                    "ओ तेरी", "हे भगवान", "भगवान", "क्या बात", "ये क्या", "यह क्या"]),
    "hype": (1.6, ["let's go", "lets go", "insane", "crazy", "clutch", "yes yes", "gg",
                   "jabardast", "zabardast", "kamaal", "gazab", "ghazab", "mast", "op bhai",
                   "जबरदस्त", "कमाल", "गज़ब", "गजब", "मस्त", "मज़ा", "मजा"]),
    "panic": (1.8, ["run", "help", "bachao", "bhago", "mar gaya", "mar gya", "mai mar", "nahi nahi",
                    "no no no", "बचाओ", "भागो", "मर गया", "नहीं नहीं", "मैं मर"]),
    "banter": (0.8, ["bro", "bhai", "yaar", "pagal", "abe", "oye", "arey", "are yaar", "chup",
                     "भाई", "यार", "पागल", "अबे", "ओए", "अरे", "चुप"]),
}

LABELS = {"laugh": "Laughter", "shock": "Shock / surprise", "hype": "Hype moment",
          "panic": "Panic moment", "banter": "Funny banter", "loud": "Big reaction"}


def _text_hits(text: str):
    t = " " + text.lower() + " "
    score, kinds, found = 0.0, set(), []
    for kind, (w, words) in KEYWORDS.items():
        for kw in words:
            if re.search(r"(?<![\wऀ-ॿ])" + re.escape(kw) + r"(?![\wऀ-ॿ])", t):
                score += w
                kinds.add(kind)
                found.append(kw)
    score += min(2.0, text.count("!") * 0.5) + min(1.0, text.count("?") * 0.25)
    return score, kinds, found


def excitement(loud: list) -> np.ndarray:
    """Loudness relative to the local average (so quiet and loud mics both work)."""
    if not loud:
        return np.zeros(0)
    x = np.maximum(np.array(loud, dtype=np.float32), -70.0)
    voiced = x > -45.0
    if voiced.sum() < 8:
        return np.zeros(len(x))
    # average loudness of the *voiced* parts in a 60 s window around each point
    win = max(1, min(int(60 / HOP), len(x)))
    k = np.ones(win)
    xs = np.where(voiced, x, 0.0)
    num = np.convolve(xs, k, mode="same")
    den = np.convolve(voiced.astype(np.float32), k, mode="same")
    base = np.where(den > 0, num / np.maximum(den, 1), np.median(x[voiced]))
    dev = np.where(voiced, x - base, 0.0)
    d = dev[voiced]
    spread = max(1.5, float(np.median(np.abs(d - np.median(d)))) * 1.4826)
    return dev / spread


def find_moments(segments: list, loud: list, limit: int = 60) -> list:
    z = excitement(loud)
    moments = []
    # 1) loudness peaks (screams, laughs, shouting)
    if len(z) >= 4:
        smooth = np.convolve(z, np.ones(4) / 4, mode="same")
        i = 0
        while i < len(smooth):
            if smooth[i] > 1.6:
                j = i
                while j < len(smooth) and smooth[j] > 0.9:
                    j += 1
                peak = i + int(np.argmax(smooth[i:j]))
                moments.append({"t": peak * HOP, "score": float(min(6.0, smooth[peak])) * 0.8,
                                "kinds": {"loud"}, "words": []})
                i = j + int(4 / HOP)  # no new peak in the next 4 s
            else:
                i += 1
    # 2) reaction words
    for s in segments:
        sc, kinds, found = _text_hits(s["text"])
        dur = max(0.3, s["end"] - s["start"])
        rate = len(s["text"].split()) / dur
        if rate > 3.8:
            sc += 0.6
        if sc >= 1.5:
            moments.append({"t": (s["start"] + s["end"]) / 2, "score": sc, "kinds": kinds, "words": found})
    # merge moments that are close together
    moments.sort(key=lambda m: m["t"])
    merged = []
    for m in moments:
        if merged and m["t"] - merged[-1]["t"] < 6:
            last = merged[-1]
            last["score"] += m["score"] * 0.7
            last["kinds"] |= m["kinds"]
            last["words"] += m["words"]
            if m["score"] > last.get("_best", 0):
                last["t"], last["_best"] = m["t"], m["score"]
        else:
            m["_best"] = m["score"]
            merged.append(m)
    merged.sort(key=lambda m: -m["score"])
    return merged[:limit]


def _snap_start(segments, t, near=1.5):
    """Start of the sentence nearest to t (within `near` s), else the sentence that contains t."""
    if not segments:
        return max(0.0, t)
    close = min(segments, key=lambda s: abs(s["start"] - t))
    if abs(close["start"] - t) <= near:
        return close["start"]
    best = 0.0
    for s in segments:
        if s["start"] <= t:
            best = s["start"]
        else:
            break
    return best


def _snap_end(segments, t, duration, near=1.5):
    if not segments:
        return min(duration, t)
    close = min(segments, key=lambda s: abs(s["end"] - t))
    if abs(close["end"] - t) <= near:
        return close["end"]
    for s in segments:
        if s["end"] >= t:
            return s["end"]
    return duration


def text_between(segments, a, b):
    return " ".join(s["text"] for s in segments if s["end"] > a and s["start"] < b).strip()


def build_clip(segments, duration, start, end, min_len, max_len):
    start = max(0.0, start)
    end = min(duration, end)
    if end - start < min_len:
        end = min(duration, start + min_len)
        if end - start < min_len:
            start = max(0.0, end - min_len)
    if end - start > max_len:
        # too long: start at the first sentence that fits, so the clip never begins mid-sentence
        starts = [s["start"] for s in segments if end - max_len <= s["start"] <= end - min_len]
        start = starts[0] if starts else end - max_len
    return round(start, 2), round(end, 2)


def local_clips(segments: list, loud: list, duration: float, settings: dict) -> list:
    min_len = float(settings.get("min_clip_sec", 15))
    max_len = float(settings.get("max_clip_sec", 60))
    n = int(settings.get("max_clips", 12))
    moments = find_moments(segments, loud)
    clips = []
    for m in moments:
        t = m["t"]
        s = _snap_start(segments, t - 18)
        e = _snap_end(segments, t + 5, duration)
        s, e = build_clip(segments, duration, s, e, min_len, max_len)
        if any(not (e <= c["start"] or s >= c["end"]) for c in clips):
            continue
        kinds = sorted(m["kinds"], key=lambda k: list(LABELS).index(k))
        words = list(dict.fromkeys(m["words"]))[:3]
        reason = " + ".join(LABELS[k] for k in kinds[:2])
        if words:
            reason += f" (“{words[0]}”)"
        text = text_between(segments, s, e)
        clips.append({
            "start": s, "end": e,
            "title": _title_from(text_between(segments, t - 3, t + 3) or text),
            "reason": reason, "score": round(min(99, 40 + m["score"] * 8)),
            "category": kinds[0] if kinds else "loud", "source": "local",
        })
        if len(clips) >= n:
            break
    clips.sort(key=lambda c: -c["score"])
    return clips


def _title_from(text: str) -> str:
    words = text.split()
    t = " ".join(words[:8])
    return (t + "…") if len(words) > 8 else (t or "Highlight")
