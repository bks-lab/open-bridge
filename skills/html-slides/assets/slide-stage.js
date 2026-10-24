/* slide-engine v2: slide-stage (optional module, new-deck.py --with-stage) */
/*  SLIDE STAGE: live simulations inside slides, the parent side
    ============================================================================
    A stage is an element that holds one running page (usually an html-canvas
    simulation) in an iframe:

      <div class="stage" data-src="run.html"></div>
      <div class="stage" data-srcdoc-ref="run-1" data-mode="read"></div>
      plus an inert script element of type text/plain, id "run-1",
      data-encoding="base64", whose text is the page

    This file is spliced inline into a deck, so it must never contain the
    closing tag of a script element, not even in a comment.

    Attributes on the stage:
      data-src          relative path of the page to run
      data-srcdoc-ref   id of an inert <script type="text/plain"> or <template>
                        holding the page itself; base64 when it carries
                        data-encoding="base64" (UTF-8 safe). Wins over data-src,
                        so a send-out copy runs without the file next to it.
      data-mode         "fit" (default): the page renders in a logical window
                        (data-viewport, default 1440x900) and is scaled down to
                        the frame, never up. "read": no scaling, the page fills
                        the frame and scrolls at its natural size.
      data-title        accessible name of the iframe
    Buttons anywhere in the same slide: data-stage="maximize" | "restart".
    Keys in the deck: V toggles the large stage of the active slide, Escape
    leaves it. Older decks: data-buehne, data-buehne-modus (buehne, lesen) and
    data-buehne-viewport are read as aliases, on the stage or on its slide with
    a .buehne__rahmen inside.

    Five scars shaped this file. Each has a test in tests/test_stage.py.
      N1  the placeholder sits over the frame and swallows every click unless
          it ignores pointers AND disappears once the frame is loaded
      N2  a transform, filter or contain on any ancestor turns position:fixed
          into "fixed to that ancestor": the large stage fills the slide, not
          the window, on every slide but the first
      N3  large means window-filling CSS, not the browser's full screen
          interface: that one differs per browser, needs a permission inside
          frames and fails for pages opened from a file in some browsers
      N4  two kinds of stage: a scaled one for pictures, an unscaled one for
          documents. Fit follows the frame through a ResizeObserver, because
          the frame also changes size when the text above it rewraps
      N5  only the active stage runs: load on arrival so the run starts from
          the beginning in front of the audience, unload two slides away. A
          loaded stage is never reloaded by a second load call, only by restart

    The contract with the page inside (stage:ready, stage:key, stage:maximize,
    stage:restart) is documented in html-canvas references/simulation.md,
    "Embedding in a slide". A message counts only when its source is the
    window of one of our own frames: srcdoc and file:// pages have no origin
    worth comparing, so the window is the only reliable check.
    ========================================================================== */
(function () {
  'use strict';

  var doc = document, root = doc.documentElement;
  var stages = [];
  var maxed = null;
  var closer = null;
  var DECK_KEYS = ['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'PageDown', 'PageUp',
                   ' ', 'Home', 'End', 'f', 'F', 'n', 'N'];
  var LABELS = {
    en: { close: 'Exit full view', closeTitle: 'Back to the slide (Escape)', frame: 'Embedded simulation' },
    de: { close: 'Vollbild beenden', closeTitle: 'Zurück (Escape)', frame: 'Eingebettete Simulation' }
  };

  function lang() {
    var l = (root.getAttribute('lang') || 'en').toLowerCase().slice(0, 2);
    return LABELS[l] ? l : 'en';
  }
  function reduced() {
    return !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);
  }
  function attr(el, names) {
    for (var i = 0; i < names.length; i++) {
      var v = el.getAttribute(names[i]);
      if (v !== null && v !== '') return v;
    }
    return null;
  }

  /* ===== Discovery ===== */

  function describe(host, frame) {
    var src = attr(host, ['data-src', 'data-buehne']);
    var ref = attr(host, ['data-srcdoc-ref']);
    /* An older send-out copy carried the page as viz-<path>, with every
       character outside a-z and 0-9 replaced by a hyphen. */
    if (!ref && src && doc.getElementById('viz-' + src.replace(/[^a-z0-9]/gi, '-'))) {
      ref = 'viz-' + src.replace(/[^a-z0-9]/gi, '-');
    }
    var mode = (attr(host, ['data-mode', 'data-buehne-modus']) || 'fit').trim().toLowerCase();
    mode = (mode === 'read' || mode === 'lesen') ? 'read' : 'fit';
    var vp = (attr(host, ['data-viewport', 'data-buehne-viewport']) || '1440x900').split('x');
    var st = {
      host: host, frame: frame, src: src, ref: ref, mode: mode,
      vw: parseInt(vp[0], 10) || 1440, vh: parseInt(vp[1], 10) || 900,
      slide: frame.closest('.slide'), iframe: null, ready: false
    };
    frame.setAttribute('data-mode', mode);
    return st;
  }

  function discover() {
    var seen = [];
    [].forEach.call(doc.querySelectorAll('.stage, [data-buehne]'), function (el) {
      var frame = el;
      if (!el.classList.contains('stage')) {
        frame = el.querySelector('.buehne__rahmen');
        if (!frame) return;
      }
      if (seen.indexOf(frame) > -1) return;
      seen.push(frame);
      var st = describe(el, frame);
      if (st.src || st.ref) stages.push(st);
    });
  }

  function forFrameWindow(win) {
    for (var i = 0; i < stages.length; i++) {
      var f = stages[i].iframe;
      if (f && f.contentWindow === win) return stages[i];
    }
    return null;
  }

  /* ===== Loading (N5) ===== */

  function inlinePage(ref) {
    var el = doc.getElementById(ref);
    if (!el) return null;
    if (el.tagName === 'TEMPLATE') return el.innerHTML;
    var text = el.textContent;
    if ((el.getAttribute('data-encoding') || '').toLowerCase() !== 'base64') return text;
    var raw = atob(String(text).replace(/\s+/g, ''));
    var bytes = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    return new TextDecoder('utf-8').decode(bytes);
  }

  /* Gentle: a stage that already runs is left alone. Only restart() starts a
     run over, otherwise a print request would restart every running stage. */
  function load(st) {
    if (st.iframe) return;
    var f = doc.createElement('iframe');
    f.setAttribute('title', attr(st.host, ['data-title']) || LABELS[lang()].frame);
    /* Deliberately no permission for the full screen interface (N3). */
    var page = st.ref ? inlinePage(st.ref) : null;
    if (page !== null) f.setAttribute('srcdoc', page);
    else if (st.src) f.setAttribute('src', st.src);
    else return;
    f.addEventListener('load', function () { fit(st); });
    st.iframe = f;
    st.ready = false;
    st.frame.appendChild(f);
    st.frame.setAttribute('data-loaded', '');
    st.frame.removeAttribute('data-ready');
    fit(st);
  }

  function unload(st) {
    if (st === maxed || !st.iframe) return;
    if (st.iframe.parentNode) st.iframe.parentNode.removeChild(st.iframe);
    st.iframe = null;
    st.ready = false;
    st.frame.removeAttribute('data-loaded');
    st.frame.removeAttribute('data-ready');
    st.frame.removeAttribute('data-scale');
  }

  function restart(st) {
    if (st.iframe && st.ready) { tell(st, { type: 'stage:restart' }); return; }
    var keep = st === maxed;
    if (keep) maxed = null;
    unload(st);
    load(st);
    if (keep) maxed = st;
  }

  function tell(st, msg) {
    var w = st.iframe && st.iframe.contentWindow;
    if (w) try { w.postMessage(msg, '*'); } catch (err) { /* frame gone */ }
  }

  /* ===== Which slide is active ===== */

  function visibleSlides() {
    return [].filter.call(doc.querySelectorAll('.slide'), function (s) {
      return s.getClientRects().length > 0;
    });
  }

  /* The slide covering most of the window. Measured, not taken from the
     engine, so the module works with any engine version or none. */
  function activeSlide(list) {
    var best = null, bestArea = 0, vh = window.innerHeight, vw = window.innerWidth;
    list.forEach(function (s) {
      var r = s.getBoundingClientRect();
      var h = Math.min(r.bottom, vh) - Math.max(r.top, 0);
      var w = Math.min(r.right, vw) - Math.max(r.left, 0);
      var area = (h > 0 && w > 0) ? h * w : 0;
      if (area > bestArea) { bestArea = area; best = s; }
    });
    return best;
  }

  function refresh() {
    var list = visibleSlides();
    var active = activeSlide(list);
    var ai = active ? list.indexOf(active) : -1;
    if (maxed && maxed.slide && list.indexOf(maxed.slide) < 0) exitMax();
    stages.forEach(function (st) {
      if (!st.slide) { load(st); return; }
      var si = list.indexOf(st.slide);
      if (si < 0 || ai < 0) { if (si < 0) unload(st); return; }
      var d = Math.abs(si - ai);
      if (d === 0) load(st);
      else if (d >= 2) unload(st);
    });
  }

  function loadAll() { stages.forEach(load); }

  /* ===== Fit (N4) ===== */

  function fit(st) {
    var f = st.iframe;
    if (!f) return;
    if (st.mode === 'read') {
      f.style.width = ''; f.style.height = ''; f.style.position = '';
      f.style.left = ''; f.style.top = ''; f.style.transform = '';
      st.frame.removeAttribute('data-scale');
      return;
    }
    var w = st.frame.clientWidth, h = st.frame.clientHeight;
    if (!w || !h) return;                       /* nothing to fit into yet */
    var s = Math.min(w / st.vw, h / st.vh, 1);  /* scale down, never up */
    /* The transform sits on the iframe itself, the click target, never on an
       ancestor: a scaled ancestor would also break the large stage (N2). */
    f.style.width = st.vw + 'px';
    f.style.height = st.vh + 'px';
    f.style.position = 'absolute';
    f.style.left = Math.round((w - st.vw * s) / 2) + 'px';
    f.style.top = Math.round((h - st.vh * s) / 2) + 'px';
    f.style.transform = 'scale(' + s + ')';
    st.frame.setAttribute('data-scale', s.toFixed(3));
  }

  function fitAll() { stages.forEach(fit); }

  /* ===== Large stage (N2, N3) ===== */

  function hosts(st, on) {
    for (var el = st.frame.parentElement; el; el = el.parentElement) {
      el.classList.toggle('stage-max-host', on);
    }
  }

  function buttons(st, on) {
    if (!st.slide) return;
    [].forEach.call(st.slide.querySelectorAll('[data-stage="maximize"]'), function (b) {
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  function enterMax(st) {
    if (maxed === st) return;
    if (maxed) exitMax();
    load(st);
    maxed = st;
    hosts(st, true);
    st.frame.classList.add('is-max');
    root.classList.add('stage-max-on');
    if (!closer) {
      closer = doc.createElement('button');
      closer.type = 'button';
      closer.className = 'stage-close';
      closer.addEventListener('click', exitMax);
    }
    closer.textContent = LABELS[lang()].close;
    closer.title = LABELS[lang()].closeTitle;
    doc.body.appendChild(closer);
    buttons(st, true);
    fit(st);
    tell(st, { type: 'stage:maximize', on: true });
  }

  function exitMax() {
    if (!maxed) return;
    var st = maxed;
    maxed = null;
    st.frame.classList.remove('is-max');
    root.classList.remove('stage-max-on');
    hosts(st, false);
    if (closer && closer.parentNode) closer.parentNode.removeChild(closer);
    buttons(st, false);
    fit(st);
    tell(st, { type: 'stage:maximize', on: false });
    refresh();
  }

  function toggleMax(st) { if (maxed === st) exitMax(); else enterMax(st); }

  function stageOfActiveSlide() {
    var active = activeSlide(visibleSlides());
    for (var i = 0; i < stages.length; i++) {
      if (stages[i].slide === active || (!stages[i].slide && stages.length === 1)) return stages[i];
    }
    return null;
  }

  function deckStep(dir) {
    var api = window.SlideDeck || window.slideEngine || window.__slideEngine;
    if (api && typeof api[dir] === 'function') api[dir]();
  }

  /* ===== Wiring ===== */

  function typing(t) {
    return t && (t.isContentEditable || /^(input|textarea|select)$/i.test(t.tagName || ''));
  }

  function onKey(e) {
    if (e.metaKey || e.ctrlKey || e.altKey || typing(e.target)) return;
    var k = e.key;
    if (maxed) {
      if (k === 'Escape' || k === 'v' || k === 'V') {
        e.preventDefault(); e.stopPropagation(); exitMax();
      } else if (DECK_KEYS.indexOf(k) > -1) {
        /* Capture phase, so this runs before the deck: while a stage fills the
           window, an arrow key must not move the slide behind it unseen. */
        e.stopPropagation();
        /* No scrolling behind it either. Space keeps its job on a button. */
        var onButton = e.target && e.target.closest && e.target.closest('button,a[href],summary');
        if (!(k === ' ' && onButton)) e.preventDefault();
      }
      return;
    }
    if (k === 'v' || k === 'V') {
      var st = stageOfActiveSlide();
      if (st) { e.preventDefault(); e.stopPropagation(); enterMax(st); }
    }
  }

  function onMessage(e) {
    var d = e.data;
    if (!d || typeof d !== 'object' || typeof d.type !== 'string' || d.type.indexOf('stage:') !== 0) return;
    var st = forFrameWindow(e.source);
    if (!st) return;                            /* not one of our frames */
    if (d.type === 'stage:ready') {
      st.ready = true;
      st.frame.setAttribute('data-ready', 'yes');
      fit(st);
      tell(st, { type: 'stage:maximize', on: maxed === st });
    } else if (d.type === 'stage:maximize') {
      if (d.on === true) enterMax(st);
      else if (d.on === false) { if (maxed === st) exitMax(); }
      else toggleMax(st);
    } else if (d.type === 'stage:key') {
      if (d.key === 'v') toggleMax(st);
      else if (d.key === 'Escape') { if (maxed === st) exitMax(); }
      else if (!maxed && d.key === 'PageDown') deckStep('next');
      else if (!maxed && d.key === 'PageUp') deckStep('prev');
    }
  }

  function bindButtons() {
    stages.forEach(function (st) {
      if (!st.slide) return;
      [].forEach.call(st.slide.querySelectorAll('[data-stage]'), function (b) {
        var what = b.getAttribute('data-stage');
        if (what === 'maximize') {
          b.setAttribute('aria-pressed', 'false');
          b.addEventListener('click', function (e) { e.preventDefault(); toggleMax(st); });
        } else if (what === 'restart') {
          b.addEventListener('click', function (e) { e.preventDefault(); restart(st); });
        }
      });
    });
  }

  function start() {
    discover();
    if (!stages.length) return;
    bindButtons();
    window.addEventListener('keydown', onKey, true);
    window.addEventListener('message', onMessage);
    window.addEventListener('resize', fitAll);
    if (window.ResizeObserver) {
      var ro = new ResizeObserver(function (entries) {
        entries.forEach(function (en) {
          for (var i = 0; i < stages.length; i++) if (stages[i].frame === en.target) fit(stages[i]);
        });
      });
      stages.forEach(function (st) { ro.observe(st.frame); });
    }

    /* Under reduced motion every stage loads at once: each simulation then
       computes its end state, and no slide is left with an empty frame. */
    if (reduced()) {
      loadAll();
    } else {
      if (window.IntersectionObserver) {
        var io = new IntersectionObserver(refresh, { threshold: [0, 0.25, 0.55, 0.9] });
        [].forEach.call(doc.querySelectorAll('.slide'), function (s) { io.observe(s); });
      }
      var api = window.SlideDeck;
      if (api && typeof api.on === 'function') {
        try { api.on('slidechange', refresh); } catch (err) { /* older engine */ }
      }
      refresh();
    }

    /* Paper shows every stage. */
    window.addEventListener('beforeprint', loadAll);
    if (window.matchMedia) {
      var mq = matchMedia('print');
      if (mq.matches) loadAll();
      if (mq.addEventListener) mq.addEventListener('change', function (e) { if (e.matches) loadAll(); });
    }
  }

  /* The one global, for content and for checks from outside. */
  window.SlideStage = {
    list: function () {
      return stages.map(function (st) {
        return { id: st.frame.id || null, mode: st.mode, loaded: !!st.iframe,
                 ready: st.ready, maximized: maxed === st };
      });
    },
    maximize: function (i, on) {
      var st = stages[i];
      if (!st) return;
      if (on === false) { if (maxed === st) exitMax(); } else enterMax(st);
    },
    exit: exitMax,
    restart: function (i) { if (stages[i]) restart(stages[i]); },
    refresh: refresh
  };

  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', start);
  else start();
})();
