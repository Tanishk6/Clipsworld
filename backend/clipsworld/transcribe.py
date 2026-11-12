"""Speech to text with faster-whisper (word-level timestamps)."""
import os
import wave
import threading

from . import gpu
from .paths import models_dir

MODEL_SIZES_MB = {"tiny": 75, "base": 145, "small": 480, "medium": 1500, "large-v3-turbo": 1600}

_cache = {}
_lock = threading.Lock()


def _load(name: str, device: str):
    key = (name, device)
    with _lock:
        if key in _cache:
            return _cache[key]
        gpu.activate()
        from faster_whisper import WhisperModel
        if device == "cuda":
            model = WhisperModel(name, device="cuda", compute_type="int8_float16",
                                 download_root=str(models_dir()))
        else:
            model = WhisperModel(name, device="cpu", compute_type="int8",
                                 cpu_threads=max(1, (os.cpu_count() or 4)),
                                 download_root=str(models_dir()))
        _cache.clear()  # keep only one model in memory
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
    return any(k in s for k in ("cuda", "cublas", "cudnn", "dll", "gpu"))


def transcribe(job, wav_path: str, duration: float, settings: dict) -> dict:
    name = settings.get("whisper_model", "large-v3-turbo")
    device = pick_device(settings.get("device", "auto"))
    lang = settings.get("language", "auto")
    lang = None if lang in ("auto", "", None) else lang
    try:
        return _run(job, name, device, wav_path, duration, lang)
    except Exception as e:  # noqa: BLE001
        if device == "cuda" and _is_cuda_error(e):
            job.update(stage="GPU not available, switching to CPU…")
            return _run(job, name, "cpu", wav_path, duration, lang)
        raise


def _read_wav(path, start_s, dur_s, sr=16000):
    import numpy as np
    with wave.open(path, "rb") as w:
        w.setpos(min(w.getnframes(), int(start_s * sr)))
        frames = w.readframes(int(dur_s * sr))
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def _run_mixed(job, model, device, wav_path, duration):
    """Hindi + English in one video: detect the language for each speech chunk separately."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    sr, block = 16000, 600.0
    out = []
    t0 = 0.0
    while t0 < duration:
        audio = _read_wav(wav_path, t0, block)
        if len(audio) < sr // 2:
            break
        speech = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=500, speech_pad_ms=200))
        chunks, cur = [], None
        for sp in speech:
            if cur and (sp["end"] - cur[0]) / sr <= 25 and (sp["start"] - cur[1]) / sr < 1.5:
                cur[1] = sp["end"]
            else:
                if cur:
                    chunks.append(cur)
                cur = [sp["start"], sp["end"]]
        if cur:
            chunks.append(cur)
        for a, b in chunks:
            piece = audio[a:b]
            if len(piece) < sr * 0.4:
                continue
            _, _, probs = model.detect_language(piece)
            p = dict(probs)
            hi = p.get("hi", 0) + p.get("ur", 0)
            lang = "hi" if hi >= p.get("en", 0) else "en"
            segs, _ = model.transcribe(piece, language=lang, word_timestamps=True, beam_size=5,
                                       condition_on_previous_text=False)
            off = t0 + a / sr
            for seg in segs:
                words = [{"start": round(off + w.start, 3), "end": round(off + w.end, 3), "word": w.word.strip()}
                         for w in (seg.words or []) if w.word.strip()]
                if seg.text.strip():
                    out.append({"start": round(off + seg.start, 3), "end": round(off + seg.end, 3),
                                "text": seg.text.strip(), "words": words, "lang": lang})
            pos = off + len(piece) / sr
            job.update(progress=min(1.0, pos / duration),
                       stage=f"Listening (Hindi + English)… {int(pos // 60)}:{int(pos % 60):02d} / "
                             f"{int(duration // 60)}:{int(duration % 60):02d}")
        t0 += block
    langs = [s["lang"] for s in out]
    main = max(set(langs), key=langs.count) if langs else "hi"
    return {"language": main, "language_probability": 1.0, "device": device, "mixed": True, "segments": out}


def _run(job, name, device, wav_path, duration, lang):
    mb = MODEL_SIZES_MB.get(name, 500)
    job.update(stage=f"Loading speech model ({name}, {device.upper()}) — first run downloads ~{mb} MB…")
    model = _load(name, device)
    if lang == "mixed":
        r = _run_mixed(job, model, device, wav_path, duration)
        r["model"] = name
        return r
    job.update(stage=f"Listening to the video ({device.upper()})…")
    segments, info = model.transcribe(
        wav_path, language=lang, word_timestamps=True, vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 700}, beam_size=5,
        condition_on_previous_text=False,
    )
    out = []
    for seg in segments:
        words = [{"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word.strip()}
                 for w in (seg.words or []) if w.word.strip()]
        out.append({"start": round(seg.start, 3), "end": round(seg.end, 3),
                    "text": seg.text.strip(), "words": words})
        if duration > 0:
            job.update(progress=seg.end / duration,
                       stage=f"Listening… {int(seg.end // 60)}:{int(seg.end % 60):02d} / "
                             f"{int(duration // 60)}:{int(duration % 60):02d}")
    return {"language": info.language, "language_probability": round(info.language_probability, 3),
            "device": device, "model": name, "segments": out}
