"""Generate Clipsworld's built-in sound effects (original, royalty-free, synthesized).

Run: python tools/make_sfx.py  -> writes resources/sfx/*.wav
"""
import wave
from pathlib import Path

import numpy as np

SR = 48000
OUT = Path(__file__).resolve().parents[1] / "resources" / "sfx"
rng = np.random.default_rng(7)


def t_(d):
    return np.arange(int(SR * d)) / SR


def env(n, a=0.005, r=0.2, curve=3.0):
    e = np.ones(n)
    na = max(1, int(SR * a))
    e[:na] = np.linspace(0, 1, na)
    x = np.linspace(0, 1, n)
    return e * (1 - x) ** curve if r is None else e * np.exp(-x * n / SR / max(r, 1e-3))


def lowpass(x, cutoff):
    # simple one-pole low-pass, cutoff can be an array
    cutoff = np.broadcast_to(np.asarray(cutoff, dtype=float), x.shape)
    y = np.zeros_like(x)
    acc = 0.0
    k = 1 - np.exp(-2 * np.pi * cutoff / SR)
    for i in range(len(x)):
        acc += k[i] * (x[i] - acc)
        y[i] = acc
    return y


def bandnoise(d, f0, f1, q=0.25):
    n = int(SR * d)
    noise = rng.standard_normal(n)
    f = np.linspace(f0, f1, n)
    hi = lowpass(noise, f * (1 + q))
    lo = lowpass(noise, f * (1 - q))
    return hi - lo


def norm(x, peak=0.89):
    m = np.max(np.abs(x)) or 1
    return x / m * peak


def save(name, x, stereo_width=0.0):
    x = norm(x)
    if stereo_width:
        d = int(SR * 0.012)
        r = np.concatenate([np.zeros(d), x[:-d]])
        st = np.stack([x, (1 - stereo_width) * x + stereo_width * r], axis=1)
    else:
        st = np.stack([x, x], axis=1)
    pcm = (np.clip(st, -1, 1) * 32767).astype(np.int16)
    OUT.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT / f"{name}.wav"), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def whoosh():
    d = 0.55
    x = bandnoise(d, 300, 3500, 0.35)
    n = len(x)
    e = np.sin(np.linspace(0, np.pi, n)) ** 2
    return x * e


def swoosh_up():
    d = 0.45
    x = bandnoise(d, 500, 7000, 0.3)
    e = np.linspace(0, 1, len(x)) ** 2 * np.exp(-np.linspace(0, 1, len(x)) * 0.5)
    e[-int(SR * 0.04):] *= np.linspace(1, 0, int(SR * 0.04))
    return x * e


def boom():
    # deep "vine boom" style hit: pitched-down sine thump + sub + reverb tail
    t = t_(1.6)
    f = 70 * np.exp(-t * 2.2) + 38
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t * 2.4)
    click = bandnoise(0.05, 800, 200, 0.5) * np.linspace(1, 0, int(SR * 0.05))
    body[:len(click)] += click * 0.6
    tail = lowpass(rng.standard_normal(len(t)), 400) * np.exp(-t * 3) * 0.6
    sat = np.tanh(2.2 * (body + tail))
    return sat


def bass_drop():
    t = t_(1.8)
    f = 160 * np.exp(-t * 1.8) + 32
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.tanh(3 * np.sin(ph)) * np.exp(-t * 1.1)
    return x


def pop():
    t = t_(0.12)
    f = 900 * np.exp(-t * 40) + 300
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 45)
    return x


def ding():
    t = t_(1.4)
    x = sum(a * np.sin(2 * np.pi * f * t) * np.exp(-t * dcy) for f, a, dcy in
            [(1318.5, 1.0, 3.2), (2637, 0.35, 5), (3951, 0.15, 7), (1975.5, 0.25, 4)])
    x[: int(SR * 0.003)] *= np.linspace(0, 1, int(SR * 0.003))
    return x


def sparkle():
    out = np.zeros(int(SR * 1.0))
    notes = [2093, 2637, 3136, 4186, 3520, 5274]
    for i, f in enumerate(notes):
        st = int(SR * 0.07 * i)
        t = t_(0.5)
        tone = np.sin(2 * np.pi * f * t) * np.exp(-t * 9)
        out[st:st + len(tone)] += tone[: len(out) - st] * (0.9 - i * 0.08)
    return out


def airhorn():
    t = t_(1.3)
    x = np.zeros_like(t)
    for f in (466, 554, 698):  # Bb chord-ish, sawtooth stack
        vib = 1 + 0.004 * np.sin(2 * np.pi * 5.5 * t)
        ph = np.cumsum(f * vib) / SR
        x += 2 * (ph % 1) - 1
    e = np.ones_like(t)
    a = int(SR * 0.03)
    e[:a] = np.linspace(0, 1, a)
    e[-int(SR * 0.25):] = np.linspace(1, 0, int(SR * 0.25))
    # three short blasts
    gate = np.ones_like(t)
    for s, en in ((0.22, 0.30), (0.52, 0.60)):
        gate[int(s * SR):int(en * SR)] = 0.0
    x = lowpass(x * e * gate, 4500)
    return np.tanh(1.8 * x)


def record_scratch():
    d = 0.5
    t = t_(d)
    noise = rng.standard_normal(len(t))
    speed = np.sin(2 * np.pi * 3.2 * t) * np.exp(-t * 2.5)
    cut = 600 + 3000 * np.abs(speed)
    x = lowpass(noise, cut) - lowpass(noise, cut * 0.4)
    x *= np.abs(speed) ** 0.6
    return x


def rewind():
    d = 0.9
    t = t_(d)
    f = 1800 * (1 - t / d) ** 2 + 200
    ph = 2 * np.pi * np.cumsum(f) / SR
    tone = np.sign(np.sin(ph)) * 0.25 + np.sin(ph * 1.5) * 0.3
    chop = (np.sin(2 * np.pi * (14 + 30 * t / d) * t) > 0).astype(float)
    x = lowpass(tone * chop + bandnoise(d, 3000, 400, 0.4) * 0.6, 5000)
    return x * np.sin(np.linspace(0, np.pi, len(t))) ** 0.4


def glitch():
    out = []
    for _ in range(14):
        d = rng.uniform(0.01, 0.045)
        t = t_(d)
        kind = rng.integers(0, 3)
        if kind == 0:
            seg = np.sign(np.sin(2 * np.pi * rng.uniform(200, 2000) * t))
        elif kind == 1:
            seg = rng.standard_normal(len(t))
        else:
            seg = np.zeros(len(t))
        out.append(seg * rng.uniform(0.4, 1))
    return np.concatenate(out)


def error_buzz():
    t = t_(0.7)
    x = np.zeros_like(t)
    for f in (150, 155):
        x += 2 * ((f * t) % 1) - 1
    gate = np.ones_like(t)
    gate[int(0.3 * SR):int(0.36 * SR)] = 0
    return lowpass(x * gate * np.exp(-t * 0.5), 2500)


def camera_click():
    a = bandnoise(0.02, 4000, 2000, 0.5) * np.linspace(1, 0, int(SR * 0.02))
    gap = np.zeros(int(SR * 0.06))
    b = bandnoise(0.05, 2500, 800, 0.5) * np.linspace(1, 0, int(SR * 0.05)) * 0.8
    return np.concatenate([a, gap, b, np.zeros(int(SR * 0.05))])


def heartbeat():
    out = np.zeros(int(SR * 1.6))
    for st, amp in ((0.0, 1.0), (0.22, 0.7), (0.8, 1.0), (1.02, 0.7)):
        t = t_(0.18)
        f = 60 * np.exp(-t * 8) + 40
        thump = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 22) * amp
        i = int(st * SR)
        out[i:i + len(thump)] += thump[: len(out) - i]
    return np.tanh(2 * out)


def drumroll():
    d = 1.6
    out = np.zeros(int(SR * (d + 0.5)))
    i, k = 0.0, 0
    while i < d:
        t = t_(0.06)
        hit = bandnoise(0.06, 3000, 1500, 0.5) * np.exp(-t * 60) * (0.4 + 0.6 * i / d)
        s = int(i * SR)
        out[s:s + len(hit)] += hit
        i += 0.045 - 0.015 * (i / d)
        k += 1
    t = t_(0.5)
    crash = bandnoise(0.5, 6000, 4000, 0.6) * np.exp(-t * 6)
    s = int(d * SR)
    out[s:s + len(crash)] += crash[: len(out) - s] * 1.5
    return out


def tada():
    out = np.zeros(int(SR * 1.5))
    chord = [523.25, 659.25, 783.99, 1046.5]
    for j, (st, notes) in enumerate(((0.0, chord[:2]), (0.12, chord))):
        t = t_(1.3)
        tone = sum(np.sign(np.sin(2 * np.pi * f * t)) * 0.3 + np.sin(2 * np.pi * f * t) for f in notes)
        tone *= np.exp(-t * (6 if j == 0 else 2.2))
        s = int(st * SR)
        out[s:s + len(tone)] += lowpass(tone, 3500)[: len(out) - s]
    return out


SOUNDS = {
    "whoosh": whoosh, "swoosh_up": swoosh_up, "boom": boom, "bass_drop": bass_drop, "pop": pop,
    "ding": ding, "sparkle": sparkle, "airhorn": airhorn, "record_scratch": record_scratch,
    "rewind": rewind, "glitch": glitch, "error_buzz": error_buzz, "camera_click": camera_click,
    "heartbeat": heartbeat, "drumroll": drumroll, "tada": tada,
}

if __name__ == "__main__":
    for name, fn in SOUNDS.items():
        save(name, fn(), stereo_width=0.3)
        print("made", name)
