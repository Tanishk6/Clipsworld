"""Claude API: choose the best clips and translate captions."""
import json
import math
import re

from . import highlights

SYSTEM_CLIPS = """You are the clip editor for an Indian YouTube Shorts channel. You find the moments in a \
video or stream that will make viewers stop scrolling: funny lines, big reactions, shocking twists, \
clutch plays, rage, wholesome or story moments. The speech can be Hindi, Hinglish or English.

Rules for every clip:
- It must make sense on its own: start where the setup starts (a natural sentence start), end right \
after the payoff or reaction. Never cut in the middle of a sentence.
- Length between {min_len} and {max_len} seconds.
- Clips must not overlap.
- Prefer moments with strong emotion, a clear punchline, or a "wait what" twist. Skip boring talk, \
ads, sponsor reads, intros and outros.
- title: a short catchy Shorts title (max 60 characters) in the same language style the speaker uses \
(Hinglish in Roman letters if they speak Hindi/Hinglish). No clickbait lies.
- hook: the first caption line viewers should read (max 8 words).
- reason: one short line on why this clip works.
- category: one of funny, shock, hype, rage, skill, wholesome, story, panic.
- score: 0-100, how likely it is to perform well.

Reply with JSON only, no other text:
{{"clips":[{{"start":12.3,"end":41.0,"title":"...","hook":"...","reason":"...","category":"funny","score":87}}]}}"""

LANG_NAMES = {
    "en": "English",
    "hi": "Hindi written in Devanagari script",
    "hinglish": "Hinglish: Hindi written in Roman (English) letters, the way Indian YouTubers type "
                "comments (for example “bhai ye kya ho gaya”). Keep English words in English.",
}


class AIError(RuntimeError):
    pass


def _client(key: str):
    if not key:
        raise AIError("Add your Claude API key in Settings to use AI features.")
    import anthropic
    return anthropic.Anthropic(api_key=key, max_retries=3, timeout=180)


def _ask(key, model, system, user, max_tokens=4000) -> str:
    import anthropic
    try:
        msg = _client(key).messages.create(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.AuthenticationError:
        raise AIError("Claude rejected the API key. Check it in Settings.")
    except anthropic.PermissionDeniedError as e:
        raise AIError(f"Claude API permission problem: {e.message}")
    except anthropic.NotFoundError:
        raise AIError(f"Model '{model}' was not found. Pick another model in Settings.")
    except anthropic.RateLimitError:
        raise AIError("Claude rate limit reached. Wait a minute and try again.")
    except anthropic.BadRequestError as e:
        m = str(e.message)
        if "credit" in m.lower():
            raise AIError("Your Claude API credits are used up for this month (or not claimed yet).")
        raise AIError(f"Claude API error: {m}")
    except anthropic.APIConnectionError:
        raise AIError("Can't reach Claude. Check your internet connection.")
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def _parse_json(text: str):
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0:
        raise AIError("Claude's answer was not in the expected format. Try again.")
    return json.loads(text[start:end + 1])


def test_key(key: str, model: str) -> dict:
    out = _ask(key, model, "Reply with the single word OK.", "Say OK.", max_tokens=5)
    return {"ok": True, "reply": out.strip()[:20], "model": model}


def _fmt(t: float) -> str:
    return f"{t:.1f}"


def _chunks(segments, max_chars=90_000):
    chunk, size = [], 0
    for s in segments:
        line = f"[{_fmt(s['start'])}-{_fmt(s['end'])}] {s['text']}"
        if size + len(line) > max_chars and chunk:
            yield chunk
            chunk, size = [], 0
        chunk.append(line)
        size += len(line) + 1
    if chunk:
        yield chunk


def find_clips(job, segments, loud, duration, settings) -> list:
    key, model = settings.get("claude_api_key", ""), settings.get("claude_model", "claude-haiku-5-5")
    min_len = float(settings.get("min_clip_sec", 15))
    max_len = float(settings.get("max_clip_sec", 60))
    n = int(settings.get("max_clips", 12))
    moments = highlights.find_moments(segments, loud, limit=80)
    chunks = list(_chunks(segments))
    want = max(3, math.ceil(n * 1.5 / max(1, len(chunks))))
    system = SYSTEM_CLIPS.format(min_len=int(min_len), max_len=int(max_len))
    found = []
    for i, lines in enumerate(chunks):
        job.update(progress=0.1 + 0.8 * i / len(chunks),
                   stage=f"Claude is watching the transcript ({i + 1}/{len(chunks)})…")
        a = float(lines[0][1:].split("-")[0])
        b = float(lines[-1][1:].split("]")[0].split("-")[1])
        hints = [m for m in moments if a <= m["t"] <= b][:25]
        hint_txt = "\n".join(
            f"- {m['t']:.1f}s: {', '.join(sorted(m['kinds']))}" + (f" ({', '.join(m['words'][:3])})" if m['words'] else "")
            for m in hints) or "- none"
        user = (f"Video length: {duration:.0f} seconds.\n"
                f"Audio analysis found these loud/reaction moments (seconds):\n{hint_txt}\n\n"
                f"Transcript with [start-end] seconds:\n" + "\n".join(lines) +
                f"\n\nFind the best {want} clips in this part (fewer if the content is weak).")
        data = _parse_json(_ask(key, model, system, user, max_tokens=4000))
        for c in data.get("clips", []):
            try:
                s, e = float(c["start"]), float(c["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (0 <= s < e <= duration + 1):
                continue
            s = highlights._snap_start(segments, s + 0.05)
            e = highlights._snap_end(segments, e - 0.05, duration)
            s, e = highlights.build_clip(segments, duration, s, e, min_len, max_len)
            found.append({
                "start": s, "end": e,
                "title": str(c.get("title", "")).strip()[:80] or "Highlight",
                "hook": str(c.get("hook", "")).strip()[:80],
                "reason": str(c.get("reason", "")).strip()[:160],
                "category": str(c.get("category", "funny")).strip().lower(),
                "score": max(0, min(100, int(float(c.get("score", 60))))),
                "source": "claude",
            })
    found.sort(key=lambda c: -c["score"])
    picked = []
    for c in found:
        if all(c["end"] <= p["start"] or c["start"] >= p["end"] for p in picked):
            picked.append(c)
        if len(picked) >= n:
            break
    return picked


def translate_lines(job, lines: list, target: str, settings: dict) -> list:
    key, model = settings.get("claude_api_key", ""), settings.get("claude_model", "claude-haiku-5-5")
    if target not in LANG_NAMES:
        raise AIError(f"Unknown language: {target}")
    out = []
    batch = 60
    for i in range(0, len(lines), batch):
        part = lines[i:i + batch]
        if job:
            job.update(progress=i / max(1, len(lines)), stage=f"Translating captions to {target}…")
        system = ("You translate short video captions. Keep the meaning, slang, jokes and energy. "
                  "Keep each line short and natural for on-screen captions. Do not add or merge lines. "
                  'Reply with JSON only: {"lines": ["...", "..."]} with exactly the same number of lines.')
        user = (f"Translate every line into {LANG_NAMES[target]}.\n" +
                json.dumps({"lines": part}, ensure_ascii=False))
        data = _parse_json(_ask(key, model, system, user, max_tokens=4000))
        got = [str(x) for x in data.get("lines", [])]
        if len(got) != len(part):
            got = (got + part)[:len(part)]
        out.extend(got)
    return out
