"""Speech to text with faster-whisper (word-level timestamps), tuned for Hindi / Hinglish creators.

Language handling (setting "language"):
  mixed (default) - first listens to samples across the whole video to decide:
                    mostly Hindi  -> the whole video is written in Hindi (English words stay inside it)
                    mostly English -> English
                    really both    -> each speech chunk is checked, and only *clearly* English chunks
                                      are written in English. (Whisper set to English on Hindi audio
                                      would translate it into English, which we never want.)
  hi / en         - force one language
  auto            - Whisper's own single detection
"""
import os
import threading
import wave

from . import captions, downloads, gpu

MODEL_SIZES_MB = {"tiny": 75, "base": 145, "small": 480, "medium": 1500, "large-v3-turbo": 1600, "large-v3": 3100}
HINDI_PROMPT = "नमस्ते दोस्तों, आज की वीडियो में हम बात करेंगे। चलो शुरू करते हैं।"
SR = 16000

_cache = {}
_lock = threading.Lock()


def _load(name: str, device: str):
    key = (name, device)
    with _lock:
        if key in _cache:
            return _cache[key]
        gpu.activate()
        from faster_whisper import WhisperModel
        path = str(downloads.model_path(name))
        _cache.clear()  # keep only one model in memory
        if device == "cuda":
            model = WhisperModel(path, device="cuda", compute_type="int8_float16")
        else:
            model = WhisperModel(path, device="cpu", compute_type="int8",
                                 cpu_threads=max(1, (os.cpu_count() or 4)))
        _cache[key] = model
        return model


def pick_device(pref: str) -> str:
    if pref == "cpu":
        return "cpu"
    if gpu.cuda_device_count() > 0 and (pref == "cuda" or gpu.pack_installed() or os.name != "nt"):
        return "cuda"
    return "cpu"


def _is_cuda_error(e: Exception) -> bool:
    s = str(e).lower()
    return any(k in s for k in ("cuda", "cublas", "cudnn", "dll", "gpu", "out of memory"))


def transcribe(job, wav_path: str, duration: float, settings: dict) -> dict:
    name = settings.get("whisper_model", "large-v3-turbo")
    device = pick_device(settings.get("device", "auto"))
    lang = settings.get("language", "mixed") or "mixed"
    try:
        return _run(job, name, device, wav_path, duration, lang)
    except Exception as e:  # noqa: BLE001
        if device == "cuda" and _is_cuda_error(e):
            job.update(stage="GPU not available, switching to CPU…")
            with _lock:
                _cache.clear()
            return _run(job, name, "cpu", wav_path, duration, lang)
        raise


def _read_wav(path, start_s, dur_s):
    import numpy as np
    with wave.open(path, "rb") as w:
        w.setpos(min(w.getnframes(), int(start_s * SR)))
        frames = w.readframes(int(dur_s * SR))
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def _lang_probs(model, audio) -> tuple:
    """(hindi, english) probability for a piece of audio. Urdu counts as Hindi (same spoken language)."""
    _, _, probs = model.detect_language(audio)
    p = dict(probs)
    return p.get("hi", 0) + p.get("ur", 0) + p.get("pa", 0) * 0.5, p.get("en", 0)


def _speech_chunks(audio, max_len=25.0):
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    speech = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=500, speech_pad_ms=200))
    chunks, cur = [], None
    for sp in speech:
        if cur and (sp["end"] - cur[0]) / SR <= max_len and (sp["start"] - cur[1]) / SR < 1.5:
            cur[1] = sp["end"]
        else:
            if cur:
                chunks.append(cur)
            cur = [sp["start"], sp["end"]]
    if cur:
        chunks.append(cur)
    return chunks


def _is_english(hi: float, en: float) -> bool:
    return en >= 0.8 and en > 4 * hi


def detect_profile(model, wav_path: str, duration: float) -> float:
    """Share of speech that is clearly English, measured on short speech pieces across the video."""
    n_windows = max(1, min(8, int(duration // 60) or 1))
    votes = []
    for i in range(n_windows):
        t = max(0.0, duration * (i + 0.5) / n_windows - 30)
        audio = _read_wav(wav_path, t, 60)
        if len(audio) < SR * 2:
            continue
        for a, b in _speech_chunks(audio, 12.0)[:4]:
            piece = audio[a:b]
            if len(piece) < SR * 1.0:
                continue
            votes.append(_is_english(*_lang_probs(model, piece)))
    if not votes:
        return 0.0
    return sum(votes) / len(votes)


_JUNK = __import__("re").compile(r"[^\u0900-\u097F\u0020-\u024F\u2000-\u206F\u20B9\u2600-\u27BF\U0001F300-\U0001FAFF\u0964\u0965]")


def clean_text(text: str) -> str:
    """Remove characters from other scripts that Whisper sometimes invents (Korean, Chinese, ...)."""
    t = _JUNK.sub("", text)
    return " ".join(t.split())


def _segments_out(segs, offset=0.0, lang=None, out=None, job=None, duration=0.0):
    out = [] if out is None else out
    for seg in segs:
        text = clean_text(captions.fix_text(seg.text.strip()))
        if not text or not any(ch.isalnum() for ch in text):
            continue
        words = captions.fix_words([{"start": round(offset + w.start, 3), "end": round(offset + w.end, 3),
                                     "word": clean_text(w.word.strip())} for w in (seg.words or []) if clean_text(w.word.strip())])
        item = {"start": round(offset + seg.start, 3), "end": round(offset + seg.end, 3), "text": text, "words": words}
        if lang:
            item["lang"] = lang
        out.append(item)
        if job and duration > 0:
            pos = offset + seg.end
            job.update(progress=min(1.0, pos / duration),
                       stage=f"Listening… {int(pos // 60)}:{int(pos % 60):02d} / {int(duration // 60)}:{int(duration % 60):02d}")
    return out


def _whole(job, model, wav_path, duration, lang):
    segs, info = model.transcribe(
        wav_path, language=lang, task="transcribe", word_timestamps=True, vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 600, "speech_pad_ms": 250}, beam_size=5,
        condition_on_previous_text=False, initial_prompt=HINDI_PROMPT if lang == "hi" else None,
        no_speech_threshold=0.6, log_prob_threshold=-1.2, compression_ratio_threshold=2.4,
    )
    out = _segments_out(segs, 0.0, lang, job=job, duration=duration)
    return out, info.language


def _per_chunk(job, model, wav_path, duration):
    """Both languages: check each speech chunk, write Hindi unless the chunk is clearly English."""
    block = 600.0
    out = []
    t0 = 0.0
    while t0 < duration:
        audio = _read_wav(wav_path, t0, block)
        if len(audio) < SR // 2:
            break
        chunks = _speech_chunks(audio)
        for a, b in chunks:
            piece = audio[a:b]
            if len(piece) < SR * 0.4:
                continue
            lang = "en" if _is_english(*_lang_probs(model, piece)) else "hi"
            segs, _ = model.transcribe(piece, language=lang, task="transcribe", word_timestamps=True, beam_size=5,
                                       condition_on_previous_text=False,
                                       initial_prompt=HINDI_PROMPT if lang == "hi" else None)
            _segments_out(segs, t0 + a / SR, lang, out)
            pos = t0 + b / SR
            job.update(progress=min(1.0, pos / duration),
                       stage=f"Listening (Hindi + English)… {int(pos // 60)}:{int(pos % 60):02d} / "
                             f"{int(duration // 60)}:{int(duration % 60):02d}")
        t0 += block
    return out


def _run(job, name, device, wav_path, duration, lang):
    downloads.wait_for(f"model:{name}", job, "Downloading speech model")
    job.update(stage=f"Loading speech model ({name}, {device.upper()})…")
    model = _load(name, device)
    profile = None
    if lang == "mixed":
        job.update(stage="Checking which language is spoken…")
        en_share = detect_profile(model, wav_path, duration)
        profile = {"english_share": round(en_share, 3)}
        if en_share <= 0.08:
            mode = "hi"      # Hindi video (English words inside are fine)
        elif en_share >= 0.92:
            mode = "en"
        else:
            mode = "both"    # really mixed: decide per speech chunk
    elif lang in ("hi", "en"):
        mode = lang
    else:
        mode = "auto"
    job.update(stage=f"Listening to the video ({device.upper()})…")
    if mode == "both":
        segs = _per_chunk(job, model, wav_path, duration)
        main = "hi" if sum(1 for s in segs if s.get("lang") == "hi") >= len(segs) / 2 else "en"
    else:
        segs, main = _whole(job, model, wav_path, duration, None if mode == "auto" else mode)
    return {"language": main, "mode": mode, "profile": profile, "mixed": mode == "both",
            "device": device, "model": name, "segments": segs}
