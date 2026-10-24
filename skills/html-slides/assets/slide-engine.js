/* slide-engine v2 */
/* Scroll-snap presentation engine for single-file HTML decks.
   Contract (reference/slide-types.md, section "Engine contract"):
   - Slides are .slide inside .deck. Options sit on .deck or <html> (deck wins):
     data-tracks-default, data-tracks-cycle, data-deck-id, data-counter-format="padded",
     data-dots="off", data-back-href, data-back-label, data-deep-link="off".
   - API: window.SlideDeck = {goTo(i), next(), prev(), current(), count(), setTrack(name),
     track(), on(event, fn), toggleTheme(), toggleNotes(), toggleHelp(), strings()}.
     Indexes are 0-based positions among the slides the active track shows.
     Events: "ready", "slidechange" {index, count, slide}, "trackchange" {track, count},
     also dispatched on document as "slidedeck:<event>".
     The old names window.slideEngine and window.__slideEngine point at the one engine instance.
   - Buttons: data-deck="next|prev|theme|notes|help|track|track:<name>|goto:<n>|goto:#<id>",
     where goto:<n> is the 1-based slide number the counter shows.
   - Tracks: data-track on a slide (old decks: data-spur), several names separated by spaces.
     A slide without one belongs to every track. Key F cycles.
   - Notes: <aside class="notes"> inside a slide, key N shows them in a panel.
   - Tracks named only by data-tracks-default or data-tracks-cycle exist too; they show
     the untagged slides.
   - Deep link: #<slide id> when the active slide has an id, else #<n> (1-based among the
     slides the track shows), plus .<step> while a module step is above 0 (#<id>.2);
     all forms are read, kept current with history.replaceState.
   - Modules (reference/modules.md): SlideDeck.use({name, keys, step, transition, help, init}),
     plus slides(), state(), setStep(n), step(), setLang(l), setTheme(t), reducedMotion() and
     the events stepchange, themechange, langchange.
   - Core keys: B / W cover the screen, digits + Enter jump, L switches a bilingual deck
     (data-de / data-en pairs), Alt+click zooms. data-print-notes prints a notes page
     after every slide that has notes. */
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
      keyStage: 'Enlarge or restore the live stage',
      keyLang: 'Switch language (DE / EN)', keyCover: 'Black or white screen, any key returns',
      keyJump: 'Jump to slide number', keyZoom: 'Zoom in at the pointer, click returns',
      jump: 'Go to slide', handout: 'Notes on slide {n}'
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
      keyStage: 'Live-Bühne vergrößern oder zurück',
      keyLang: 'Sprache wechseln (DE / EN)', keyCover: 'Bildschirm schwarz oder weiß, jede Taste zurück',
      keyJump: 'Zu Foliennummer springen', keyZoom: 'An der Stelle vergrößern, Klick zurück',
      jump: 'Gehe zu Folie', handout: 'Notizen zu Folie {n}'
    }
  };
  /* i18n:end */

  var root = document.documentElement;
  var instance = null;
  var listeners = {};
  var modules = [];   /* SlideDeck.use(), in registration order */
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
  function later(err) { setTimeout(function () { throw err; }); }
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
    this.step = 0;
    this.navSeq = 0;
    this.initLang();
    this.padded = this.opt('data-counter-format') === 'padded';
    this.deepLink = this.opt('data-deep-link') !== 'off';
    this.initTracks();
    this.markSlides();
    this.buildChrome();
    this.bindEvents();
    this.observe();
    this.applyTrack(true);
    this.handout();
    this.ready = true;
    if (!this.fromHash(true)) this.update();
    modules.forEach(initModule);
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
    if (this.trackBadge) this.trackBadge.textContent = this.t.track + ': ' + (eff === 'all' ? this.t.allTracks : eff);
    if (!initial) {
      this.lastEmitted = null;
      this.goTo(keep ? this.visibleIndexOf(keep) : 0, true);
      this.say(this.trackBadge ? this.trackBadge.textContent : '');
      emit('trackchange', { track: eff, count: this.total });
    }
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
    });
  };
  SlideEngine.prototype.labelSlides = function () {
    var self = this;
    this.slides.forEach(function (s, i) { s.setAttribute('aria-label', (i + 1) + ' / ' + self.total); });
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
    this.hintKeys = keys.join(' · ');
    this.hints.textContent = this.hintKeys + ' · ' + t.hint;
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
    this.helpList = el('dl', 'deck-help__list', card);
    help.addEventListener('click', function (e) { if (e.target === help) self.toggleHelp(false); });
    this.helpBox = help;
    this.renderHelp();

    this.coverBox = el('div', 'deck-cover', body);
    this.coverBox.hidden = true;
    this.coverBox.setAttribute('aria-hidden', 'true');
    this.coverBox.addEventListener('click', function () { self.setCover(null); });
    this.jumpBox = el('div', 'deck-jump', body);
    this.jumpBox.hidden = true;
  };
  SlideEngine.prototype.renderHelp = function () {
    var t = this.t, dl = this.helpList, lang = this.lang;
    if (!dl) return;
    var rows = [['→ ↓ Space PgDn', t.keyNext], ['← ↑ Shift+Space PgUp', t.keyPrev], ['Home End', t.keyEnds], ['T', t.keyTheme]];
    if (this.trackNames.length) rows.push(['F', t.keyTrack]);
    if (document.querySelector('.stage, [data-buehne]')) rows.push(['V', t.keyStage]);
    rows.push(['N', t.keyNotes]);
    if (this.bilingual) rows.push(['L', t.keyLang]);
    rows.push(['B W', t.keyCover], ['0-9 Enter', t.keyJump], ['Alt+click', t.keyZoom]);
    modules.forEach(function (m) {
      (m.help || []).forEach(function (r) { if (r && r.key) rows.push([String(r.key), r[lang] || r.en || r.de || '']); });
    });
    rows.push(['?', t.keyHelp], ['Esc', t.keyClose]);
    dl.textContent = '';
    rows.forEach(function (r) {
      var dt = el('dt', '', dl);
      r[0].split(' ').forEach(function (k) { el('kbd', '', dt).textContent = k; });
      el('dd', '', dl).textContent = r[1];
    });
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
    this.setTheme(isLight ? 'dark' : 'light');
  };
  SlideEngine.prototype.setTheme = function (next) {
    if (next !== 'light' && next !== 'dark') return;
    root.classList.remove('theme-light', 'theme-dark');
    root.classList.add('theme-' + next);
    storeSet('slide-theme', next);
    emit('themechange', { theme: next });
  };
  SlideEngine.prototype.theme = function () {
    if (root.classList.contains('theme-light')) return 'light';
    if (root.classList.contains('theme-dark')) return 'dark';
    return window.matchMedia && matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
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
      if (/^(Shift|Control|Alt|Meta|CapsLock|Dead)$/.test(k)) return;
      if (self.coverBox && !self.coverBox.hidden) {
        /* B and W switch the cover, every other key lifts it and does nothing else */
        var c = k.toLowerCase(), want = c === 'b' ? 'black' : (c === 'w' ? 'white' : null);
        self.setCover(want && self.coverBox.getAttribute('data-cover') !== want ? want : null);
        e.preventDefault();
        return;
      }
      if (/^[0-9]$/.test(k)) { self.jumpType(k); e.preventDefault(); return; }
      if (self.jumpBuf) {
        if (k === 'Enter') self.jumpGo();
        else if (k === 'Backspace') self.jumpType(null);
        else self.jumpClear();
        if (k === 'Enter' || k === 'Backspace' || k === 'Escape') { e.preventDefault(); return; }
      }
      if ((k === ' ' || k === 'Enter') && tg && tg.closest && tg.closest(ACTIVATES)) return;
      if (self.moduleKey(k, e)) { e.preventDefault(); self.fadeHints(); return; }
      if (k === ' ' || k === 'Spacebar') { if (e.shiftKey) self.prev(); else self.next(); }
      else if (k === 'ArrowDown' || k === 'ArrowRight' || k === 'PageDown') self.next();
      else if (k === 'ArrowUp' || k === 'ArrowLeft' || k === 'PageUp') self.prev();
      else if (k === 'Home') self.goTo(0);
      else if (k === 'End') self.goTo(self.total - 1);
      else if (k === 't' || k === 'T') self.toggleTheme();
      else if ((k === 'f' || k === 'F') && self.trackNames.length) self.cycleTrack();
      else if (k === 'n' || k === 'N') self.toggleNotes();
      else if ((k === 'l' || k === 'L') && self.bilingual) self.toggleLang();
      else if (k === 'b' || k === 'B') self.setCover('black');
      else if (k === 'w' || k === 'W') self.setCover('white');
      else if (k === '?') self.toggleHelp();
      else if (k === 'Escape' && self.zoomed) self.unzoom();
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
      else if (v === 'lang') self.toggleLang();
      else if ((m = /^track:(.+)$/.exec(v))) self.setTrack(m[1]);
      else if ((m = /^goto:#(.+)$/.exec(v))) self.goToId(m[1]);
      else if ((m = /^goto:(\d+)$/.exec(v))) self.goTo(parseInt(m[1], 10) - 1);
      else return;
      e.preventDefault();
    });
    /* Alt+click zooms around the pointer; while zoomed, the next click only resets. */
    document.addEventListener('click', function (e) {
      if (self.zoomed && !e.altKey) { self.unzoom(); e.preventDefault(); e.stopPropagation(); return; }
      if (!e.altKey || e.ctrlKey || e.metaKey || e.button !== 0) return;
      var s = slideOf(e.target);
      if (!s || s !== self.slides[self.current]) return;
      self.zoomAt(s, e.clientX, e.clientY);
      e.preventDefault();
      e.stopPropagation();
    }, true);
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
    var forceVisible = function () {
      self.all.forEach(function (s) { s.classList.add('visible'); });
      self.unzoom(true);
      self.handout();
    };
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
    var from = this.slides[this.current], self = this, seq = ++this.navSeq, done = false, timer;
    if (s !== from) { this.step = 0; this.unzoom(true); }
    this.current = i;
    this.pending = i;
    var apply = function (o) {
      if (done) return;
      done = true;
      clearTimeout(timer);
      if (seq !== self.navSeq) return; /* a newer goTo took over */
      self.current = i;
      self.pending = i;
      self.armSettle(700);
      s.classList.add('visible');
      var behavior = (instant || (o && o.instant)) ? 'instant' : (reducedMotion() ? 'auto' : 'smooth');
      try { s.scrollIntoView({ behavior: behavior, block: 'start' }); } catch (e) { s.scrollIntoView(true); }
      self.update();
    };
    var chain = (instant || !from || s === from || reducedMotion()) ? [] : modules.filter(function (m) { return typeof m.transition === 'function'; });
    if (!chain.length) return apply();
    timer = setTimeout(apply, 1500); /* a transition that never applies must not strand the deck */
    chain.reduceRight(function (next, m) {
      return function (o) {
        try { m.transition(from, s, next); } catch (err) { next(o); later(err); }
      };
    }, apply)();
  };
  SlideEngine.prototype.goToId = function (id) {
    var s = slideOf(document.getElementById(id));
    if (s) this.goTo(this.visibleIndexOf(s));
  };
  SlideEngine.prototype.next = function () { if (!this.stepBy(1) && this.current < this.total - 1) this.goTo(this.current + 1); };
  SlideEngine.prototype.prev = function () { if (!this.stepBy(-1) && this.current > 0) this.goTo(this.current - 1); };
  SlideEngine.prototype.fromHash = function (instant) {
    var h = (location.hash || '').slice(1);
    try { h = decodeURIComponent(h); } catch (e) { /* keep raw */ }
    if (!h) return false;
    var m = /^(\d+)(?:\.(\d+))?$/.exec(h), i, step = 0, s;
    if (m) { i = parseInt(m[1], 10) - 1; step = m[2] ? parseInt(m[2], 10) : 0; }
    else {
      /* an id may hold a dot itself: the whole hash is tried as an id first */
      s = slideOf(document.getElementById(h));
      if (!s && (m = /^(.+)\.(\d+)$/.exec(h))) { s = slideOf(document.getElementById(m[1])); step = parseInt(m[2], 10); }
      if (!s) return false;
      i = this.visibleIndexOf(s);
    }
    if (instant || i !== this.current) this.goTo(i, instant);
    this.setStep(step);
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
    if (i !== this.current) { this.current = i; this.step = 0; this.unzoom(true); this.update(); }
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
    var s = this.slides[c];
    /* only the active slide takes focus and clicks; the others stay in the DOM for scroll-snap */
    this.all.forEach(function (x) {
      x.classList.toggle('is-active', x === s);
      if (x === s) x.removeAttribute('inert'); else x.setAttribute('inert', '');
    });
    this.renderNotes();
    if (!this.ready || this.lastEmitted === s) return;
    var first = this.lastEmitted === undefined;
    this.lastEmitted = s;
    if (!(first && c === 0 && !location.hash)) this.writeHash();
    if (first) return;
    this.say(fill(this.t.status, c + 1, n));
    emit('slidechange', { index: c, count: n, slide: s });
  };
  SlideEngine.prototype.writeHash = function () {
    var s = this.slides[this.current];
    if (!this.deepLink || !s) return;
    /* a slide id holds in every track; a number counts the slides the track shows */
    var h = '#' + (s.id ? encodeURIComponent(s.id) : String(this.current + 1)) + (this.step > 0 ? '.' + this.step : '');
    if (location.hash !== h) { try { history.replaceState(history.state, '', h); } catch (e) { /* sandboxed frame */ } }
  };
  SlideEngine.prototype.fadeHints = function () { clearTimeout(this.hintTimer); this.hints.classList.add('faded'); };

  /* ============ language ============ */
  /* A deck is bilingual when it holds data-de / data-en pairs: then key L switches and the
     choice is kept per deck id. setLang() works in any deck (it relabels the controls). */
  SlideEngine.prototype.initLang = function () {
    var pick = function (v) { v = String(v || '').toLowerCase().split('-')[0]; return STRINGS[v] ? v : null; };
    this.bilingual = !!document.querySelector('[data-de], [data-en]');
    this.langKey = 'slide-lang:' + (this.opt('data-deck-id') || location.pathname);
    this.lang = pick(storeGet(this.langKey)) || pick(root.getAttribute('data-lang')) || pick(root.getAttribute('lang')) || 'en';
    this.t = STRINGS[this.lang];
    if (this.bilingual) { root.setAttribute('lang', this.lang); root.setAttribute('data-lang', this.lang); this.applyAria(); }
  };
  SlideEngine.prototype.setLang = function (l) {
    if (!STRINGS[l] || l === this.lang) return;
    this.lang = l;
    this.t = STRINGS[l];
    root.setAttribute('lang', l);
    root.setAttribute('data-lang', l);
    storeSet(this.langKey, l);
    this.relabel();
    emit('langchange', { lang: l });
  };
  SlideEngine.prototype.toggleLang = function () { this.setLang(this.lang === 'de' ? 'en' : 'de'); };
  /* aria-label and title in the active language for elements with data-aria-de / data-aria-en */
  SlideEngine.prototype.applyAria = function () {
    var l = this.lang, o = l === 'de' ? 'en' : 'de';
    [].forEach.call(document.querySelectorAll('[data-aria-de], [data-aria-en]'), function (e) {
      var v = e.getAttribute('data-aria-' + l) || e.getAttribute('data-aria-' + o);
      if (v) { e.setAttribute('aria-label', v); e.setAttribute('title', v); }
    });
  };
  SlideEngine.prototype.relabel = function () {
    var t = this.t, back = document.querySelector('.deck-back');
    this.markSlides();
    this.themeBtn.setAttribute('aria-label', t.theme);
    this.themeBtn.title = t.themeTitle;
    this.notesPanel.setAttribute('aria-label', t.notes);
    this.notesPanel.querySelector('.deck-notes__title').textContent = t.notes;
    this.helpBox.setAttribute('aria-label', t.help);
    this.helpBox.querySelector('.deck-help__title').textContent = t.help;
    this.hints.textContent = this.hintKeys + ' · ' + t.hint;
    if (back && !this.opt('data-back-label')) back.textContent = '← ' + t.back;
    if (this.trackBadge) this.trackBadge.textContent = t.track + ': ' + (this.activeTrack === 'all' ? t.allTracks : this.activeTrack);
    this.renderHelp();
    this.buildDots();
    this.lastEmitted = this.slides[this.current];
    this.update();
    this.renderNotes();
    this.applyAria();
    if (this.handoutBuilt) this.handout();
  };

  /* ============ cover, number jump, zoom ============ */
  SlideEngine.prototype.setCover = function (kind) {
    var on = kind === 'black' || kind === 'white';
    this.coverBox.hidden = !on;
    if (on) this.coverBox.setAttribute('data-cover', kind); else this.coverBox.removeAttribute('data-cover');
    root.classList.toggle('deck-covered', on);
  };
  SlideEngine.prototype.jumpType = function (d) {
    var self = this;
    this.jumpBuf = d === null ? (this.jumpBuf || '').slice(0, -1) : ((this.jumpBuf || '') + d).slice(0, 4);
    if (!this.jumpBuf) return this.jumpClear();
    this.jumpBox.textContent = this.t.jump + ' ' + this.jumpBuf;
    this.jumpBox.hidden = false;
    clearTimeout(this.jumpTimer);
    this.jumpTimer = setTimeout(function () { self.jumpClear(); }, 3000);
  };
  SlideEngine.prototype.jumpClear = function () {
    clearTimeout(this.jumpTimer);
    this.jumpBuf = '';
    this.jumpBox.hidden = true;
  };
  SlideEngine.prototype.jumpGo = function () {
    var n = parseInt(this.jumpBuf, 10);
    this.jumpClear();
    if (n > 0) this.goTo(n - 1);
  };
  /* Zoom scales the slide's children, never the slide: the slide clips them, so the
     scroll-snap deck behind keeps its geometry. */
  SlideEngine.prototype.zoomAt = function (s, x, y) {
    this.unzoom(true);
    var ease = reducedMotion() ? '' : 'transform 0.3s ease';
    [].forEach.call(s.children, function (c) {
      if (c.matches('aside.notes')) return;
      var r = c.getBoundingClientRect(), z = parseFloat(getComputedStyle(c).zoom) || 1;
      c.setAttribute('data-deck-zoom', '');
      c.style.transition = ease;
      c.style.transformOrigin = ((x - r.left) / z) + 'px ' + ((y - r.top) / z) + 'px';
      c.style.transform = 'scale(2)';
    });
    this.zoomed = s;
    root.classList.add('deck-zoomed');
  };
  SlideEngine.prototype.unzoom = function (instant) {
    var s = this.zoomed;
    if (!s) return;
    this.zoomed = null;
    root.classList.remove('deck-zoomed');
    var kids = [].filter.call(s.children, function (c) { return c.hasAttribute('data-deck-zoom'); });
    var clear = function () {
      kids.forEach(function (c) {
        if (c.style.transform) return; /* zoomed again meanwhile */
        c.removeAttribute('data-deck-zoom');
        c.style.transition = '';
        c.style.transformOrigin = '';
      });
    };
    kids.forEach(function (c) { if (instant) c.style.transition = ''; c.style.transform = ''; });
    if (instant || reducedMotion()) clear(); else setTimeout(clear, 350);
  };

  /* ============ print handout (data-print-notes) ============ */
  SlideEngine.prototype.handout = function () {
    var want = this.opt('data-print-notes'), t = this.t;
    if (want === null || want === 'off') return;
    [].forEach.call(document.querySelectorAll('.deck-print-notes'), function (e) { e.parentNode.removeChild(e); });
    this.all.forEach(function (s, i) {
      var a = s.querySelector('aside.notes');
      if (!a) return;
      var page = document.createElement('div');
      page.className = 'deck-print-notes';
      page.setAttribute('aria-hidden', 'true');
      el('div', 'deck-print-notes__title', page).textContent = fill(t.handout, i + 1);
      el('div', 'deck-print-notes__body', page).innerHTML = a.innerHTML;
      s.parentNode.insertBefore(page, s.nextSibling);
    });
    this.handoutBuilt = true;
  };

  /* ============ modules ============ */
  SlideEngine.prototype.moduleKey = function (k, e) {
    var lk = String(k).toLowerCase();
    for (var i = 0; i < modules.length; i++) {
      var fn = modules[i].keys && modules[i].keys[lk];
      if (typeof fn !== 'function') continue;
      try { if (fn(e) === true) return true; } catch (err) { later(err); }
    }
    return false;
  };
  SlideEngine.prototype.stepBy = function (dir) {
    for (var i = 0; i < modules.length; i++) {
      if (typeof modules[i].step !== 'function') continue;
      try { if (modules[i].step(dir) === true) return true; } catch (err) { later(err); }
    }
    return false;
  };
  SlideEngine.prototype.setStep = function (n) {
    n = Math.max(0, Math.floor(Number(n)) || 0);
    if (n === this.step) return;
    this.step = n;
    this.writeHash();
    if (this.ready) emit('stepchange', { index: this.current, step: n, slide: this.slides[this.current] });
  };
  function initModule(m) {
    if (m.inited || typeof m.init !== 'function') return;
    m.inited = true;
    try { m.init(api); } catch (err) { later(err); }
  }

  /* ============ public API ============ */
  var api = {
    version: 2,
    goTo: function (i) { if (instance) instance.goTo(i); },
    next: function () { if (instance) instance.next(); },
    prev: function () { if (instance) instance.prev(); },
    current: function () { return instance ? instance.current : 0; },
    count: function () { return instance ? instance.total : 0; },
    track: function () { return instance ? instance.activeTrack : 'all'; },
    setTrack: function (name) { if (instance) instance.setTrack(name); },
    toggleTheme: function () { if (instance) instance.toggleTheme(); },
    toggleNotes: function (force) { if (instance) instance.toggleNotes(force); },
    toggleHelp: function (force) { if (instance) instance.toggleHelp(force); },
    setTheme: function (name) { if (instance) instance.setTheme(name); },
    setLang: function (l) { if (instance) instance.setLang(l); },
    setStep: function (n) { if (instance) instance.setStep(n); },
    step: function () { return instance ? instance.step : 0; },
    slides: function () { return instance ? instance.slides.slice() : []; },
    reducedMotion: reducedMotion,
    state: function () {
      var e = instance;
      if (!e) return { index: 0, id: '', step: 0, track: 'all', theme: 'dark', lang: 'en', notes: false };
      var s = e.slides[e.current];
      return { index: e.current, id: (s && s.id) || '', step: e.step, track: e.activeTrack,
               theme: e.theme(), lang: e.lang, notes: !e.notesPanel.hidden };
    },
    /* A module: {name, keys, step, transition, help, init}; reference/modules.md. A second
       module with a name already in use is ignored. */
    use: function (m) {
      if (!m || !m.name || modules.some(function (x) { return x.name === m.name; })) return api;
      modules.push(m);
      if (instance && instance.ready) { instance.renderHelp(); initModule(m); }
      return api;
    },
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
