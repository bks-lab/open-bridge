// SPDX-License-Identifier: MIT
// Classic (non-module) script, the first one in <head>: the boot guard of the page. Right after a restart of the
// server every open page loads anew while the server is still starting; when app.js or a style sheet of that load
// fails (a connection reset), the page would stay blank for good. Then it loads again by itself, a second later the
// first time and a little later each time after, at most three times in a row, so a server that is down never makes
// it loop. app.js calls window.cockpitBootDone once it runs: the count starts over, and a later failure (a picture,
// a module loaded on demand) reloads nothing. Without sessionStorage there is no count, so no reload either.
(function (win, doc) {
  var KEY = 'bridge-cockpit.boot-retries'
  var MAX = 3
  var STEP_MS = 1000
  var planned = false

  function tries() {
    try { return Number(win.sessionStorage.getItem(KEY)) || 0 } catch (e) { return MAX }
  }

  function remember(n) {
    try {
      if (n) win.sessionStorage.setItem(KEY, String(n))
      else win.sessionStorage.removeItem(KEY)
    } catch (e) { /* storage blocked: nothing to remember */ }
  }

  doc.addEventListener('error', function (ev) {
    var el = ev && ev.target
    var tag = el && el.tagName
    if (planned || win.cockpitBooted) return
    if (!(tag === 'SCRIPT' || (tag === 'LINK' && el.rel === 'stylesheet'))) return
    var n = tries()
    if (n >= MAX) return
    planned = true
    remember(n + 1)
    win.setTimeout(function () { win.location.reload() }, STEP_MS * (n + 1))
  }, true)

  win.cockpitBootDone = function () {
    win.cockpitBooted = true
    // a load that failed keeps its count, even when app.js still ran: a style sheet that keeps failing must not
    // reload the page forever
    if (!planned) remember(0)
  }
})(window, document)
