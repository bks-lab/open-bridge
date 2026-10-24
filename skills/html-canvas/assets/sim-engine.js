/*  html-canvas: SIMULATION ENGINE (optional layer, paste-in)
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
  /* Own-key test that a key named like an Object builtin cannot shadow. */
  function has(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }

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
    if (attrs) for (var k in attrs) if (has(attrs, k)) n.setAttribute(k, attrs[k]);
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
    /* the generator's whole state is one integer: a snapshot carries it */
    f.save = function () { return a; };
    f.load = function (s) { a = s | 0; };
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
     opts.marker()   optional: a value that changes once per discrete step (plan
                     entry, message, station hop). Enables single step forward
                     and back on the timeline; the step is still made of ticks.
     opts.snapshot() optional, with opts.restore(s): a COPY of the model state,
                     and the way back to it. The clock keeps a ring buffer of
                     them so a seek replays at most a few ticks.
     opts.stepOnce() legacy single step outside the clock. Still honoured, but
                     such a run cannot be replayed, so it gets no timeline.
     opts.seed       optional: the clock owns `clock.random`, a Sim.rng that is
                     reseeded on every reset and restored with every snapshot.
     opts.tick       the fixed quantum of model time in ms (default 20).
     opts.format(ms) the timeline readout (default mm:ss of model time).
     opts.onState(s) 'idle' | 'running' | 'paused' | 'done'
     opts.onGuard(n) the run did not finish within `guard` ticks. Never silent: a
                     model that cannot terminate is a defect, not a long run.

     THE RULE THAT MAKES THE TIMELINE HONEST: the model only ever advances in
     whole ticks of the same size, whatever the frame rate or the speed. The
     state at tick n is then one state, so a scrubbed position, a replay from
     the start and a live run paused at the same tick show the same picture. */
  function Clock(opts) {
    var self = this;
    this._step = opts.step;
    this._render = opts.render || function () {};
    this._reset = opts.reset || function () {};
    this._stepOnce = opts.stepOnce || null;
    this._marker = opts.marker || null;
    this._snapshot = opts.snapshot || null;
    this._restore = opts.restore || null;
    this._format = opts.format || mmss;
    this._onState = opts.onState || function () {};
    this._onGuard = opts.onGuard || function (n) {
      if (global.console) console.warn('[sim] run did not finish within ' + n + ' steps');
    };
    this.tick = opts.tick || opts.slice || 20;  /* `slice` is the older name */
    this.slice = this.tick;
    this.maxCatchUp = opts.maxCatchUp || 1200;
    this.guard = opts.guard || Math.ceil(480000 / this.tick);
    this.speed = opts.speed || 1;
    this.seed = opts.seed;
    this.random = (opts.seed !== undefined) ? rng(opts.seed) : null;
    this.snapEvery = opts.snapEvery || Math.max(1, Math.round(500 / this.tick));
    this.snapKeep = opts.snapKeep || 96;
    this.backTicks = Math.max(1, Math.round((opts.back || 1000) / this.tick));
    /* A model that steps outside the clock cannot be replayed tick by tick. */
    this.replayable = !(this._stepOnce && !this._marker);
    this.running = false; this.started = false; this.finished = false; this.touched = false;
    this.ticks = 0; this.state = 'idle';
    this._budget = 0; this._ring = []; this._ringAt = {}; this._marks = {}; this._length = null;
    this._lastMark = this._marker ? this._marker() : null;
    this._listeners = [];
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

  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function mmss(ms) {
    var s = Math.floor(ms / 1000);
    return pad2(Math.floor(s / 60)) + ':' + pad2(s % 60);
  }

  /* listeners hear every repaint and every state change (the timeline uses it) */
  Clock.prototype.on = function (fn) { this._listeners.push(fn); };
  Clock.prototype._emit = function () {
    for (var i = 0; i < this._listeners.length; i++) this._listeners[i](this);
  };
  Clock.prototype.paint = function () { this._render(); this._emit(); };
  Clock.prototype._setState = function (s) { this.state = s; this._onState(s); this._emit(); };
  Clock.prototype.time = function () { return this.ticks * this.tick; };
  Clock.prototype.format = function (ms) { return this._format(ms === undefined ? this.time() : ms); };

  /* One tick of model time: the only place the model is advanced. */
  Clock.prototype._advanceOne = function () {
    var done = !!this._step(this.tick);
    this.ticks += 1;
    if (this._marker) {
      var m = this._marker();
      if (m !== this._lastMark) { this._lastMark = m; this._marks[this.ticks] = true; }
    }
    if (this._snapshot && this._restore && this.ticks % this.snapEvery === 0) this._remember();
    if (done) this._length = this.ticks;
    return done;
  };

  /* Ring buffer: the newest `snapKeep` snapshots, oldest dropped first. A seek
     before the oldest one replays from the start, which is slower, never wrong. */
  Clock.prototype._remember = function () {
    if (this._ringAt[this.ticks]) return;
    var e = { tick: this.ticks, data: this._snapshot(), mark: this._lastMark,
              rng: this.random ? this.random.save() : null };
    this._ring.push(e); this._ringAt[e.tick] = e;
    while (this._ring.length > this.snapKeep) delete this._ringAt[this._ring.shift().tick];
  };
  Clock.prototype.ring = function () { return this._ring.slice(); };
  /* Drop everything learned about the run: call it when the model changed
     (a scenario or control value), never for a plain reset. */
  Clock.prototype.forget = function () {
    this._ring = []; this._ringAt = {}; this._marks = {}; this._length = null;
  };

  Clock.prototype._hardReset = function () {
    this._reset();
    this.ticks = 0; this._budget = 0; this.finished = false;
    if (this.seed !== undefined) this.random = rng(this.seed);
    this._lastMark = this._marker ? this._marker() : null;
  };

  /* Bring the model to tick n without painting or changing the run state. */
  Clock.prototype._seekRaw = function (n) {
    var best = null, i;
    for (i = 0; i < this._ring.length; i++) {
      var e = this._ring[i];
      if (e.tick <= n && (!best || e.tick > best.tick)) best = e;
    }
    seeking = true;
    try {
      var forward = this.ticks <= n && (!best || best.tick <= this.ticks);
      if (!forward) {
        if (best) {
          this._restore(best.data);
          this.ticks = best.tick; this._budget = 0; this.finished = false;
          if (this.random && best.rng !== null) this.random.load(best.rng);
          this._lastMark = best.mark;
        } else {
          this._hardReset();
        }
      }
      var g = 0;
      while (this.ticks < n && !this.finished && g < this.guard) {
        if (this._advanceOne()) this.finished = true;
        g++;
      }
      /* A snapshot taken at the last tick restores an unfinished run: the end
         is known from the dry run, so Play never steps the model past it. */
      if (!this.finished && this._length !== null && this.ticks >= this._length) this.finished = true;
    } finally { seeking = false; }
  };

  /* Ticks in the whole run. Computed once by a dry run that also fills the
     ring buffer, then the model is put back where it was. */
  Clock.prototype.length = function () {
    if (this._length !== null) return this._length;
    if (!this.replayable) return null;
    var keep = this.ticks, g = 0, done = false;
    seeking = true;
    try {
      this._hardReset();
      while (!done && g < this.guard) { done = this._advanceOne(); g++; }
    } finally { seeking = false; }
    if (!done) { this._onGuard(g); this._length = this.ticks; }
    this._seekRaw(keep);
    this._render();
    return this._length;
  };

  /* Jump to tick n and stay there, paused. */
  Clock.prototype.seek = function (n) {
    if (!this.replayable) return;
    this.touched = true;
    var len = this.length();
    n = Math.max(0, Math.floor(+n || 0));
    if (len !== null && n > len) n = len;
    this.running = false;
    this._cancel();
    this._seekRaw(n);
    this.started = this.ticks > 0;
    this._render();
    this._setState(this.finished ? 'done' : (this.ticks ? 'paused' : 'idle'));
  };

  /* One discrete step back: to the previous marker change, or one model second. */
  Clock.prototype.back = function () {
    if (!this.replayable || this.ticks === 0) return;
    var target = 0;
    if (this._marker) {
      this.length();                       /* the dry run has seen every marker */
      for (var k in this._marks) if (has(this._marks, k)) {
        var t = +k;
        if (t < this.ticks && t > target) target = t;
      }
    } else {
      target = Math.max(0, this.ticks - this.backTicks);
    }
    this.seek(target);
  };

  Clock.prototype.advance = function (ts) {
    if (!this.running) return;
    if (!this._last) { this._last = ts; return; }
    var real = ts - this._last;
    if (real <= 0) return;
    this._last = ts;
    /* No catch-up leap after a long pause: a tab that sat in the background for
       two minutes must resume, not replay the whole run in a single frame. */
    if (real > this.maxCatchUp) real = this.maxCatchUp;
    this._budget += real * this.speed;
    while (this._budget >= this.tick && this.running) {
      this._budget -= this.tick;
      if (this._advanceOne()) { this._finish(); break; }
    }
    this.paint();
  };

  Clock.prototype.start = function () {
    if (this.finished || this.running) return;
    this.started = true; this.running = true; this._last = 0;
    this._setState('running');
    if (!this._raf) this._raf = global.requestAnimationFrame(this._frame);
  };
  Clock.prototype.pause = function () {
    if (!this.running) return;
    this.running = false;
    this._cancel();
    this._setState('paused');
  };
  Clock.prototype.toggle = function () {
    if (this.finished) return;
    this.touched = true;
    if (this.running) this.pause(); else this.start();
  };
  Clock.prototype.setSpeed = function (v) { this.speed = v; };

  Clock.prototype.single = function () {
    if (this.finished) return;
    if (this._marker) {
      this.touched = true;
      if (this.running) { this.running = false; this._cancel(); }
      this.started = true;
      var m0 = this._marker(), g = 0, done = false;
      while (!done && this._marker() === m0 && g < this.guard) { done = this._advanceOne(); g++; }
      this._render();
      if (done) this._finish(); else this._setState('paused');
      return;
    }
    if (!this._stepOnce) return;
    this.touched = true;
    if (this.running) this.pause();
    this.started = true;
    if (this._stepOnce()) this._finish(); else this._setState('paused');
    this.paint();
  };

  /* Compute the whole run without animating it, then paint the end state.
     Three callers, one code path: reduced motion, printing, and the "skip to the
     end" button. A run stopped halfway and printed prints a half-truth. */
  Clock.prototype.runToEnd = function () {
    this.running = false;
    this._cancel();
    this.started = true;
    var g = 0, done = this.finished;
    seeking = true;
    try {
      while (!done && g < this.guard) { done = this._advanceOne(); g++; }
    } finally { seeking = false; }
    this._render();
    if (done) this._finish(); else { this._onGuard(g); this._emit(); }
  };

  Clock.prototype.reset = function () {
    this.running = false;
    this._cancel();
    this.started = false; this._last = 0;
    this._hardReset();
    this._render();
    this._setState('idle');
  };

  Clock.prototype._finish = function () {
    this.running = false; this.finished = true;
    this._cancel();
    this._setState('done');
  };
  Clock.prototype._cancel = function () {
    if (this._raf) { global.cancelAnimationFrame(this._raf); this._raf = null; }
  };

  /* -- Controls ---------------------------------------------------------------
     Wires the markup from references/simulation.md:
       [data-sim-run] [data-sim-step] [data-sim-back] [data-sim-end] [data-sim-reset]
       [data-sim-speed] > button[data-speed]
       [data-sim-scrub] (input type=range) + [data-sim-scrub-time]
       [data-sim-copy-link] + [data-sim-link]
     The run button carries no JS-authored label: it holds one span per state,
     each with its own DE/EN pair, and CSS shows the one matching data-state.
     Every one of them is optional; a control the model cannot serve is removed,
     never left dead. */
  function Controls(clock, scope) {
    scope = scope || doc;
    var runBtn = scope.querySelector('[data-sim-run]');
    var stepBtn = scope.querySelector('[data-sim-step]');
    var backBtn = scope.querySelector('[data-sim-back]');
    var endBtn = scope.querySelector('[data-sim-end]');
    var resetBtn = scope.querySelector('[data-sim-reset]');
    var seg = scope.querySelector('[data-sim-speed]');
    var scrub = scope.querySelector('[data-sim-scrub]');
    var scrubTime = scope.querySelector('[data-sim-scrub-time]');
    var copyBtn = scope.querySelector('[data-sim-copy-link]');
    var linkOut = scope.querySelector('[data-sim-link]');

    function drop(el) { if (el && el.parentNode) el.parentNode.removeChild(el); }

    if (runBtn) runBtn.addEventListener('click', function () { clock.toggle(); });
    if (resetBtn) resetBtn.addEventListener('click', function () { clock.touched = true; clock.reset(); });
    if (endBtn) endBtn.addEventListener('click', function () { clock.touched = true; clock.runToEnd(); });
    if (stepBtn) {
      if (clock._stepOnce || clock._marker) stepBtn.addEventListener('click', function () { clock.single(); });
      else drop(stepBtn);   /* never offer a dead control */
    }
    if (!clock.replayable) {
      drop(backBtn); backBtn = null;
      if (scrub) drop(scrub.closest ? (scrub.closest('[data-sim-timeline]') || scrub) : scrub);
      scrub = null; scrubTime = null;
    }
    if (backBtn) backBtn.addEventListener('click', function () { clock.back(); });
    if (scrub) {
      scrub.min = '0'; scrub.step = '1';
      scrub.addEventListener('input', function () { clock.seek(parseInt(scrub.value, 10) || 0); });
    }

    function speeds() { return seg ? [].slice.call(seg.querySelectorAll('button[data-speed]')) : []; }
    var pressed = speeds().filter(function (b) { return b.getAttribute('aria-pressed') === 'true'; })[0];
    var defSpeed = pressed ? parseFloat(pressed.getAttribute('data-speed')) : clock.speed;
    function setSpeed(v, quiet) {
      clock.setSpeed(v);
      speeds().forEach(function (b) {
        b.setAttribute('aria-pressed', parseFloat(b.getAttribute('data-speed')) === v ? 'true' : 'false');
      });
      if (!quiet) url.write();
    }
    speeds().forEach(function (b) {
      b.addEventListener('click', function () { setSpeed(parseFloat(b.getAttribute('data-speed'))); });
    });
    if (seg) {
      url.add(function () { return clock.speed !== defSpeed ? [['speed', String(clock.speed)]] : []; });
      var hs = url.parse().speed;
      if (hs !== undefined && speeds().some(function (b) { return b.getAttribute('data-speed') === hs; })) {
        setSpeed(parseFloat(hs), true);
      } else {
        setSpeed(defSpeed, true);
      }
    }

    if (copyBtn) {
      copyBtn.setAttribute('data-state', 'idle');
      if (linkOut) linkOut.hidden = true;
      copyBtn.addEventListener('click', function () {
        var href = link(clock);
        var timer = null;
        function copied() {
          copyBtn.setAttribute('data-state', 'copied');
          if (linkOut) linkOut.value = href;
          if (timer) global.clearTimeout(timer);
          timer = global.setTimeout(function () { copyBtn.setAttribute('data-state', 'idle'); }, 2400);
        }
        /* No clipboard (an old browser, a denied permission): show the link,
           selected, so the reader can copy it by hand. */
        function manual() {
          copyBtn.setAttribute('data-state', 'manual');
          if (!linkOut) return;
          linkOut.value = href; linkOut.hidden = false;
          try { linkOut.focus(); linkOut.select(); } catch (err) { /* not focusable */ }
        }
        function legacy() {
          var ok = false;
          try {
            var ta = doc.createElement('textarea');
            ta.value = href; ta.setAttribute('readonly', '');
            ta.style.position = 'fixed'; ta.style.opacity = '0';
            doc.body.appendChild(ta); ta.select();
            ok = doc.execCommand && doc.execCommand('copy');
            doc.body.removeChild(ta);
          } catch (err) { ok = false; }
          if (ok) copied(); else manual();
        }
        try {
          if (global.navigator && navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(href).then(copied, legacy);
          } else legacy();
        } catch (err) { legacy(); }
      });
    }

    var lastText = null;
    clock.on(function () {
      if (backBtn) backBtn.disabled = clock.ticks === 0;
      if (!scrub) return;
      var len = clock._length !== null ? clock._length : clock.length();
      if (String(len) !== scrub.max) scrub.max = String(len);
      if (String(clock.ticks) !== scrub.value) scrub.value = String(clock.ticks);
      var text = clock.format() + ' / ' + clock.format(len * clock.tick);
      if (text !== lastText) {
        lastText = text;
        scrub.setAttribute('aria-valuetext', text);
        if (scrubTime) scrubTime.textContent = text;
      }
    });

    doc.addEventListener('keydown', function (e) {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      var t = e.target || {};
      if (t.isContentEditable || /^(input|textarea|select)$/i.test(t.tagName || '')) return;
      /* Space already activates a focused button, link or summary. Taking it here
         would run the clock AND press the control, so those keep the key. */
      if (e.code === 'Space') {
        if (t.closest && t.closest('button,a[href],summary,[role="button"]')) return;
        e.preventDefault(); clock.toggle();
      }
      else if (e.key === 'r' || e.key === 'R') { clock.touched = true; clock.reset(); }
      else if (e.key === 's' || e.key === 'S' || e.key === 'ArrowRight') { clock.single(); }
      else if (e.key === 'ArrowLeft') { clock.back(); }
      else if (e.key === '1' || e.key === '2' || e.key === '3') {
        var b = speeds()[parseInt(e.key, 10) - 1];
        if (b) setSpeed(parseFloat(b.getAttribute('data-speed')));
      }
    });

    clock._emit();
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
    this._log = [];
  }
  Feed.prototype.push = function (entry) {
    if (!this.el) return null;
    var lv = this.levels[entry.level] || this.levels.info;
    var li = doc.createElement('li');
    li.className = seeking ? 'sim-feed__row' : 'sim-feed__row is-new';
    this._log.push(entry);
    if (this._log.length > this.max) this._log.shift();
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
    this._log = [];
    if (this.el) while (this.el.firstChild) this.el.removeChild(this.el.firstChild);
  };
  /* For a model's snapshot(): the rows as data, oldest first, and the way back. */
  Feed.prototype.snapshot = function () { return this._log.slice(); };
  Feed.prototype.restore = function (rows) {
    this.clear();
    var was = seeking;
    seeking = true;
    try { for (var i = 0; i < rows.length; i++) this.push(rows[i]); } finally { seeking = was; }
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

  /* -- Stage: the child side of the stage contract ------------------------------
     A simulation embedded in a slide runs inside an iframe that the slide's
     stage module owns (html-slides/assets/slide-stage.js is that parent side).
     The two talk through postMessage, and the full contract lives in
     references/simulation.md, "Embedding in a slide". This side:
       posts  stage:ready     once Sim.boot has painted the first frame
              stage:key       for the few keys the PARENT owns (see FORWARD)
              stage:maximize  when [data-sim-maximize] is pressed
       hears  stage:restart   reset the run in place, then start it again
              stage:maximize  the parent reports {on: bool}; mirrored on <html>
              stage:theme     {theme: 'dark'|'light'} and
              stage:lang      {lang: 'de'|'en'}: the slide's theme and language,
                              applied without storing a choice (see "Stage look")
     Framed, the page marks <html data-sim-embedded="yes">; simulation.css hides
     the page's own toolbar then, because theme, language and print belong to
     the slide around it.
     A page opened on its own (window.parent === window) posts nothing, hears
     nothing and removes its maximize button: a control without a stage to
     enlarge would be a dead control.
     Every incoming message is checked against window.parent. A frame next to
     this one can post here too, and srcdoc and file:// pages have no origin to
     compare, so the window itself is the only reliable check. The target
     origin on the way out is '*' for the same reason; the messages carry no
     data that a foreign listener could misuse. */
  var stage = (function () {
    var embedded = false;
    try { embedded = !!global.parent && global.parent !== global; } catch (err) { embedded = false; }
    var clock = null, readySent = false;
    /* Keys the deck needs while focus sits inside the frame: V toggles the
       large stage, Escape leaves it, PageDown and PageUp are what presentation
       clickers send, T and L are the slide's theme and language (the frame
       follows the slide and stores no choice of its own). Space, R, S and the
       digits stay with the simulation. */
    var FORWARD = { v: 'v', V: 'v', Escape: 'Escape', PageDown: 'PageDown', PageUp: 'PageUp',
                    t: 't', T: 't', l: 'l', L: 'l' };

    function post(type, extra) {
      if (!embedded) return;
      var msg = { type: type };
      if (extra) for (var k in extra) if (has(extra, k)) msg[k] = extra[k];
      try { global.parent.postMessage(msg, '*'); } catch (err) { /* parent gone */ }
    }

    function reflect(on) {
      doc.documentElement.setAttribute('data-sim-maximized', on ? 'yes' : 'no');
      [].forEach.call(doc.querySelectorAll('[data-sim-maximize]'), function (b) {
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
    }

    function wireButtons() {
      [].forEach.call(doc.querySelectorAll('[data-sim-maximize]'), function (b) {
        if (!embedded) { if (b.parentNode) b.parentNode.removeChild(b); return; }
        b.hidden = false;
        b.setAttribute('aria-pressed', 'false');
        b.addEventListener('click', function () { post('stage:maximize'); });
      });
    }

    if (embedded) {
      doc.documentElement.setAttribute('data-sim-embedded', 'yes');
      global.addEventListener('message', function (e) {
        if (e.source !== global.parent) return;
        var d = e.data;
        if (!d || typeof d !== 'object') return;
        if (d.type === 'stage:restart' && clock) {
          clock.reset();
          if (reduced()) clock.runToEnd(); else clock.start();
        } else if (d.type === 'stage:maximize' && typeof d.on === 'boolean') {
          reflect(d.on);
        }
      });
      /* Capture on the window, so the page's own T and L handlers (the shell's,
         which would flip only the frame and store the choice) never see them. */
      global.addEventListener('keydown', function (e) {
        if (e.metaKey || e.ctrlKey || e.altKey) return;
        var t = e.target || {};
        if (t.isContentEditable || /^(input|textarea|select)$/i.test(t.tagName || '')) return;
        var key = FORWARD[e.key];
        if (!key) return;
        if (key === 'PageDown' || key === 'PageUp') e.preventDefault();
        if (key === 't' || key === 'l') { e.preventDefault(); e.stopPropagation(); }
        post('stage:key', { key: key });
      }, true);
    }
    if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', wireButtons);
    else wireButtons();

    return {
      embedded: embedded,
      post: post,
      /* Called by Sim.boot. A page with its own boot calls it itself. */
      ready: function (c) {
        if (c) clock = c;
        if (readySent) return;
        readySent = true;
        post('stage:ready', { contract: 1, title: doc.title || '' });
      },
      maximize: function () { post('stage:maximize'); }
    };
  })();

  /* -- Boot -------------------------------------------------------------------
     The things every simulation must do at load, in one call.
       a position     a link with #t=<tick> opens paused at that tick and never
                      starts by itself: somebody wants to show exactly that moment.
       reduced motion compute the run, show the end state, reveal the note that
                      says so. "No animation" is not "no content". Nothing starts
                      by itself afterwards either; step, back and the scrubber
                      move through the run, play only on an explicit press.
       print          same code path, so paper never shows a half-finished run.
       autostart      an unattended page starts itself after a grace period,
                      never under reduced motion, never once the reader has
                      touched a control. */
  function boot(clock, opts) {
    opts = opts || {};
    Sim.active = { clock: clock, params: opts.params || null };
    var note = opts.note ? doc.querySelector(opts.note) : null;
    var t = url.parse().t;
    t = (t !== undefined && /^\d+$/.test(t)) ? parseInt(t, 10) : 0;
    clock.paint();
    global.addEventListener('beforeprint', function () {
      if (!clock.finished) clock.runToEnd();
    });
    if (global.matchMedia) {
      var mq = matchMedia('print');
      if (mq.addEventListener) mq.addEventListener('change', function (e) {
        if (e.matches && !clock.finished) clock.runToEnd();
      });
    }
    if (t > 0 && clock.replayable) {
      clock.seek(t);
      stage.ready(clock);
      return;
    }
    if (reduced()) {
      clock.runToEnd();
      if (note) note.hidden = false;
      stage.ready(clock);
      return;
    }
    stage.ready(clock);
    if (opts.autostart) {
      global.setTimeout(function () {
        if (!clock.started && !clock.finished && !clock.touched && !reduced()) clock.start();
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

  /* -- Seeking flag -------------------------------------------------------------
     True while the clock replays ticks it does not paint (a seek, a dry run, a
     fast-forward). Decoration that only makes sense live, such as the entry
     animation of a feed row, checks it. */
  var seeking = false;

  /* -- URL hash: scenario and control values ------------------------------------
     A simulation is worth pointing at: "look at tick 340 with a capacity of 2".
     Values live in the hash as #name=value&..., only where they differ from the
     default, so an untouched page keeps a clean address. A hash without "=" is
     an ordinary anchor and is left alone. Sources register a function that
     returns [[name, value], ...] for whatever they own (Sim.params, the speed). */
  var url = (function () {
    var sources = [];
    function parse() {
      /* No prototype: a name such as hasOwnProperty or __proto__ in a link is
         a plain key here, never a builtin. */
      var out = Object.create(null), h = String(global.location && global.location.hash || '').replace(/^#/, '');
      if (h.indexOf('=') < 0) return out;
      h.split('&').forEach(function (kv) {
        var i = kv.indexOf('=');
        if (i < 1) return;
        try { out[decodeURIComponent(kv.slice(0, i))] = decodeURIComponent(kv.slice(i + 1)); }
        catch (err) { /* a malformed escape is ignored, not fatal */ }
      });
      return out;
    }
    function encode(list) {
      return list.map(function (p) {
        return encodeURIComponent(p[0]) + '=' + encodeURIComponent(p[1]);
      }).join('&');
    }
    function pairs() {
      var all = [];
      sources.forEach(function (f) { all = all.concat(f()); });
      return all;
    }
    function base() { return String(global.location.href).split('#')[0]; }
    function write() {
      var h = encode(pairs());
      try {
        global.history.replaceState(global.history.state, '', h ? '#' + h : base());
      } catch (err) {
        /* srcdoc and some sandboxed frames refuse replaceState; the page still
           works, only the address does not follow. */
      }
    }
    return {
      parse: parse, write: write, encode: encode, base: base, pairs: pairs,
      add: function (f) { sources.push(f); }
    };
  })();

  /* The address of exactly this view: every non-default value plus the current
     position on the timeline. What "copy link" copies. */
  function link(clock) {
    clock = clock || (Sim.active && Sim.active.clock);
    var list = url.pairs();
    if (clock && clock.replayable && clock.ticks > 0) list.push(['t', String(clock.ticks)]);
    var h = url.encode(list);
    return url.base() + (h ? '#' + h : '');
  }

  /* -- Scenario and control values ----------------------------------------------
     var P = Sim.params({
       approach: { value: 3, min: 1, max: 5 },              // number
       scenario: { value: 'rework', options: ['rework', 'clean'] },
       seed:     { value: 42 }                              // reseeds clock.random
     });
     P.get(name)  P.set(name, v)  P.on(fn(name, v))  P.bind(clock)
     Markup: [data-sim-param="name"] on a <select>, an <input> (range, number,
     checkbox) or a group of button[data-value]; [data-sim-param-out="name"]
     shows a number. The hash is read once, here, so the model's first blank()
     already sees the restored values. An invalid value in the hash is ignored
     and the default kept. "speed" and "t" are taken by the engine. */
  function Params(defs) {
    var self = this;
    this.defs = defs; this.names = []; this.values = {}; this._fns = [];
    var h = url.parse();
    for (var n in defs) if (has(defs, n)) {
      if (n === 'speed' || n === 't') throw new Error('[sim] param name "' + n + '" is reserved');
      this.names.push(n);
      this.values[n] = defs[n].value;
      if (has(h, n)) {
        var v = this._coerce(n, h[n]);
        if (v !== undefined) this.values[n] = v;
      }
    }
    url.add(function () {
      return self.names.filter(function (k) { return self.values[k] !== self.defs[k].value; })
        .map(function (k) { return [k, String(self.values[k])]; });
    });
    if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', function () { self._wire(); });
    else this._wire();
  }
  Params.prototype._coerce = function (name, raw) {
    var d = this.defs[name], s = String(raw);
    if (d.options) {
      for (var i = 0; i < d.options.length; i++) if (String(d.options[i]) === s) return d.options[i];
      return undefined;
    }
    if (typeof d.value === 'boolean') {
      if (s === '1' || s === 'true') return true;
      if (s === '0' || s === 'false') return false;
      return undefined;
    }
    if (typeof d.value === 'number') {
      if (!/^-?\d+(\.\d+)?$/.test(s)) return undefined;
      var x = parseFloat(s);
      if (d.min !== undefined && x < d.min) return undefined;
      if (d.max !== undefined && x > d.max) return undefined;
      if (Math.floor(d.value) === d.value && d.integer !== false && Math.floor(x) !== x) return undefined;
      return x;
    }
    return s;
  };
  Params.prototype.get = function (name) { return this.values[name]; };
  Params.prototype.on = function (fn) { this._fns.push(fn); };
  Params.prototype.set = function (name, raw) {
    if (!has(this.defs, name)) return false;
    var v = this._coerce(name, raw);
    if (v === undefined) { this._sync(); return false; }
    if (v === this.values[name]) { this._sync(); return true; }
    this.values[name] = v;
    this._sync();
    url.write();
    for (var i = 0; i < this._fns.length; i++) this._fns[i](name, v);
    return true;
  };
  /* A changed value is a different model: the run is forgotten and reset. */
  Params.prototype.bind = function (clock) {
    var self = this;
    if (this.defs.seed) clock.seed = this.values.seed;
    this.on(function (name, v) {
      if (name === 'seed') clock.seed = v;
      clock.forget();
      clock.reset();
    });
    return this;
  };
  Params.prototype._els = function () {
    return [].slice.call(doc.querySelectorAll('[data-sim-param]'));
  };
  Params.prototype._sync = function () {
    var self = this;
    this._els().forEach(function (el) {
      var n = el.getAttribute('data-sim-param');
      if (!has(self.defs, n)) return;
      var v = self.values[n];
      if (/^(select|input)$/i.test(el.tagName)) {
        if (el.type === 'checkbox') el.checked = !!v; else el.value = String(v);
      } else {
        [].forEach.call(el.querySelectorAll('button[data-value]'), function (b) {
          b.setAttribute('aria-pressed', b.getAttribute('data-value') === String(v) ? 'true' : 'false');
        });
      }
    });
    [].forEach.call(doc.querySelectorAll('[data-sim-param-out]'), function (o) {
      var n = o.getAttribute('data-sim-param-out');
      if (has(self.defs, n)) put(o, String(self.values[n]));
    });
  };
  Params.prototype._wire = function () {
    var self = this;
    this._els().forEach(function (el) {
      var n = el.getAttribute('data-sim-param');
      if (!has(self.defs, n)) return;
      if (/^(select|input)$/i.test(el.tagName)) {
        el.addEventListener('change', function () {
          self.set(n, el.type === 'checkbox' ? el.checked : el.value);
        });
        /* a range shows its value while it moves, the model changes on release */
        if (el.type === 'range') el.addEventListener('input', function () {
          [].forEach.call(doc.querySelectorAll('[data-sim-param-out="' + n + '"]'), function (o) { put(o, el.value); });
        });
      } else {
        [].forEach.call(el.querySelectorAll('button[data-value]'), function (b) {
          b.addEventListener('click', function () { self.set(n, b.getAttribute('data-value')); });
        });
      }
    });
    this._sync();
  };
  function params(defs) { return new Params(defs); }

  /* -- State as a table ---------------------------------------------------------
     The text alternative for a stage: the same state as rows and columns, for a
     screen reader, a reader who wants the numbers, and a page pasted into a
     document. Hidden until its toggle is pressed; while hidden it costs nothing.
       var table = new Sim.Table(document.getElementById('simTable'), {
         columns: [{de: 'Vorgang', en: 'Item'}, ...],
         rows: function () { return [[id, {de, en}, ...], ...]; }
       });
       call table.render() at the end of the model's render().
     The toggle is a [data-sim-table-toggle] button whose aria-controls names the
     element that is shown and hidden (the table or a wrapper around it). Its
     label is one span per state, data-state-off and data-state-on. */
  function Table(el, opts) {
    var self = this;
    this.el = el; this.rows = opts.rows; this.columns = opts.columns || [];
    if (!el) return;
    var thead = el.querySelector('thead') || el.insertBefore(doc.createElement('thead'), el.firstChild);
    var tr = doc.createElement('tr');
    this.columns.forEach(function (c) {
      var th = doc.createElement('th');
      th.setAttribute('scope', 'col');
      th.appendChild(pair(c));
      tr.appendChild(th);
    });
    while (thead.firstChild) thead.removeChild(thead.firstChild);
    thead.appendChild(tr);
    this.body = el.querySelector('tbody') || el.appendChild(doc.createElement('tbody'));
    var box = null, btn = null;
    [].forEach.call(doc.querySelectorAll('[data-sim-table-toggle]'), function (b) {
      var target = doc.getElementById(b.getAttribute('aria-controls') || '');
      if (target && (target === el || target.contains(el))) { btn = b; box = target; }
    });
    this.box = box || el;
    this.box.hidden = true;
    if (btn) {
      btn.setAttribute('aria-expanded', 'false');
      btn.setAttribute('data-state', 'off');
      btn.addEventListener('click', function () { self.show(self.box.hidden); });
    }
    this.btn = btn;
  }
  Table.prototype.show = function (on) {
    this.box.hidden = !on;
    if (this.btn) {
      this.btn.setAttribute('aria-expanded', on ? 'true' : 'false');
      this.btn.setAttribute('data-state', on ? 'on' : 'off');
    }
    if (on) this.render();
  };
  Table.prototype.render = function () {
    if (!this.el || this.box.hidden) return;
    var rows = this.rows() || [], body = this.body, i, j;
    while (body.childElementCount > rows.length) body.removeChild(body.lastElementChild);
    for (i = 0; i < rows.length; i++) {
      var tr = body.children[i];
      if (!tr) { tr = doc.createElement('tr'); body.appendChild(tr); }
      for (j = 0; j < rows[i].length; j++) {
        var td = tr.children[j];
        if (!td) { td = doc.createElement(j === 0 ? 'th' : 'td'); if (j === 0) td.setAttribute('scope', 'row'); tr.appendChild(td); }
        put(td, rows[i][j]);
      }
      while (tr.childElementCount > rows[i].length) tr.removeChild(tr.lastElementChild);
    }
  };

  /* -- Stage look: stage:theme and stage:lang, child side -----------------------
     The slide owns the theme and the language. It posts stage:theme {theme:
     'dark'|'light'} and stage:lang {lang: 'de'|'en'} on every change and once
     after stage:ready, and the frame follows. The choice is the slide's, so it
     is NOT stored: a standalone visit to the same page keeps its own preference.
     The shell's controllers already follow a `storage` event for cross-tab sync;
     dispatching one (without writing storage) relabels the T and L buttons and
     the aria labels through the shell's own code. Same source check as every
     other stage message. */
  (function () {
    if (!stage.embedded) return;
    var root = doc.documentElement;
    function nudge(key, value) {
      try { global.dispatchEvent(new StorageEvent('storage', { key: key, newValue: value })); }
      catch (err) { /* no StorageEvent constructor: attributes are set anyway */ }
    }
    global.addEventListener('message', function (e) {
      if (e.source !== global.parent) return;
      var d = e.data;
      if (!d || typeof d !== 'object') return;
      if (d.type === 'stage:theme' && (d.theme === 'dark' || d.theme === 'light')) {
        root.classList.toggle('dark', d.theme === 'dark');
        nudge('html-canvas-theme', d.theme);
      } else if (d.type === 'stage:lang' && (d.lang === 'de' || d.lang === 'en')) {
        root.setAttribute('data-lang', d.lang);
        root.setAttribute('lang', d.lang);
        nudge('html-canvas-lang', d.lang);
        if (typeof global.hcApplyAria === 'function') global.hcApplyAria();
      }
    });
  })();

  var Sim = global.Sim = {
    LEVELS: LEVELS,
    Clock: Clock, Controls: Controls, Feed: Feed, Table: Table,
    params: params, link: link, url: url,
    seeking: function () { return seeking; },
    active: null,
    pair: pair, put: put,
    svg: svg, svgText: svgText, routeD: routeD, alongRoute: alongRoute,
    centreOf: centreOf, show: show, ease: ease,
    rng: rng, flight: flight, boot: boot, afterFonts: afterFonts,
    reduced: reduced, stage: stage
  };
})(window);
