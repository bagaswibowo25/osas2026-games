"""Original keroncong loops for Last Geeko Standing (openSUSE.Asia Summit 2026, Yogyakarta).

Everything is synthesized here: no samples, no third-party melodies. Released as CC0.
The classic keroncong band: cak and cuk (small ukuleles: off-beat chops and interlocking 16ths),
pizzicato cello that "drums" the rhythm, plucked double bass, guitar runs, flute and violin.

  python keroncong.py rancak keroncong-rancak-134.wav   # 134 BPM, flute leads first, for play
  python keroncong.py langgam langgam-senja-108.wav     # 108 BPM, violin leads first, lighter, for lobby/results
  An optional third argument overrides the tempo (BPM).

Then: ffmpeg -i x.wav -af loudnorm=I=-16:TP=-1.5:LRA=7 -b:a 160k x.mp3
"""
import sys
import wave

import numpy as np

SR = 44100
MODE = sys.argv[1]
OUT_FILE = sys.argv[2]
RANCAK = MODE == "rancak"
BPM = int(sys.argv[3]) if len(sys.argv) > 3 else (134 if RANCAK else 108)
BEAT = 60 / BPM
BAR = 4 * BEAT
rng = np.random.default_rng(1945)

NOTE = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def midi(name):
    """'F#5' -> MIDI number."""
    return NOTE[name[:-1]] + 12 * (int(name[-1]) + 1)


def fq(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def parse(line):
    """'D5:1 G5:.5 -:1' -> [(beat, midi or None, length)]."""
    out, beat = [], 0.0
    for tok in line.split():
        n, ln = tok.split(":")
        ln = float(ln)
        out.append((beat, None if n == "-" else midi(n), ln))
        beat += ln
    return out


# Keroncong-style progression in G, 16 bars
PROG = ["G", "G", "D", "D", "G", "G", "C", "C", "G", "G", "D", "D", "C", "D", "G", "G"]
CHORD = {"G": ["G3", "B3", "D4"], "D": ["D3", "F#3", "A3"], "C": ["C3", "E3", "G3"]}

# Tune A (bright, flute) and tune B (lyrical, violin), one bar per string
TUNE_A = parse(" ".join([
    "D5:1 G5:1 B5:1 A5:.5 G5:.5", "A5:1.5 G5:.5 E5:1 D5:1",
    "F#5:1 A5:1 D6:1.5 C6:.5", "B5:1 A5:1 F#5:1 -:1",
    "G5:1 B5:.5 A5:.5 G5:1 D5:1", "E5:.5 F#5:.5 G5:1 A5:2",
    "C6:1.5 B5:.5 A5:1 G5:1", "E5:1 G5:1 C6:2",
    "B5:1 A5:.5 G5:.5 D5:1 G5:1", "B5:1.5 C6:.5 D6:2",
    "C6:1 B5:1 A5:1 F#5:1", "A5:1 D6:1 C6:.5 B5:.5 A5:1",
    "G5:1 E5:1 C6:1 B5:1", "A5:1 F#5:1 A5:1 C6:1",
    "B5:2 A5:.5 B5:.5 G5:1", "G5:3 -:1",
]))
TUNE_B = parse(" ".join([
    "G4:2 B4:1 D5:1", "E5:1.5 D5:.5 B4:2",
    "A4:2 D5:1 F#5:1", "E5:1 D5:1 A4:2",
    "B4:1.5 C5:.5 D5:2", "G5:1 F#5:1 E5:1 D5:1",
    "E5:2 G5:1 E5:1", "C5:3 -:1",
    "D5:1 B4:1 G4:1 B4:1", "D5:2 G5:2",
    "F#5:1.5 E5:.5 D5:1 A4:1", "D5:2 E5:1 F#5:1",
    "G5:2 E5:1 C5:1", "D5:2 A4:1 C5:1",
    "B4:2 A4:1 B4:1", "G4:4",
]))

# 32 bars: the progression twice; who leads swaps halfway
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
    """Plucked string. `slide` > 0 starts that many semitones flat and slides up (cello 'dung')."""
    def make():
        t = tt(dur)
        bend = 2 ** (-slide / 12 * np.exp(-t / 0.025)) if slide else 1.0
        ph = 2 * np.pi * np.cumsum(f * np.ones_like(t) * bend) / SR
        sig = np.zeros_like(t)
        for k in range(1, nh + 1):
            sig += (bright ** (k - 1)) / k ** 0.5 * np.sin(k * ph + k) * np.exp(-t / decay * (1 + 0.4 * k))
        return sig * np.minimum(1, t / 0.002) * np.minimum(1, (dur - t) / 0.015)
    return cached(("pl", round(f, 2), dur, bright, decay, nh, slide), make)


def flute(f, dur):
    """Western flute with a grace note from above on longer notes (keroncong ornament)."""
    def make():
        t = tt(dur)
        grace = 2 ** (2 / 12 * (t < 0.055)) if dur >= 0.45 else 1.0
        vib = 1 + 0.005 * np.sin(2 * np.pi * 5.2 * t) * np.minimum(1, t / 0.3)
        ph = 2 * np.pi * np.cumsum(f * grace * vib) / SR
        tone = np.sin(ph) + 0.25 * np.sin(2 * ph) + 0.07 * np.sin(3 * ph)
        n = len(t)
        spec = np.fft.rfft(rng.standard_normal(n))
        fr = np.fft.rfftfreq(n, 1 / SR)
        spec *= np.exp(-((fr - 2.5 * f) / (1.5 * f)) ** 2)
        breath = np.fft.irfft(spec, n)
        breath /= np.max(np.abs(breath)) + 1e-9
        env = np.minimum(1, t / 0.035) * np.minimum(1, (dur - t) / 0.06)
        return (tone + 0.06 * breath) * env
    return cached(("fl", round(f, 2), dur), make)


def violin(f, dur):
    """Bowed string: bright harmonic stack, portamento into the note, growing vibrato."""
    def make():
        t = tt(dur)
        glide = 2 ** (-0.7 / 12 * np.exp(-t / 0.04))
        vib = 1 + 0.007 * np.sin(2 * np.pi * 5.8 * t) * np.minimum(1, np.maximum(0, t - 0.12) / 0.25)
        ph = 2 * np.pi * np.cumsum(f * glide * vib) / SR
        sig = np.zeros_like(t)
        for k in range(1, 13):
            amp = (0.88 ** k) / k * (1.6 if 3 <= k <= 5 else 1.0)  # body resonance
            sig += amp * np.sin(k * ph)
        n = len(t)
        bow = rng.standard_normal(n) * 0.015
        env = np.minimum(1, t / 0.07) * np.minimum(1, (dur - t) / 0.09)
        return (sig + bow) * env
    return cached(("vn", round(f, 2), dur), make)


def shaker():
    def make():
        n = int(0.05 * SR)
        spec = np.fft.rfft(rng.standard_normal(n))
        fr = np.fft.rfftfreq(n, 1 / SR)
        spec[(fr < 5000) | (fr > 11000)] = 0
        s = np.fft.irfft(spec, n)
        return s / (np.max(np.abs(s)) + 1e-9) * np.exp(-np.arange(n) / SR / 0.014)
    return cached("sh", make)


lead_first = "flute" if RANCAK else "violin"
for b in range(N_BARS):
    t0 = b * BAR
    root = PROG[b % 16]
    ch = [midi(n) for n in CHORD[root]]
    second_half = b >= 16

    # double bass: root on 1, fifth on 3
    add(pluck(fq(ch[0] - 12), BEAT * 1.6, 0.3, 0.45, 5), t0, 0.42)
    add(pluck(fq(ch[2] - 12), BEAT * 1.6, 0.3, 0.45, 5), t0 + 2 * BEAT, 0.36)

    # cello: the keroncong "kendang" with an upward slide on each pluck
    cello = [(0.5, 0), (1.0, 7), (1.5, 12), (2.5, 0), (3.0, 7), (3.5, 12), (3.75, 7)]
    if not RANCAK:
        cello = [(0.5, 0), (1.5, 12), (2.5, 0), (3.5, 12)]
    for beat, iv in cello:
        add(pluck(fq(ch[0] + iv), 0.32, 0.45, 0.12, 6, slide=1.2), t0 + beat * BEAT, 0.3)

    # cak: bright off-beat chops (the "crong" of keroncong)
    cak = [fq(n + 24) for n in ch]
    for k in range(4):
        t = t0 + (k + 0.5) * BEAT
        for i, f in enumerate(cak):
            add(pluck(f, 0.16, 0.75, 0.05, 6), t + i * 0.006, 0.11)

    # cuk: lower chops on the 16ths around the beat ("e" and "a"), only in the rancak version
    if RANCAK:
        cuk = [fq(n + 12) for n in ch]
        for k in range(16):
            if k % 4 in (1, 3):
                for i, f in enumerate(cuk):
                    add(pluck(f, 0.11, 0.55, 0.035, 5), t0 + k * BEAT / 4 + i * 0.004, 0.08)

    # guitar: broken-chord runs on 8ths (16ths in the second half of rancak)
    run = [ch[0], ch[1], ch[2], ch[0] + 12, ch[1] + 12, ch[0] + 12, ch[2], ch[1]]
    if RANCAK and second_half:
        step = BEAT / 4
        notes = run + run[::-1]
    else:
        step = BEAT / 2
        notes = run
    for k, n in enumerate(notes):
        add(pluck(fq(n), 0.4, 0.5, 0.18, 7), t0 + k * step, 0.09)

    if RANCAK:  # a soft shaker keeps the energy up
        for k in range(8):
            add(shaker(), t0 + k * BEAT / 2, 0.06 if k % 2 else 0.09)

# melodies: first 16 bars led by one instrument, then the other with the second tune
for half in range(2):
    t_half = half * 16 * BAR
    leader = lead_first if half == 0 else ("violin" if lead_first == "flute" else "flute")
    tune = TUNE_A if leader == "flute" else TUNE_B
    for beat, n, ln in tune:
        if n is None:
            continue
        if leader == "flute":
            add(flute(fq(n), ln * BEAT * 0.95), t_half + beat * BEAT, 0.3)
        else:
            add(violin(fq(n), ln * BEAT * 0.98), t_half + beat * BEAT, 0.22)
    # the other instrument answers at the end of every 4-bar phrase (obbligato)
    for phrase in range(4):
        tb = t_half + (phrase * 4 + 3) * BAR + 2 * BEAT
        root = PROG[phrase * 4 + 3]
        ch = [midi(n) for n in CHORD[root]]
        fill = [ch[2] + 24, ch[1] + 24, ch[0] + 24, ch[2] + 12] if leader == "violin" else [ch[0] + 12, ch[1] + 12, ch[2] + 12, ch[0] + 24]
        for k, n in enumerate(fill):
            if leader == "violin":
                add(flute(fq(n), BEAT / 2 * 0.9), tb + k * BEAT / 2, 0.16)
            else:
                add(violin(fq(n), BEAT / 2 * 0.95), tb + k * BEAT / 2, 0.12)

# master: fold tails, high-pass, gentle glue, normalise
loop = out[:LOOP_LEN].copy()
loop[:TAIL] += out[LOOP_LEN:]
spec = np.fft.rfft(loop)
fr = np.fft.rfftfreq(len(loop), 1 / SR)
spec *= 1 / np.sqrt(1 + (45 / np.maximum(fr, 1e-3)) ** 8)
loop = np.fft.irfft(spec, len(loop))
loop = np.tanh(loop * 1.1) / np.tanh(1.1)
loop *= 0.89 / np.max(np.abs(loop))
pcm = (np.stack([loop, loop], axis=1) * 32767).astype(np.int16)
with wave.open(OUT_FILE, "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print(f"{MODE}: {N_BARS} bars at {BPM} BPM = {LOOP_LEN / SR:.2f}s, rms={np.sqrt(np.mean(loop ** 2)):.3f}")
