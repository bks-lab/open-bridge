/* html-canvas section scripts: the behaviour of the blocks that need one, one marker
   line per block, the same names as in sections.css. new-page.py copies the parts a
   page asks for into the page's section-scripts region, so a page without these
   blocks carries none of this. Every part degrades: without script the markup still
   reads (a term links to its entry, a chart keeps its table next to it). */

/* @block: glossary */
(function () {
  var doc = document, root = doc.documentElement;
  var triggers = [].slice.call(doc.querySelectorAll('a[data-term], dfn[data-term]'));
  if (!triggers.length) return;
  var native = typeof HTMLElement !== 'undefined' && 'popover' in HTMLElement.prototype &&
               typeof HTMLElement.prototype.showPopover === 'function';
  function entry(key) { return doc.getElementById('gl-' + key); }
  function clone(node) {
    /* clones keep data-de and data-en, so the language switch reaches them */
    var c = node.cloneNode(true);
    if (c.removeAttribute) c.removeAttribute('id');
    [].forEach.call(c.querySelectorAll ? c.querySelectorAll('[id]') : [], function (x) { x.removeAttribute('id'); });
    return c;
  }
  var pop = null, head = null, body = null, more = null, owner = null;
  function build() {
    pop = doc.createElement('div');
    pop.className = 'gl-pop';
    pop.id = 'gl-pop';
    pop.setAttribute('popover', 'auto');
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-labelledby', 'gl-pop-h');
    pop.tabIndex = -1;
    head = doc.createElement('span'); head.className = 'gl-pop-h'; head.id = 'gl-pop-h';
    body = doc.createElement('div'); body.className = 'gl-pop-b';
    more = doc.createElement('a'); more.className = 'gl-pop-more';
    more.innerHTML = '<span data-de>Im Glossar</span><span data-en>In the glossary</span>';
    more.addEventListener('click', function () { pop.hidePopover(); });
    pop.appendChild(head); pop.appendChild(body); pop.appendChild(more);
    doc.body.appendChild(pop);
    /* beforetoggle fires at once (toggle arrives later), so the state is right before the next trigger */
    function closing(e) {
      if (e.newState !== 'closed' || !owner) return;
      var back = owner; owner = null;
      back.setAttribute('aria-expanded', 'false');
      var a = doc.activeElement;
      if (!a || a === doc.body || pop.contains(a)) back.focus({ preventScroll: true });
    }
    pop.addEventListener('beforetoggle', closing);
    pop.addEventListener('toggle', closing);
    window.addEventListener('resize', function () { if (owner) place(owner); });
  }
  function place(t) {
    var r = t.getBoundingClientRect(), w = pop.offsetWidth, h = pop.offsetHeight;
    var vw = root.clientWidth, vh = window.innerHeight;
    var left = Math.max(16, Math.min(r.left, vw - w - 16));
    var top = r.bottom + 6;
    if (top + h > vh - 8 && r.top - h - 6 > 8) top = r.top - h - 6;
    pop.style.left = left + 'px';
    pop.style.top = top + 'px';
  }
  function show(t) {
    var key = t.getAttribute('data-term'), dt = entry(key);
    if (!dt) return false;
    if (!native) { location.hash = 'gl-' + key; return true; }
    if (!pop) build();
    if (owner && owner !== t) owner.setAttribute('aria-expanded', 'false');
    head.textContent = '';
    head.appendChild(clone(dt.querySelector('dfn') || dt));
    body.textContent = '';
    for (var dd = dt.nextElementSibling; dd && dd.tagName === 'DD'; dd = dd.nextElementSibling) {
      var p = doc.createElement('div');
      [].forEach.call(dd.childNodes, function (n) { p.appendChild(clone(n)); });
      body.appendChild(p);
    }
    more.setAttribute('href', '#gl-' + key);
    owner = t;
    t.setAttribute('aria-expanded', 'true');
    if (!pop.matches(':popover-open')) pop.showPopover();
    place(t);
    pop.focus({ preventScroll: true });
    return true;
  }
  triggers.forEach(function (t) {
    if (!entry(t.getAttribute('data-term'))) return;
    t.setAttribute('aria-haspopup', 'dialog');
    t.setAttribute('aria-expanded', 'false');
    if (native) t.setAttribute('aria-controls', 'gl-pop');
    if (t.tagName === 'DFN') {
      t.tabIndex = 0;
      t.setAttribute('role', 'button');
      t.addEventListener('keydown', function (e) {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        e.preventDefault();
        show(t);
      });
    }
    t.addEventListener('click', function (e) {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button > 0) return;
      if (!native && t.tagName === 'A') return;   /* the link jumps on its own */
      if (show(t)) e.preventDefault();
    });
  });
})();

/* @block: toc */
(function () {
  var doc = document;
  [].forEach.call(doc.querySelectorAll('nav.toc'), function (nav) {
    var list = nav.querySelector('ol');
    if (!list) return;
    if (nav.getAttribute('data-toc') === 'auto' && !list.querySelector('li')) {
      [].forEach.call(doc.querySelectorAll('main h2'), function (h, i) {
        if (nav.contains(h)) return;
        var host = h.id ? h : (h.closest('section[id]') || h.closest('.blk[id]'));
        if (!host) { h.id = 'toc-' + (i + 1); host = h; }
        var li = doc.createElement('li'), a = doc.createElement('a');
        a.href = '#' + host.id;
        [].forEach.call(h.childNodes, function (n) {
          var c = n.cloneNode(true);
          if (c.removeAttribute) c.removeAttribute('id');
          a.appendChild(c);
        });
        li.appendChild(a);
        list.appendChild(li);
      });
    }
    var links = [].slice.call(list.querySelectorAll('a[href^="#"]')), targets = [];
    links.forEach(function (a) {
      var el = doc.getElementById(decodeURIComponent(a.getAttribute('href').slice(1)));
      if (el) targets.push({ a: a, el: el });
    });
    if (!targets.length) return;
    var current = null, queued = false;
    function spy() {
      queued = false;
      var line = window.innerHeight * 0.3, pick = targets[0];
      targets.forEach(function (t) { if (t.el.getBoundingClientRect().top <= line) pick = t; });
      /* at the very bottom the last section counts, however short it is */
      if (window.innerHeight + window.scrollY >= doc.documentElement.scrollHeight - 2) pick = targets[targets.length - 1];
      if (pick === current) return;
      if (current) current.a.removeAttribute('aria-current');
      current = pick;
      current.a.setAttribute('aria-current', 'location');
    }
    window.addEventListener('scroll', function () {
      if (!queued) { queued = true; requestAnimationFrame(spy); }
    }, { passive: true });
    window.addEventListener('resize', spy);
    spy();
  });
})();

/* @block: alt-table */
(function () {
  [].forEach.call(document.querySelectorAll('.alt-fig'), function (fig) {
    var btn = fig.querySelector('.alt-toggle'), chart = fig.querySelector('.alt-chart');
    var table = btn && document.getElementById(btn.getAttribute('aria-controls') || '');
    if (!btn || !chart || !table) return;
    fig.classList.add('js');
    btn.hidden = false;
    btn.addEventListener('click', function () {
      var on = !fig.classList.contains('as-table');
      fig.classList.toggle('as-table', on);
      btn.setAttribute('aria-expanded', on ? 'true' : 'false');
    });
  });
})();

/* @block: print */
(function () {
  var opened = [];
  function before() {
    [].forEach.call(document.querySelectorAll('details:not([open])'), function (d) { d.open = true; opened.push(d); });
  }
  function after() {
    opened.forEach(function (d) { d.open = false; });
    opened = [];
  }
  window.addEventListener('beforeprint', before);
  window.addEventListener('afterprint', after);
})();
