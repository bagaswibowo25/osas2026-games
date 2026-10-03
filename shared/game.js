// Shared helpers for the booth games: screen switching, countdown, shuffle.
window.Booth = (function () {
  function $(sel) { return document.querySelector(sel); }

  function shuffle(a) {
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }

  // Show exactly one of the ready / play / done screens; stats only while playing.
  function show(phase) {
    ['ready', 'play', 'done'].forEach((p) => { $('#' + p).hidden = p !== phase; });
    $('#stats').hidden = phase !== 'play';
  }

  function fmt(sec) {
    const m = Math.floor(sec / 60), s = sec % 60;
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  // Countdown that renders into #timer and calls onEnd when it hits zero.
  function countdown(seconds, onEnd) {
    let left = seconds;
    const el = $('#timer');
    const paint = () => { el.textContent = fmt(left); el.classList.toggle('low', left <= 10); };
    paint();
    const id = setInterval(() => {
      left -= 1;
      paint();
      if (left <= 0) { clearInterval(id); onEnd(); }
    }, 1000);
    return {
      stop() { clearInterval(id); },
      left() { return left; },
      used() { return seconds - left; }
    };
  }

  function finish(resultLine, prize) {
    $('#result').textContent = resultLine;
    $('#prize').textContent = prize;
    show('done');
  }

  // Prize config lives in config/<game>.json (mounted from the host, editable
  // without a rebuild). Fetched fresh for every new player; falls back to the
  // defaults baked into the page if the file is missing or not valid JSON.
  async function loadConfig(name, defaults) {
    try {
      const r = await fetch('config/' + name + '.json', { cache: 'no-store' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return Object.assign({}, defaults, await r.json());
    } catch (e) {
      console.warn('config/' + name + '.json not usable, using defaults:', e);
      return defaults;
    }
  }

  // rows: [[condition, prize], ...] for the Prizes panel on the ready screen.
  function renderPrizes(rows) {
    const box = $('#prize-rows');
    box.textContent = '';
    rows.forEach(([cond, prize]) => {
      const row = document.createElement('div');
      row.className = 'row';
      const s = document.createElement('span');
      s.textContent = cond;
      const p = document.createElement('strong');
      p.textContent = prize;
      row.append(s, p);
      box.appendChild(row);
    });
  }

  // --- Players and leaderboard ------------------------------------------
  // api/* is proxied by this container's nginx to the admin service.
  async function post(path, body) {
    const r = await fetch('api/' + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || 'Cannot reach the booth server (HTTP ' + r.status + ')');
    return data;
  }

  // The signed-in player ({ name, ig }) lives in this tab's sessionStorage, which every
  // page under /games/ shares, so they sign in once on the hub and keep it across games.
  const KEY = 'booth.player';
  function stored() {
    try { return JSON.parse(sessionStorage.getItem(KEY)); } catch (e) { return null; }
  }
  function remember(p) {
    try { sessionStorage.setItem(KEY, JSON.stringify({ name: p.name, ig: p.ig })); } catch (e) { /* private mode */ }
  }
  function forget() {
    try { sessionStorage.removeItem(KEY); } catch (e) { /* private mode */ }
  }

  // Same rule as the server: letters, numbers, . and _, at most 30; a leading @ is fine.
  const IG_RE = /^[a-z0-9._]{1,30}$/;

  // Sign in (or resume an unfinished session). Throws with a message for the player.
  async function register(rawName, rawIg) {
    const name = rawName.replace(/\s+/g, ' ').trim();
    const ig = rawIg.trim().replace(/^@/, '').toLowerCase();
    if (!name) throw Object.assign(new Error('Please enter your name first.'), { field: 'name' });
    if (!ig) throw Object.assign(new Error('Please enter your Instagram username.'), { field: 'ig' });
    if (!IG_RE.test(ig)) throw Object.assign(new Error('Instagram username can only have letters, numbers, . and _'), { field: 'ig' });
    const state = await post('register', { name, ig });
    remember(state);
    return state;
  }

  // Current player state from the server, or null (and forgotten) if there is none
  // or their turn is over.
  async function current() {
    const p = stored();
    if (!p) return null;
    try { return await register(p.name, p.ig); } catch (e) { forget(); return null; }
  }

  // Game pages: who is playing, or back to the hub to sign in.
  async function requirePlayer() {
    const p = await current();
    if (!p || p.left < 1) { location.replace('../'); return null; }
    const line = $('#player');
    line.textContent = '';
    const b = document.createElement('strong');
    b.textContent = p.name;
    line.append('Playing as ', b, ' · chance ' + (p.plays + 1) + ' of ' + (p.plays + p.left));
    const warn = $('#drop-warn');
    warn.hidden = !p.result;
    if (p.result) warn.textContent = 'Last chance: pressing Start drops your first result (' + p.result.prize + ').';
    return p;
  }

  // Get a one-time token for this round; uses up one chance. Returns null on error.
  async function begin(game) {
    const p = stored();
    if (!p) { location.replace('../'); return null; }
    $('#name-err').textContent = '';
    try {
      const r = await post('start', { game, ig: p.ig });
      return { game, name: p.name, ig: p.ig, token: r.token, attempt: r.attempt, left: r.left };
    } catch (e) {
      $('#name-err').textContent = e.message;
      return null;
    }
  }

  async function submit(session, result) {
    const el = $('#rank');
    const claim = $('#claim'), retry = $('#retry');
    $('#done-actions').hidden = true;
    $('#chance-note').textContent = '';
    el.textContent = 'Saving your score…';
    try {
      const r = await post('finish', Object.assign({ game: session.game, token: session.token }, result));
      if (r.prize) $('#prize').textContent = r.prize;
      el.textContent = r.rank ? session.name + ', you are #' + r.rank + ' of ' + r.players + ' players today.' : '';
    } catch (e) {
      el.textContent = 'Score not saved: ' + e.message;
    }
    // Chances left: take this prize, or drop it and play again. Last chance: just finish.
    retry.hidden = session.left < 1;
    claim.textContent = session.left < 1 ? 'Done, next player' : 'Take this prize';
    $('#chance-note').textContent = session.left < 1 ? 'That was your last chance. Thanks for playing!'
      : 'You have 1 more chance. If you play again, this result is dropped.';
    $('#done-actions').hidden = false;
    claim.focus();
  }

  // Done screen: Take prize closes the session; Play again goes back to the game list.
  // getSession returns the round that just ended.
  function doneButtons(getSession) {
    $('#claim').addEventListener('click', async (ev) => {
      const btn = ev.currentTarget;
      const s = getSession();
      btn.disabled = true;
      try {
        if (s.left > 0) await post('close', { ig: s.ig });
        forget();
        location.href = '../';
      } catch (e) {
        $('#chance-note').textContent = 'Could not finish: ' + e.message + '. Please try again.';
        btn.disabled = false;
      }
    });
    $('#retry').addEventListener('click', () => { location.href = '../'; });
  }

  return { $, shuffle, show, countdown, finish, loadConfig, renderPrizes, post, register, current, forget,
           requirePlayer, begin, submit, doneButtons };
})();
