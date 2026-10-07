"""Original congdut (keroncong + dangdut) loops for Last Geeko Standing, openSUSE.Asia Summit 2026.

Everything is synthesized here: no samples, no third-party melodies. Released as CC0.
Keroncong band (cak, cuk, pizzicato cello) on top of a dangdut rhythm section (kendang "dhut"
with its pitch bend, ketipung, kecrek, bass), with a dangdut-style suling on the melody.

  python congdut.py koplo congdut-koplo.wav     # 132 BPM, busy koplo kendang, for questions and games
  python congdut.py santai congdut-santai.wav   # 108 BPM, classic dangdut "tak-dhut", for lobby/results
  An optional third argument overrides the tempo (BPM).

Then: ffmpeg -i x.wav -af loudnorm=I=-16:TP=-1.5:LRA=7 -b:a 160k x.mp3
"""
import sys
import wave

import numpy as np

SR = 44100
MODE = sys.argv[1]
OUT_FILE = sys.argv[2]
KOPLO = MODE == "koplo"
BPM = int(sys.argv[3]) if len(sys.argv) > 3 else (132 if KOPLO else 108)
BEAT = 60 / BPM
BAR = 4 * BEAT
S16 = BEAT / 4
rng = np.random.default_rng(1928)

NOTE = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def midi(name):
    return NOTE[name[:-1]] + 12 * (int(name[-1]) + 1)


def fq(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def parse(bars):
    out, beat = [], 0.0
    for tok in " ".join(bars).split():
        n, ln = tok.split(":")
        out.append((beat, None if n == "-" else midi(n), float(ln)))
        beat += float(ln)
    assert abs(beat - 4 * len(bars)) < 1e-6, beat
    return out


PROG = ["Am", "Am", "Dm", "Dm", "Am", "Am", "E", "E", "Am", "Am", "Dm", "Dm", "G", "C", "E", "Am"]
CHORD = {"Am": ["A3", "C4", "E4"], "Dm": ["D3", "F3", "A3"], "E": ["E3", "G#3", "B3"],
         "G": ["G3", "B3", "D4"], "C": ["C3", "E3", "G3"]}

TUNE_A = parse([
    "E5:1 A5:1 C6:1 B5:.5 A5:.5", "B5:1.5 A5:.5 E5:2",
    "F5:1 A5:1 D6:1 C6:.5 B5:.5", "A5:1.5 F5:.5 D5:2",
    "E5:.5 F5:.5 E5:1 C5:1 E5:1", "A5:2 G#5:1 A5:1",
    "B5:1 G#5:1 E5:1 G#5:1", "B5:3 -:1",
    "C6:1 B5:1 A5:1 E5:1", "A5:1.5 B5:.5 C6:2",
    "D6:1 C6:1 A5:1 F5:1", "A5:2 F5:1 D5:1",
    "D5:1 G5:1 B5:1 D6:1", "C6:1.5 B5:.5 G5:1 E5:1",
    "G#5:1 B5:1 E6:1 D6:.5 B5:.5", "A5:3 -:1",
])
TUNE_B = parse([
    "A5:.5 C6:.5 E6:1 D6:.5 C6:.5 B5:1", "C6:.5 B5:.5 A5:1 E5:2",
    "D6:.5 E6:.5 F6:1 E6:.5 D6:.5 C6:1", "D6:.5 C6:.5 A5:1 F5:2",
    "E5:.5 A5:.5 C6:.5 E6:.5 D6:1 C6:1", "B5:.5 C6:.5 A5:1 -:2",
    "G#5:.5 B5:.5 E6:1 D6:.5 B5:.5 G#5:1", "E5:.5 G#5:.5 B5:1 E6:2",
    "E6:1 D6:.5 C6:.5 B5:1 A5:1", "C6:.5 B5:.5 A5:1 E6:2",
    "F6:1 E6:.5 D6:.5 C6:1 A5:1", "D6:2 C6:.5 A5:.5 F5:1",
    "G5:.5 B5:.5 D6:1 B5:.5 D6:.5 G6:1", "E6:1 C6:1 G5:1 C6:1",
    "B5:.5 G#5:.5 E5:1 G#5:.5 B5:.5 D6:1", "C6:1 B5:1 A5:2",
])

N_BARS = 32
LOOP_LEN = int(round(N_BARS * BAR * SR))
TAIL = int(5 * SR)
out = np.zeros(LOOP_LEN + TAIL)
_cache = {}


def cached(key, fn):
    if key not in _cache:
        _cache[key] = fn()
    return _cache[key]


def add(sig, t, gain):
    s = int(round(t * SR))
    e = min(s + len(sig), len(out))
    if e > s:
        out[s:e] += gain * sig[: e - s]


def tt(dur):
    return np.arange(int(dur * SR)) / SR


def pluck(f, dur, bright, decay, nh=8, slide=0.0):
    def make():
        t = tt(dur)
        bend = 2 ** (-slide / 12 * np.exp(-t / 0.025)) if slide else 1.0
        ph = 2 * np.pi * np.cumsum(f * np.ones_like(t) * bend) / SR
        sig = np.zeros_like(t)
        for k in range(1, nh + 1):
            sig += (bright ** (k - 1)) / k ** 0.5 * np.sin(k * ph + k) * np.exp(-t / decay * (1 + 0.4 * k))
        return sig * np.minimum(1, t / 0.002) * np.minimum(1, (dur - t) / 0.015)
    return cached(("pl", round(f, 2), dur, bright, decay, nh, slide), make)


def bass(f, dur):
    def make():
        t = tt(dur)
        sig = np.zeros_like(t)
        for k in range(1, 7):
            sig += (1 / k) * np.sin(2 * np.pi * f * k * t) * np.exp(-t * (4 + 6 * k))
        sig += 0.8 * np.sin(2 * np.pi * f * t) * np.exp(-t * 2.5)
        return sig * np.minimum(1, t / 0.004) * np.minimum(1, (dur - t) / 0.02)
    return cached(("bass", round(f, 2), dur), make)


def suling(f, dur):
    """Dangdut suling: slides up into the note, wide vibrato, breathy."""
    def make():
        t = tt(dur)
        scoop = 2 ** (-1.0 / 12 * np.exp(-t / 0.035))
        vib = 1 + 0.009 * np.sin(2 * np.pi * 6.0 * t) * np.minimum(1, np.maximum(0, t - 0.1) / 0.2)
        ph = 2 * np.pi * np.cumsum(f * scoop * vib) / SR
        tone = np.sin(ph) + 0.22 * np.sin(2 * ph) + 0.08 * np.sin(3 * ph)
        n = len(t)
        spec = np.fft.rfft(rng.standard_normal(n))
        fr = np.fft.rfftfreq(n, 1 / SR)
        spec *= np.exp(-((fr - 2 * f) / f) ** 2)
        breath = np.fft.irfft(spec, n)
        breath /= np.max(np.abs(breath)) + 1e-9
        env = np.minimum(1, t / 0.03) * np.minimum(1, (dur - t) / 0.06)
        return (tone + 0.1 * breath) * env
    return cached(("su", round(f, 2), dur), make)


def drum(f0, f1, dur, tau, sweep=0.03):
    def make():
        t = tt(dur)
        f = f1 + (f0 - f1) * np.exp(-t / sweep)
        return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / tau)
    return cached(("drum", f0, f1, dur, tau, sweep), make)


def noise(dur, lo, hi, tau, seed):
    def make():
        n = int(dur * SR)
        spec = np.fft.rfft(np.random.default_rng(seed).standard_normal(n))
        fr = np.fft.rfftfreq(n, 1 / SR)
        spec[(fr < lo) | (fr > hi)] = 0
        s = np.fft.irfft(spec, n)
        return s / (np.max(np.abs(s)) + 1e-9) * np.exp(-np.arange(n) / SR / tau)
    return cached(("nz", dur, lo, hi, tau, seed), make)


# The dangdut "dhut": a low drum whose pitch rises as the palm presses the skin
DHUT = drum(95, 150, 0.32, 0.11, 0.08)
TAK = noise(0.07, 1500, 4500, 0.02, 1) * 0.8 + drum(420, 380, 0.07, 0.02)[: int(0.07 * SR)] * 0.4
TUNG = drum(330, 260, 0.16, 0.05, 0.015)
KICK = drum(130, 50, 0.3, 0.1, 0.025)
KECREK = noise(0.09, 4500, 12000, 0.03, 2)

for b in range(N_BARS):
    t0 = b * BAR
    ch = [midi(n) for n in CHORD[PROG[b % 16]]]
    root = ch[0]

    # kendang
    if KOPLO:
        pattern = [(0, DHUT, .5), (2, TAK, .45), (3, DHUT, .4), (4, TAK, .5), (6, TUNG, .35), (7, DHUT, .4),
                   (8, DHUT, .5), (10, TAK, .45), (11, DHUT, .4), (12, TAK, .5), (14, TUNG, .35), (15, TUNG, .3)]
        if b % 4 == 3:  # fill into the next phrase
            pattern = pattern[:6] + [(8, TAK, .5), (9, TUNG, .35), (10, TAK, .5), (11, TUNG, .35),
                                     (12, TAK, .55), (13, TUNG, .4), (14, DHUT, .5), (15, TAK, .55)]
        for k, sig, g in pattern:
            add(sig, t0 + k * S16, g)
        for beat in range(4):
            add(KICK, t0 + beat * BEAT, 0.12)
    else:
        for k, sig, g in [(0, DHUT, .45), (4, TAK, .4), (10, DHUT, .4), (12, TAK, .4), (14, TUNG, .25)]:
            add(sig, t0 + k * S16, g)
    for k in range(8):  # kecrek on the 8ths
        add(KECREK, t0 + k * BEAT / 2, 0.16 if k % 2 else 0.1)

    # bass: dangdut walk on the 8ths
    walk = [0, 0, 7, 12, 0, 7, 12, 7] if KOPLO else [0, 0, 7, 7]
    step = BEAT / 2 if KOPLO else BEAT
    for k, iv in enumerate(walk):
        add(bass(fq(root - 12 + iv), step * 0.9), t0 + k * step, 0.17 if KOPLO else 0.22)

    # keroncong layer: cak off-beats, cuk 16ths (koplo only), cello "dung" with a slide
    for k in range(4):
        for i, n in enumerate(ch):
            add(pluck(fq(n + 24), 0.15, 0.75, 0.05, 6), t0 + (k + 0.5) * BEAT + i * 0.006, 0.13)
    if KOPLO:
        for k in range(16):
            if k % 4 in (1, 3):
                for i, n in enumerate(ch):
                    add(pluck(fq(n + 12), 0.1, 0.55, 0.035, 5), t0 + k * S16 + i * 0.004, 0.07)
    for beat, iv in [(0.5, 0), (1.5, 12), (2.5, 7), (3.5, 12)]:
        add(pluck(fq(root + iv), 0.3, 0.45, 0.12, 6, slide=1.2), t0 + beat * BEAT, 0.2)

# suling melody: first 16 bars tune A, then tune B (koplo) or A again an octave down (santai)
for half in range(2):
    tune = TUNE_B if (KOPLO and half == 1) else TUNE_A
    shift = -12 if (not KOPLO and half == 1) else 0
    for beat, n, ln in tune:
        if n is not None:
            add(suling(fq(n + shift), ln * BEAT * 0.94), half * 16 * BAR + beat * BEAT, 0.42 if KOPLO else 0.32)

loop = out[:LOOP_LEN].copy()
loop[:TAIL] += out[LOOP_LEN:]
spec = np.fft.rfft(loop)
fr = np.fft.rfftfreq(len(loop), 1 / SR)
spec *= 1 / np.sqrt(1 + (45 / np.maximum(fr, 1e-3)) ** 8)
loop = np.fft.irfft(spec, len(loop))
loop = np.tanh(loop * 1.15) / np.tanh(1.15)
loop *= 0.89 / np.max(np.abs(loop))
pcm = (np.stack([loop, loop], axis=1) * 32767).astype(np.int16)
with wave.open(OUT_FILE, "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print(f"{MODE}: {N_BARS} bars at {BPM} BPM = {LOOP_LEN / SR:.2f}s, rms={np.sqrt(np.mean(loop ** 2)):.3f}")
