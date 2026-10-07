// Host screen audio: original loops (CC0, made by standing/music/*.py) plus Web Audio effects.
// Three styles, switchable on the host screen: congdut (default), keroncong and funk.
// "quiz" plays during questions and mini games, "calm" in the lobby, results and between rounds.
// Usage: Sound.music('quiz' | 'calm' | null), Sound.tick(), Sound.urgent(), Sound.timesUp(), ...
window.Sound = (function () {
  const FX_KEY = 'lgs_host_fx_muted';
  const MUSIC_KEY = 'lgs_host_music_muted';
  const STYLE_KEY = 'lgs_host_music_style';
  // loop = exact musical length; the MP3 has a few ms of encoder padding after it
  const STYLES = {
    congdut: {
      label: 'Congdut',
      quiz: { url: 'static/music/congdut-koplo.mp3', volume: 0.36, loop: 32 * 4 * 60 / 132 },
      calm: { url: 'static/music/congdut-santai.mp3', volume: 0.3, loop: 32 * 4 * 60 / 108 }
    },
    keroncong: {
      label: 'Keroncong',
      quiz: { url: 'static/music/keroncong-rancak-134.mp3', volume: 0.36, loop: 32 * 4 * 60 / 134 },
      calm: { url: 'static/music/langgam-senja-108.mp3', volume: 0.3, loop: 32 * 4 * 60 / 108 }
    },
    funk: {
      label: 'Funk',
      quiz: { url: 'static/music/jogja-funk.mp3', volume: 0.38, loop: 64.0 },
      calm: { url: 'static/music/desa-riang.mp3', volume: 0.32, loop: 32 * 4 * 60 / 104 }
    }
  };
  let style = (function () { try { return STYLES[localStorage.getItem(STYLE_KEY)] ? localStorage.getItem(STYLE_KEY) : 'congdut'; } catch (e) { return 'congdut'; } })();
  const TRACKS = {};
  Object.keys(STYLES).forEach((st) => { TRACKS[st + ':quiz'] = STYLES[st].quiz; TRACKS[st + ':calm'] = STYLES[st].calm; });
  let ctx = null;
  const buffers = {}, loading = {}, offsets = {};
  let source = null, gain = null, playing = null, startedAt = 0, wanted = null;

  function getCtx() {
    try {
      if (!ctx) {
        const C = window.AudioContext || window.webkitAudioContext;
        if (!C) return null;
        ctx = new C();
      }
      if (ctx.state === 'suspended') ctx.resume();
      return ctx;
    } catch (e) { return null; }
  }
  function flag(key) { try { return localStorage.getItem(key) === '1'; } catch (e) { return false; } }
  function setFlag(key, on) { try { localStorage.setItem(key, on ? '1' : '0'); } catch (e) { /* not persisted */ } }

  function tone(freq, dur, type, vol, delay, slideTo) {
    if (flag(FX_KEY)) return;
    const ac = getCtx();
    if (!ac) return;
    const t = ac.currentTime + (delay || 0);
    const o = ac.createOscillator(), g = ac.createGain();
    o.type = type;
    o.frequency.setValueAtTime(freq, t);
    if (slideTo) o.frequency.exponentialRampToValueAtTime(slideTo, t + dur);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(vol, t + 0.01);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(ac.destination);
    o.start(t);
    o.stop(t + dur + 0.05);
  }

  function load(track) {
    const ac = getCtx();
    if (!ac) return Promise.resolve(null);
    if (buffers[track]) return Promise.resolve(buffers[track]);
    if (!loading[track]) {
      loading[track] = fetch(TRACKS[track].url)
        .then((r) => r.arrayBuffer())
        .then((d) => ac.decodeAudioData(d))
        .then((b) => (buffers[track] = b))
        .catch(() => { delete loading[track]; return null; });
    }
    return loading[track];
  }

  function stop(fade) {
    if (!source || !ctx) return;
    const now = ctx.currentTime, f = fade == null ? 0.6 : fade;
    const buf = buffers[playing];
    if (buf) offsets[playing] = (now - startedAt) % Math.min(TRACKS[playing].loop, buf.duration);
    gain.gain.cancelScheduledValues(now);
    gain.gain.setValueAtTime(Math.max(gain.gain.value, 0.0001), now);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + f);
    source.stop(now + f + 0.05);
    source = gain = playing = null;
  }

  async function music(role) {
    wanted = role;
    const track = role ? style + ':' + role : null;
    if (playing === track) return;
    if (playing) stop(0.5);
    if (!track || flag(MUSIC_KEY)) return;
    const buf = await load(track);
    if (!buf || wanted !== role || style + ':' + role !== track || playing || flag(MUSIC_KEY)) return;
    const ac = getCtx();
    const src = ac.createBufferSource(), g = ac.createGain(), now = ac.currentTime;
    src.buffer = buf; src.loop = true;
    src.loopStart = 0; src.loopEnd = Math.min(TRACKS[track].loop, buf.duration);
    g.gain.setValueAtTime(0.0001, now);
    g.gain.exponentialRampToValueAtTime(TRACKS[track].volume, now + 0.8);
    src.connect(g).connect(ac.destination);
    const off = (offsets[track] || 0) % Math.min(TRACKS[track].loop, buf.duration);
    src.start(now, off);
    startedAt = now - off;
    source = src; gain = g; playing = track;
  }

  return {
    unlock: () => { getCtx(); load(style + ':calm'); load(style + ':quiz'); },
    styleLabel: () => STYLES[style].label,
    nextStyle: () => {
      const names = Object.keys(STYLES);
      style = names[(names.indexOf(style) + 1) % names.length];
      try { localStorage.setItem(STYLE_KEY, style); } catch (e) { /* not persisted */ }
      const w = wanted;
      stop(0.4);
      if (w) music(w);
      return STYLES[style].label;
    },
    music: music,
    fxMuted: () => flag(FX_KEY),
    musicMuted: () => flag(MUSIC_KEY),
    setFxMuted: (on) => setFlag(FX_KEY, on),
    setMusicMuted: (on) => {
      setFlag(MUSIC_KEY, on);
      const w = wanted;
      if (on) { stop(0.3); wanted = w; } else if (w) { music(w); }
    },
    tick: () => tone(1400, 0.04, 'square', 0.04),
    urgent: () => { tone(880, 0.14, 'square', 0.12); tone(1320, 0.1, 'sine', 0.08, 0.02); },
    timesUp: () => { tone(784, 0.25, 'triangle', 0.3); tone(587, 0.3, 'triangle', 0.3, 0.2); tone(392, 0.7, 'triangle', 0.32, 0.42); },
    // Geeko tumbling off: a few falling whistles
    fall: () => { for (let i = 0; i < 4; i++) tone(900 - i * 90, 0.55, 'sine', 0.1, i * 0.12, 180); },
    survive: () => { tone(523, 0.15, 'triangle', 0.2); tone(659, 0.15, 'triangle', 0.2, 0.12); tone(784, 0.3, 'triangle', 0.22, 0.24); },
    // Kendang-style roll before the winners
    roll: () => { for (let i = 0; i < 24; i++) tone(140 + (i % 2) * 40, 0.08, 'triangle', 0.05 + i * 0.008, i * 0.07); },
    // Countdown: kendang "dhut" plus a rising beep for 3, 2, 1, then a bright START chord
    count: (step) => {
      tone(190, 0.32, 'sine', 0.5, 0, 70);
      tone([659, 784, 988][step] || 659, 0.2, 'square', 0.1, 0.01);
      tone(([659, 784, 988][step] || 659) * 2, 0.16, 'sine', 0.07, 0.01);
    },
    go: () => {
      tone(150, 0.45, 'sine', 0.6, 0, 55);
      [784, 988, 1175, 1568].forEach((f, i) => tone(f, 0.18, 'square', 0.07, i * 0.06));
      tone(1568, 0.9, 'triangle', 0.26, 0.24); tone(1175, 0.9, 'triangle', 0.2, 0.24); tone(784, 1.0, 'sine', 0.22, 0.24);
      for (let i = 0; i < 6; i++) tone(2400 - i * 250, 0.12, 'sine', 0.05, 0.3 + i * 0.05, 3200);
    },
    fanfare: () => {
      [523, 659, 784, 1047].forEach((f, i) => tone(f, 0.22, 'triangle', 0.26, i * 0.14));
      tone(1047, 0.9, 'triangle', 0.3, 0.6); tone(784, 0.9, 'sine', 0.18, 0.6);
    }
  };
})();
