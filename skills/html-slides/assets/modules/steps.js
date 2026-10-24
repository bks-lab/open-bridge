/* deck module: steps (reference/modules.md, section "steps")
   - data-step on an element reveals it on a forward move; data-step="2" puts it on
     step 2 (same number = same step); data-steps on a container makes each child a step.
   - data-step-effect="rise|dim|highlight" (on the element or the data-steps container).
   - data-lines="1-3|5|*" on a code block (pre or code) highlights one line group per
     step; the first group shows with the block, "*" shows every line.
   - The engine owns the step number and the deep link (#id.step); this module owns
     what a step shows. Backward onto a slide shows all of its steps. */
(function () {
  'use strict';
  var D = window.SlideDeck;
  if (!D || typeof D.use !== 'function') return;

  var plans = typeof WeakMap === 'function' ? new WeakMap() : null;
  var navDir = 0, navAt = 0;

  /* "1-3,7|5|*" -> [[1,2,3,7], [5], null]; null shows every line */
  function groupsOf(spec) {
    return String(spec || '').split('|').map(function (g) {
      g = g.trim();
      if (!g || g === '*' || g === 'all') return null;
      var set = [];
      g.split(',').forEach(function (part) {
        var m = /^\s*(\d+)\s*(?:-\s*(\d+))?\s*$/.exec(part);
        if (!m) return;
        var a = parseInt(m[1], 10), b = m[2] ? parseInt(m[2], 10) : a;
        for (var i = Math.min(a, b); i <= Math.max(a, b); i++) set.push(i);
      });
      return set;
    });
  }

  /* Wrap every line of a code element in span.code-line, keeping highlight spans that
     cross a line break (each line gets its own shallow copy of them). */
  function splitLines(code) {
    if (code.querySelector('.code-line')) return [].slice.call(code.querySelectorAll('.code-line'));
    var segs = [];
    (function walk(node, chain) {
      [].forEach.call(node.childNodes, function (c) {
        if (c.nodeType === 3) segs.push({ text: c.nodeValue, chain: chain });
        else if (c.nodeType === 1) walk(c, chain.concat([c]));
      });
    })(code, []);
    var lines = [[]];
    segs.forEach(function (sg) {
      sg.text.split('\n').forEach(function (part, j) {
        if (j > 0) lines.push([]);
        if (part) lines[lines.length - 1].push({ text: part, chain: sg.chain });
      });
    });
    if (lines.length > 1 && !lines[lines.length - 1].length) lines.pop();
    code.textContent = '';
    return lines.map(function (line, i) {
      var span = document.createElement('span');
      span.className = 'code-line';
      span.setAttribute('data-line', String(i + 1));
      line.forEach(function (sg) {
        var node = document.createTextNode(sg.text);
        for (var k = sg.chain.length - 1; k >= 0; k--) {
          var w = sg.chain[k].cloneNode(false);
          w.appendChild(node);
          node = w;
        }
        span.appendChild(node);
      });
      code.appendChild(span);
      return span;
    });
  }

  function isStep(e, slide) {
    if (e.hasAttribute('data-step')) return true;
    var p = e.parentElement;
    return !!(p && p !== slide && p.hasAttribute('data-steps') && slide.contains(p));
  }

  /* Which step shows what on one slide: items [{el, at}], blocks [{lines, groups:[{at, set}]}] */
  function plan(slide) {
    if (plans && plans.has(slide)) return plans.get(slide);
    var items = [], blocks = [], n = 0;
    [].forEach.call(slide.querySelectorAll('[data-step], [data-steps] > *, [data-lines]'), function (e) {
      if (e.closest('aside.notes')) return;
      var at = 0;
      items.forEach(function (it) { if (it.el.contains(e) && it.at > at) at = it.at; });
      if (isStep(e, slide)) {
        var v = (e.getAttribute('data-step') || '').trim();
        if (/^\d+$/.test(v) && parseInt(v, 10) > 0) { at = parseInt(v, 10); n = Math.max(n, at); }
        else at = ++n;
        items.push({ el: e, at: at });
      }
      if (e.hasAttribute('data-lines')) {
        var code = e.matches('pre') && e.querySelector('code') ? e.querySelector('code') : e;
        var groups = groupsOf(e.getAttribute('data-lines')).map(function (set, j) {
          return { at: j === 0 ? at : ++n, set: set };
        });
        blocks.push({ lines: splitLines(code), groups: groups });
      }
    });
    var p = { items: items, blocks: blocks, max: n };
    if (plans) plans.set(slide, p);
    return p;
  }

  function render(slide, step) {
    if (!slide) return;
    var p = plan(slide);
    p.items.forEach(function (it) {
      var c = it.el.classList;
      c.toggle('step-hidden', it.at > step);
      c.toggle('step-shown', it.at <= step);
      c.toggle('step-current', step > 0 && it.at === step);
      c.toggle('step-past', it.at < step);
    });
    p.blocks.forEach(function (b) {
      var g = b.groups[0];
      b.groups.forEach(function (x) { if (x.at <= step) g = x; });
      b.lines.forEach(function (l, i) {
        var on = !g.set || g.set.indexOf(i + 1) > -1;
        l.classList.toggle('is-on', !!g.set && on);
        l.classList.toggle('is-dim', !on);
      });
    });
  }

  function currentSlide() { return D.slides()[D.current()]; }

  /* A deep link may name a step past the slide's last one: show the last. */
  function show(slide, step) {
    var p = slide ? plan(slide) : null;
    if (p && p.max > 0 && step > p.max && slide === currentSlide()) { D.setStep(p.max); return; }
    render(slide, step);
  }

  D.use({
    name: 'steps',
    step: function (dir) {
      var s = currentSlide(), p = s ? plan(s) : null;
      var next = p ? Math.min(D.step(), p.max) + dir : 0;
      if (!p || !p.max || next < 0 || next > p.max) { navDir = dir; navAt = Date.now(); return false; }
      navDir = 0;
      D.setStep(next);
      return true;
    },
    init: function () {
      [].forEach.call(document.querySelectorAll('.slide'), function (s) { render(s, 0); });
      show(currentSlide(), D.step());
      D.on('stepchange', function (e) { show(e.slide, e.step); });
      D.on('slidechange', function (e) {
        /* only a backward move (key, swipe, prev) lands on the last step; a jump, a
           deep link or a scroll lands on step 0 */
        var back = navDir === -1 && Date.now() - navAt < 2000;
        navDir = 0;
        var p = plan(e.slide);
        if (back && p.max > 0 && D.step() === 0) { D.setStep(p.max); return; }
        show(e.slide, D.step());
      });
    }
  });
})();
