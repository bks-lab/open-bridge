/* deck module: motion (reference/modules.md, section "motion")
   Motion that plays when its slide becomes active and resets when it leaves, so it
   plays again on the next visit:
   - data-count="1200" on an element: the number in its text counts up from
     data-count-from (default 0) in data-count-duration ms (default 1200); the text
     as written is the end state.
   - data-stagger on a container: its children enter one after another, data-stagger="120"
     sets the gap in ms (default 90).
   - data-draw on an svg or a shape: every stroke draws itself, data-draw="1600" sets the
     duration in ms (default 1200).
   - the html-canvas message flow (.flow-line, .msg-fwd, .msg-back) runs on its slide only.
   Reduced motion, print, the reading view (read module) and a presenter preview show
   the end state; the CSS hangs on :root.motion-ready, which only this script sets. */
(function () {
  'use strict';
  var D = window.SlideDeck;
  if (!D || typeof D.use !== 'function') return;
  var root = document.documentElement;
  /* a presenter preview is a still copy of the deck: nothing moves there */
  if (root.hasAttribute('data-deck-preview')) return;

  var SHAPES = 'path, line, polyline, polygon, circle, ellipse, rect';
  var NUM = /-?\d+(?:[.,]\d+)?/;
  var shown = null;

  function own(slide, sel) {
    return slide ? [].filter.call(slide.querySelectorAll(sel), function (e) { return !e.closest('aside.notes'); }) : [];
  }
  function ms(el, name) { var v = parseInt(el.getAttribute(name), 10); return v > 0 ? v : 0; }

  /* --- count-up --- */
  function stop(e) {
    if (e.__motionRaf) cancelAnimationFrame(e.__motionRaf);
    e.__motionRaf = 0;
    if (e.__motionText != null) e.textContent = e.__motionText;
  }
  function count(e) {
    var spec = e.getAttribute('data-count') || '', to = parseFloat(spec);
    if (isNaN(to)) return;
    var from = parseFloat(e.getAttribute('data-count-from')) || 0;
    var dec = (spec.split('.')[1] || '').length, dur = ms(e, 'data-count-duration') || 1200;
    var text = e.__motionText, m = NUM.exec(text), t0 = 0;
    function put(v) {
      var s = v.toFixed(dec);
      if (m && m[0].indexOf(',') > -1) s = s.replace('.', ',');
      e.textContent = m ? text.slice(0, m.index) + s + text.slice(m.index + m[0].length) : s;
    }
    stop(e);
    put(from);
    function frame(now) {
      if (!t0) t0 = now;
      var k = Math.min(1, (now - t0) / dur);
      if (k >= 1) { e.__motionRaf = 0; e.textContent = text; return; }
      put(from + (to - from) * (1 - Math.pow(1 - k, 3)));
      e.__motionRaf = requestAnimationFrame(frame);
    }
    e.__motionRaf = requestAnimationFrame(frame);
  }
  function finish() { [].forEach.call(document.querySelectorAll('[data-count]'), stop); }

  /* --- what the CSS needs: a child's place in its row, a stroke's length --- */
  function prepare() {
    [].forEach.call(document.querySelectorAll('[data-stagger]'), function (box) {
      [].forEach.call(box.children, function (c, i) { c.style.setProperty('--motion-i', String(i)); });
      if (ms(box, 'data-stagger')) box.style.setProperty('--motion-step', ms(box, 'data-stagger') + 'ms');
    });
    [].forEach.call(document.querySelectorAll('[data-draw]'), function (host) {
      var list = host.matches(SHAPES) ? [host] : [].slice.call(host.querySelectorAll(SHAPES));
      list.forEach(function (s) {
        var len = 0;
        try { len = Math.ceil(s.getTotalLength()); } catch (err) { len = 0; }
        if (!(len > 0)) return;
        s.style.strokeDasharray = len + ' ' + len;
        s.style.setProperty('--motion-len', len + 'px');
        if (ms(host, 'data-draw')) s.style.setProperty('--motion-draw', ms(host, 'data-draw') + 'ms');
        s.classList.add('motion-draw');
      });
    });
    [].forEach.call(document.querySelectorAll('[data-count]'), function (e) { e.__motionText = e.textContent; });
  }

  function live() { return root.classList.contains('motion-ready') && !root.classList.contains('deck-read'); }
  function enter(slide) {
    if (shown && shown !== slide) own(shown, '[data-count]').forEach(stop);
    shown = slide;
    if (live()) own(slide, '[data-count]').forEach(count);
  }

  D.use({
    name: 'motion',
    init: function () {
      prepare();
      root.classList.toggle('motion-ready', !D.reducedMotion());
      if (window.matchMedia) {
        var mq = matchMedia('(prefers-reduced-motion: reduce)');
        var follow = function () { root.classList.toggle('motion-ready', !mq.matches); if (mq.matches) finish(); };
        if (mq.addEventListener) mq.addEventListener('change', follow);
      }
      window.addEventListener('beforeprint', finish);
      document.addEventListener('deckread:change', function (e) { if (e.detail && e.detail.read) finish(); });
      enter(D.slides()[D.current()]);
      D.on('slidechange', function (e) { enter(e.slide); });
    }
  });
})();
