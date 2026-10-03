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
    $('#again').focus();
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

  return { $, shuffle, show, countdown, finish, loadConfig, renderPrizes };
})();
