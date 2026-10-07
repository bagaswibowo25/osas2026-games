// Confetti for the winners: one canvas over the page, no libraries.
// Confetti.burst(x, y, n) from a point, Confetti.cannons() from both bottom corners, Confetti.rain(ms) from the top.
window.Confetti = (function () {
  const COLORS = ['#73ba25', '#35b9ab', '#21a4df', '#f5c400', '#ec6fb0', '#a77be8', '#ffffff', '#f2a65a'];
  const MAX = 700;
  const calm = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  let cv = null, ctx = null, parts = [], raf = 0, last = 0, rainUntil = 0;

  function ensure() {
    if (cv) return;
    cv = document.createElement('canvas');
    cv.setAttribute('aria-hidden', 'true');
    cv.style.cssText = 'position:fixed;inset:0;width:100%;height:100%;pointer-events:none;z-index:50';
    document.body.appendChild(cv);
    ctx = cv.getContext('2d');
    resize();
    addEventListener('resize', resize);
  }
  function resize() {
    const d = Math.min(2, devicePixelRatio || 1);
    cv.width = innerWidth * d; cv.height = innerHeight * d;
    ctx.setTransform(d, 0, 0, d, 0, 0);
  }
  function piece(x, y, angle, speed) {
    if (parts.length >= MAX) return;
    const s = Math.min(innerWidth, innerHeight) / 90;
    parts.push({
      x, y, vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed,
      w: s * (0.8 + Math.random() * 0.8), h: s * (1.4 + Math.random() * 1.2),
      color: COLORS[Math.floor(Math.random() * COLORS.length)], round: Math.random() < 0.25,
      rot: Math.random() * 6.28, vr: (Math.random() - 0.5) * 12, wob: Math.random() * 6.28
    });
  }
  function start() {
    ensure();
    if (!raf) { last = performance.now(); raf = requestAnimationFrame(frame); }
  }
  function frame(t) {
    const dt = Math.min(0.05, (t - last) / 1000);
    last = t;
    if (t < rainUntil) for (let k = 0; k < 4; k++) piece(Math.random() * innerWidth, -20, Math.PI / 2, 60 + Math.random() * 80);
    const g = innerHeight * 0.9;
    ctx.clearRect(0, 0, innerWidth, innerHeight);
    parts = parts.filter((p) => {
      p.vy += g * dt; p.vx *= 0.985; p.vy *= 0.985;
      p.vy = Math.min(p.vy, innerHeight * 0.35);  // flutter down instead of dropping
      p.wob += dt * 6; p.rot += p.vr * dt;
      p.x += (p.vx + Math.sin(p.wob) * 40) * dt; p.y += p.vy * dt;
      ctx.save();
      ctx.translate(p.x, p.y); ctx.rotate(p.rot);
      ctx.scale(1, Math.abs(Math.cos(p.wob)) * 0.8 + 0.2);
      ctx.fillStyle = p.color;
      if (p.round) { ctx.beginPath(); ctx.arc(0, 0, p.w * 0.6, 0, 6.28); ctx.fill(); } else ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
      ctx.restore();
      return p.y < innerHeight + 40;
    });
    if (parts.length || t < rainUntil) raf = requestAnimationFrame(frame);
    else { raf = 0; ctx.clearRect(0, 0, innerWidth, innerHeight); }
  }
  const scale = (n) => Math.round(calm ? n / 4 : n);

  return {
    burst(x, y, n) {
      start();
      const v = Math.min(innerWidth, innerHeight);
      for (let k = 0; k < scale(n || 90); k++) piece(x, y, Math.random() * 6.28, v * (0.4 + Math.random() * 0.9));
    },
    cannons(n) {
      start();
      const v = Math.min(innerWidth, innerHeight);
      for (let k = 0; k < scale(n || 120); k++) {
        piece(0, innerHeight, -Math.PI / 2 + 0.25 + Math.random() * 0.55, v * (1 + Math.random() * 0.9));
        piece(innerWidth, innerHeight, -Math.PI / 2 - 0.25 - Math.random() * 0.55, v * (1 + Math.random() * 0.9));
      }
    },
    rain(ms) {
      if (calm) return;
      start();
      rainUntil = Math.max(rainUntil, performance.now() + (ms || 4000));
    }
  };
})();
