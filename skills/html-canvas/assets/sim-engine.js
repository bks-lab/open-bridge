/*  html-canvas — SIMULATION ENGINE (optional layer, paste-in)
    ============================================================================
    Turns an html-canvas page from a document into a RUNNING MODEL: a clock, a
    stage, controls, a protocol feed. Vanilla, single-file, zero dependencies,
    ES5 syntax so it pastes into any shell without a build step.

    Pair with assets/simulation.css (the visual layer) and one archetype from
    references/simulation.md. Copy this whole file into a <script> at the end of
    <body>; it exposes one global, `Sim`.

    THE ONE RULE THAT SHAPES THE API: the engine never authors user-visible text.
    The shell swaps DE/EN in pure CSS by showing one of two sibling nodes, and a
    string written by JS at runtime has no sibling, so it would freeze in one
    language and silently break the toggle. Therefore every label the engine
    renders arrives as {de:..., en:...} and is written as a PAIR. Language-neutral
    runs (ids, clock times, counts) pass through as plain strings. The single
    sanctioned exception is the four level words in LEVELS below, a closed
    vocabulary the engine owns so a feed row can never lose its second channel.
    ========================================================================== */
(function (global) {
  'use strict';

  var doc = global.document;
  var SVGNS = 'http://www.w3.org/2000/svg';

  function now() {
    return (global.performance && performance.now) ? performance.now() : Date.now();
  }
  function reduced() {
    return !!(global.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  /* -- Level vocabulary -------------------------------------------------------
     Criticality ALWAYS rides two channels: a colour AND a glyph plus a word.
     Colour alone fails for roughly 8 percent of male readers, in print, and in a
     screenshot pasted into a grey slide. Override the wording per deliverable if
     the domain needs other words; never drop a channel. */
  var LEVELS = {
    info: { glyph: '●', de: 'Hinweis',    en: 'note' },
    ok:   { glyph: '✓', de: 'in Ordnung', en: 'ok' },
    warn: { glyph: '▲', de: 'Warnung',    en: 'warning' },
    crit: { glyph: '✖', de: 'kritisch',   en: 'critical' }
  };

  /* -- Bilingual text nodes -------------------------------------------------- */
  /* pair('STM-4471')                  one text node, same in both languages
     pair({de:'Eingang', en:'Intake'}) <span data-de>...</span><span data-en>...</span>
     pair(v, 'tspan')                  the same inside an SVG <text>            */
  function pair(value, tag) {
    var frag = doc.createDocumentFragment();
    if (value === null || value === undefined) return frag;
    if (typeof value !== 'object') {
      frag.appendChild(doc.createTextNode(String(value)));
      return frag;
    }
    ['de', 'en'].forEach(function (l) {
      if (value[l] === null || value[l] === undefined) return;
      var n = tag === 'tspan' ? doc.createElementNS(SVGNS, 'tspan') : doc.createElement('span');
      n.setAttribute('data-' + l, '');
      n.textContent = String(value[l]);
      frag.appendChild(n);
    });
    return frag;
  }

  /* Write a value into an element, skipping the DOM write when it did not change.
     A simulation re-renders every frame; without this cache a dozen counters
     rewrite their text 60 times a second and the browser re-lays-out each time. */
  function put(el, value, tag) {
    if (!el) return;
    var key = (typeof value === 'object' && value !== null)
      ? (value.de + ' ' + value.en) : String(value);
    if (el.__simLast === key) return;
    el.__simLast = key;
    while (el.firstChild) el.removeChild(el.firstChild);
    el.appendChild(pair(value, tag));
  }

  /* -- SVG helpers ----------------------------------------------------------- */
  function svg(tag, attrs, parent) {
    var n = doc.createElementNS(SVGNS, tag);
    if (attrs) for (var k in attrs) if (attrs.hasOwnProperty(k)) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function svgText(parent, x, y, cls, value, anchor) {
    var t = svg('text', { x: x, y: y, 'class': cls || '' }, parent);
    if (anchor) t.setAttribute('text-anchor', anchor);
    put(t, value, 'tspan');
    return t;
  }

  function dist(a, b) { var dx = b[0] - a[0], dy = b[1] - a[1]; return Math.sqrt(dx * dx + dy * dy); }

  /* Orthogonal route through a list of points, corners rounded to `r`.
     Straight lines with square corners read as a wiring diagram; the same points
     with rounded corners read as a route that something travels. */
  function routeD(pts, r) {
    if (!pts || pts.length < 2) return '';
    r = (r === undefined) ? 11 : r;
    var d = 'M ' + pts[0][0] + ' ' + pts[0][1];
    for (var i = 1; i < pts.length - 1; i++) {
      var p = pts[i], a = pts[i - 1], b = pts[i + 1];
      var la = dist(a, p), lb = dist(p, b);
      if (la < 0.5 || lb < 0.5) continue;
      var rr = Math.min(r, la / 2, lb / 2);
      if (rr < 0.6) { d += ' L ' + p[0] + ' ' + p[1]; continue; }
      var ux = (a[0] - p[0]) / la, uy = (a[1] - p[1]) / la;
      var vx = (b[0] - p[0]) / lb, vy = (b[1] - p[1]) / lb;
      d += ' L ' + (p[0] + ux * rr).toFixed(2) + ' ' + (p[1] + uy * rr).toFixed(2);
      d += ' Q ' + p[0] + ' ' + p[1] + ' ' + (p[0] + vx * rr).toFixed(2) + ' ' + (p[1] + vy * rr).toFixed(2);
    }
    var last = pts[pts.length - 1];
    return d + ' L ' + last[0] + ' ' + last[1];
  }

  function ease(t) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }

  /* A point along a route, 0..1, held clear of both ends.
     `inset` keeps a travelling token off the station labels it departs from and
     arrives at: without it the token parks on top of the lettering at both ends
     of every leg, which reads as a rendering fault rather than as a stop. */
  function alongRoute(path, t, inset) {
    var total = path.getTotalLength();
    var head = Math.min((inset && inset[0]) || 0, total * 0.3);
    var tail = Math.min((inset && inset[1]) || 0, total * 0.3);
    var span = Math.max(1, total - head - tail);
    var p = path.getPointAtLength(head + span * Math.max(0, Math.min(1, t)));
    return { x: p.x, y: p.y };
  }

  /* Centre of a drawn shape, in the SVG's own coordinates.
     Positions are MEASURED from the drawing, never computed by distributing
     steps over a route length: a step belongs to a station, and the station sits
     wherever it was actually drawn. A derived position lands between two
     stations the first time the layout moves, which reads as a stall. */
  function centreOf(el, selector) {
    var shape = selector ? (el && el.querySelector(selector)) : el;
    if (!shape || !shape.getBBox) return null;
    var b = shape.getBBox();
    return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
  }

  /* SVG elements have no `hidden` property (it is defined on HTMLElement only),
     and a class rule carrying its own `display` beats the [hidden] attribute.
     Both failures are silent. simulation.css ships the matching rule. */
  function show(el, visible) {
    if (!el) return;
    el.setAttribute('data-shown', visible ? 'yes' : 'no');
  }

  /* -- Seeded randomness ------------------------------------------------------
     A generated stream MUST be reproducible: an unseeded simulation shows a
     different picture on every reload, so a screenshot cannot be re-taken, a
     reviewer cannot point at what they saw, and a defect cannot be repeated.
     One seed constant at the top of the model, and the run is the same run. */
  function rng(seed) {
    var a = seed | 0;
    var f = function () {
      a |= 0; a = a + 0x6D2B79F5 | 0;
      var t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
    f.int = function (lo, hi) { return lo + Math.floor(f() * (hi - lo + 1)); };
    f.pick = function (arr) { return arr[Math.floor(f() * arr.length)]; };
    f.weighted = function (arr, key) {
      key = key || 'w';
      var s = 0, i;
      for (i = 0; i < arr.length; i++) s += arr[i][key];
      var r = f() * s;
      for (i = 0; i < arr.length; i++) { r -= arr[i][key]; if (r <= 0) return arr[i]; }
      return arr[arr.length - 1];
    };
    return f;
  }

  /* -- Clock ------------------------------------------------------------------
     opts.step(dt)   advance the model by dt simulated ms, return truthy when the
                     run is over. Pure model work, no DOM.
     opts.render()   paint the current state. Once per frame, not once per step.
     opts.reset()    return the model to its starting state.
     opts.stepOnce() optional: advance exactly one discrete step (plan entry,
                     message, station hop) for the single-step button.
     opts.onState(s) 'idle' | 'running' | 'paused' | 'done'
     opts.onGuard(n) the run did not finish within `guard` steps. Never silent: a
                     model that cannot terminate is a defect, not a long run. */
  function Clock(opts) {
    var self = this;
    this._step = opts.step;
    this._render = opts.render || function () {};
    this._reset = opts.reset || function () {};
    this._stepOnce = opts.stepOnce || null;
    this._onState = opts.onState || function () {};
    this._onGuard = opts.onGuard || function (n) {
      if (global.console) console.warn('[sim] run did not finish within ' + n + ' steps');
    };
    this.slice = opts.slice || 60;          /* the model never sees a larger dt */
    this.maxCatchUp = opts.maxCatchUp || 1200;
    this.guard = opts.guard || 8000;
    this.speed = opts.speed || 1;
    this.running = false; this.started = false; this.finished = false;
    this._raf = null; this._last = 0;
    this._frame = function () {
      self._raf = null;
      if (!self.running) return;
      self.advance(now());
      if (self.running) self._raf = global.requestAnimationFrame(self._frame);
    };
    /* Second driver on the SAME clock. Browsers throttle requestAnimationFrame
       to a stop whenever a window is not being painted: a background tab, a
       second screen, a shared or remote-controlled desktop. Without this
       watchdog the run freezes in exactly the situation it gets demonstrated in.
       Both drivers read the same wall clock, so no time is counted twice. */
    this._watch = global.setInterval(function () {
      if (self.running) self.advance(now());
    }, 200);
  }

  Clock.prototype.advance = function (ts) {
    if (!this.running) return;
    if (!this._last) { this._last = ts; return; }
    var real = ts - this._last;
    if (real <= 0) return;
    this._last = ts;
    /* No catch-up leap after a long pause: a tab that sat in the background for
       two minutes must resume, not replay the whole run in a single frame. */
    if (real > this.maxCatchUp) real = this.maxCatchUp;
    while (real > 0 && this.running) {
      var s = Math.min(this.slice, real);
      real -= s;
      if (this._step(s * this.speed)) { this._finish(); break; }
    }
    this._render();
  };

  Clock.prototype.start = function () {
    if (this.finished || this.running) return;
    this.started = true; this.running = true; this._last = 0;
    this._onState('running');
    if (!this._raf) this._raf = global.requestAnimationFrame(this._frame);
  };
  Clock.prototype.pause = function () {
    if (!this.running) return;
    this.running = false;
    this._cancel();
    this._onState('paused');
  };
  Clock.prototype.toggle = function () {
    if (this.finished) return;
    if (this.running) this.pause(); else this.start();
  };
  Clock.prototype.setSpeed = function (v) { this.speed = v; };

  Clock.prototype.single = function () {
    if (this.finished || !this._stepOnce) return;
    if (this.running) this.pause();
    this.started = true;
    if (this._stepOnce()) this._finish(); else this._onState('paused');
    this._render();
  };

  /* Compute the whole run without animating it, then paint the end state.
     Three callers, one code path: reduced motion, printing, and the "skip to the
     end" button. A run stopped halfway and printed prints a half-truth. */
  Clock.prototype.runToEnd = function () {
    this.running = false;
    this._cancel();
    this.started = true;
    var g = 0, done = this.finished;
    while (!done && g < this.guard) { done = !!this._step(this.slice); g++; }
    this._render();
    if (done) this._finish(); else this._onGuard(g);
  };

  Clock.prototype.reset = function () {
    this.running = false;
    this._cancel();
    this.started = false; this.finished = false; this._last = 0;
    this._reset();
    this._onState('idle');
    this._render();
  };

  Clock.prototype._finish = function () {
    this.running = false; this.finished = true;
    this._cancel();
    this._onState('done');
  };
  Clock.prototype._cancel = function () {
    if (this._raf) { global.cancelAnimationFrame(this._raf); this._raf = null; }
  };

  /* -- Controls ---------------------------------------------------------------
     Wires the markup from references/simulation.md:
       [data-sim-run] [data-sim-step] [data-sim-end] [data-sim-reset]
       [data-sim-speed] > button[data-speed]
     The run button carries no JS-authored label: it holds one span per state,
     each with its own DE/EN pair, and CSS shows the one matching data-state. */
  function Controls(clock, scope) {
    scope = scope || doc;
    var runBtn = scope.querySelector('[data-sim-run]');
    var stepBtn = scope.querySelector('[data-sim-step]');
    var endBtn = scope.querySelector('[data-sim-end]');
    var resetBtn = scope.querySelector('[data-sim-reset]');
    var seg = scope.querySelector('[data-sim-speed]');

    if (runBtn) runBtn.addEventListener('click', function () { clock.toggle(); });
    if (resetBtn) resetBtn.addEventListener('click', function () { clock.reset(); });
    if (endBtn) endBtn.addEventListener('click', function () { clock.runToEnd(); });
    if (stepBtn) {
      if (clock._stepOnce) stepBtn.addEventListener('click', function () { clock.single(); });
      else stepBtn.parentNode.removeChild(stepBtn);   /* never offer a dead control */
    }

    function speeds() { return seg ? [].slice.call(seg.querySelectorAll('button[data-speed]')) : []; }
    function setSpeed(v) {
      clock.setSpeed(v);
      speeds().forEach(function (b) {
        b.setAttribute('aria-pressed', parseFloat(b.getAttribute('data-speed')) === v ? 'true' : 'false');
      });
    }
    speeds().forEach(function (b) {
      b.addEventListener('click', function () { setSpeed(parseFloat(b.getAttribute('data-speed'))); });
    });

    doc.addEventListener('keydown', function (e) {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      var t = e.target || {};
      if (t.isContentEditable || /^(input|textarea|select)$/i.test(t.tagName || '')) return;
      if (e.code === 'Space') { e.preventDefault(); clock.toggle(); }
      else if (e.key === 'r' || e.key === 'R') { clock.reset(); }
      else if (e.key === 's' || e.key === 'S') { clock.single(); }
      else if (e.key === '1' || e.key === '2' || e.key === '3') {
        var b = speeds()[parseInt(e.key, 10) - 1];
        if (b) setSpeed(parseFloat(b.getAttribute('data-speed')));
      }
    });

    return {
      state: function (s) {
        if (runBtn) {
          runBtn.setAttribute('data-state', s);
          runBtn.disabled = (s === 'done');
          runBtn.classList.toggle('is-idle', s === 'idle');
        }
        if (stepBtn) stepBtn.disabled = (s === 'done');
        if (endBtn) endBtn.disabled = (s === 'done');
      },
      setSpeed: setSpeed
    };
  }

  /* -- Feed (protocol / message stream) ---------------------------------------
     Newest row on top by default: a reader watching a running stream wants the
     latest line where their eye already is, not after a scroll. */
  function Feed(el, opts) {
    opts = opts || {};
    this.el = el;
    this.max = opts.max || 40;
    this.newestFirst = opts.newestFirst !== false;
    this.levels = opts.levels || LEVELS;
  }
  Feed.prototype.push = function (entry) {
    if (!this.el) return null;
    var lv = this.levels[entry.level] || this.levels.info;
    var li = doc.createElement('li');
    li.className = 'sim-feed__row is-new';
    li.setAttribute('data-level', entry.level || 'info');

    var g = doc.createElement('span');
    g.className = 'sim-feed__glyph';
    g.setAttribute('aria-hidden', 'true');
    g.textContent = lv.glyph;
    li.appendChild(g);

    var sr = doc.createElement('span');
    sr.className = 'vh';
    sr.appendChild(pair({ de: lv.de, en: lv.en }));
    li.appendChild(sr);

    if (entry.time !== undefined) {
      var t = doc.createElement('span');
      t.className = 'sim-feed__time';
      t.appendChild(pair(entry.time));
      li.appendChild(t);
    }
    var body = doc.createElement('span');
    body.className = 'sim-feed__body';
    if (entry.where !== undefined) {
      var w = doc.createElement('span');
      w.className = 'sim-feed__where';
      w.appendChild(pair(entry.where));
      body.appendChild(w);
    }
    var x = doc.createElement('span');
    x.className = 'sim-feed__what';
    x.appendChild(pair(entry.what));
    body.appendChild(x);
    li.appendChild(body);

    if (this.newestFirst && this.el.firstChild) this.el.insertBefore(li, this.el.firstChild);
    else this.el.appendChild(li);

    while (this.el.childElementCount > this.max) {
      this.el.removeChild(this.newestFirst ? this.el.lastElementChild : this.el.firstElementChild);
    }
    if (!this.newestFirst) this.el.scrollTop = this.el.scrollHeight;
    return li;
  };
  Feed.prototype.clear = function () {
    if (this.el) while (this.el.firstChild) this.el.removeChild(this.el.firstChild);
  };

  /* -- Packet flight between two DOM anchors (for non-SVG stages) ------------- */
  function flight(layer) {
    var cache = null, seq = 0;
    function box(el) {
      if (!cache) cache = {};
      var key = el.id || el.__simKey || (el.__simKey = 'a' + (++seq));
      if (cache[key]) return cache[key];
      var c = layer.getBoundingClientRect(), a = el.getBoundingClientRect();
      cache[key] = { x: a.left - c.left + a.width / 2, y: a.top - c.top + Math.min(a.height / 2, 46) };
      return cache[key];
    }
    return {
      invalidate: function () { cache = null; },
      send: function (fromEl, toEl, level) {
        if (reduced() || !layer || !fromEl || !toEl) return;
        if (layer.childElementCount > 26) return;      /* a backlog of dots is noise */
        var a = box(fromEl), b = box(toEl);
        var d = doc.createElement('span');
        d.className = 'sim-packet';
        if (level) d.setAttribute('data-level', level);
        d.style.transform = 'translate(' + a.x + 'px,' + a.y + 'px)';
        layer.appendChild(d);
        global.requestAnimationFrame(function () {
          d.style.transform = 'translate(' + b.x + 'px,' + b.y + 'px)';
          d.style.opacity = '0.1';
        });
        global.setTimeout(function () { if (d.parentNode) d.parentNode.removeChild(d); }, 520);
      }
    };
  }

  /* -- Boot -------------------------------------------------------------------
     The three things every simulation must do at load, in one call.
       reduced motion   compute the run, show the end state, reveal the note that
                        says so. "No animation" is not "no content".
       print            same code path, so paper never shows a half-finished run.
       autostart        an unattended page starts itself after a grace period,
                        never under reduced motion (there is nothing to start). */
  function boot(clock, opts) {
    opts = opts || {};
    var note = opts.note ? doc.querySelector(opts.note) : null;
    clock._render();
    if (reduced()) {
      clock.runToEnd();
      if (note) note.hidden = false;
      return;
    }
    global.addEventListener('beforeprint', function () {
      if (!clock.finished) clock.runToEnd();
    });
    if (global.matchMedia) {
      var mq = matchMedia('print');
      if (mq.addEventListener) mq.addEventListener('change', function (e) {
        if (e.matches && !clock.finished) clock.runToEnd();
      });
    }
    if (opts.autostart) {
      global.setTimeout(function () {
        if (!clock.started && !clock.finished) clock.start();
      }, opts.autostart);
    }
  }

  /* Fonts change text metrics, so geometry read from a drawing before the
     webfont lands is measured against the fallback face and is wrong by a few
     pixels in every direction. Measure after the fonts, or do not measure. */
  function afterFonts(fn) {
    if (doc.fonts && doc.fonts.ready && doc.fonts.ready.then) doc.fonts.ready.then(fn);
    else global.setTimeout(fn, 0);
  }

  global.Sim = {
    LEVELS: LEVELS,
    Clock: Clock, Controls: Controls, Feed: Feed,
    pair: pair, put: put,
    svg: svg, svgText: svgText, routeD: routeD, alongRoute: alongRoute,
    centreOf: centreOf, show: show, ease: ease,
    rng: rng, flight: flight, boot: boot, afterFonts: afterFonts,
    reduced: reduced
  };
})(window);
