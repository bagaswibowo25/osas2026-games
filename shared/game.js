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

  return { $, shuffle, show, countdown, finish };
})();
