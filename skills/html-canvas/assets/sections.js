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
    var current = null, queued = false, wanted = null;
    /* the section a link or the address went to: on a page too short to bring it to
       the top it still counts while it is in view */
    function fromHash() {
      var h = location.hash ? decodeURIComponent(location.hash.slice(1)) : '';
      wanted = null;
      targets.forEach(function (t) { if (t.el.id === h) wanted = t; });
    }
    function spy() {
      queued = false;
      var line = window.innerHeight * 0.3, pick = targets[0];
      targets.forEach(function (t) { if (t.el.getBoundingClientRect().top <= line) pick = t; });
      /* at the very bottom the last section counts, however short it is */
      if (window.innerHeight + window.scrollY >= doc.documentElement.scrollHeight - 2) pick = targets[targets.length - 1];
      if (wanted) {
        var r = wanted.el.getBoundingClientRect();
        if (r.top >= -1 && r.top < window.innerHeight) pick = wanted;
        else wanted = null;
      }
      if (pick === current) return;
      if (current) current.a.removeAttribute('aria-current');
      current = pick;
      current.a.setAttribute('aria-current', 'location');
    }
    window.addEventListener('scroll', function () {
      if (!queued) { queued = true; requestAnimationFrame(spy); }
    }, { passive: true });
    window.addEventListener('resize', spy);
    window.addEventListener('hashchange', function () { fromHash(); spy(); });
    fromHash();
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

/* @block: knowledge */
(function () {
  /* Terms marked [data-know] open their knowledge in a panel beside the page: no
     pop-up, the page makes room (a deck scales its slide to the left). The pack is
     JSON in #knowledge-pack, or fetched from data-knowledge-src with the embedded
     one as fallback. Layout of the term view after the entity page of an
     associative podcast player: kind, name, aliases, summary, relations, passages
     with their source, sources. */
  var doc = document, root = doc.documentElement;
  var T = {
    kind: ['Wissen', 'Knowledge'], close: ['Schließen', 'Close'], back: ['Zurück', 'Back'],
    rel: ['Zusammenhang', 'Related'], pass: ['Belegstellen', 'Passages'], src: ['Quellen', 'Sources'],
    here: ['Begriffe hier', 'Terms here'], none: ['Hier ist kein Begriff markiert.', 'No term is marked here.'],
    as: ['Stand', 'As of'], help: ['Wissen zu den Begriffen', 'Knowledge for the terms']
  };
  function pair(k) { return '<span data-de>' + T[k][0] + '</span><span data-en>' + T[k][1] + '</span>'; }
  function el(tag, cls, parent, html) {
    var e = doc.createElement(tag);
    if (cls) e.className = cls;
    if (html) e.innerHTML = html;
    if (parent) parent.appendChild(e);
    return e;
  }
  function text(tag, cls, parent, s) { var e = el(tag, cls, parent); e.textContent = s; return e; }
  /* a pack can come from any tool: follow only web, mail and scheme-less links */
  function safeHref(h) {
    var m = /^\s*([a-z][a-z0-9+.-]*):/i.exec(h || '');
    return !!h && (!m || /^(https?|mailto)$/i.test(m[1]));
  }
  function link(parent, label, href) {
    if (!safeHref(href)) { parent.appendChild(doc.createTextNode(label)); return; }
    var a = text('a', '', parent, label);
    a.href = href; a.target = '_blank'; a.rel = 'noopener';
  }
  function english() {
    var l = root.getAttribute('data-lang') || root.getAttribute('lang') || 'en';
    return l.slice(0, 2).toLowerCase() !== 'de';
  }
  function inline() {
    var s = doc.getElementById('knowledge-pack');
    if (!s) return null;
    try { return JSON.parse(s.textContent); } catch (e) { return null; }
  }
  var deckEl = doc.querySelector('.deck');
  var pack = null, byId = {}, panel, body, head, back, foot, owner = null, mode = null, cur = null, hist = [];
  /* where the focus goes on close: back to what opened the panel from the keyboard,
     nowhere after a pointer (a focused term would take the next Space or Enter,
     which in a deck has to move the slides on) */
  var returnTo = null, closeBtn = null;

  function deck() { return deckEl && window.SlideDeck ? window.SlideDeck : null; }
  function scope() {
    var d = deck();
    if (!d) return doc.body;
    var st = d.state(), list = d.slides();
    return list[st.index] || doc.body;
  }
  function build() {
    panel = el('aside', 'kp-panel', doc.body);
    panel.id = 'kp-panel';
    panel.hidden = true;
    panel.setAttribute('aria-labelledby', 'kp-head');
    var bar = el('div', 'kp-bar', panel);
    back = el('button', 'kp-back', bar, '‹ ' + pair('back'));
    back.type = 'button';
    back.hidden = true;
    head = el('span', 'kp-kind', bar, pair('kind'));
    head.id = 'kp-head';
    var x = el('button', 'kp-close', bar, '×');
    x.type = 'button';
    closeBtn = x;
    body = el('div', 'kp-body', panel);
    foot = el('p', 'kp-foot', panel);
    if (pack.title || (pack.source && pack.source.revision)) {
      var s = pack.source || {};
      foot.innerHTML = pair('as') + ': ';
      foot.appendChild(doc.createTextNode([pack.title, s.revision, s.generated].filter(Boolean).join(' · ')));
    } else foot.hidden = true;
    x.addEventListener('click', close);
    back.addEventListener('click', function () {
      var h = hist.pop();
      if (!h) return;
      var t = render(h.mode, h.id);
      if (t) t.focus({ preventScroll: true });
    });
    panel.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('[data-kp-go]') : null;
      if (b) { e.preventDefault(); go('term', b.getAttribute('data-kp-go')); }
    });
    window.addEventListener('resize', layout);
  }
  function section(cls, label) {
    var s = el('section', cls, body);
    el('h3', '', s, pair(label));
    return s;
  }
  function termLink(id, label, parent) {
    if (byId[id]) {
      var b = text('button', '', parent, label);
      b.type = 'button';
      b.setAttribute('data-kp-go', id);
      return b;
    }
    return text('span', '', parent, label);
  }
  function renderTerm(t) {
    if (t.type) text('p', 'kp-type', body, t.type);
    var h = text('h2', 'kp-title', body, t.label);
    h.tabIndex = -1;
    if (t.aliases && t.aliases.length) text('p', 'kp-aliases', body, t.aliases.join(' · '));
    if (t.summary) text('p', 'kp-summary', body, t.summary);
    if (t.neighbours && t.neighbours.length) {
      var ul = el('ul', '', section('kp-rel', 'rel'));
      t.neighbours.forEach(function (n) {
        var li = el('li', '', ul);
        if (n.rel) text('span', 'kp-relv', li, n.rel);
        termLink(n.id, n.label || n.id, li);
      });
    }
    if (t.passages && t.passages.length) {
      var ol = el('ol', '', section('kp-pass', 'pass'));
      t.passages.forEach(function (p) {
        var li = el('li', '', ol);
        text('blockquote', '', li, p.text);
        var s = p.source || {}, c = el('cite', '', li), label = [s.title, s.locator].filter(Boolean).join(' · ');
        link(c, label, s.href);
      });
    }
    if (t.sources && t.sources.length) {
      var su = el('ul', '', section('kp-src', 'src'));
      t.sources.forEach(function (s) {
        var li = el('li', '', su);
        link(li, s.title, s.href);
      });
    }
    return h;
  }
  function renderList() {
    var h = el('h2', 'kp-title', body, pair('here'));
    h.tabIndex = -1;
    var seen = {}, ids = [];
    [].forEach.call(scope().querySelectorAll('[data-know]'), function (n) {
      var id = n.getAttribute('data-know');
      if (byId[id] && !seen[id]) { seen[id] = 1; ids.push(id); }
    });
    var s = el('section', 'kp-list', body);
    if (!ids.length) { el('p', 'kp-empty', s, pair('none')); return h; }
    var ul = el('ul', '', s);
    ids.forEach(function (id) {
      var li = el('li', '', ul);
      termLink(id, byId[id].label, li);
      if (byId[id].type) text('span', 'kp-lt', li, byId[id].type);
    });
    return h;
  }
  function render(m, id) {
    mode = m; cur = id;
    body.textContent = '';
    body.scrollTop = 0;
    back.hidden = !hist.length;
    return m === 'term' && byId[id] ? renderTerm(byId[id]) : renderList();
  }
  function go(m, id) {
    if (mode) hist.push({ mode: mode, id: cur });
    var h = render(m, id);
    if (h) h.focus({ preventScroll: true });
  }
  function layout() {
    if (!panel || panel.hidden || !deckEl) return;
    var vw = root.clientWidth || window.innerWidth, pw = panel.getBoundingClientRect().width;
    var s = vw < 900 ? 1 : Math.max(0.3, (vw - pw - 8) / vw);
    root.style.setProperty('--kp-scale', String(s));
  }
  function open(m, id, trigger, byKeyboard) {
    if (!panel) build();
    var a = doc.activeElement;
    returnTo = byKeyboard ? (trigger || (a && a !== doc.body ? a : null)) : null;
    if (owner && owner !== trigger) owner.setAttribute('aria-expanded', 'false');
    owner = trigger || null;
    if (owner) owner.setAttribute('aria-expanded', 'true');
    hist = [];
    mode = null;
    var en = english();
    closeBtn.setAttribute('aria-label', en ? T.close[1] : T.close[0]);
    closeBtn.title = (en ? T.close[1] : T.close[0]) + ' (Esc)';
    panel.hidden = false;
    root.classList.add('kp-open');
    layout();
    var h = render(m, id);
    if (h) h.focus({ preventScroll: true });
  }
  function isOpen() { return !!panel && !panel.hidden; }
  function close() {
    if (!isOpen()) return;
    panel.hidden = true;
    root.classList.remove('kp-open');
    mode = null;
    var a = doc.activeElement, inside = !a || a === doc.body || panel.contains(a) || a === owner;
    if (owner) owner.setAttribute('aria-expanded', 'false');
    if (inside) {
      if (returnTo && doc.contains(returnTo)) returnTo.focus({ preventScroll: true });
      else if (a && a !== doc.body && a.blur) a.blur();
    }
    owner = null;
    returnTo = null;
  }
  function toggleList() { if (isOpen()) close(); else open('list', null, null, true); }

  function wire(d) {
    d.use({
      name: 'knowledge',
      keys: {
        k: function () { toggleList(); return true; }
      },
      help: [{ key: 'K', de: T.help[0], en: T.help[1] }],
      init: function (api) {
        api.on('slidechange', function () {
          if (!isOpen() || mode !== 'list') return;
          var had = panel.contains(doc.activeElement);
          hist = [];
          var t = render('list', null);
          if (had && t) t.focus({ preventScroll: true });
        });
      }
    });
  }
  function start(p) {
    var triggers = [].slice.call(doc.querySelectorAll('[data-know]'));
    pack = p && p.terms ? p : null;
    if (pack) pack.terms.forEach(function (t) { byId[t.id] = t; });
    triggers.forEach(function (t) {
      var id = t.getAttribute('data-know');
      if (!byId[id]) { t.setAttribute('aria-disabled', 'true'); t.disabled = true; return; }
      t.setAttribute('aria-expanded', 'false');
      t.setAttribute('aria-controls', 'kp-panel');
      t.addEventListener('click', function (e) {
        e.preventDefault();
        if (isOpen() && owner === t && mode === 'term' && cur === id) { close(); return; }
        /* a click from Enter or Space carries detail 0, a pointer click 1 or more */
        open('term', id, t, e.detail === 0);
      });
    });
    if (!pack) return;
    /* Esc closes the panel before anything else on the page sees it (a reading view or
       a deck module would otherwise take it first); an open help overlay goes first */
    window.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape' || !isOpen() || e.ctrlKey || e.metaKey || e.altKey) return;
      var help = doc.querySelector('.deck-help');
      if (help && !help.hidden) return;
      close();
      e.preventDefault();
      e.stopImmediatePropagation();
    }, true);
    if (deckEl) {
      root.classList.add('kp-deck');
      if (window.SlideDeck) wire(window.SlideDeck);
      else doc.addEventListener('slidedeck:ready', function () { if (window.SlideDeck) wire(window.SlideDeck); }, { once: true });
    } else {
      doc.addEventListener('keydown', function (e) {
        if (e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented) return;
        var t = e.target, tag = t && t.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (t && t.isContentEditable)) return;
        if (e.key === 'k' || e.key === 'K') { toggleList(); e.preventDefault(); }
      });
    }
  }
  function boot() {
    var holder = root.hasAttribute('data-knowledge-src') ? root : doc.querySelector('[data-knowledge-src]');
    var src = holder && holder.getAttribute('data-knowledge-src');
    var embedded = inline();
    if (src && window.fetch) {
      fetch(src).then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function (p) { start(p && p.terms ? p : embedded); }, function () { start(embedded); });
    } else start(embedded);
  }
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
