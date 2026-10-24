/* slide-engine v2 */
/* Scroll-snap presentation engine for single-file HTML decks.
   Contract (reference/slide-types.md, section "Engine contract"):
   - Slides are .slide inside .deck. Options sit on .deck or <html> (deck wins):
     data-tracks-default, data-tracks-cycle, data-deck-id, data-counter-format="padded",
     data-dots="off", data-back-href, data-back-label, data-deep-link="off",
     data-tracks-labels="<name>=<label> ..." (what the track badge shows for a name).
   - API: window.SlideDeck = {goTo(i), next(), prev(), current(), count(), setTrack(name),
     track(), trackLabel(), on(event, fn), toggleTheme(), toggleNotes(), toggleHelp(), strings()}.
     Indexes are 0-based positions among the slides the active track shows.
     Events: "ready", "slidechange" {index, count, slide}, "trackchange" {track, label, count},
     also dispatched on document as "slidedeck:<event>".
     The old names window.slideEngine and window.__slideEngine point at the one engine instance.
   - Buttons: data-deck="next|prev|theme|notes|help|track|track:<name>|goto:<n>|goto:#<id>",
     where goto:<n> is the 1-based slide number the counter shows. A track:<name> button
     carries aria-pressed, true while its track is the active one.
   - Tracks: data-track on a slide (old decks: data-spur), several names separated by spaces.
     A slide without one belongs to every track. Key F cycles.
   - Notes: <aside class="notes"> inside a slide, key N shows them in a panel.
   - Tracks named only by data-tracks-default or data-tracks-cycle exist too; they show
     the untagged slides.
   - Deep link: #<slide id> when the active slide has an id, else #<n> (1-based among the
     slides the track shows); both are read, kept current with history.replaceState. */
(function () {
  'use strict';

  /* i18n:start */
  var STRINGS = {
    en: {
      slide: 'Slide', status: 'Slide {n} of {m}', goTo: 'Go to slide {n}',
      theme: 'Toggle light or dark theme', themeTitle: 'Toggle theme (T)',
      back: 'Back', notes: 'Speaker notes', noNotes: 'No notes on this slide.',
      track: 'Track', allTracks: 'all slides', help: 'Keyboard shortcuts',
      hint: 'arrows, space or scroll · ? help',
      keyNext: 'Next slide', keyPrev: 'Previous slide', keyEnds: 'First or last slide',
      keyTheme: 'Light or dark theme', keyTrack: 'Switch track', keyNotes: 'Speaker notes',
      keyHelp: 'Show or hide this help', keyClose: 'Close a panel',
      keyStage: 'Enlarge or restore the live stage'
    },
    de: {
      slide: 'Folie', status: 'Folie {n} von {m}', goTo: 'Zu Folie {n}',
      theme: 'Hell oder dunkel umschalten', themeTitle: 'Darstellung umschalten (T)',
      back: 'Zurück', notes: 'Sprechernotizen', noNotes: 'Zu dieser Folie gibt es keine Notizen.',
      track: 'Spur', allTracks: 'alle Folien', help: 'Tastenkürzel',
      hint: 'Pfeile, Leertaste oder Scrollen · ? Hilfe',
      keyNext: 'Nächste Folie', keyPrev: 'Vorige Folie', keyEnds: 'Erste oder letzte Folie',
      keyTheme: 'Hell oder dunkel', keyTrack: 'Spur wechseln', keyNotes: 'Notizen zeigen',
      keyHelp: 'Hilfe zeigen oder schließen', keyClose: 'Panel schließen',
      keyStage: 'Live-Bühne vergrößern oder zurück'
    }
  };
  /* i18n:end */

  var root = document.documentElement;
  var instance = null;
  var listeners = {};
  var IGNORE = 'input, textarea, select, [contenteditable]:not([contenteditable="false"]), [data-key-ignore], .table-scroll, .code-scroll';
  var ACTIVATES = 'button, a[href], summary, [role="button"]';

  function fill(s, n, m) { return String(s).replace('{n}', n).replace('{m}', m); }
  function el(tag, cls, parent) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (parent) parent.appendChild(e);
    return e;
  }
  function tracksOf(s) { return (s.getAttribute('data-track') || s.getAttribute('data-spur') || '').split(/[\s,]+/).filter(Boolean); }
  function slideOf(node) { return node ? (node.classList.contains('slide') ? node : node.closest('.slide')) : null; }
  function reducedMotion() { return !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches); }
  function storeGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function storeSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage blocked */ } }
  function emit(ev, detail) {
    (listeners[ev] || []).slice().forEach(function (fn) {
      try { fn(detail); } catch (err) { setTimeout(function () { throw err; }); }
    });
    try { document.dispatchEvent(new CustomEvent('slidedeck:' + ev, { detail: detail })); } catch (e) { /* old browser */ }
  }

  function SlideEngine() {
    if (instance) return instance;
    instance = this;
    window.slideEngine = window.__slideEngine = this;
    this.deck = document.querySelector('.deck') || document.body;
    this.all = [].slice.call(document.querySelectorAll('.slide'));
    this.slides = this.all.slice();
    this.total = this.slides.length;
    this.current = 0;
    this.pending = null;
    this.ready = false;
    var lang = (root.getAttribute('lang') || 'en').toLowerCase().split('-')[0];
    this.t = STRINGS[lang] || STRINGS.en;
    this.padded = this.opt('data-counter-format') === 'padded';
    this.deepLink = this.opt('data-deep-link') !== 'off';
    this.initTracks();
    this.markSlides();
    this.buildChrome();
    this.bindEvents();
    this.observe();
    this.applyTrack(true);
    this.ready = true;
    if (!this.fromHash(true)) this.update();
    emit('ready', api);
  }

  SlideEngine.prototype.opt = function (name) {
    var v = this.deck && this.deck.getAttribute ? this.deck.getAttribute(name) : null;
    return v == null ? root.getAttribute(name) : v;
  };

  /* ============ tracks ============ */
  SlideEngine.prototype.initTracks = function () {
    var names = [];
    var add = function (n) { if (n && n !== 'all' && names.indexOf(n) < 0) names.push(n); };
    this.all.forEach(function (s) { tracksOf(s).forEach(add); });
    this.trackDefault = this.opt('data-tracks-default') || '';
    this.trackKey = 'slide-track:' + (this.opt('data-deck-id') || location.pathname);
    var cycle = (this.opt('data-tracks-cycle') || '').split(/[\s,]+/).filter(Boolean);
    /* A track the deck names (default or cycle) exists even when no slide names it:
       untagged slides belong to every track, so it shows those. */
    add(this.trackDefault);
    cycle.forEach(add);
    this.trackNames = names;
    if (!cycle.length) cycle = this.trackDefault ? [this.trackDefault, 'all'] : ['all'].concat(names);
    this.trackCycle = cycle;
    /* Display names: data-tracks-labels="short=kurz full=lang". The name stays the key
       (data-track, storage, deep links); only what a person reads changes. */
    var labels = {};
    (this.opt('data-tracks-labels') || '').split(/\s+/).forEach(function (pair) {
      var i = pair.indexOf('=');
      if (i > 0 && i < pair.length - 1) labels[pair.slice(0, i)] = pair.slice(i + 1);
    });
    this.trackLabels = labels;
    var stored = names.length ? storeGet(this.trackKey) : null;
    this.track = stored || this.trackDefault || 'all';
  };
  SlideEngine.prototype.setTrack = function (name) {
    this.track = name ? String(name) : 'all';
    if (this.trackNames.length) storeSet(this.trackKey, this.track);
    this.applyTrack(false);
  };
  SlideEngine.prototype.cycleTrack = function () {
    var c = this.trackCycle, i = c.indexOf(this.track);
    if (i < 0) i = c.indexOf(this.activeTrack);
    this.setTrack(c[(i + 1) % c.length]);
  };
  SlideEngine.prototype.applyTrack = function (initial) {
    var t = this.track, eff = (t === 'all' || this.trackNames.indexOf(t) < 0) ? 'all' : t;
    var vis = this.all.filter(function (s) {
      var tr = tracksOf(s);
      return eff === 'all' || !tr.length || tr.indexOf(eff) > -1;
    });
    if (!vis.length) { vis = this.all.slice(); eff = 'all'; } /* a named track with no slide of its own and no untagged slide: never an empty deck */
    var keep = initial ? null : this.slides[this.current];
    this.all.forEach(function (s) { s.classList.toggle('is-filtered', vis.indexOf(s) < 0); });
    this.activeTrack = eff;
    if (this.trackNames.length) root.setAttribute('data-track-active', eff);
    this.slides = vis;
    this.total = vis.length;
    this.labelSlides();
    this.buildDots();
    if (this.trackBadge) this.trackBadge.textContent = this.t.track + ': ' + this.labelOf(eff);
    [].forEach.call(document.querySelectorAll('[data-deck^="track:"]'), function (b) {
      b.setAttribute('aria-pressed', b.getAttribute('data-deck').slice(6) === eff ? 'true' : 'false');
    });
    if (!initial) {
      this.lastEmitted = null;
      this.goTo(keep ? this.visibleIndexOf(keep) : 0, true);
      this.say(this.trackBadge ? this.trackBadge.textContent : '');
      emit('trackchange', { track: eff, label: this.labelOf(eff), count: this.total });
    }
  };
  SlideEngine.prototype.labelOf = function (name) {
    if (name === 'all') return this.t.allTracks;
    return Object.prototype.hasOwnProperty.call(this.trackLabels, name) ? this.trackLabels[name] : name;
  };
  SlideEngine.prototype.visibleIndexOf = function (slide) {
    var a = this.all, i = a.indexOf(slide), j, k;
    if (i < 0) return 0;
    for (j = i; j < a.length; j++) { k = this.slides.indexOf(a[j]); if (k > -1) return k; }
    for (j = i; j >= 0; j--) { k = this.slides.indexOf(a[j]); if (k > -1) return k; }
    return 0;
  };

  /* ============ chrome ============ */
  SlideEngine.prototype.markSlides = function () {
    var t = this.t;
    this.all.forEach(function (s) {
      if (!s.getAttribute('role')) s.setAttribute('role', 'group');
      s.setAttribute('aria-roledescription', t.slide.toLowerCase());
      /* the big chapter number is decoration: the heading beside it says the chapter */
      [].forEach.call(s.querySelectorAll('.slide__number:not([aria-hidden])'), function (n) { n.setAttribute('aria-hidden', 'true'); });
    });
  };
  SlideEngine.prototype.labelSlides = function () {
    var self = this;
    this.slides.forEach(function (s, i) { s.setAttribute('aria-label', fill(self.t.status, i + 1, self.total)); });
  };
  SlideEngine.prototype.buildChrome = function () {
    var self = this, t = this.t, body = document.body;
    this.bar = el('div', 'deck-progress', body);
    if (this.opt('data-dots') !== 'off') this.dotBox = el('nav', 'deck-dots', body);
    this.dots = [];
    this.counter = el('div', 'deck-counter', body);
    this.live = el('div', 'deck-live', body);
    this.live.setAttribute('aria-live', 'polite');
    this.live.setAttribute('aria-atomic', 'true');
    if (this.trackNames.length) this.trackBadge = el('div', 'deck-track', body);

    var keys = ['← →', 'T'];
    if (this.trackNames.length) keys.push('F');
    if (document.querySelector('.slide aside.notes')) keys.push('N');
    this.hints = el('div', 'deck-hints', body);
    this.hints.textContent = keys.join(' · ') + ' · ' + t.hint;
    this.hintTimer = setTimeout(function () { self.hints.classList.add('faded'); }, 4000);

    var back = this.opt('data-back-href');
    if (back) {
      var a = el('a', 'deck-back', body);
      a.href = back;
      a.textContent = '← ' + (this.opt('data-back-label') || t.back);
    }

    var tt = el('button', 'theme-toggle', body);
    tt.type = 'button';
    tt.setAttribute('aria-label', t.theme);
    tt.title = t.themeTitle;
    tt.innerHTML = '<svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg><svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
    tt.onclick = function () { self.toggleTheme(); tt.blur(); };
    this.themeBtn = tt;

    var notes = el('aside', 'deck-notes', body);
    notes.setAttribute('aria-label', t.notes);
    notes.hidden = true;
    el('div', 'deck-notes__title', notes).textContent = t.notes;
    this.notesBody = el('div', 'deck-notes__body', notes);
    this.notesPanel = notes;

    var help = el('div', 'deck-help', body);
    help.setAttribute('role', 'dialog');
    help.setAttribute('aria-label', t.help);
    help.hidden = true;
    var card = el('div', 'deck-help__card', help);
    el('h2', 'deck-help__title', card).textContent = t.help;
    var dl = el('dl', 'deck-help__list', card);
    var rows = [['→ ↓ Space PgDn', t.keyNext], ['← ↑ Shift+Space PgUp', t.keyPrev], ['Home End', t.keyEnds], ['T', t.keyTheme]];
    if (this.trackNames.length) rows.push(['F', t.keyTrack]);
    if (document.querySelector('.stage, [data-buehne]')) rows.push(['V', t.keyStage]);
    rows.push(['N', t.keyNotes], ['?', t.keyHelp], ['Esc', t.keyClose]);
    rows.forEach(function (r) {
      var dt = el('dt', '', dl);
      r[0].split(' ').forEach(function (k) { el('kbd', '', dt).textContent = k; });
      el('dd', '', dl).textContent = r[1];
    });
    help.addEventListener('click', function (e) { if (e.target === help) self.toggleHelp(false); });
    this.helpBox = help;
  };
  SlideEngine.prototype.buildDots = function () {
    if (!this.dotBox) return;
    var self = this;
    this.dotBox.textContent = '';
    this.dots = this.slides.map(function (_, i) {
      var d = el('button', 'deck-dot', self.dotBox);
      d.type = 'button';
      d.title = fill(self.t.goTo, i + 1);
      d.setAttribute('aria-label', fill(self.t.goTo, i + 1));
      d.onclick = function () { self.goTo(i); d.blur(); };
      return d;
    });
  };

  SlideEngine.prototype.toggleTheme = function () {
    var isLight;
    if (root.classList.contains('theme-light')) isLight = true;
    else if (root.classList.contains('theme-dark')) isLight = false;
    else isLight = !!(window.matchMedia && matchMedia('(prefers-color-scheme: light)').matches);
    var next = isLight ? 'dark' : 'light';
    root.classList.remove('theme-light', 'theme-dark');
    root.classList.add('theme-' + next);
    storeSet('slide-theme', next);
  };
  SlideEngine.prototype.toggleNotes = function (force) {
    var open = typeof force === 'boolean' ? force : this.notesPanel.hidden;
    this.notesPanel.hidden = !open;
    root.classList.toggle('deck-notes-open', open);
    this.renderNotes();
  };
  SlideEngine.prototype.renderNotes = function () {
    if (!this.notesPanel || this.notesPanel.hidden) return;
    var s = this.slides[this.current], a = s && s.querySelector('aside.notes');
    this.notesBody.textContent = '';
    if (a) this.notesBody.innerHTML = a.innerHTML;
    else el('p', 'deck-notes__empty', this.notesBody).textContent = this.t.noNotes;
  };
  SlideEngine.prototype.toggleHelp = function (force) {
    var open = typeof force === 'boolean' ? force : this.helpBox.hidden;
    this.helpBox.hidden = !open;
  };
  SlideEngine.prototype.say = function (text) { if (this.live && text) this.live.textContent = text; };

  /* ============ events ============ */
  SlideEngine.prototype.bindEvents = function () {
    var self = this;
    document.addEventListener('keydown', function (e) {
      if (e.defaultPrevented || e.isComposing || e.ctrlKey || e.metaKey || e.altKey) return;
      var tg = e.target, k = e.key;
      if (tg && tg.closest && tg.closest(IGNORE)) return;
      if ((k === ' ' || k === 'Enter') && tg && tg.closest && tg.closest(ACTIVATES)) return;
      if (k === ' ' || k === 'Spacebar') { if (e.shiftKey) self.prev(); else self.next(); }
      else if (k === 'ArrowDown' || k === 'ArrowRight' || k === 'PageDown') self.next();
      else if (k === 'ArrowUp' || k === 'ArrowLeft' || k === 'PageUp') self.prev();
      else if (k === 'Home') self.goTo(0);
      else if (k === 'End') self.goTo(self.total - 1);
      else if (k === 't' || k === 'T') self.toggleTheme();
      else if ((k === 'f' || k === 'F') && self.trackNames.length) self.cycleTrack();
      else if (k === 'n' || k === 'N') self.toggleNotes();
      else if (k === '?') self.toggleHelp();
      else if (k === 'Escape' && !self.helpBox.hidden) self.toggleHelp(false);
      else if (k === 'Escape' && !self.notesPanel.hidden) self.toggleNotes(false);
      else return;
      e.preventDefault();
      self.fadeHints();
    });
    document.addEventListener('click', function (e) {
      var b = e.target && e.target.closest ? e.target.closest('[data-deck]') : null;
      if (!b) return;
      var v = b.getAttribute('data-deck') || '', m;
      if (v === 'next') self.next();
      else if (v === 'prev') self.prev();
      else if (v === 'theme') self.toggleTheme();
      else if (v === 'notes') self.toggleNotes();
      else if (v === 'help') self.toggleHelp();
      else if (v === 'track') self.cycleTrack();
      else if ((m = /^track:(.+)$/.exec(v))) self.setTrack(m[1]);
      else if ((m = /^goto:#(.+)$/.exec(v))) self.goToId(m[1]);
      else if ((m = /^goto:(\d+)$/.exec(v))) self.goTo(parseInt(m[1], 10) - 1);
      else return;
      e.preventDefault();
    });
    document.addEventListener('scroll', function () { self.onScroll(); }, true);
    window.addEventListener('hashchange', function () { self.fromHash(false); });
    var tY;
    this.deck.addEventListener('touchstart', function (e) { tY = e.touches[0].clientY; }, { passive: true });
    this.deck.addEventListener('touchend', function (e) {
      var dy = tY - e.changedTouches[0].clientY;
      if (Math.abs(dy) > 50) { if (dy > 0) self.next(); else self.prev(); }
    });
  };
  SlideEngine.prototype.observe = function () {
    var self = this;
    if ('IntersectionObserver' in window) {
      var obs = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) { if (en.isIntersecting) en.target.classList.add('visible'); });
      }, { threshold: 0.2 });
      this.all.forEach(function (s) { obs.observe(s); });
    } else {
      this.all.forEach(function (s) { s.classList.add('visible'); });
    }
    /* IntersectionObserver does not fire in print; reveal everything first. */
    var forceVisible = function () { self.all.forEach(function (s) { s.classList.add('visible'); }); };
    window.addEventListener('beforeprint', forceVisible);
    if (window.matchMedia) {
      var mq = matchMedia('print');
      if (mq.matches) forceVisible();
      if (mq.addEventListener) mq.addEventListener('change', function (e) { if (e.matches) forceVisible(); });
    }
  };

  /* ============ navigation ============ */
  /* The target index is taken at once, so key presses during a smooth scroll add up.
     The scroll position only takes over again once it has come to rest. */
  SlideEngine.prototype.goTo = function (i, instant) {
    var n = this.total;
    i = Number(i);
    if (!n || isNaN(i)) return;
    i = Math.max(0, Math.min(i === Infinity ? n - 1 : Math.floor(i) || 0, n - 1));
    var s = this.slides[i];
    if (!s) return;
    this.current = i;
    this.pending = i;
    this.armSettle(700);
    s.classList.add('visible');
    var behavior = instant ? 'instant' : (reducedMotion() ? 'auto' : 'smooth');
    try { s.scrollIntoView({ behavior: behavior, block: 'start' }); } catch (e) { s.scrollIntoView(true); }
    this.update();
  };
  SlideEngine.prototype.goToId = function (id) {
    var s = slideOf(document.getElementById(id));
    if (s) this.goTo(this.visibleIndexOf(s));
  };
  SlideEngine.prototype.next = function () { if (this.current < this.total - 1) this.goTo(this.current + 1); };
  SlideEngine.prototype.prev = function () { if (this.current > 0) this.goTo(this.current - 1); };
  SlideEngine.prototype.fromHash = function (instant) {
    var h = (location.hash || '').slice(1);
    try { h = decodeURIComponent(h); } catch (e) { /* keep raw */ }
    if (!h) return false;
    if (/^\d+$/.test(h)) {
      if (parseInt(h, 10) - 1 === this.current && !instant) return true;
      this.goTo(parseInt(h, 10) - 1, instant);
      return true;
    }
    var s = slideOf(document.getElementById(h));
    if (!s) return false;
    this.goTo(this.visibleIndexOf(s), instant);
    return true;
  };
  SlideEngine.prototype.indexFromScroll = function () {
    var top = this.deck === document.body ? 0 : this.deck.getBoundingClientRect().top;
    var line = top + (window.innerHeight || 0) * 0.4, best = 0, bestTop = -Infinity;
    this.slides.forEach(function (s, i) {
      var r = s.getBoundingClientRect().top;
      if (r <= line && r > bestTop) { bestTop = r; best = i; }
    });
    return best;
  };
  SlideEngine.prototype.armSettle = function (ms) {
    var self = this;
    clearTimeout(this.settleTimer);
    this.settleTimer = setTimeout(function () { self.settle(true); }, ms);
  };
  SlideEngine.prototype.onScroll = function () {
    if (!this.ready) return;
    var self = this;
    this.armSettle(this.pending === null ? 150 : 700);
    clearTimeout(this.quickTimer);
    this.quickTimer = setTimeout(function () { self.settle(false); }, 150);
  };
  SlideEngine.prototype.settle = function (force) {
    var i = this.indexFromScroll();
    if (this.pending !== null) {
      if (i !== this.pending && !force) return;
      this.pending = null;
    }
    clearTimeout(this.settleTimer);
    clearTimeout(this.quickTimer);
    if (i !== this.current) { this.current = i; this.update(); }
  };
  SlideEngine.prototype.update = function () {
    var n = this.total, c = this.current, self = this;
    if (!n) return;
    var w = Math.max(2, String(n).length);
    var fmt = function (x) { x = String(x); return self.padded && x.length < w ? new Array(w - x.length + 1).join('0') + x : x; };
    this.bar.style.width = ((c + 1) / n * 100) + '%';
    this.dots.forEach(function (d, i) {
      d.classList.toggle('active', i === c);
      if (i === c) d.setAttribute('aria-current', 'true'); else d.removeAttribute('aria-current');
    });
    this.counter.textContent = fmt(c + 1) + ' / ' + fmt(n);
    this.all.forEach(function (s) { s.classList.remove('is-active'); });
    var s = this.slides[c];
    if (s) s.classList.add('is-active');
    this.renderNotes();
    if (!this.ready || this.lastEmitted === s) return;
    var first = this.lastEmitted === undefined;
    this.lastEmitted = s;
    if (this.deepLink && !(first && c === 0 && !location.hash)) {
      /* a slide id holds in every track; a number counts the slides the track shows */
      var h = '#' + (s.id ? encodeURIComponent(s.id) : String(c + 1));
      if (location.hash !== h) { try { history.replaceState(history.state, '', h); } catch (e) { /* sandboxed frame */ } }
    }
    if (first) return;
    this.say(fill(this.t.status, c + 1, n));
    emit('slidechange', { index: c, count: n, slide: s });
  };
  SlideEngine.prototype.fadeHints = function () { clearTimeout(this.hintTimer); this.hints.classList.add('faded'); };

  /* ============ public API ============ */
  var api = {
    version: 2,
    goTo: function (i) { if (instance) instance.goTo(i); },
    next: function () { if (instance) instance.next(); },
    prev: function () { if (instance) instance.prev(); },
    current: function () { return instance ? instance.current : 0; },
    count: function () { return instance ? instance.total : 0; },
    track: function () { return instance ? instance.activeTrack : 'all'; },
    trackLabel: function (name) {
      return instance ? instance.labelOf(name == null ? instance.activeTrack : String(name)) : (name || 'all');
    },
    setTrack: function (name) { if (instance) instance.setTrack(name); },
    toggleTheme: function () { if (instance) instance.toggleTheme(); },
    toggleNotes: function (force) { if (instance) instance.toggleNotes(force); },
    toggleHelp: function (force) { if (instance) instance.toggleHelp(force); },
    strings: function () {
      var t = instance ? instance.t : STRINGS.en, o = {};
      for (var k in t) if (Object.prototype.hasOwnProperty.call(t, k)) o[k] = t[k];
      return o;
    },
    on: function (ev, fn) {
      (listeners[ev] = listeners[ev] || []).push(fn);
      if (ev === 'ready' && instance && instance.ready) fn(api);
      return api;
    }
  };
  window.SlideDeck = api;
  window.SlideEngine = SlideEngine;

  function start() { if (!instance && document.querySelector('.slide')) new SlideEngine(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
