/* read: deck module, reference/modules.md § Module: read.
   Key R (or a data-deck="read" button) turns the deck into a reading view: the slides
   of the active track as one vertical document, each with a number and a "present
   from here" button above it and its speaker notes below, under normal page scroll.
   R or Esc returns to the exact slide and step the deck was on (or to the slide a
   number jump or a goto button picked while reading). Theme, language, track and the
   cover keys keep working. data-read-default on the deck (or <html>) opens the deck
   in this view, for a copy that is sent to be read rather than presented;
   data-read-default="off" switches that off again.
   While reading, <html> carries the class deck-read and document gets the event
   "deckread:change" {read}; other modules use either to stand aside. */
(function () {
  'use strict';
  var D = window.SlideDeck;
  if (!D || typeof D.use !== 'function') return;
  /* a presenter preview (data-deck-preview, presenter module) is a copy that shows
     slides: a send copy's data-read-default must not turn it into a document */
  if (document.documentElement.hasAttribute('data-deck-preview')) return;

  /* i18n:start */
  var TEXT = {
    en: { view: 'Reading view', present: 'Present', here: 'Present from here', notes: 'Notes',
          open: 'Reading view opened', closed: 'Back to the slides',
          help: 'Reading view: every slide with its notes, R or Esc returns' },
    de: { view: 'Leseansicht', present: 'Präsentieren', here: 'Ab hier präsentieren', notes: 'Notizen',
          open: 'Leseansicht geöffnet', closed: 'Zurück zu den Folien',
          help: 'Leseansicht: alle Folien mit Notizen, R oder Esc zurück' }
  };
  /* i18n:end */

  var root = document.documentElement;
  var reading = false, target = null, bilingual = false, built = [], bar = null, bar2 = null, live = null;

  function el(tag, cls, parent) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (parent) parent.appendChild(e);
    return e;
  }
  /* a text in both languages; the engine stylesheet hides the inactive one */
  function pair(parent, key) {
    ['en', 'de'].forEach(function (l) {
      var sp = el('span', '', parent);
      sp.setAttribute('data-' + l, '');
      sp.textContent = TEXT[l][key];
    });
    return parent;
  }
  function opt(name) {
    var deck = document.querySelector('.deck');
    var v = deck ? deck.getAttribute(name) : null;
    return v == null ? root.getAttribute(name) : v;
  }
  function deck() { return document.querySelector('.deck') || document.body; }
  /* an instant scroll: the deck to its top, or `node` into view */
  function jump(node) {
    if (!node) { deck().scrollTop = 0; return; }
    try { node.scrollIntoView({ block: 'start', behavior: 'instant' }); } catch (e) { node.scrollIntoView(true); }
  }
  function say(key) { if (live) { live.textContent = ''; live.textContent = TEXT[D.state().lang === 'de' ? 'de' : 'en'][key]; } }
  function signal() {
    try { document.dispatchEvent(new CustomEvent('deckread:change', { detail: { read: reading } })); } catch (e) { /* old browser */ }
  }

  /* ============ the document: a head before and the notes after each slide ============ */
  function clear() {
    built.forEach(function (n) { if (n.parentNode) n.parentNode.removeChild(n); });
    built = [];
  }
  function build() {
    clear();
    var list = D.slides(), total = list.length;
    list.forEach(function (s, i) {
      var head = document.createElement('header');
      head.className = 'deck-read-head';
      var num = el('span', 'deck-read-num', head);
      num.textContent = (i + 1) + ' / ' + total;
      num.setAttribute('aria-hidden', 'true');
      var go = pair(el('button', 'deck-read-go', head), 'here');
      go.type = 'button';
      el('span', 'deck-read-sr', go).textContent = ' (' + (i + 1) + ' / ' + total + ')';
      go.addEventListener('click', function () { close(s); });
      s.parentNode.insertBefore(head, s);
      built.push(head);
      var a = s.querySelector('aside.notes');
      if (!a) return;
      var box = document.createElement('aside');
      box.className = 'deck-read-notes';
      pair(el('div', 'deck-read-notes__title', box), 'notes');
      el('div', 'deck-read-notes__body', box).innerHTML = a.innerHTML;
      s.parentNode.insertBefore(box, s.nextSibling);
      built.push(box);
    });
  }
  function chrome() {
    bar2 = el('div', 'deck-read-progress', document.body);
    bar2.setAttribute('aria-hidden', 'true');
    bar = el('div', 'deck-read-bar', document.body);
    bar.setAttribute('role', 'toolbar');
    pair(el('span', 'deck-read-label', bar), 'view');
    if (bilingual) {
      var l = el('button', 'deck-read-lang', bar);
      l.type = 'button';
      l.setAttribute('data-deck', 'lang');
      l.textContent = 'DE / EN';
      l.setAttribute('aria-keyshortcuts', 'L');
    }
    var p = pair(el('button', 'deck-read-present', bar), 'present');
    p.type = 'button';
    p.setAttribute('data-deck', 'read');
    p.setAttribute('aria-keyshortcuts', 'R');
    if (!live) {
      live = el('div', 'deck-read-live', document.body);
      live.setAttribute('aria-live', 'polite');
      live.setAttribute('aria-atomic', 'true');
    }
  }
  function unchrome() {
    [bar, bar2].forEach(function (n) { if (n && n.parentNode) n.parentNode.removeChild(n); });
    bar = bar2 = null;
  }
  function progress() {
    if (!bar2) return;
    var d = deck(), room = d.scrollHeight - d.clientHeight;
    bar2.style.width = (room > 0 ? Math.min(100, Math.max(0, d.scrollTop / room * 100)) : 100) + '%';
  }

  /* ============ open and close ============ */
  function open() {
    if (reading) return;
    var st = D.state();
    target = D.slides()[st.index] || null;
    reading = true;
    /* the engine stops picking the slide from scroll, leaves the scroll keys to the
       page and marks no slide inert: every slide is content while reading */
    D.pauseTracking();
    build();
    chrome();
    root.classList.add('deck-read');
    var d = deck();
    if (!d.hasAttribute('tabindex')) { d.setAttribute('tabindex', '-1'); d.setAttribute('data-read-tabindex', ''); }
    if (!document.activeElement || document.activeElement === document.body) { try { d.focus({ preventScroll: true }); } catch (e) { /* old browser */ } }
    if (target && st.index > 0) jump(target.previousElementSibling || target);
    else jump();
    progress();
    say('open');
    signal();
  }
  /* back to the slide view, at `at` (a slide) or at the slide the deck was on */
  function close(at) {
    if (!reading) return;
    reading = false;
    clear();
    root.classList.remove('deck-read');
    var d = deck();
    if (d.hasAttribute('data-read-tabindex')) { d.removeAttribute('tabindex'); d.removeAttribute('data-read-tabindex'); }
    var list = D.slides(), dest = at || target, i = list.indexOf(dest);
    if (i < 0) { i = D.state().index; dest = list[i]; }
    /* an instant scroll, then the engine takes the slide from it: no transition, and
       the step stays when the slide is the same one */
    if (dest) jump(dest);
    D.resumeTracking();
    say('closed');
    unchrome();
    signal();
  }
  function toggle() { if (reading) close(); else open(); }

  /* ============ while reading: the page scrolls, the deck stands still ============ */
  /* The deck is the scroller and its scroll does not bubble, hence the capture phase. */
  window.addEventListener('scroll', function () { if (reading) progress(); }, true);
  document.addEventListener('click', function (e) {
    var b = e.target && e.target.closest ? e.target.closest('[data-deck="read"]') : null;
    if (!b) return;
    e.preventDefault();
    toggle();
  });

  D.use({
    name: 'read',
    keys: {
      r: function () { toggle(); return true; },
      escape: function () {
        if (!reading) return false;
        var help = document.querySelector('.deck-help');
        if ((help && !help.hidden) || root.classList.contains('deck-zoomed')) return false;
        close();
        return true;
      }
    },
    help: [{ key: 'R', de: TEXT.de.help, en: TEXT.en.help }],
    init: function (api) {
      bilingual = !!document.querySelector('[data-de], [data-en]');
      api.on('slidechange', function (d) { if (reading) target = d.slide; });
      api.on('trackchange', function () {
        if (!reading) return;
        target = api.slides()[api.state().index] || target;
        build();
      });
      var v = opt('data-read-default');
      if (v !== null && v !== 'off' && v !== 'false') open();
    }
  });
})();
