/* presenter: deck module (reference/modules.md, section "Module: presenter").
   Key P opens a presenter window: the current slide and what comes next as live previews,
   the notes, a clock, the elapsed time and a time budget per slide (data-time="90",
   seconds, or "1:30") and for the active track. In that window R records a rehearsal
   (actual time per slide, kept per deck and track) and A shows it as plan vs actual.
   Shift+P opens a floating timer through Document Picture-in-Picture where the browser
   has it; elsewhere the key does nothing.
   The deck owns the timer and the state; the window only renders what the deck sends and
   sends commands back. Messages go by postMessage on the window reference (source and
   origin checked; file:// pages send origin "null") and, only with the per-tab secret
   the presenter page carries, by BroadcastChannel where it exists. Each message carries sender id and sequence number, so one that arrives on both
   paths counts once. Nothing happens and nothing is added to the deck until a key asks. */
(function () {
  'use strict';
  var D = window.SlideDeck;
  if (!D || typeof D.use !== 'function') return;
  var root = document.documentElement;
  var KEY = 'deck-presenter';

  /* ============ pure helpers, also serialised into the presenter window ============ */
  /* m:ss (h:mm:ss from an hour); up rounds a countdown up, so 59.99 s left reads 1:00 */
  function fmt(ms, up) {
    var a = Math.abs(ms) / 1000, s = up ? Math.ceil(a - 0.001) : Math.floor(a);
    var h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, x = s % 60;
    return (h ? h + ':' + (m < 10 ? '0' : '') : '') + m + ':' + (x < 10 ? '0' : '') + x;
  }
  /* Budget view of a state message at time t (ms). A state is "ok", "low" with a fifth
     of the budget or less left, "over" once it is used up, "none" without a budget. */
  function calc(st, t) {
    var tm = st.timer, dt = tm.running ? Math.max(0, t - st.at) : 0;
    var elapsed = tm.elapsed + dt, spent = tm.slideSpent + dt;
    var plan = st.plan || [], cur = plan[st.index] || {}, total = 0, before = 0, covered = 0;
    for (var i = 0; i < plan.length; i++) {
      var p = plan[i].time || 0;
      total += p;
      if (p) covered++;
      if (i < st.index) before += p;
    }
    var state = function (left, budget) { return !budget ? 'none' : (left <= 0 ? 'over' : (left <= budget * 0.2 ? 'low' : 'ok')); };
    var b = (cur.time || 0) * 1000, T = total * 1000;
    return {
      elapsed: elapsed, spent: spent, budget: b, left: b - spent, slideState: state(b - spent, b),
      total: T, totalLeft: T - elapsed, totalState: state(T - elapsed, T),
      pace: elapsed - (before * 1000 + Math.min(spent, b)), covered: covered, count: plan.length,
      running: tm.running, started: tm.started
    };
  }

  /* ============ preview copy: the deck inside the presenter window's previews ============ */
  if (root.hasAttribute('data-deck-preview')) {
    D.use({
      name: 'presenter',
      /* previews jump, they never scroll smoothly */
      transition: function (from, to, apply) { apply({ instant: true }); },
      init: function () {
        var s = document.createElement('style');
        s.textContent = '.deck-progress, .deck-dots, .deck-counter, .deck-hints, .theme-toggle, .deck-track,'
          + ' .deck-back, .deck-notes, .deck-help, .deck-jump, .deck-live, .deck-cover { display: none !important; }'
          + ' html, body, .deck { overflow: hidden !important; }';
        document.head.appendChild(s);
      }
    });
    return;
  }

  /* ============ strings ============ */
  /* i18n:start */
  var STR = {
    en: {
      presenter: 'Presenter', current: 'Now', next: 'Next', end: 'End of the deck', notes: 'Notes',
      noNotes: 'No notes on this slide.', elapsed: 'Elapsed', start: 'Start', pause: 'Pause',
      resume: 'Resume', reset: 'Reset', prev: 'Back', fwd: 'Next', slideBudget: 'This slide',
      total: 'Plan', left: '{t} left', over: '{t} over', noBudget: 'no budget', ahead: '{t} ahead',
      behind: '{t} behind', onTime: 'on time', rehearse: 'Rehearse', stop: 'Stop rehearsal',
      recording: 'Recording', table: 'Plan vs actual', colN: '#', colSlide: 'Slide', colPlan: 'Plan',
      colActual: 'Actual', colDiff: 'Diff', sum: 'Total', copy: 'Copy', close: 'Close',
      noRecord: 'No rehearsal for this track yet. Press R to record one.',
      waiting: 'Waiting for the deck…', closed: 'The deck window is closed.', track: 'Track',
      allTracks: 'all slides', covered: '{n} of {m} slides have a budget', slide: 'Slide',
      keys: '→ ← next, back · 0-9 Enter jump · S start or pause · X reset · R rehearse · A plan vs actual · + - notes size',
      blocked: 'The pop-up was blocked. Allow pop-ups for this page, then press P again.',
      helpP: 'Presenter view (second window)', helpPip: 'Floating timer'
    },
    de: {
      presenter: 'Referent', current: 'Jetzt', next: 'Als Nächstes', end: 'Ende der Präsentation',
      notes: 'Notizen', noNotes: 'Zu dieser Folie gibt es keine Notizen.', elapsed: 'Verstrichen',
      start: 'Start', pause: 'Pause', resume: 'Fortsetzen', reset: 'Zurücksetzen', prev: 'Zurück',
      fwd: 'Weiter', slideBudget: 'Diese Folie', total: 'Plan', left: 'noch {t}', over: '{t} drüber',
      noBudget: 'kein Zeitbudget', ahead: '{t} voraus', behind: '{t} hinterher', onTime: 'im Plan',
      rehearse: 'Probelauf', stop: 'Probelauf beenden', recording: 'Aufnahme', table: 'Plan und Ist',
      colN: '#', colSlide: 'Folie', colPlan: 'Plan', colActual: 'Ist', colDiff: 'Differenz',
      sum: 'Summe', copy: 'Kopieren', close: 'Schließen',
      noRecord: 'Für diese Spur gibt es noch keinen Probelauf. R nimmt einen auf.',
      waiting: 'Warte auf die Präsentation…', closed: 'Das Fenster der Präsentation ist geschlossen.',
      track: 'Spur', allTracks: 'alle Folien', covered: '{n} von {m} Folien haben ein Zeitbudget',
      slide: 'Folie',
      keys: '→ ← weiter, zurück · 0-9 Enter springen · S Start oder Pause · X zurücksetzen · R Probelauf · A Plan und Ist · + - Notizgröße',
      blocked: 'Das Pop-up wurde blockiert. Pop-ups für diese Seite erlauben, dann erneut P drücken.',
      helpP: 'Referentenansicht (zweites Fenster)', helpPip: 'Schwebender Timer'
    }
  };
  /* i18n:end */
  function str() { return STR[D.state().lang] || STR.en; }

  /* ============ identity, origin ============ */
  var deckEl = document.querySelector('.deck');
  function opt(n) { var v = deckEl ? deckEl.getAttribute(n) : null; return v == null ? root.getAttribute(n) : v; }
  var deckKey = opt('data-deck-id') || location.pathname;
  function hashStr(s) {
    var h = 5381;
    for (var i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
    return (h >>> 0).toString(36);
  }
  function winName() { return 'deckPresenter_' + hashStr(deckKey); }
  var opaque = location.protocol === 'file:' || location.origin === 'null';
  function okOrigin(o) { return o === location.origin || (o === 'null' && opaque); }
  /* The deck talks to its window only while that window has said hello and not yet bye:
     an opaque origin (file://) cannot be named as a postMessage target, so the window
     reference plus that handshake is what keeps the notes from reaching another page. */
  function open_(win) { try { return !!win && !win.closed; } catch (e) { return false; } }
  var nonce = Math.random().toString(36).slice(2) + Date.now().toString(36);
  /* A BroadcastChannel reaches every page of the origin, and under file:// every
     local file. So the presenter page carries a secret in its own source, and the
     deck accepts a message on that channel only when it holds the secret. It is
     kept in sessionStorage, so a presenter window outlives a reload of the deck tab. */
  var secret = (function () {
    var k = 'deck-presenter-secret:' + deckKey, v = null;
    try { v = sessionStorage.getItem(k); } catch (e) { v = null; }
    if (!v) {
      v = '';
      for (var i = 0; i < 3; i++) v += Math.random().toString(36).slice(2);
      try { sessionStorage.setItem(k, v); } catch (e) { /* storage blocked: this tab only */ }
    }
    return v;
  })();

  /* The document as loaded, for the previews: taken before the engine adds its chrome. */
  var SOURCE = '', FP = '';
  function capture() {
    SOURCE = '<!DOCTYPE html>\n' + root.outerHTML.replace(/^<html/i, '<html data-deck-preview=""');
    FP = SOURCE.length.toString(36) + '.' + hashStr(SOURCE);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('readystatechange', function once() {
      if (document.readyState === 'loading') return;
      document.removeEventListener('readystatechange', once);
      capture();
    });
  } else {
    capture();
  }

  /* ============ slides and budget ============ */
  function allSlides() { return [].slice.call(document.querySelectorAll('.slide')); }
  function keyOf(s) { return s.id || 'n' + (allSlides().indexOf(s) + 1); }
  function budgetOf(s) {
    var v = (s.getAttribute('data-time') || '').trim(), m = /^(\d+):(\d{1,2})$/.exec(v);
    if (m) return parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
    var n = parseFloat(v);
    return n > 0 ? n : 0;
  }
  /* A bilingual deck hides the other language with CSS; the presenter gets text, so the
     same rule is applied to a copy (the engine's: [data-de]:not([data-en]) and back). */
  function otherLang() {
    if (!root.hasAttribute('data-lang') || !document.querySelector('[data-de], [data-en]')) return null;
    return D.state().lang === 'de' ? '[data-en]:not([data-de])' : '[data-de]:not([data-en])';
  }
  function shown(list, other) {
    for (var i = 0; i < list.length; i++) if (!other || !list[i].matches(other)) return list[i];
    return null;
  }
  function inLang(el, other) {
    if (!other) return el;
    var c = el.cloneNode(true);
    [].forEach.call(c.querySelectorAll(other), function (n) { n.parentNode.removeChild(n); });
    return c;
  }
  function titleOf(s, i) {
    var other = otherLang(), h = shown(s.querySelectorAll('h1, h2, h3, .slide__heading'), other);
    var t = h ? inLang(h, other).textContent.replace(/\s+/g, ' ').trim() : '';
    return t.slice(0, 90) || (str().slide + ' ' + (i + 1));
  }
  function notesOf(s) {
    var other = otherLang(), a = s && shown(s.querySelectorAll('aside.notes'), other);
    return a ? inLang(a, other).innerHTML : '';
  }
  var TOKENS = ['bg', 'surface', 'surface2', 'surface-elevated', 'text', 'text-dim', 'accent', 'border',
                'border-bright', 'green', 'amber', 'red', 'font-body', 'font-mono', 'font-display'];
  function tokens() {
    var cs = getComputedStyle(root), o = {};
    TOKENS.forEach(function (k) { var v = cs.getPropertyValue('--' + k).trim(); if (v) o[k] = v; });
    return o;
  }

  /* ============ timer (the deck owns it) ============ */
  function now() { return Date.now(); }
  var tm = { running: false, started: false, acc: 0, since: 0, spent: {}, key: null, mark: 0 };
  var rh = { on: false, last: null };
  function curKey() { var s = D.slides()[D.state().index]; return s ? keyOf(s) : null; }
  function charge(t) {
    t = t || now();
    if (tm.running && tm.key != null) tm.spent[tm.key] = (tm.spent[tm.key] || 0) + (t - tm.mark);
    tm.mark = t;
    tm.key = curKey();
  }
  function elapsed(t) { return tm.acc + (tm.running ? t - tm.since : 0); }
  function spentAt(k, t) { return (tm.spent[k] || 0) + (tm.running && k === tm.key ? t - tm.mark : 0); }
  function setRunning(on) {
    if (on === tm.running) return;
    var t = now();
    charge(t);
    if (on) { tm.since = t; tm.started = true; } else { tm.acc += t - tm.since; }
    tm.running = on;
    tm.mark = t;
  }
  function resetTimer() {
    tm.running = false; tm.started = false; tm.acc = 0; tm.spent = {};
    tm.mark = now(); tm.key = curKey();
  }

  /* ============ rehearsal record, per deck and track ============ */
  function recKey() { return 'deck-rehearsal:' + deckKey; }
  function loadAll() { try { return JSON.parse(localStorage.getItem(recKey()) || '{}') || {}; } catch (e) { return {}; } }
  function loadRecord(track) {
    var r = loadAll()[track];
    if (r && r.rows) return r;
    return rh.last && rh.last.track === track ? rh.last : null;   /* storage blocked: this session's */
  }
  function saveRecord() {
    var s = D.state(), t = now();
    var rec = {
      at: new Date(t).toISOString(), track: s.track,
      rows: D.slides().map(function (sl, i) {
        var k = keyOf(sl);
        return { key: k, title: titleOf(sl, i), plan: budgetOf(sl), actual: Math.round(spentAt(k, t) / 1000) };
      })
    };
    rh.last = rec;
    try { var all = loadAll(); all[s.track] = rec; localStorage.setItem(recKey(), JSON.stringify(all)); } catch (e) { /* storage blocked */ }
  }
  function toggleRehearsal() {
    if (!rh.on) { resetTimer(); rh.on = true; setRunning(true); return; }
    charge();
    saveRecord();
    rh.on = false;
    setRunning(false);
  }

  /* ============ state and messages ============ */
  function snapshot() {
    var s = D.state(), list = D.slides(), cur = list[s.index], t = now(), spent = {};
    var plan = list.map(function (sl, i) {
      var k = keyOf(sl);
      spent[k] = Math.round(spentAt(k, t));
      return { key: k, title: titleOf(sl, i), time: budgetOf(sl) };
    });
    return {
      type: 'state', index: s.index, count: list.length, step: s.step, track: s.track,
      trackLabel: typeof D.trackLabel === 'function' ? D.trackLabel() : s.track,
      tracks: root.hasAttribute('data-track-active'), theme: s.theme, lang: s.lang, title: document.title,
      notes: notesOf(cur), plan: plan, tokens: tokens(), vw: window.innerWidth, vh: window.innerHeight,
      fp: FP, at: t,
      timer: { running: tm.running, started: tm.started, elapsed: elapsed(t),
               slideSpent: cur ? spentAt(keyOf(cur), t) : 0, spent: spent },
      rehearsal: { on: rh.on, record: rh.on ? null : loadRecord(s.track) }
    };
  }
  var w = null, live = false, bc = null, seq = 0, seen = {}, peer = false, ready = false;
  function linked() { return live && open_(w); }
  function post(msg, big) {
    msg[KEY] = 1; msg.role = 'deck'; msg.deck = deckKey; msg.from = nonce; msg.seq = ++seq;
    var sent = false;
    if (linked()) { try { w.postMessage(msg, opaque ? '*' : location.origin); sent = true; } catch (e) { /* closed meanwhile */ } }
    /* The channel is heard by every page of the origin: it carries deck content only
       while a presenter that proved the secret listens there and the window path is
       not open. */
    if (bc && peer && !sent) { try { bc.postMessage(msg); } catch (e) { /* channel closed */ } }
  }
  function push() {
    if (!ready) return;
    if (linked() || peer) post(snapshot());
    updatePip();
  }
  /* a message from a presenter, counted once whichever path brought it */
  function fresh(m) {
    if (typeof m.from !== 'string' || typeof m.seq !== 'number') return false;
    if (seen[m.from] >= m.seq) return false;
    seen[m.from] = m.seq;
    return true;
  }
  function mine(m) { return !!m && m[KEY] === 1 && m.role === 'presenter' && m.deck === deckKey; }
  function handle(m, viaWindow) {
    var a = m.action;
    if (m.type === 'hello') {
      if (viaWindow) live = true;
      if (m.fp !== FP && SOURCE) post({ type: 'source', html: SOURCE, fp: FP }, true);
      push();
      return;
    }
    if (m.type === 'bye') { if (viaWindow) live = false; else peer = false; return; }
    if (m.type !== 'cmd') return;
    if (a === 'next') D.next();
    else if (a === 'prev') D.prev();
    else if (a === 'first') D.goTo(0);
    else if (a === 'last') D.goTo(D.count() - 1);
    else if (a === 'goto') D.goTo(Number(m.index));
    else if (a === 'timer') setRunning(!tm.running);
    else if (a === 'reset') { resetTimer(); if (rh.on) rh.on = false; }
    else if (a === 'rehearse') toggleRehearsal();
    else return;
    push();
  }
  window.addEventListener('message', function (e) {
    var m = e.data;
    if (!ready || !mine(m) || !okOrigin(e.origin)) return;
    if (!w || e.source !== w) {
      /* A presenter this tab opened before a reload says hello: take it back. */
      var ours = false;
      try { ours = !!e.source && e.source !== window && e.source.opener === window; } catch (x) { ours = false; }
      if (!ours || m.type !== 'hello') return;
      w = e.source;
    }
    if (fresh(m)) handle(m, true);
  });
  try {
    bc = new BroadcastChannel(KEY + ':' + deckKey);
    bc.onmessage = function (e) {
      var m = e.data;
      if (!ready || !mine(m) || m.secret !== secret) return;
      /* Commands name this deck instance; a hello may come from a presenter whose deck was
         reloaded, unless this deck already has its own presenter. */
      if (m.to !== nonce && (m.type !== 'hello' || linked())) return;
      if (!fresh(m)) return;
      peer = true;
      handle(m, false);
    };
  } catch (e) { bc = null; }

  /* ============ the presenter window ============ */
  var toastTimer = null;
  function toast(msg) {
    var el = document.querySelector('.deck-presenter-toast');
    if (!el) {
      el = document.createElement('div');
      el.className = 'deck-presenter-toast';
      el.setAttribute('role', 'status');
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.hidden = true; }, 6000);
  }
  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'); }
  /* The presenter page is a Blob URL: offline, and a reload of that window reloads the
     page instead of leaving it blank. Same origin as the deck over http(s); under
     file:// both sides are opaque and only talk by message. */
  var pageUrl = null;
  function makePage() {
    var lang = D.state().lang, t = STR[lang] || STR.en;
    var cfg = { deck: deckKey, lang: lang, strings: STR, secret: secret };
    var json = JSON.stringify(cfg).replace(/</g, '\\u003c');
    var html = '<!DOCTYPE html><html data-deck-presenter="" lang="' + esc(lang) + '"><head><meta charset="utf-8">'
      + '<meta name="viewport" content="width=device-width, initial-scale=1"><title>' + esc(t.presenter + ': ' + document.title)
      + '</title><style>' + PAGE_CSS + '<\/style></head><body>' + PAGE_BODY
      + '<script>(' + presenterMain + ')(' + json + ', ' + calc + ', ' + fmt + ');<\/script></body></html>';
    if (pageUrl) { try { URL.revokeObjectURL(pageUrl); } catch (e) { /* gone */ } }
    pageUrl = URL.createObjectURL(new Blob([html], { type: 'text/html' }));
    return pageUrl;
  }
  function openPresenter() {
    if (open_(w)) { try { w.focus(); } catch (e) { /* not allowed */ } push(); return true; }
    var win = null;
    try { win = window.open(makePage(), winName(), 'popup=yes,width=1280,height=800'); } catch (e) { win = null; }
    if (!win) { toast(str().blocked); return true; }
    w = win;
    live = false;   /* until its hello */
    return true;
  }

  var PAGE_CSS = [
    ':root { color-scheme: light dark; }',
    '* { box-sizing: border-box; }',
    'html, body { margin: 0; height: 100%; }',
    'body { display: grid; grid-template-rows: auto minmax(0, 1fr) auto; background: var(--bg, Canvas);',
    '  color: var(--text, CanvasText); font-family: var(--font-body, system-ui, sans-serif); }',
    '[hidden] { display: none !important; }',
    '.pp-bar { display: flex; align-items: center; gap: 16px; padding: 10px 16px; border-bottom: 1px solid var(--border, GrayText); }',
    '.pp-title { flex: 1; min-width: 0; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }',
    '.pp-rec { display: none; font-weight: 700; color: var(--red, var(--accent)); }',
    '.pp-recording .pp-rec { display: inline; }',
    '.pp-count, .pp-clock, .pp-track { font-family: var(--font-mono, monospace); color: var(--text-dim, inherit); white-space: nowrap; }',
    '.pp-clock { font-size: 20px; color: var(--text, inherit); }',
    '.pp-main { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr);',
    '  grid-template-rows: minmax(0, 1.25fr) minmax(0, 1fr); gap: 12px; padding: 12px; min-height: 0; }',
    '.pp-cur { grid-column: 1; grid-row: 1; }',
    '.pp-notes { grid-column: 1; grid-row: 2; }',
    '.pp-side { grid-column: 2; grid-row: 1 / span 2; display: flex; flex-direction: column; gap: 12px; min-height: 0; }',
    '.pp-box { display: flex; flex-direction: column; min-height: 0; padding: 10px 12px; border-radius: 8px;',
    '  background: var(--surface, transparent); border: 1px solid var(--border, GrayText); }',
    '.pp-next { flex: 1; }',
    '.pp-label { margin-bottom: 6px; font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-dim, inherit); }',
    '.pp-frame { position: relative; flex: 1; min-height: 80px; overflow: hidden; border-radius: 4px; background: var(--bg, Canvas); }',
    '.pp-frame iframe { position: absolute; left: 0; top: 0; border: 0; transform-origin: 0 0; pointer-events: none; background: var(--bg, Canvas); }',
    '.pp-next .pp-frame { cursor: pointer; }',
    '.pp-end { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;',
    '  background: var(--surface, Canvas); color: var(--text-dim, inherit); }',
    '.pp-next-title { margin-top: 6px; font-size: 14px; color: var(--text-dim, inherit); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }',
    '.pp-time { gap: 10px; }',
    '.pp-row { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px 12px; }',
    '.pp-elapsed { font-family: var(--font-mono, monospace); font-size: 44px; font-weight: 600; line-height: 1; font-variant-numeric: tabular-nums; }',
    '.pp-budget b { font-family: var(--font-mono, monospace); font-size: 22px; font-variant-numeric: tabular-nums; }',
    '.pp-budget small, .pp-budget [data-pp=pace], .pp-budget [data-pp=total-left] { color: var(--text-dim, inherit); }',
    '[data-state=ok] > b { color: var(--green, var(--accent)); }',
    '[data-state=low] > b { color: var(--amber, var(--accent)); }',
    '[data-state=over] > b { color: var(--red, var(--accent)); }',
    '[data-state=none] > b { color: var(--text-dim, inherit); font-size: 16px; }',
    '.pp-meter { flex-basis: 100%; height: 6px; border-radius: 3px; overflow: hidden; background: var(--surface2, var(--border, GrayText)); }',
    '.pp-meter i { display: block; height: 100%; width: 0; background: var(--green, var(--accent)); }',
    '[data-state=low] .pp-meter i { background: var(--amber, var(--accent)); }',
    '[data-state=over] .pp-meter i { background: var(--red, var(--accent)); }',
    '[data-state=none] .pp-meter { display: none; }',
    '.pp-notes__body { overflow: auto; font-size: var(--pp-notes-size, 22px); line-height: 1.5; }',
    '.pp-notes__body > :first-child { margin-top: 0; }',
    '.pp-empty { color: var(--text-dim, inherit); }',
    'button { font: inherit; font-size: 14px; padding: 4px 10px; border-radius: 6px; cursor: pointer;',
    '  color: var(--text, inherit); background: var(--surface2, transparent); border: 1px solid var(--border-bright, var(--border, GrayText)); }',
    'button:focus-visible { outline: 2px solid var(--accent, Highlight); outline-offset: 2px; }',
    '.pp-keys { padding: 6px 16px; font-size: 12px; color: var(--text-dim, inherit); border-top: 1px solid var(--border, GrayText); }',
    '.pp-table { position: fixed; inset: 6% 8%; z-index: 5; overflow: auto; padding: 16px 20px; border-radius: 10px;',
    '  background: var(--surface-elevated, var(--surface, Canvas)); border: 1px solid var(--border-bright, var(--border, GrayText)); }',
    '.pp-table h2 { flex: 1; margin: 0; font-size: 20px; }',
    '.pp-table table { width: 100%; margin-top: 12px; border-collapse: collapse; font-variant-numeric: tabular-nums; }',
    '.pp-table th, .pp-table td { padding: 6px 8px; text-align: left; border-bottom: 1px solid var(--border, GrayText); }',
    '.pp-table .num { text-align: right; font-family: var(--font-mono, monospace); }',
    '.pp-table tfoot td { font-weight: 600; }',
    'tr[data-state=over] .pp-diff { color: var(--red, var(--accent)); }',
    'tr[data-state=ok] .pp-diff { color: var(--green, var(--accent)); }',
    '.pp-status { position: fixed; left: 50%; bottom: 44px; transform: translateX(-50%); z-index: 6; padding: 8px 14px;',
    '  border-radius: 8px; background: var(--surface-elevated, var(--surface, Canvas)); border: 1px solid var(--amber, var(--accent)); }',
    '@media (max-width: 760px) {',
    '  .pp-main { grid-template-columns: minmax(0, 1fr); grid-template-rows: none; overflow: auto; }',
    '  .pp-cur, .pp-notes, .pp-side { grid-column: 1; grid-row: auto; }',
    '  .pp-cur, .pp-next { min-height: 34vh; }',
    '}'
  ].join('\n');

  var PAGE_BODY = [
    '<header class="pp-bar"><span class="pp-rec" data-t="recording"></span>',
    '<span class="pp-title" data-pp="title"></span><span class="pp-track" data-pp="track"></span>',
    '<span class="pp-count" data-pp="count"></span><span class="pp-clock" data-pp="clock"></span></header>',
    '<main class="pp-main">',
    '<section class="pp-box pp-cur"><div class="pp-label" data-t="current"></div>',
    '<div class="pp-frame" data-pp="cur"><iframe tabindex="-1" aria-hidden="true" title="current"></iframe></div></section>',
    '<div class="pp-side">',
    '<section class="pp-box pp-next"><div class="pp-label" data-t="next"></div>',
    '<div class="pp-frame" data-pp="next" data-act="next"><iframe tabindex="-1" aria-hidden="true" title="next"></iframe>',
    '<div class="pp-end" data-pp="end" data-t="end" hidden></div></div>',
    '<div class="pp-next-title" data-pp="next-title"></div></section>',
    '<section class="pp-box pp-time"><div class="pp-label" data-t="elapsed"></div>',
    '<div class="pp-row"><span class="pp-elapsed" data-pp="elapsed">0:00</span>',
    '<button type="button" data-act="timer" data-pp="timer-btn"></button>',
    '<button type="button" data-act="reset" data-t="reset"></button></div>',
    '<div class="pp-budget pp-row" data-pp="slide-budget" data-state="none"><span data-t="slideBudget"></span>',
    '<b data-pp="slide-left"></b><span class="pp-meter"><i data-pp="slide-meter"></i></span></div>',
    '<div class="pp-budget pp-row" data-pp="total-budget" data-state="none"><span data-t="total"></span>',
    '<b data-pp="total-plan"></b><span data-pp="total-left"></span><span data-pp="pace"></span>',
    '<small data-pp="covered"></small></div>',
    '<div class="pp-row"><button type="button" data-act="prev" data-t="prev"></button>',
    '<button type="button" data-act="next" data-t="fwd"></button>',
    '<button type="button" data-act="rehearse" data-pp="rehearse-btn"></button>',
    '<button type="button" data-act="table" data-t="table"></button></div></section>',
    '</div>',
    '<section class="pp-box pp-notes"><div class="pp-label" data-t="notes"></div>',
    '<div class="pp-notes__body" data-pp="notes"></div></section>',
    '</main>',
    '<footer class="pp-keys" data-t="keys"></footer>',
    '<div class="pp-table" data-pp="table" role="dialog" hidden><div class="pp-row"><h2 data-t="table"></h2>',
    '<button type="button" data-act="copy" data-t="copy"></button>',
    '<button type="button" data-act="close-table" data-t="close"></button></div>',
    '<p class="pp-empty" data-pp="table-empty" data-t="noRecord" hidden></p>',
    '<table><thead><tr><th class="num" data-t="colN"></th><th data-t="colSlide"></th><th class="num" data-t="colPlan"></th>',
    '<th class="num" data-t="colActual"></th><th class="num" data-t="colDiff"></th></tr></thead><tbody></tbody><tfoot></tfoot></table></div>',
    '<div class="pp-status" data-pp="status" role="status" hidden></div>'
  ].join('');

  /* Runs inside the presenter window, serialised there by makePage(): it sees only its
     arguments and its own window, never this module's variables. */
  function presenterMain(cfg, calc, fmt) {
    'use strict';
    var KEY = 'deck-presenter', doc = document, root = doc.documentElement;
    var nonce = Math.random().toString(36).slice(2) + Date.now().toString(36);
    var seq = 0, seen = {}, st = null, deckNonce = null, heard = 0, lastHello = 0;
    var fp = '', asked = '', tableOpen = false, jump = '', wasRec = false, notesHtml = null;
    var opaque = location.protocol === 'file:' || location.origin === 'null';
    var bc = null;
    try { bc = new BroadcastChannel(KEY + ':' + cfg.deck); } catch (e) { bc = null; }
    function $(n) { return doc.querySelector('[data-pp="' + n + '"]'); }
    function T() { return cfg.strings[(st && st.lang) || cfg.lang] || cfg.strings.en; }
    function opener() { try { var o = window.opener; return o && !o.closed ? o : null; } catch (e) { return null; } }
    function okOrigin(o) { return o === location.origin || (o === 'null' && opaque); }
    function send(m) {
      m[KEY] = 1; m.role = 'presenter'; m.deck = cfg.deck; m.from = nonce; m.seq = ++seq; m.to = deckNonce;
      m.secret = cfg.secret;
      /* only commands and hellos go this way, never deck content */
      var o = opener();
      if (o) { try { o.postMessage(m, opaque ? '*' : location.origin); } catch (e) { /* gone */ } }
      if (bc) { try { bc.postMessage(m); } catch (e) { /* closed */ } }
    }
    function cmd(action, index) { send({ type: 'cmd', action: action, index: index }); }
    function receive(m, viaWindow) {
      if (!m || m[KEY] !== 1 || m.role !== 'deck' || m.deck !== cfg.deck) return;
      if (typeof m.from !== 'string' || typeof m.seq !== 'number') return;
      var quiet = Date.now() - heard > 3000;
      /* by BroadcastChannel only the known deck, or any deck of this file once it went quiet */
      if (!viaWindow && deckNonce && m.from !== deckNonce && !quiet) return;
      if (seen[m.from] >= m.seq) return;
      seen[m.from] = m.seq;
      deckNonce = m.from;
      heard = Date.now();
      if (m.type === 'source') { setSource(m.html, m.fp); return; }
      if (m.type === 'bye') { heard = 0; status(T().waiting); return; }
      if (m.type === 'state') { st = m; render(); }
    }
    window.addEventListener('message', function (e) {
      var o = opener();
      if (!o || e.source !== o || !okOrigin(e.origin)) return;
      receive(e.data, true);
    });
    if (bc) bc.onmessage = function (e) { receive(e.data, false); };
    window.addEventListener('pagehide', function () { send({ type: 'bye' }); });

    /* ---------- previews: two copies of the deck, driven through their own API ---------- */
    function setSource(html, f) {
      fp = f;
      ['cur', 'next'].forEach(function (n) {
        var fr = $(n).querySelector('iframe');
        fr.onload = function () { drive(); };
        fr.srcdoc = html;
      });
    }
    function deckIn(n) {
      try {
        var cw = $(n).querySelector('iframe').contentWindow, d = cw && cw.SlideDeck;
        return d && d.count && d.count() ? d : null;
      } catch (e) { return null; }
    }
    function place(d, advance) {
      if (d.track() !== st.track) d.setTrack(st.track);
      var s = d.state();
      if (s.theme !== st.theme) d.setTheme(st.theme);
      if (s.lang !== st.lang) d.setLang(st.lang);
      d.goTo(st.index);
      d.setStep(st.step);
      if (!advance) return true;
      d.next();   /* whatever the deck does next: a step of the same slide, or the next slide */
      var a = d.state();
      return !(a.index === st.index && a.step === st.step);
    }
    function fit() {
      ['cur', 'next'].forEach(function (n) {
        var box = $(n), fr = box.querySelector('iframe'), vw = st.vw || 1280, vh = st.vh || 720;
        var bw = box.clientWidth, bh = box.clientHeight, k = Math.min(bw / vw, bh / vh) || 0.1;
        fr.style.width = vw + 'px';
        fr.style.height = vh + 'px';
        fr.style.transform = 'translate(' + ((bw - vw * k) / 2) + 'px, ' + ((bh - vh * k) / 2) + 'px) scale(' + k + ')';
      });
    }
    function drive() {
      if (!st) return;
      fit();
      var c = deckIn('cur'), x = deckIn('next');
      try { if (c) place(c, false); } catch (e) { /* preview not ready */ }
      try { if (x) $('end').hidden = place(x, true); } catch (e) { /* preview not ready */ }
    }
    window.addEventListener('resize', function () { if (st) fit(); });

    /* ---------- rendering ---------- */
    function labels(t) {
      [].forEach.call(doc.querySelectorAll('[data-t]'), function (e) { var v = t[e.getAttribute('data-t')]; if (v != null) e.textContent = v; });
    }
    function status(msg) { var e = $('status'); e.textContent = msg || ''; e.hidden = !msg; }
    function render() {
      var t = T(), s = st, tok = s.tokens || {};
      root.lang = s.lang;
      Object.keys(tok).forEach(function (k) { root.style.setProperty('--' + k, tok[k]); });
      root.style.colorScheme = s.theme === 'light' ? 'light' : 'dark';
      root.classList.toggle('pp-recording', !!s.rehearsal.on);
      labels(t);
      doc.title = t.presenter + ': ' + s.title;
      $('title').textContent = s.title;
      $('count').textContent = (s.index + 1) + ' / ' + s.count;
      $('track').hidden = !s.tracks;
      $('track').textContent = t.track + ': ' + (s.track === 'all' ? t.allTracks : (s.trackLabel || s.track));
      if (notesHtml !== s.notes + '|' + s.lang) {
        notesHtml = s.notes + '|' + s.lang;
        var nb = $('notes');
        if (s.notes) nb.innerHTML = s.notes;
        else { nb.textContent = ''; var p = doc.createElement('p'); p.className = 'pp-empty'; p.textContent = t.noNotes; nb.appendChild(p); }
        nb.scrollTop = 0;
      }
      var nx = s.plan[s.index + 1];
      $('next-title').textContent = nx ? (s.index + 2) + ' · ' + nx.title : t.end;
      $('rehearse-btn').textContent = s.rehearsal.on ? t.stop : t.rehearse;
      if (wasRec && !s.rehearsal.on) openTable(true);
      wasRec = !!s.rehearsal.on;
      if (s.fp && s.fp !== fp && s.fp !== asked) { asked = s.fp; send({ type: 'hello', fp: fp }); }
      status('');
      drive();
      tick();
    }
    function pad(n) { return (n < 10 ? '0' : '') + n; }
    function tick() {
      var d = new Date(), t = T(), nowMs = Date.now();
      $('clock').textContent = pad(d.getHours()) + ':' + pad(d.getMinutes());
      if (!opener() && !bc) status(t.closed);
      else if (nowMs - heard > 2500 && nowMs - lastHello > 2000) {
        lastHello = nowMs;
        send({ type: 'hello', fp: fp });
        if (nowMs - heard > 5000) status(opener() ? t.waiting : t.closed);
      }
      if (!st) return;
      var v = calc(st, nowMs);
      $('elapsed').textContent = fmt(v.elapsed);
      $('timer-btn').textContent = v.running ? t.pause : (v.started ? t.resume : t.start);
      var sb = $('slide-budget');
      sb.setAttribute('data-state', v.slideState);
      $('slide-left').textContent = !v.budget ? t.noBudget
        : (v.left > 0 ? t.left.replace('{t}', fmt(v.left, true)) : t.over.replace('{t}', fmt(-v.left)));
      $('slide-meter').style.width = v.budget ? Math.min(100, v.spent / v.budget * 100) + '%' : '0';
      var tb = $('total-budget');
      tb.setAttribute('data-state', v.totalState);
      $('total-plan').textContent = v.total ? fmt(v.total) : t.noBudget;
      $('total-left').textContent = !v.total || !v.started ? ''
        : (v.totalLeft > 0 ? t.left.replace('{t}', fmt(v.totalLeft, true)) : t.over.replace('{t}', fmt(-v.totalLeft)));
      $('pace').textContent = !v.total || !v.started ? ''
        : (Math.abs(v.pace) < 5000 ? t.onTime : (v.pace > 0 ? t.behind : t.ahead).replace('{t}', fmt(v.pace)));
      $('covered').textContent = v.covered && v.covered < v.count ? t.covered.replace('{n}', v.covered).replace('{m}', v.count) : '';
      if (tableOpen && st.rehearsal.on) renderTable();
    }

    /* ---------- plan vs actual ---------- */
    function rows() {
      var s = st, rec = s.rehearsal.record, by = {};
      if (rec && rec.rows) rec.rows.forEach(function (r) { by[r.key] = r.actual; });
      var dt = s.timer.running ? Date.now() - s.at : 0, ck = (s.plan[s.index] || {}).key;
      return s.plan.map(function (p, i) {
        var actual = s.rehearsal.on
          ? Math.round(((s.timer.spent[p.key] || 0) + (p.key === ck ? dt : 0)) / 1000)
          : by[p.key];
        /* 0 s is a slide the rehearsal never reached: no actual, never "under budget" */
        return { n: i + 1, title: p.title, plan: p.time || 0, actual: actual ? actual : null };
      });
    }
    function diff(d) { return d > 0 ? '+' + fmt(d * 1000) : (d < 0 ? '-' + fmt(-d * 1000) : '0:00'); }
    function renderTable() {
      if (!st) return;
      var list = rows(), body = doc.querySelector('[data-pp=table] tbody'), foot = doc.querySelector('[data-pp=table] tfoot');
      var has = st.rehearsal.on || !!st.rehearsal.record || list.some(function (r) { return r.actual != null; });
      $('table-empty').hidden = has;
      body.textContent = '';
      foot.textContent = '';
      var sp = 0, sa = 0;
      var row = function (parent, cells, state) {
        var tr = doc.createElement('tr');
        if (state) tr.setAttribute('data-state', state);
        cells.forEach(function (c, i) {
          var td = doc.createElement('td');
          td.textContent = c;
          td.className = (i === 1 ? '' : 'num') + (i === 4 ? ' pp-diff' : '');
          tr.appendChild(td);
        });
        parent.appendChild(tr);
      };
      list.forEach(function (r) {
        var d = r.plan && r.actual != null ? r.actual - r.plan : null;
        if (r.actual != null) { sp += r.plan; sa += r.actual; }   /* the sums count the slides reached */
        row(body, [String(r.n), r.title, r.plan ? fmt(r.plan * 1000) : '', r.actual == null ? '' : fmt(r.actual * 1000),
                   d == null ? '' : diff(d)], d == null ? 'none' : (d > 0 ? 'over' : 'ok'));
      });
      if (has) row(foot, ['', T().sum, sp ? fmt(sp * 1000) : '', fmt(sa * 1000), sp ? diff(sa - sp) : ''],
                   sp ? (sa > sp ? 'over' : 'ok') : 'none');
    }
    function openTable(on) {
      tableOpen = on;
      $('table').hidden = !on;
      if (on) renderTable();
    }
    function copyTable() {
      var t = T(), lines = [[t.colN, t.colSlide, t.colPlan, t.colActual, t.colDiff].join('\t')];
      [].forEach.call(doc.querySelectorAll('[data-pp=table] tbody tr, [data-pp=table] tfoot tr'), function (tr) {
        lines.push([].map.call(tr.cells, function (c) { return c.textContent; }).join('\t'));
      });
      try { navigator.clipboard.writeText(lines.join('\n')).catch(function () {}); } catch (e) { /* no clipboard */ }
    }

    /* ---------- input ---------- */
    var size = 22;
    try { size = parseInt(localStorage.getItem('deck-presenter-notes-size'), 10) || 22; } catch (e) { size = 22; }
    function notesSize(by) {
      size = Math.max(14, Math.min(48, size + by));
      root.style.setProperty('--pp-notes-size', size + 'px');
      try { localStorage.setItem('deck-presenter-notes-size', String(size)); } catch (e) { /* storage blocked */ }
    }
    notesSize(0);
    doc.addEventListener('keydown', function (e) {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
      var k = e.key, lk = String(k).toLowerCase();
      if ((k === ' ' || k === 'Enter') && e.target && e.target.closest && e.target.closest('button')) return;
      if (/^[0-9]$/.test(k)) { jump = (jump + k).slice(0, 4); e.preventDefault(); return; }
      if (k === 'Enter' && jump) { cmd('goto', parseInt(jump, 10) - 1); jump = ''; e.preventDefault(); return; }
      jump = '';
      if (k === 'Escape' && tableOpen) openTable(false);
      else if (k === 'ArrowRight' || k === 'ArrowDown' || k === 'PageDown' || (k === ' ' && !e.shiftKey)) cmd('next');
      else if (k === 'ArrowLeft' || k === 'ArrowUp' || k === 'PageUp' || (k === ' ' && e.shiftKey)) cmd('prev');
      else if (k === 'Home') cmd('first');
      else if (k === 'End') cmd('last');
      else if (lk === 's') cmd('timer');
      else if (lk === 'x') cmd('reset');
      else if (lk === 'r') cmd('rehearse');
      else if (lk === 'a') openTable(!tableOpen);
      else if (k === '+' || k === '=') notesSize(2);
      else if (k === '-') notesSize(-2);
      else return;
      e.preventDefault();
    });
    doc.addEventListener('click', function (e) {
      var b = e.target && e.target.closest ? e.target.closest('[data-act]') : null;
      if (!b) return;
      var a = b.getAttribute('data-act');
      if (a === 'table') openTable(!tableOpen);
      else if (a === 'close-table') openTable(false);
      else if (a === 'copy') copyTable();
      else cmd(a);
      if (b.blur) b.blur();
    });

    window.__deckPresenter = { deckNonce: function () { return deckNonce; } };
    labels(T());
    send({ type: 'hello', fp: fp });
    lastHello = Date.now();
    setInterval(tick, 500);
  }

  /* ============ floating timer (Document Picture-in-Picture) ============ */
  var PIP = !!(window.documentPictureInPicture && typeof window.documentPictureInPicture.requestWindow === 'function');
  var pip = null, pipTick = null;
  var PIP_CSS = [
    'html, body { margin: 0; height: 100%; }',
    'body { display: flex; flex-direction: column; justify-content: center; gap: 4px; padding: 8px 12px; box-sizing: border-box;',
    '  background: var(--bg, Canvas); color: var(--text, CanvasText); font-family: var(--font-body, system-ui, sans-serif); }',
    '.pp-top { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; font-family: var(--font-mono, monospace); color: var(--text-dim, inherit); font-size: 13px; }',
    '[data-pp=elapsed] { font-family: var(--font-mono, monospace); font-size: 34px; font-weight: 600; line-height: 1.1; font-variant-numeric: tabular-nums; }',
    '[data-pp=slide-left] { font-family: var(--font-mono, monospace); font-size: 15px; }',
    '[data-state=ok] [data-pp=slide-left] { color: var(--green, var(--accent)); }',
    '[data-state=low] [data-pp=slide-left] { color: var(--amber, var(--accent)); }',
    '[data-state=over] [data-pp=slide-left] { color: var(--red, var(--accent)); }',
    '[data-state=none] [data-pp=slide-left] { color: var(--text-dim, inherit); }',
    'button { font: inherit; font-size: 12px; padding: 2px 8px; border-radius: 6px; cursor: pointer; color: var(--text, inherit);',
    '  background: var(--surface2, transparent); border: 1px solid var(--border-bright, var(--border, GrayText)); }'
  ].join('\n');
  function openPip() {
    if (!PIP) return false;
    if (pip && !pip.closed) { try { pip.close(); } catch (e) { /* already gone */ } pip = null; return true; }
    try {
      window.documentPictureInPicture.requestWindow({ width: 260, height: 130 }).then(buildPip, function () { /* refused */ });
    } catch (e) { /* not allowed here */ }
    return true;
  }
  function buildPip(pw) {
    pip = pw;
    var d = pw.document, s = d.createElement('style');
    s.textContent = PIP_CSS;
    d.head.appendChild(s);
    d.body.innerHTML = '<div class="pp-top"><span data-pp="count"></span><button type="button" data-act="timer"></button></div>'
      + '<div data-pp="elapsed">0:00</div><div data-pp="slide-budget" data-state="none"><span data-pp="slide-left"></span></div>';
    d.body.addEventListener('click', function (e) {
      if (e.target && e.target.closest && e.target.closest('[data-act=timer]')) { setRunning(!tm.running); push(); }
    });
    clearInterval(pipTick);
    pipTick = setInterval(updatePip, 500);
    pw.addEventListener('pagehide', function () { clearInterval(pipTick); pip = null; });
    updatePip();
  }
  function updatePip() {
    if (!pip) return;
    if (pip.closed) { clearInterval(pipTick); pip = null; return; }
    var d = pip.document, s = snapshot(), v = calc(s, s.at), t = STR[s.lang] || STR.en, tok = s.tokens;
    var q = function (n) { return d.querySelector('[data-pp="' + n + '"]'); };
    if (!q('elapsed')) return;
    Object.keys(tok).forEach(function (k) { d.documentElement.style.setProperty('--' + k, tok[k]); });
    q('count').textContent = (s.index + 1) + ' / ' + s.count;
    q('elapsed').textContent = fmt(v.elapsed);
    q('slide-budget').setAttribute('data-state', v.slideState);
    q('slide-left').textContent = !v.budget ? t.noBudget
      : (v.left > 0 ? t.left.replace('{t}', fmt(v.left, true)) : t.over.replace('{t}', fmt(-v.left)));
    d.querySelector('[data-act=timer]').textContent = v.running ? t.pause : (v.started ? t.resume : t.start);
  }

  /* ============ registration ============ */
  var help = [{ key: 'P', de: STR.de.helpP, en: STR.en.helpP }];
  if (PIP) help.push({ key: 'Shift+P', de: STR.de.helpPip, en: STR.en.helpPip });
  var lastTrack = null;
  D.use({
    name: 'presenter',
    keys: { p: function (e) { return e.shiftKey ? openPip() : openPresenter(); } },
    help: help,
    init: function () {
      ready = true;
      lastTrack = D.track();
      tm.mark = now();
      tm.key = curKey();
      D.on('slidechange', function () {
        charge();
        /* the first slide change starts the clock, unless it came from a track switch */
        if (!tm.started && D.track() === lastTrack) setRunning(true);
        if (rh.on) saveRecord();
        push();
      });
      D.on('trackchange', function (e) { lastTrack = e.track; charge(); push(); });
      D.on('stepchange', push);
      D.on('themechange', push);
      D.on('langchange', push);
      var rt = null;
      window.addEventListener('resize', function () { clearTimeout(rt); rt = setTimeout(push, 200); });
      window.addEventListener('pagehide', function () {
        if (rh.on) { charge(); saveRecord(); }
        post({ type: 'bye' });
        if (pip && !pip.closed) { try { pip.close(); } catch (e) { /* gone */ } }
      });
    }
  });
})();
