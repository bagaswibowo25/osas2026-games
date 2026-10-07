"""Original upbeat loops for Last Geeko Standing (openSUSE.Asia Summit 2026, Yogyakarta).

Everything is synthesized here from sine waves and noise: no samples, no third-party material.
Released as CC0. Two seamless loops, written as 16-bit stereo WAV:

  python compose.py funk jogja-funk.wav      # 120 BPM: kendang koplo + funk bass + saron riff (play)
  python compose.py desa desa-riang.wav      # 104 BPM: suling + cak-cuk + pizz bass (lobby, results)

Then: ffmpeg -i x.wav -af loudnorm=I=-16:TP=-1.5:LRA=7 -b:a 160k x.mp3
"""
import sys
import wave

import numpy as np

SR = 44100
MODE = sys.argv[1]
OUT_FILE = sys.argv[2]
BPM = 120 if MODE == "funk" else 104
BEAT = 60 / BPM
S16 = BEAT / 4  # one sixteenth
rng = np.random.default_rng(2026 if MODE == "funk" else 1004)

NOTE = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def hz(name, octave):
    return 440.0 * 2 ** ((NOTE[name] + 12 * (octave + 1) - 69) / 12)


def midi_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def m(name, octave):
    return NOTE[name] + 12 * (octave + 1)


# ------------------------------------------------------------------ instruments
_cache = {}


def cached(key, fn):
    if key not in _cache:
        _cache[key] = fn()
    return _cache[key]


def env_t(dur):
    return np.arange(int(dur * SR)) / SR


def metal(f, dur, tau, partials, beat_hz=4.0):
    """Gamelan metallophone: inharmonic partials, exponential decay, ombak (detuned pair)."""
    def make():
        t = env_t(dur)
        sig = np.zeros_like(t)
        for ratio, amp, dm in partials:
            sig += amp * np.exp(-t / (tau * dm)) * (np.sin(2 * np.pi * f * ratio * t) + np.sin(2 * np.pi * (f * ratio + beat_hz) * t))
        return sig * np.minimum(1, t / 0.003) * 0.5
    return cached(("metal", round(f, 2), dur, tau, tuple(partials), beat_hz), make)


SARON = ((1, 1.0, 1.0), (2.76, 0.32, 0.45), (5.4, 0.1, 0.25))
PEKING = ((1, 1.0, 1.0), (2.76, 0.25, 0.4))
BONANG = ((1, 1.0, 1.0), (2.0, 0.4, 0.5), (3.0, 0.15, 0.3))  # kettle gong: closer to harmonic
KENONG = ((1, 1.0, 1.0), (2.0, 0.25, 0.6), (3.01, 0.08, 0.3))


def gong(f):
    def make():
        t = env_t(5.0)
        env = np.exp(-t / 2.8) * np.minimum(1, t / 0.03)
        wob = 1 + 0.35 * np.sin(2 * np.pi * 1.3 * t)
        return (np.sin(2 * np.pi * f * t) + 0.45 * np.sin(2 * np.pi * f * 2.01 * t) * np.exp(-t / 1.4)) * env * wob
    return cached(("gong", f), make)


def pluck(f, dur, bright=0.6, decay=0.35, harmonics=10):
    """Plucked string (guitar / cak / cuk / bass): additive harmonics, higher ones die faster."""
    def make():
        t = env_t(dur)
        sig = np.zeros_like(t)
        for k in range(1, harmonics + 1):
            amp = (bright ** (k - 1)) / k ** 0.5
            sig += amp * np.sin(2 * np.pi * f * k * t + k) * np.exp(-t * (1 / decay) * (1 + 0.35 * k))
        rel = np.minimum(1, (dur - t) / 0.02)
        return sig * np.minimum(1, t / 0.002) * rel
    return cached(("pluck", round(f, 2), dur, bright, decay, harmonics), make)


def funk_bass(f, dur):
    """Rounded synth/slap bass: saw-like stack with a quick filter-ish brightness drop."""
    def make():
        t = env_t(dur)
        sig = np.zeros_like(t)
        for k in range(1, 9):
            sig += (1 / k) * np.sin(2 * np.pi * f * k * t) * np.exp(-t * (6 + 9 * k))
        sig += 0.9 * np.sin(2 * np.pi * f * t) * np.exp(-t * 3)
        rel = np.minimum(1, (dur - t) / 0.015)
        return sig * np.minimum(1, t / 0.003) * rel
    return cached(("bass", round(f, 2), dur), make)


def epiano(freqs, dur):
    """Short FM e-piano chord stab."""
    def make():
        t = env_t(dur)
        sig = np.zeros_like(t)
        for f in freqs:
            idx = 1.6 * np.exp(-t * 14)
            sig += np.sin(2 * np.pi * f * t + idx * np.sin(2 * np.pi * f * t)) * np.exp(-t * 7)
        rel = np.minimum(1, (dur - t) / 0.02)
        return sig * np.minimum(1, t / 0.003) * rel / len(freqs)
    return cached(("ep", tuple(round(f, 2) for f in freqs), dur), make)


def suling(f, dur):
    """Bamboo flute: sine + a little 2nd/3rd harmonic, vibrato that grows, breath noise."""
    def make():
        t = env_t(dur)
        vib = 1 + 0.006 * np.sin(2 * np.pi * 5.6 * t) * np.minimum(1, t / 0.35)
        ph = 2 * np.pi * np.cumsum(f * vib) / SR
        tone = np.sin(ph) + 0.18 * np.sin(2 * ph) + 0.06 * np.sin(3 * ph)
        n = len(t)
        spec = np.fft.rfft(rng.standard_normal(n))
        fr = np.fft.rfftfreq(n, 1 / SR)
        spec *= np.exp(-((fr - f * 2) / (f * 0.8)) ** 2)
        breath = np.fft.irfft(spec, n)
        breath /= np.max(np.abs(breath)) + 1e-9
        env = np.minimum(1, t / 0.06) * np.minimum(1, (dur - t) / 0.08)
        return (tone + 0.12 * breath) * env
    return cached(("suling", round(f, 2), dur), make)


def band_noise(dur, lo, hi, tau, seed=0):
    def make():
        n = int(dur * SR)
        r = np.random.default_rng(seed)
        spec = np.fft.rfft(r.standard_normal(n))
        fr = np.fft.rfftfreq(n, 1 / SR)
        spec[(fr < lo) | (fr > hi)] = 0
        sig = np.fft.irfft(spec, n)
        sig /= np.max(np.abs(sig)) + 1e-9
        return sig * np.exp(-np.arange(n) / SR / tau)
    return cached(("noise", dur, lo, hi, tau, seed), make)


def drum(f0, f1, dur, tau, sweep=0.03):
    def make():
        t = env_t(dur)
        f = f1 + (f0 - f1) * np.exp(-t / sweep)
        return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / tau)
    return cached(("drum", f0, f1, dur, tau, sweep), make)


KICK = drum(140, 48, 0.35, 0.12, 0.025)
DHUNG = drum(150, 72, 0.3, 0.1)  # kendang low
TUNG = drum(420, 260, 0.18, 0.06, 0.01)  # ketipung
TAK = band_noise(0.08, 1800, 4200, 0.018, 1)
HAT = band_noise(0.05, 6500, 12000, 0.012, 2)
OPENHAT = band_noise(0.2, 6000, 12000, 0.06, 3)
SHAKER = band_noise(0.05, 5000, 11000, 0.014, 4)


def clap():
    def make():
        n = band_noise(0.25, 900, 5000, 0.05, 5)
        out = np.zeros(int(0.27 * SR))
        for k, d in enumerate((0, 0.009, 0.018)):
            s = int(d * SR)
            out[s:s + len(n)] += n[: len(out) - s] * (0.6 if k < 2 else 1.0)
        return out
    return cached("clap", make)


CLAP = clap()

# ------------------------------------------------------------------ arrangement helpers
if MODE == "funk":
    # 32 bars: A (groove) x 8, B (lift) x 8, A' x 8, B' x 8
    PROG_A = [("D", "maj"), ("D", "maj"), ("B", "min"), ("B", "min"), ("G", "maj"), ("G", "maj"), ("A", "maj"), ("A", "maj")]
    PROG_B = [("G", "maj"), ("A", "maj"), ("F#", "min"), ("B", "min"), ("G", "maj"), ("A", "maj"), ("D", "maj"), ("A", "maj")]
    BARS = PROG_A + PROG_B + PROG_A + PROG_B
else:
    PROG_A = [("G", "maj"), ("C", "maj"), ("D", "maj"), ("G", "maj"), ("E", "min"), ("C", "maj"), ("D", "maj"), ("G", "maj")]
    PROG_B = [("C", "maj"), ("G", "maj"), ("A", "min"), ("D", "maj"), ("C", "maj"), ("G", "maj"), ("D", "maj"), ("D", "maj")]
    BARS = PROG_A + PROG_B + PROG_A + PROG_B

N_BARS = len(BARS)
BAR = 4 * BEAT
LOOP_LEN = int(round(N_BARS * BAR * SR))
TAIL = int(6 * SR)
out = np.zeros(LOOP_LEN + TAIL)


def add(sig, t, gain, pan=0.0):
    start = int(round(t * SR))
    end = min(start + len(sig), len(out))
    if end > start:
        out[start:end] += gain * sig[: end - start]


def chord_notes(root, kind, octave=4):
    r = m(root, octave)
    third = 4 if kind == "maj" else 3
    return [r, r + third, r + 7]


def swing(k):
    """Light 16th swing: delay every second sixteenth."""
    return k * S16 + (0.18 * S16 if k % 2 else 0)


# ------------------------------------------------------------------ FUNK: "Jogja Funk"
if MODE == "funk":
    # Bass rhythm per bar (sixteenth index, interval in semitones from root, length in 16ths)
    BASS_A = [(0, 0, 2), (3, 0, 1), (6, 12, 1), (7, 10, 1), (8, 0, 2), (10, 7, 1), (12, 0, 1), (14, 12, 1), (15, 10, 1)]
    BASS_B = [(0, 0, 1), (2, 0, 1), (3, 12, 1), (6, 7, 2), (8, 0, 1), (10, 5, 1), (11, 7, 1), (13, 0, 1), (14, 12, 2)]
    # Saron riff in D major pentatonic (D E F# A B), as (sixteenth in 2-bar phrase, midi)
    D5, E5, FS5, A5, B5, D6, E6 = m("D", 5), m("E", 5), m("F#", 5), m("A", 5), m("B", 5), m("D", 6), m("E", 6)
    A4, B4 = m("A", 4), m("B", 4)
    RIFF_A = [(0, A5), (2, B5), (4, D6), (6, B5), (8, A5), (11, FS5), (12, E5), (14, D5),
              (16, E5), (18, FS5), (20, A5), (22, FS5), (24, E5), (26, D5), (28, B4), (30, D5)]
    RIFF_B = [(0, D6), (3, B5), (4, A5), (6, B5), (8, D6), (10, E6), (12, D6), (14, B5),
              (16, A5), (19, FS5), (20, A5), (22, B5), (24, A5), (26, FS5), (28, E5), (30, FS5)]
    for b, (root, kind) in enumerate(BARS):
        t_bar = b * BAR
        section = (b // 8) % 2  # 0 = A, 1 = B
        last_of_4 = b % 4 == 3
        root_bass = m(root, 2) if NOTE[root] <= NOTE["E"] else m(root, 1)
        # drums: four-on-the-floor kick with koplo kendang on top
        for beat in range(4):
            add(KICK, t_bar + beat * BEAT, 0.3)
            if beat in (1, 3):
                add(CLAP, t_bar + beat * BEAT, 0.42)
        for k in range(16):
            add(HAT, t_bar + swing(k), 0.2 if k % 2 else 0.28)
        add(OPENHAT, t_bar + swing(14), 0.12)
        # kendang koplo: dhut-tak with ketipung chatter
        add(DHUNG, t_bar + swing(0), 0.2)
        add(TAK, t_bar + swing(2), 0.4)
        add(TUNG, t_bar + swing(5), 0.3)
        add(DHUNG, t_bar + swing(7), 0.16)
        add(TAK, t_bar + swing(10), 0.4)
        add(TUNG, t_bar + swing(13), 0.3)
        if last_of_4:  # fill: ketipung run into the next phrase
            for k in (12, 13, 14, 15):
                add(TUNG if k % 2 else TAK, t_bar + swing(k), 0.34)
        # bass
        for (k, iv, ln) in (BASS_A if section == 0 else BASS_B):
            f = midi_hz(root_bass + iv)
            add(funk_bass(f, ln * S16 * 0.95), t_bar + swing(k), 0.2)
        # e-piano stabs on the off-beats
        notes = [midi_hz(n) for n in chord_notes(root, kind, 4)]
        for k in (2, 6, 10, 14) if section == 0 else (2, 5, 8, 10, 14):
            add(epiano(notes, S16 * 1.4), t_bar + swing(k), 0.34)
        # saron riff (2-bar phrases)
        riff = RIFF_A if section == 0 else RIFF_B
        half = b % 2
        for (k, note) in riff:
            if half * 16 <= k < half * 16 + 16:
                add(metal(midi_hz(note), 1.2, 0.5, SARON), t_bar + swing(k - half * 16), 0.36)
        # bonang imbal: interlocking high notes on the off-sixteenths in the B sections
        if section == 1:
            cn = chord_notes(root, kind, 6)
            for k in range(1, 16, 2):
                add(metal(midi_hz(cn[(k // 2) % 3]), 0.5, 0.15, BONANG, 7.0), t_bar + swing(k), 0.09)
        # kenong on beat 1, kempul on beat 3, gong every 8 bars
        add(metal(midi_hz(m(root, 3)), 2.0, 1.0, KENONG, 2.0), t_bar, 0.12)
        add(metal(midi_hz(m(root, 2) + 7), 2.0, 0.9, KENONG, 1.5), t_bar + 2 * BEAT, 0.07)
        if b % 8 == 0:
            add(gong(73.4), t_bar, 0.16)

# ------------------------------------------------------------------ DESA: "Desa Riang"
else:
    G4, A4, B4, D5, E5, G5, A5, B5 = (m("G", 4), m("A", 4), m("B", 4), m("D", 5), m("E", 5), m("G", 5), m("A", 5), m("B", 5))
    D4, E4 = m("D", 4), m("E", 4)
    # Suling melody, 8 bars per line: (beat in phrase, midi, length in beats)
    MEL_A = [(0, D5, 1), (1, E5, 0.5), (1.5, G5, 1.5), (3, E5, 1),
             (4, E5, 0.5), (4.5, D5, 0.5), (5, B4, 1), (6, A4, 2),
             (8, A4, 1), (9, B4, 0.5), (9.5, D5, 1.5), (11, E5, 1),
             (12, D5, 3), (15, B4, 1),
             (16, E5, 1), (17, G5, 0.5), (17.5, A5, 1.5), (19, G5, 1),
             (20, E5, 0.5), (20.5, D5, 0.5), (21, E5, 1), (22, G5, 1), (23, E5, 1),
             (24, D5, 1), (25, B4, 0.5), (25.5, A4, 1.5), (27, B4, 1),
             (28, G4, 4)]
    MEL_B = [(0, G5, 1.5), (1.5, E5, 0.5), (2, G5, 1), (3, A5, 1),
             (4, B5, 2), (6, A5, 1), (7, G5, 1),
             (8, A5, 1.5), (9.5, G5, 0.5), (10, E5, 1), (11, D5, 1),
             (12, E5, 2), (14, D5, 1), (15, E5, 1),
             (16, G5, 1.5), (17.5, E5, 0.5), (18, D5, 1), (19, B4, 1),
             (20, D5, 2), (22, E5, 1), (23, G5, 1),
             (24, A5, 2), (26, G5, 0.5), (26.5, E5, 0.5), (27, D5, 1),
             (28, D5, 2), (30, E5, 1), (31, A4, 1)]
    for b, (root, kind) in enumerate(BARS):
        t_bar = b * BAR
        section = (b // 8) % 2
        # kroncong-style "cello" pizz bass: root on 1, fifth on 2-and, root on 3, approach on 4-and
        r = m(root, 2)
        for (beat, iv, ln) in ((0, 0, 0.9), (1.5, 7, 0.45), (2, 12, 0.9), (3.5, 7, 0.45)):
            add(pluck(midi_hz(r + iv), ln * BEAT, 0.35, 0.25, 6), t_bar + beat * BEAT, 0.32)
        # cak (high, offbeat 8ths) and cuk (chord, interlocking 16ths): the bright kroncong strum
        cn = chord_notes(root, kind, 4)
        cak = [midi_hz(n + 12) for n in cn]
        for k in range(8):
            t = t_bar + k * BEAT / 2
            if k % 2:
                for i, f in enumerate(cak):
                    add(pluck(f, 0.22, 0.7, 0.08, 6), t + i * 0.008, 0.1)
            else:
                add(pluck(midi_hz(cn[(k // 2) % 3] + 12), 0.25, 0.65, 0.1, 6), t + BEAT / 4, 0.08)
        # guitar arpeggio on 8ths, low register
        arp = [cn[0], cn[1], cn[2], cn[1] + 12, cn[2], cn[1], cn[0] + 12, cn[2]]
        for k, n in enumerate(arp):
            add(pluck(midi_hz(n - 12), 0.6, 0.55, 0.3, 8), t_bar + k * BEAT / 2, 0.1)
        # light kendang + shaker
        add(DHUNG, t_bar, 0.18)
        add(TAK, t_bar + BEAT, 0.16)
        add(DHUNG, t_bar + 2.5 * BEAT, 0.14)
        add(TAK, t_bar + 3 * BEAT, 0.16)
        if b % 4 == 3:
            add(TUNG, t_bar + 3.5 * BEAT, 0.14)
            add(TUNG, t_bar + 3.75 * BEAT, 0.14)
        for k in range(8):
            add(SHAKER, t_bar + k * BEAT / 2 + (0.03 if k % 2 else 0), 0.14 if k % 2 else 0.18)
        # peking sparkle on the "and" of 4, gong every 8 bars
        add(metal(midi_hz(cn[2] + 24), 0.8, 0.3, PEKING, 6.0), t_bar + 3.5 * BEAT, 0.05)
        if b % 8 == 0:
            add(gong(98.0), t_bar, 0.16)
    # suling melody over each 8-bar line (A on A sections, B on B sections)
    for line in range(N_BARS // 8):
        mel = MEL_A if line % 2 == 0 else MEL_B
        t_line = line * 8 * BAR
        for (beat, note, ln) in mel:
            add(suling(midi_hz(note), ln * BEAT * 0.96), t_line + beat * BEAT, 0.26)

# ------------------------------------------------------------------ master
loop = out[:LOOP_LEN].copy()
loop[:TAIL] += out[LOOP_LEN:]  # fold tails back so the loop is seamless

spec = np.fft.rfft(loop)
fr = np.fft.rfftfreq(len(loop), 1 / SR)
spec *= 1 / np.sqrt(1 + (40 / np.maximum(fr, 1e-3)) ** 8)  # high-pass ~40 Hz
loop = np.fft.irfft(spec, len(loop))
loop = np.tanh(loop * 1.1) / np.tanh(1.1)  # glue
loop *= 0.89 / np.max(np.abs(loop))

pcm = (np.stack([loop, loop], axis=1) * 32767).astype(np.int16)
with wave.open(OUT_FILE, "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print(f"{MODE}: {N_BARS} bars at {BPM} BPM = {LOOP_LEN / SR:.1f}s, rms={np.sqrt(np.mean(loop ** 2)):.3f}")
