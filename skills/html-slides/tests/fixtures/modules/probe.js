/* probe: a test fixture module for the engine plugin API (tests/test_engine_plugins.py).
   It is not shipped: new-deck.py tests copy it into a scratch tree. */
(function () {
  var log = window.__probe = { inits: 0, keys: [], steps: [], transitions: [], api: null };
  window.SlideDeck.use({
    name: 'probe',
    keys: {
      p: function () { log.keys.push('p'); return true; },
      x: function () { log.keys.push('x'); return false; }
    },
    step: function (dir) {
      var d = window.SlideDeck, s = d.state(), slide = d.slides()[s.index];
      var max = slide ? parseInt(slide.getAttribute('data-probe-steps') || '0', 10) : 0;
      var next = s.step + dir;
      log.steps.push(dir);
      if (next < 0 || next > max) return false;
      d.setStep(next);
      return true;
    },
    transition: function (from, to, apply) {
      log.transitions.push([from && from.id, to && to.id]);
      if (window.__probeInstant) apply({ instant: true }); else apply();
    },
    help: [{ key: 'P', de: 'Sonde', en: 'Probe key' }],
    init: function (api) { log.inits++; log.api = api === window.SlideDeck; }
  });
})();
