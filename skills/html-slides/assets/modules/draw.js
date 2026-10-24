/* deck module: draw (reference/modules.md, section "Module: draw").
   Key D draws on the active slide (pen in the accent token, H marker, Z undo,
   C clears the slide, Shift+C every slide, Esc leaves), key Q shows a laser pointer.
   Strokes are kept per slide in slide coordinates while the deck is open, so they
   survive navigation, a resize and a theme switch (they take the new accent).
   Nothing is added to the page until D, Q or a data-deck="draw|laser" button is used.
   window.SlideDeckDraw = {mode(), tool(), strokes(i), setMode(m), clear(all)}. */
(function () {
  'use strict';
  var D = window.SlideDeck;
  if (!D || typeof D.use !== 'function') return;

  /* i18n:start */
  var TEXT = {
    de: { draw: 'Zeichnen', pen: 'Stift', marker: 'Marker',
          hint: 'C löscht · Z rückgängig · H Stift oder Marker · Esc beendet' },
    en: { draw: 'Drawing', pen: 'pen', marker: 'marker',
          hint: 'C clears · Z undo · H pen or marker · Esc leaves' }
  };
  var HELP = [
    { key: 'D Esc', de: 'Auf der Folie zeichnen, Esc beendet', en: 'Draw on the slide, Esc leaves' },
    { key: 'C Shift+C', de: 'Beim Zeichnen: Folie oder alle Folien löschen', en: 'While drawing: clear this slide or every slide' },
    { key: 'Z H', de: 'Beim Zeichnen: rückgängig, Stift oder Marker', en: 'While drawing: undo, pen or marker' },
    { key: 'Q', de: 'Laserpointer an oder aus', en: 'Laser pointer on or off' }
  ];
  /* i18n:end */
  var PEN = 0.005, MARKER = 0.028, MARKER_ALPHA = 0.35;   /* widths as a share of the slide height */
  var TRAIL_MS = 260, TRAIL_MAX = 12;

  var root = document.documentElement;
  var mode = 'off', tool = 'pen';
  var sheets = new Map();          /* slide -> {slide, canvas, strokes, colour, queued} */
  var live = null;                 /* {sheet, stroke, id} while a pointer is down */
  var badge = null, laser = null, trailNodes = [], trail = [], trailRaf = 0, quietTimer = 0;
  var pointer = null;              /* last pointer position, for the laser to start there */

  function text() { return TEXT[D.state().lang] || TEXT.en; }
  function active() { return D.slides()[D.current()] || null; }
  function frame(fn) { return (window.requestAnimationFrame || function (f) { return setTimeout(f, 16); })(fn); }

  /* ============ sheets: one canvas per slide that has been drawn on ============ */
  function sheet(slide, create) {
    var s = sheets.get(slide);
    if (s || !create || !slide) return s || null;
    var c = document.createElement('canvas');
    c.className = 'deck-draw';
    c.setAttribute('aria-hidden', 'true');
    slide.appendChild(c);
    s = { slide: slide, canvas: c, strokes: [], colour: null, queued: false };
    sheets.set(slide, s);
    bindCanvas(s);
    return s;
  }

  /* The accent as the slide resolves it, through a probe, so any colour syntax works. */
  function colourOf(s) {
    if (s.colour) return s.colour;
    var p = document.createElement('span');
    p.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden;color:var(--accent)';
    s.slide.appendChild(p);
    s.colour = getComputedStyle(p).color || getComputedStyle(s.slide).color;
    s.slide.removeChild(p);
    return s.colour;
  }

  function fit(s) {
    var dpr = window.devicePixelRatio || 1;
    var w = Math.max(1, Math.round(s.slide.clientWidth * dpr)), h = Math.max(1, Math.round(s.slide.clientHeight * dpr));
    if (s.canvas.width !== w) s.canvas.width = w;
    if (s.canvas.height !== h) s.canvas.height = h;
  }

  function paint(s) {
    s.queued = false;
    fit(s);
    var c = s.canvas, ctx = c.getContext('2d'), W = c.width, H = c.height;
    ctx.clearRect(0, 0, W, H);
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = ctx.fillStyle = colourOf(s);
    s.strokes.forEach(function (st) {
      var pts = st.pts, lw = Math.max(1, H * (st.tool === 'marker' ? MARKER : PEN) * st.w);
      ctx.globalAlpha = st.tool === 'marker' ? MARKER_ALPHA : 1;
      if (pts.length === 1) {
        ctx.beginPath();
        ctx.arc(pts[0][0] * W, pts[0][1] * H, lw / 2, 0, Math.PI * 2);
        ctx.fill();
        return;
      }
      /* one path per stroke, so a translucent marker does not darken where it overlaps itself */
      ctx.lineWidth = lw;
      ctx.beginPath();
      ctx.moveTo(pts[0][0] * W, pts[0][1] * H);
      for (var i = 1; i < pts.length - 1; i++) {
        var mx = (pts[i][0] + pts[i + 1][0]) / 2, my = (pts[i][1] + pts[i + 1][1]) / 2;
        ctx.quadraticCurveTo(pts[i][0] * W, pts[i][1] * H, mx * W, my * H);
      }
      var l = pts[pts.length - 1];
      ctx.lineTo(l[0] * W, l[1] * H);
      ctx.stroke();
    });
    ctx.globalAlpha = 1;
  }
  function queue(s) { if (s && !s.queued) { s.queued = true; frame(function () { paint(s); }); } }
  function paintAll(reset) { sheets.forEach(function (s) { if (reset) s.colour = null; queue(s); }); }

  function point(s, e) {
    var r = s.canvas.getBoundingClientRect();
    return [(e.clientX - r.left) / (r.width || 1), (e.clientY - r.top) / (r.height || 1)];
  }

  function bindCanvas(s) {
    var c = s.canvas;
    c.addEventListener('pointerdown', function (e) {
      if (mode !== 'draw' || s.slide !== active() || (e.pointerType === 'mouse' && e.button !== 0)) return;
      e.preventDefault();
      try { c.setPointerCapture(e.pointerId); } catch (err) { /* capture is a nicety */ }
      /* a stylus sets the width by pressure; mouse and touch report a flat 0.5 or 0 */
      var st = { tool: tool, pts: [point(s, e)], w: 1, pen: e.pointerType === 'pen', sum: 0, n: 0 };
      if (st.pen) { st.sum = e.pressure || 0.5; st.n = 1; st.w = 0.5 + st.sum; }
      s.strokes.push(st);
      live = { sheet: s, stroke: st, id: e.pointerId };
      queue(s);
    });
    c.addEventListener('pointermove', function (e) {
      if (!live || live.sheet !== s || e.pointerId !== live.id) return;
      var list = typeof e.getCoalescedEvents === 'function' ? e.getCoalescedEvents() : [];
      if (!list.length) list = [e];
      list.forEach(function (ev) {
        live.stroke.pts.push(point(s, ev));
        if (live.stroke.pen) { live.stroke.sum += ev.pressure || 0.5; live.stroke.n++; live.stroke.w = 0.5 + live.stroke.sum / live.stroke.n; }
      });
      queue(s);
    });
    var end = function (e) { if (live && live.sheet === s && e.pointerId === live.id) { live = null; queue(s); } };
    c.addEventListener('pointerup', end);
    c.addEventListener('pointercancel', end);
    /* a vertical stroke on a touch screen must not reach the engine's swipe */
    var keep = function (e) { if (mode === 'draw') e.stopPropagation(); };
    c.addEventListener('touchstart', keep, { passive: true });
    c.addEventListener('touchend', keep);
  }

  function strokesOf(i) { var s = sheet(D.slides()[i], false); return s ? s.strokes.length : 0; }
  function clear(all) {
    live = null;
    sheets.forEach(function (s) { if (all || s.slide === active()) { s.strokes = []; paint(s); } });
  }
  function undo() {
    var s = sheet(active(), false);
    if (!s || !s.strokes.length) return;
    if (live && live.sheet === s) live = null;
    s.strokes.pop();
    paint(s);
  }

  /* ============ badge: says the mode and its keys, then steps back ============ */
  function renderBadge() {
    if (!badge) return;
    var t = text();
    badge.textContent = '';
    var b = document.createElement('strong');
    b.textContent = t.draw + ' · ' + (tool === 'marker' ? t.marker : t.pen);
    badge.appendChild(b);
    badge.appendChild(document.createTextNode(' ' + t.hint));
  }
  function showBadge(on) {
    if (on && !badge) {
      badge = document.createElement('div');
      badge.className = 'deck-draw-badge';
      badge.setAttribute('role', 'status');
      document.body.appendChild(badge);
    }
    if (!badge) return;
    badge.hidden = !on;
    badge.classList.remove('is-quiet');
    clearTimeout(quietTimer);
    if (!on) return;
    renderBadge();
    quietTimer = setTimeout(function () { badge.classList.add('is-quiet'); }, 2500);
  }

  /* ============ laser ============ */
  function placeLaser() {
    if (!laser) return;
    laser.hidden = !(mode === 'laser' && pointer);
    if (!laser.hidden) { laser.style.left = pointer.x + 'px'; laser.style.top = pointer.y + 'px'; }
  }
  function renderTrail() {
    trailRaf = 0;
    var now = Date.now();
    trail = trail.filter(function (p) { return now - p.t < TRAIL_MS; });
    trailNodes.forEach(function (n, i) {
      var p = trail[trail.length - 1 - i];
      n.hidden = !p;
      if (!p) return;
      var k = 1 - (now - p.t) / TRAIL_MS;
      n.style.left = p.x + 'px';
      n.style.top = p.y + 'px';
      n.style.opacity = String(0.55 * k);
      n.style.transform = 'translate(-50%, -50%) scale(' + (0.35 + 0.55 * k) + ')';
    });
    if (trail.length) trailRaf = frame(renderTrail);
  }
  function addTrail(x, y) {
    if (D.reducedMotion()) return;
    while (trailNodes.length < TRAIL_MAX) {
      var n = document.createElement('div');
      n.className = 'deck-laser-trail';
      n.setAttribute('aria-hidden', 'true');
      n.hidden = true;
      document.body.appendChild(n);
      trailNodes.push(n);
    }
    trail.push({ x: x, y: y, t: Date.now() });
    if (trail.length > TRAIL_MAX) trail.shift();
    if (!trailRaf) trailRaf = frame(renderTrail);
  }
  function dropTrail() { trail = []; trailNodes.forEach(function (n) { n.hidden = true; }); }

  /* ============ modes ============ */
  function setMode(m) {
    if (m !== 'draw' && m !== 'laser') m = 'off';
    if (m === mode) return;
    if (mode === 'draw') { live = null; root.classList.remove('deck-drawing'); }
    if (mode === 'laser') { root.classList.remove('deck-laser-on'); dropTrail(); }
    mode = m;
    if (m === 'draw') { root.classList.add('deck-drawing'); queue(sheet(active(), true)); }
    if (m === 'laser') {
      if (!laser) {
        laser = document.createElement('div');
        laser.className = 'deck-laser';
        laser.setAttribute('aria-hidden', 'true');
        document.body.appendChild(laser);
      }
      root.classList.add('deck-laser-on');
    }
    placeLaser();
    showBadge(m === 'draw');
  }
  function toggle(m) { setMode(mode === m ? 'off' : m); }
  /* the read module shows the deck as a document: no drawing there (deckread:change) */
  function reading() { return root.classList.contains('deck-read'); }
  document.addEventListener('deckread:change', function (e) { if (e.detail && e.detail.read) setMode('off'); });

  window.SlideDeckDraw = {
    mode: function () { return mode; },
    tool: function () { return tool; },
    strokes: strokesOf,
    setMode: setMode,
    clear: clear
  };

  D.use({
    name: 'draw',
    keys: {
      d: function () { if (reading()) return false; toggle('draw'); return true; },
      q: function () { if (reading()) return false; toggle('laser'); return true; },
      escape: function () {
        if (mode === 'off') return false;
        /* the engine's Esc closes what lies on top first: the help, a zoom */
        var help = document.querySelector('.deck-help');
        if ((help && !help.hidden) || document.documentElement.classList.contains('deck-zoomed')) return false;
        setMode('off');
        return true;
      },
      c: function (e) { if (mode !== 'draw') return false; clear(!!(e && e.shiftKey)); return true; },
      z: function () { if (mode !== 'draw') return false; undo(); return true; },
      h: function () { if (mode !== 'draw') return false; tool = tool === 'pen' ? 'marker' : 'pen'; showBadge(true); return true; }
    },
    help: HELP,
    init: function (api) {
      api.on('slidechange', function () {
        live = null;
        if (mode === 'draw') queue(sheet(active(), true));
      });
      api.on('themechange', function () { paintAll(true); });
      api.on('langchange', renderBadge);
      window.addEventListener('resize', function () { paintAll(false); });
      document.addEventListener('pointermove', function (e) {
        pointer = { x: e.clientX, y: e.clientY };
        if (mode !== 'laser') return;
        placeLaser();
        addTrail(e.clientX, e.clientY);
      }, { passive: true });
      document.addEventListener('pointerout', function (e) {
        if (e.relatedTarget) return;
        pointer = null;
        placeLaser();
      }, { passive: true });
      document.addEventListener('click', function (e) {
        var b = e.target && e.target.closest ? e.target.closest('[data-deck="draw"], [data-deck="laser"]') : null;
        if (!b || reading()) return;
        toggle(b.getAttribute('data-deck'));
        e.preventDefault();
      });
    }
  });
})();
