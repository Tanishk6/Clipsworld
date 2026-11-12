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
    "hinglish": "Hinglish: write the SAME words in Roman (English) letters, the way Indian YouTubers type "
                "(for example “भाई ये क्या हो गया” → “bhai ye kya ho gaya”). Transliterate Hindi words, do not "
                "translate their meaning; keep English words as they are. If a line is already English, keep it.",
}


class AIError(RuntimeError):
    pass


def _client(key: str):
    if not key:
        raise AIError("Add your Claude API key in Settings to use AI features.")
    import anthropic
    return anthropic.Anthropic(api_key=key, max_retries=3, timeout=180)


def _call(key, model, **kw):
    import anthropic
    try:
        return _client(key).messages.create(model=model, **kw)
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


def _ask(key, model, system, user, max_tokens=4000) -> str:
    msg = _call(key, model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def _log(name: str, text: str):
    try:
        from .paths import data_dir
        d = data_dir() / "logs"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"claude_{name}.txt").write_text(text[-20000:], encoding="utf-8")
    except Exception:
        pass


def _as_list(v) -> list:
    """Claude sometimes returns a list as a JSON string ('["a","b"]') or one text block. Make it a real list."""
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        t = v.strip()
        if t.startswith("["):
            try:
                x = json.loads(t)
                if isinstance(x, list):
                    return x
            except json.JSONDecodeError:
                pass
        return [ln.strip() for ln in t.splitlines() if ln.strip()]
    return []


def _ask_json(key, model, system, user, schema: dict, name: str, max_tokens=4000) -> dict:
    """Ask Claude for structured data. Uses a forced tool call so the answer is always valid JSON."""
    last = None
    for attempt in range(2):
        msg = _call(key, model, max_tokens=max_tokens, system=system,
                    messages=[{"role": "user", "content": user}],
                    tools=[{"name": "answer", "description": "Return the result.", "input_schema": schema}],
                    tool_choice={"type": "tool", "name": "answer"})
        for b in msg.content:
            if getattr(b, "type", "") == "tool_use" and isinstance(b.input, dict):
                _log(name, json.dumps(b.input, ensure_ascii=False))
                return b.input
        text = "".join(getattr(b, "text", "") for b in msg.content)
        _log(name, f"stop={getattr(msg, 'stop_reason', '')}\n{text}")
        try:
            return _parse_json(text)
        except AIError as e:
            last = e
    raise last or AIError("Claude's answer was not in the expected format. Try again.")


_STR = {"type": "string"}
_NUM = {"type": "number"}
SCHEMA_CLIPS = {"type": "object", "required": ["clips"], "properties": {"clips": {"type": "array", "items": {
    "type": "object", "required": ["start", "end", "title"],
    "properties": {"start": _NUM, "end": _NUM, "title": _STR, "hook": _STR, "reason": _STR, "category": _STR,
                   "score": _NUM}}}}}
SCHEMA_LINES = {"type": "object", "required": ["lines"], "properties": {"lines": {
    "type": "array", "items": _STR,
    "description": "A JSON array with exactly one translated string per input line, in the same order."}}}
SCHEMA_EDIT = {"type": "object", "required": ["effects"], "properties": {"effects": {"type": "array", "items": {
    "type": "object", "required": ["type", "t"],
    "properties": {"type": {"type": "string", "enum": ["zoom", "shake", "freeze", "replay", "text", "sfx"]},
                   "t": _NUM, "dur": _NUM, "scale": _NUM, "ease": _STR, "speed": _NUM, "text": _STR, "sfx": _STR}}}}}
SCHEMA_META = {"type": "object", "required": ["title", "description", "hashtags"],
               "properties": {"title": _STR, "description": _STR, "hashtags": {"type": "array", "items": _STR}}}


def _parse_json(text: str):
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    if start < 0:
        raise AIError("Claude's answer was not in the expected format. Try again.")
    try:
        # read only the first JSON object, ignore anything Claude wrote after it
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
        return obj
    except json.JSONDecodeError:
        end = text.rfind("}")
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            raise AIError("Claude's answer was not in the expected format. Try again.")


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
        data = _ask_json(key, model, system, user, SCHEMA_CLIPS, "clips", max_tokens=4000)
        for c in _as_list(data.get("clips")):
            if not isinstance(c, dict):
                continue
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


def translate_lines(job, lines: list, target: str, settings: dict, context: str = "") -> list:
    key, model = settings.get("claude_api_key", ""), settings.get("claude_model", "claude-haiku-5-5")
    if target not in LANG_NAMES:
        raise AIError(f"Unknown language: {target}")
    out = []
    batch = 60
    for i in range(0, len(lines), batch):
        part = lines[i:i + batch]
        if job:
            job.update(progress=i / max(1, len(lines)), stage=f"Translating captions to {target}…")
        system = ("You convert short on-screen video captions for an Indian YouTube Shorts channel. "
                  "The lines are consecutive pieces of the same speech and come from automatic speech "
                  "recognition, so they can contain misheard words: fix words that are clearly misheard "
                  "using the context, but never invent new content. Keep slang, jokes and energy. "
                  "Every output line must stay short and match its input line (same order, same count). "
                  "Never merge, split, skip or add lines. Return the result with the answer tool: "
                  '{"lines": ["...", "..."]}.')
        if target == "hinglish":
            rule = ("Write every line in Hinglish: Hindi words in simple Roman letters the way Indian "
                    "YouTubers type (e.g. 'bhai ye kya ho gaya', 'mujhe nahi pata', 'chalo shuru karte hain'). "
                    "Do NOT translate Hindi into English — keep the Hindi words, just write them in Roman letters. "
                    "Keep English words as English. Use common spellings (hai, nahi, kya, bhai, yaar, accha).")
        else:
            rule = f"Translate every line into {LANG_NAMES[target]}."
        ctx = f"What the video is about: {context}\n" if context else ""
        user = (f"{rule}\n{ctx}Number of lines: {len(part)}\n" +
                json.dumps({"lines": part}, ensure_ascii=False))
        got = []
        for attempt in range(3):
            data = _ask_json(key, model, system, user, SCHEMA_LINES, "translate", max_tokens=6000)
            got = [str(x).strip() for x in _as_list(data.get("lines"))]
            if len(got) == len(part):
                break
        if len(got) != len(part):
            raise AIError("Claude's translation didn't match the caption lines. Try again.")
        out.extend(got)
    return out


SYSTEM_EDIT = """You are a top YouTube Shorts editor. You add effects to a short clip to make it punchy \
and clearly edited (not a plain re-upload). Available effects (t = seconds from the clip start):
- zoom: quick punch-in on a reaction or punchline. fields: t, dur (0.4-1.5), scale (1.15-1.5), ease ("snap" or "smooth"), sfx
- shake: camera shake on a big hit/scream. fields: t, dur (0.3-0.8), sfx
- freeze: freeze frame with big text right before/at a "wait what" moment. fields: t, dur (0.8-1.6), text (max 4 words), sfx
- replay: slow-mo replay of the best moment, inserted after it. fields: t (end of the moment), dur (1.5-3 seconds replayed), speed (0.5-0.8), sfx
- text: big meme text pop. fields: t, dur (0.8-2), text (max 3 words, Hinglish or English like "BHAI KYA", "NO WAY", "LMAO"), sfx
- sfx: sound only. fields: t, sfx
Sound effects you can use: {sfx}
Rules: 3 to 7 effects total, never more than one effect in the same 0.7 seconds, at most one freeze and
one replay, keep it tasteful and on the beat of the speech. No emojis in text.
Reply with JSON only: {{"effects":[{{"type":"zoom","t":3.2,"dur":0.8,"scale":1.3,"ease":"snap","sfx":"whoosh"}}]}}"""

SYSTEM_META = """You write YouTube Shorts upload details for an Indian gaming/entertainment clipping channel.
Return JSON only: {"title": "...", "description": "...", "hashtags": ["#shorts", "..."]}
- title: max 70 characters, curiosity-driven but honest, in the requested language style.
- description: 2-3 short lines about the moment. If a credit is given, end with "Credit: <credit>".
- hashtags: 5-8 tags, always include #shorts, relevant to the content and language.
No clickbait lies, no misleading claims."""


def auto_edit(segments, clip, peaks, settings, sfx_names) -> list:
    key, model = settings.get("claude_api_key", ""), settings.get("claude_model", "claude-haiku-5-5")
    s0, s1 = clip["start"], clip["end"]
    lines = [f"[{max(0, s['start'] - s0):.1f}-{min(s1, s['end']) - s0:.1f}] {s['text']}"
             for s in segments if s["end"] > s0 and s["start"] < s1]
    hint = ", ".join(f"{t:.1f}s" for t in peaks) or "none"
    user = (f"Clip length: {s1 - s0:.1f} seconds. Title: {clip.get('title', '')}\n"
            f"Loudest reaction moments: {hint}\nTranscript (seconds from clip start):\n" + "\n".join(lines))
    data = _ask_json(key, model, SYSTEM_EDIT.format(sfx=", ".join(sfx_names)), user, SCHEMA_EDIT, "edit", max_tokens=2000)
    return [e for e in _as_list(data.get("effects")) if isinstance(e, dict)]


def metadata(clip, transcript_text, language, credit, settings) -> dict:
    key, model = settings.get("claude_api_key", ""), settings.get("claude_model", "claude-haiku-5-5")
    lang = {"hinglish": "Hinglish (Roman Hindi)", "hi": "Hindi (Devanagari)", "en": "English"}.get(language, language)
    user = (f"Language style: {lang}\nClip title idea: {clip.get('title', '')}\nCategory: {clip.get('category', '')}\n"
            f"Credit: {credit or 'none'}\nWhat is said in the clip:\n{transcript_text[:3000]}")
    data = _ask_json(key, model, SYSTEM_META, user, SCHEMA_META, "meta", max_tokens=1000)
    tags = [t if t.startswith("#") else "#" + t for t in (str(x).strip().replace(" ", "") for x in _as_list(data.get("hashtags"))) if t]
    if "#shorts" not in [t.lower() for t in tags]:
        tags.insert(0, "#shorts")
    return {"title": str(data.get("title", ""))[:100], "description": str(data.get("description", ""))[:4000],
            "hashtags": tags[:10]}
