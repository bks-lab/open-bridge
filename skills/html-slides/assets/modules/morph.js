/* deck module: morph (reference/modules.md, section "morph")
   Elements with the same data-morph="name" on the slide left and the slide reached
   carry a view-transition-name during the move and morph through
   document.startViewTransition (the rest of the screen cross-fades). A slide pair
   without a shared name moves as before. No View Transitions support or reduced
   motion: an instant change. Any key during a morph finishes it at once
   (skipTransition), so fast presses never queue animations. Option:
   data-morph-duration="600" (ms) on the deck or <html>. */
(function () {
  'use strict';
  var D = window.SlideDeck;
  if (!D || typeof D.use !== 'function') return;

  var active = null, token = 0, named = [];

  function noop() {}
  function ident(name) { return 'morph-' + String(name).trim().replace(/[^A-Za-z0-9_-]/g, '_'); }
  /* name -> the first element carrying it on this slide (a name must be unique on screen) */
  function names(slide) {
    var out = {};
    [].forEach.call(slide.querySelectorAll('[data-morph]'), function (e) {
      var n = (e.getAttribute('data-morph') || '').trim();
      if (n && !out[n] && !e.closest('aside.notes')) out[n] = e;
    });
    return out;
  }
  function tag(e, n) { e.style.viewTransitionName = n; named.push(e); }
  function clear() { named.forEach(function (e) { e.style.viewTransitionName = ''; }); named = []; }
  function skip() {
    var t = active;
    active = null;
    if (t) { try { t.skipTransition(); } catch (e) { /* already done */ } }
  }

  D.use({
    name: 'morph',
    transition: function (from, to, apply) {
      skip();
      clear();
      var my = ++token;
      if (typeof document.startViewTransition !== 'function' || D.reducedMotion() || !from || !to) return apply();
      var a = names(from), b = names(to);
      var shared = Object.keys(a).filter(function (k) { return b[k]; });
      if (!shared.length) return apply();
      shared.forEach(function (k) { tag(a[k], ident(k)); });
      var vt;
      try {
        vt = document.startViewTransition(function () {
          if (my === token) {
            clear();
            shared.forEach(function (k) { tag(b[k], ident(k)); });
          }
          apply({ instant: true });
        });
      } catch (err) { clear(); return apply(); }
      active = vt;
      var done = function () { if (my === token) { clear(); active = null; } };
      if (vt.ready) vt.ready.catch(noop);
      if (vt.updateCallbackDone) vt.updateCallbackDone.catch(noop);
      if (vt.finished) vt.finished.then(done, done); else done();
    },
    init: function () {
      var deck = document.querySelector('.deck'), root = document.documentElement;
      var ms = parseInt((deck && deck.getAttribute('data-morph-duration')) || root.getAttribute('data-morph-duration') || '', 10);
      if (ms > 0) root.style.setProperty('--morph-duration', ms + 'ms');
      document.addEventListener('keydown', function () { if (active) skip(); }, true);
    }
  });
})();
