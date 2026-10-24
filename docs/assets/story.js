/* ============================================================================
   story.js: the command-bridge stage at the top of the landing page.

   Six scenes, driven by scroll through assets/scroll-engine.js:
     0  the finished bridge: agents left, the rest of your world around it
     1  cold start: the links drop, loose files drift
     2  the substrate: the files gather into the bridge (identity, workflow, infra, work)
     3  the links come back one by one, and each says what travels on it
     4  session start: the files travel to the agent (read), a log line travels back (write)
     5  many bridges on one shared CORE, upstream only for scope:core

   three.js (MIT, vendored) is loaded only when the stage runs. Colours come
   from the --stage-* tokens in brand.css, so light and dark both work and a
   palette change needs no edit here. Reduced motion or no WebGL: the captions
   stand stacked and a static list of the stations replaces the scene.
   Self-contained: everything is served from assets/, no network request.
   ============================================================================ */
(function () {
  "use strict";
  var root = document.documentElement;
  var section = document.getElementById("story");
  var stage = document.getElementById("story-stage");
  if (!section || !stage || !window.ScrollEngine) return;

  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var glOK = (function () { try { var c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); } catch (e) { return false; } })();
  if (reduce || !glOK) { root.classList.add("story-static"); return; }
  root.classList.add("story-live");

  var E = ScrollEngine, clamp = E.clamp, EASE = E.ease;
  var EN = function (en, de) { return '<span data-lang="en">' + en + '</span><span data-lang="de">' + de + "</span>"; };
  var topbar = document.querySelector(".topbar");

  /* ---------- the script ---------- */
  var TOTAL = 11.8;
  var story = E.create({
    section: section, stage: stage, screens: +section.dataset.screens || 8.5, total: TOTAL,
    offset: function () { return topbar ? Math.round(topbar.getBoundingClientRect().height) : 0; },
    initial: { tilt: .55, cam: 1, lift: .52, hub: 1, draw: 1, flow: .35, stOther: 1, chaos: 0, gather: 0, sub: 0, tags: 0, rwAmp: 0, rw: 0, log: 0, fleet: 0 },
    tweens: [
      // 1 cold start
      [.3, 1.1, { draw: 0, flow: 0, stOther: 0, hub: 0 }, "inOut3"],
      [.3, 1.3, { cam: .7, lift: .26 }, "inOut3"],
      [.7, 1.0, { chaos: 1, tilt: .3 }, "inOut3"],
      // 2 substrate
      [2.5, 1.2, { gather: 1, hub: 1 }, "inOut3"],
      [3.2, .8, { sub: 1 }, "out3"],
      // 3 the links, each with what travels on it
      [4.6, .5, { sub: 0 }],
      [4.7, .8, { stOther: 1, tilt: .55 }, "inOut3"],
      [4.8, 1.6, { draw: 1 }, "inOut2"],
      [5.8, .8, { flow: .9 }],
      [6.0, .6, { tags: 1 }, "out3"],
      // 4 read, then write back
      [6.9, .4, { tags: 0 }],
      [7.0, .5, { rwAmp: 1, flow: .3, stOther: .12 }],
      [7.2, 1.0, { rw: 1 }],
      [8.2, 0, { rw: 1.01 }],
      [8.2, 1.4, { log: 3 }],
      // 5 many bridges
      [9.8, .4, { rwAmp: 0, stOther: 1 }],
      [9.9, 1.5, { fleet: 1, cam: .78, tilt: .2 }, "inOut3"]
    ],
    captions: { els: [].slice.call(section.querySelectorAll(".cap")),
      times: [[-1, .3], [1.0, 2.5], [3.0, 4.6], [5.1, 7.0], [7.3, 9.8], [10.3, 1e9]] },
    steps: { els: [].slice.call(section.querySelectorAll(".story-steps b")), at: [0, 1.0, 3.0, 5.1, 7.3, 10.0] },
    onFrame: function (S, t, info) { if (paint) paint(S, t, info); }
  });
  var paint = null;

  /* ---------- the scene ---------- */
  var STATIONS = [
    { t: "Claude Code", s: EN("reads at session start", "liest beim Start"), a: 162, agent: true },
    { t: "Codex", s: EN("reads AGENTS.md", "liest AGENTS.md"), a: 182, agent: true },
    { t: "Copilot CLI", s: EN("reads AGENTS.md", "liest AGENTS.md"), a: 202, agent: true },
    { t: EN("Calendar", "Kalender"), s: EN("scheduled sends", "geplanter Versand"), a: 124 },
    { t: EN("Channels", "Kanäle"), s: "Mail · Telegram · iMessage", a: 90, tag: EN("drafts, you send", "Entwurf, du sendest") },
    { t: "Wiki", s: EN("docs · minutes", "Doku · Protokolle"), a: 54 },
    { t: "Repos", s: "ecosystem.yaml", a: 18, tag: EN("code and conventions", "Code und Konventionen") },
    { t: "Boards", s: "GitHub Projects · ADO", a: 342, tag: EN("task status", "Aufgabenstatus") },
    { t: "Secret stores", s: EN("by URI only", "nur per URI"), a: 306, tag: EN("a reference, never the secret", "Verweis, nie das Geheimnis") },
    { t: EN("Machines", "Maschinen"), s: "infra/remotes", a: 270, tag: EN("what runs where", "was wo läuft") },
    { t: "Backups", s: "infra/backups", a: 236 }
  ];
  var CHAOS = ["chat-export-final.txt", "notes (3).md", "prompt that worked.txt", "todo-maybe.md", "client stuff.docx", "chat-export-final-v2.txt", "untitled.md"];
  var LAYERS = ["identity/", "workflow/", "infra/", "work/"];
  var READ = ["AGENTS.md", "ecosystem.yaml", "work/board.md", "work/log.md"];
  // three rows of examples/agency/work/log.md (24.06), shortened to fit; the last is quoted in full on index.html
  var LOG = [["10:18", "💻", "startupxyz", "wired the email-verification step, 6 tests green"], ["11:47", "🐛", "bigcorp", "payment webhooks failing in prod"], ["14:30", "📝", "bigcorp", "logged the Stripe webhook-secret root cause"]];

  import("./vendor/three.module.min.js").then(build).catch(function (e) {
    console.error(e); story.destroy(); root.classList.remove("story-live"); root.classList.add("story-static");
  });

  function build(THREE) {
    THREE.ColorManagement.enabled = false;                 // tokens land 1:1
    var canvas = document.getElementById("story-gl");
    var renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, powerPreference: "high-performance" });
    renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
    var mobile = innerWidth < 900;
    renderer.setPixelRatio(Math.min(devicePixelRatio, mobile ? 1.5 : 2));
    var scene = new THREE.Scene();
    var camera = new THREE.PerspectiveCamera(32, 1, .1, 200);
    var TAN = Math.tan(THREE.MathUtils.degToRad(16));
    var rig = new THREE.Group(); scene.add(rig);
    var deck = new THREE.Group(); rig.add(deck);

    /* colours from CSS tokens, re-read on theme change */
    var col = {}, pulses = null, dust = null;
    var mats = { link: [], linkAgent: [], line: [], strong: [], core: [], sweep: [] };
    var tok = function (n, f) { var v = getComputedStyle(root).getPropertyValue(n).trim(); return new THREE.Color(v || f); };
    function readColors() {
      col.surface = tok("--stage-surface", "#101419"); col.line = tok("--stage-line", "#345373");
      col.link = tok("--stage-link", "#5690D2"); col.hi = tok("--stage-hi", "#5FA0D9");
      col.core = tok("--stage-core", "#182A40"); col.dust = tok("--stage-dust", "#333E4C");
      renderer.setClearColor(col.surface, 1);
      mats.link.forEach(function (m) { m.uniforms.uCol.value.copy(col.line); m.uniforms.uHi.value.copy(col.hi); });
      mats.linkAgent.forEach(function (m) { m.uniforms.uCol.value.copy(col.link); m.uniforms.uHi.value.copy(col.hi); });
      mats.line.forEach(function (m) { m.color.copy(col.line); });
      mats.strong.forEach(function (m) { m.color.copy(col.link); });
      mats.core.forEach(function (m) { m.color.copy(col.core); });
      mats.sweep.forEach(function (m) { m.color.copy(col.line); });
      if (pulses) pulses.material.uniforms.uCol.value.copy(col.hi);
      if (dust) dust.material.color.copy(col.dust);
    }
    readColors();

    var RX = mobile ? 3.6 : 5.6, RY = mobile ? 4.2 : 3.3;
    var rad = function (a) { return a * Math.PI / 180; };
    var posOf = function (a) { return new THREE.Vector3(Math.cos(rad(a)) * RX, Math.sin(rad(a)) * RY, 0); };

    function lineMat(agent) {
      var m = new THREE.ShaderMaterial({
        transparent: true, depthWrite: false,
        uniforms: { uDraw: { value: 1 }, uFlow: { value: 0 }, uDir: { value: 1 }, uTime: { value: 0 }, uA: { value: 1 },
          uCol: { value: (agent ? col.link : col.line).clone() }, uHi: { value: col.hi.clone() } },
        vertexShader: "attribute float aT; varying float vT; void main(){ vT=aT; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.); }",
        fragmentShader: "uniform float uDraw,uFlow,uDir,uTime,uA; uniform vec3 uCol,uHi; varying float vT;" +
          "void main(){ if(vT>uDraw) discard; float f=fract(vT*2.2-uTime*.45*uDir); float p=smoothstep(.78,1.,f)*uFlow;" +
          "gl_FragColor=vec4(mix(uCol,uHi,p),(.6+.4*p)*uA); }"
      });
      (agent ? mats.linkAgent : mats.link).push(m);
      return m;
    }
    function makeLink(p0, p2, bend, agent) {
      var mid = p0.clone().add(p2).multiplyScalar(.5);
      var perp = new THREE.Vector3(-(p2.y - p0.y), p2.x - p0.x, 0).normalize().multiplyScalar(bend);
      var curve = new THREE.QuadraticBezierCurve3(p0, mid.add(perp), p2);
      var pts = curve.getPoints(80);
      var g = new THREE.BufferGeometry().setFromPoints(pts);
      g.setAttribute("aT", new THREE.Float32BufferAttribute(pts.map(function (_, i) { return i / 80; }), 1));
      return { line: new THREE.Line(g, lineMat(agent)), curve: curve, draw: 0, flow: 0, dir: 1, a: 1 };
    }

    var stations = STATIONS.map(function (st, i) {
      var p = posOf(st.a);
      var link = makeLink(new THREE.Vector3(Math.cos(rad(st.a)) * 1.45, Math.sin(rad(st.a)) * 1.45, 0), p.clone().multiplyScalar(.9), i % 2 ? .35 : -.35, st.agent);
      deck.add(link.line);
      return { t: st.t, s: st.s, tag: st.tag, agent: st.agent, p: p, link: link };
    });

    function circle(r, strong) {
      var pts = []; for (var i = 0; i <= 128; i++) { var a = i / 128 * Math.PI * 2; pts.push(new THREE.Vector3(Math.cos(a) * r, Math.sin(a) * r, 0)); }
      var m = new THREE.LineBasicMaterial({ color: strong ? col.link : col.line, transparent: true });
      (strong ? mats.strong : mats.line).push(m);
      return new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), m);
    }
    function makeHub() {
      var g = new THREE.Group();
      var rings = [circle(.55, true), circle(.95, false), circle(1.4, false)];
      rings.forEach(function (r) { g.add(r); });
      var tk = []; for (var i = 0; i < 72; i++) { var a = i / 72 * Math.PI * 2, l = i % 6 ? 1.52 : 1.62;
        tk.push(new THREE.Vector3(Math.cos(a) * 1.45, Math.sin(a) * 1.45, 0), new THREE.Vector3(Math.cos(a) * l, Math.sin(a) * l, 0)); }
      var tm = new THREE.LineBasicMaterial({ color: col.line, transparent: true }); mats.line.push(tm);
      var ticks = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(tk), tm); g.add(ticks);
      var cm = new THREE.MeshBasicMaterial({ color: col.core, transparent: true }); mats.core.push(cm);
      var core = new THREE.Mesh(new THREE.CircleGeometry(.55, 64), cm); core.position.z = -.01; g.add(core);
      var sm = new THREE.MeshBasicMaterial({ color: col.line, transparent: true, side: THREE.DoubleSide }); mats.sweep.push(sm);
      var sweep = new THREE.Mesh(new THREE.RingGeometry(.97, 1.38, 64, 1, 0, Math.PI / 7), sm); g.add(sweep);
      return { g: g, ticks: ticks, sweep: sweep, set: function (a) {
        rings.forEach(function (r, i) { r.material.opacity = a * [1, .9, .7][i]; });
        ticks.material.opacity = a * .8; core.material.opacity = a; sweep.material.opacity = a * .22; } };
    }
    var hub = makeHub(); deck.add(hub.g);
    var peers = [makeHub(), makeHub()]; peers.forEach(function (h) { deck.add(h.g); });

    function rrect(w, h, r) {
      var s = new THREE.Shape(); s.moveTo(-w / 2 + r, -h / 2); s.lineTo(w / 2 - r, -h / 2); s.quadraticCurveTo(w / 2, -h / 2, w / 2, -h / 2 + r);
      s.lineTo(w / 2, h / 2 - r); s.quadraticCurveTo(w / 2, h / 2, w / 2 - r, h / 2); s.lineTo(-w / 2 + r, h / 2); s.quadraticCurveTo(-w / 2, h / 2, -w / 2, h / 2 - r);
      s.lineTo(-w / 2, -h / 2 + r); s.quadraticCurveTo(-w / 2, -h / 2, -w / 2 + r, -h / 2);
      var m = new THREE.LineBasicMaterial({ color: col.link, transparent: true }); mats.strong.push(m);
      return new THREE.Line(new THREE.BufferGeometry().setFromPoints(s.getPoints(16)), m);
    }
    var FX = mobile ? 2.05 : 4.4, FY = 1.5, CY = -2.0, UX = mobile ? 3.2 : 6.9;
    var coreBox = rrect(mobile ? 6.4 : 11, 1.0, .18); coreBox.position.set(0, CY, 0); deck.add(coreBox);
    var fleetLinks = [-FX, 0, FX].map(function (x, i) {
      var l = makeLink(new THREE.Vector3(x, CY + .5, 0), new THREE.Vector3(x, FY - (i === 1 ? 1.0 : .7), 0), 0, false); deck.add(l.line); return l; });
    var upLink = makeLink(new THREE.Vector3(mobile ? 3.2 : 5.5, CY, 0), new THREE.Vector3(UX, CY - 1.4, 0), .3, true);
    deck.add(upLink.line);

    var allLinks = stations.map(function (s) { return s.link; }).concat(fleetLinks, [upLink]);
    var PN = allLinks.length * 2;
    var pGeo = new THREE.BufferGeometry();
    pGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(PN * 3), 3));
    pGeo.setAttribute("aA", new THREE.BufferAttribute(new Float32Array(PN), 1));
    pulses = new THREE.Points(pGeo, new THREE.ShaderMaterial({ transparent: true, depthWrite: false,
      uniforms: { uPx: { value: renderer.getPixelRatio() }, uCol: { value: col.hi.clone() } },
      vertexShader: "attribute float aA; varying float vA; uniform float uPx; void main(){ vA=aA; gl_PointSize=uPx*(6.+6.*aA); gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.); }",
      fragmentShader: "uniform vec3 uCol; varying float vA; void main(){ float d=length(gl_PointCoord-.5); if(d>.5) discard; gl_FragColor=vec4(uCol, vA*smoothstep(.5,.15,d)); }" }));
    deck.add(pulses);

    var DN = mobile ? 60 : 120, dpos = new Float32Array(DN * 3);
    for (var i = 0; i < DN; i++) { dpos[i * 3] = (Math.random() - .5) * 26; dpos[i * 3 + 1] = (Math.random() - .5) * 16; dpos[i * 3 + 2] = -2 - Math.random() * 10; }
    var dGeo = new THREE.BufferGeometry(); dGeo.setAttribute("position", new THREE.BufferAttribute(dpos, 3));
    dust = new THREE.Points(dGeo, new THREE.PointsMaterial({ color: col.dust, size: 2, sizeAttenuation: false }));
    scene.add(dust);

    /* HTML labels pinned to 3D points (crisp text, page fonts, both languages) */
    var labelsEl = document.getElementById("story-labels");
    var L = [];
    function addLabel(html, cls, pos, anchor) {
      var el = document.createElement("div"); el.className = "lb"; el.innerHTML = '<div class="' + cls + '">' + html + "</div>";
      labelsEl.appendChild(el); var o = { el: el, pos: pos, a: 0, anchor: anchor || "c", scale: 1, last: "" }; L.push(o); return o;
    }
    stations.forEach(function (s) {
      if (s.tag && !mobile) s.tagLb = addLabel(s.tag, "tag", s.link.curve.getPoint(.46));
      s.lb = addLabel("<b></b><span>" + s.t + "<small>" + s.s + "</small></span>", "st" + (s.agent ? " agent" : ""), s.p);
    });
    var hubLb = addLabel("<span>open-bridge</span><small>" + EN("plain text in git", "Plain Text in Git") + "</small>", "hubl", new THREE.Vector3());
    var layerLbs = LAYERS.map(function (txt) { return addLabel(txt, "dir", new THREE.Vector3()); });
    var chaos = CHAOS.map(function (txt, i) { var a = (i / CHAOS.length) * Math.PI * 2 + .4, r = 2.4 + (i % 3) * .7;
      return { from: new THREE.Vector3(Math.cos(a) * r * (mobile ? .5 : 1.25) + (mobile ? 1.1 : 0), Math.sin(a) * r * .8, .4), lb: addLabel(txt, "fl", new THREE.Vector3()), seed: i * 1.7 }; });
    var readLbs = READ.map(function (txt) { return addLabel(txt, "fl rd", new THREE.Vector3()); });
    var writeLb = addLabel("+ 14:30 · 📝 · bigcorp", "fl wr", new THREE.Vector3());
    var logLb = addLabel('<div class="log"><div class="h">work/log.md · ' + EN("written back", "zurückgeschrieben") + "</div>" +
      LOG.map(function (r) { return '<div class="r">| ' + r[0] + " | <em>" + r[1] + "</em> " + r[2] + " | " + r[3] + "</div>"; }).join("") + "</div>", "", new THREE.Vector3(), mobile ? "c" : "l");
    var logRows = [].slice.call(logLb.el.querySelectorAll(".r"));
    var fleetLbs = [
      addLabel("<b></b><span>user/client-a<small>" + EN("one bridge per client", "eine Bridge pro Kunde") + "</small></span>", "st", new THREE.Vector3(-FX, mobile ? FY + .95 : FY - 1.0, 0)),
      addLabel("<b></b><span>user/you<small>" + EN("your context (USER)", "dein Kontext (USER)") + "</small></span>", "st agent", new THREE.Vector3(0, FY - 1.3, 0)),
      addLabel("<b></b><span>user/client-b<small>" + EN("separate data", "getrennte Daten") + "</small></span>", "st", new THREE.Vector3(FX, mobile ? FY + .95 : FY - 1.0, 0)),
      addLabel("<b></b><span>main (CORE)<small>skills · docs · schemas · standing orders</small></span>", "st core", new THREE.Vector3(0, CY, 0)),
      addLabel("<b></b><span>upstream<small>bks-lab/open-bridge · /bridge-promote</small></span>", "st", new THREE.Vector3(UX, CY - 1.4, 0))
    ];
    if (mobile) fleetLbs[4].el.style.display = "none";
    /* cold start: each agent starts empty */
    var emptyLbs = stations.filter(function (s) { return s.agent; }).map(function (s) {
      return addLabel("↺ " + EN("context: empty", "Kontext: leer"), "tag warn", s.p.clone().add(new THREE.Vector3(mobile ? .2 : -.15, -.62, 0))); });
    /* fleet: what may leave, what stays */
    var scopeLbs = [
      addLabel("scope:core · /bridge-promote", "tag", upLink.curve.getPoint(.5).add(new THREE.Vector3(mobile ? 0 : .9, .25, 0))),
      addLabel(EN("scope:user stays local", "scope:user bleibt lokal"), "tag", new THREE.Vector3(mobile ? 0 : 1.35, mobile ? CY - .95 : (FY - 1.3 + CY + .5) / 2, 0)),
      addLabel(EN("templates, conflict-free merge", "Templates, konfliktfreier Merge"), "tag", new THREE.Vector3(mobile ? -1.0 : -1.55, (FY - 1.3 + CY + .5) / 2, 0))
    ];
    if (mobile) { scopeLbs[0].el.style.display = "none"; scopeLbs[2].el.style.display = "none"; }
    var scopeSide = mobile ? null : false;

    var SIDE_MQ = window.matchMedia("(min-width:901px) and (max-height:800px) and (min-aspect-ratio:7/5)");
    var side = SIDE_MQ.matches;
    var baseCam = 20, camW = 10;
    function fit() {
      var w = canvas.clientWidth, h = canvas.clientHeight;
      renderer.setSize(w, h, false); camera.aspect = w / Math.max(1, h); camera.updateProjectionMatrix();
      side = SIDE_MQ.matches;
      var needW = RX + (mobile ? 1.4 : 2.0), needH = RY * Math.cos(.5) + .9;
      var share = mobile ? .36 : side ? .86 : .46;          // share of the height the scene may use
      camW = needW / (TAN * camera.aspect * (side ? .5 : 1));  // side layout: the right half of the width
      baseCam = Math.max(camW, needH / (TAN * share));
    }
    addEventListener("resize", fit); fit();
    new MutationObserver(readColors).observe(root, { attributes: true, attributeFilter: ["class"] });
    var par = { x: 0, y: 0, tx: 0, ty: 0 }, v = 0, v3 = new THREE.Vector3();
    if (!mobile) stage.addEventListener("pointermove", function (e) { par.tx = (e.clientX / innerWidth - .5) * .08; par.ty = (e.clientY / innerHeight - .5) * .05; });

    paint = function (S, t, info) {
      var time = info.now;
      v += (clamp(-1, 1, info.vel * .6) - v) * .08;
      par.x += (par.tx - par.x) * .05; par.y += (par.ty - par.y) * .05;
      var fleetW = mobile ? 1.25 : (UX + 2.2) / (RX + 2.0);   // the fleet is wider than the bridge
      var camF = side ? 1 : S.cam;                          // side layout: no room to win back after the hero
      var cam = Math.max(baseCam * camF, camW * (1 + (fleetW - 1) * S.fleet)), halfH = TAN * cam;
      camera.position.z = cam;
      rig.position.y = side ? 0 : halfH * (mobile ? S.lift + .04 : S.lift);
      rig.position.x = side ? halfH * camera.aspect * (.38 - .12 * S.fleet) : 0;
      rig.rotation.y = par.x; rig.rotation.x = par.y;
      deck.rotation.x = -S.tilt * .9;

      hub.g.position.set(0, S.fleet * FY, 0); hub.g.scale.setScalar(1 - .38 * S.fleet);
      hub.set(.25 + .75 * S.hub);
      hub.ticks.rotation.z = info.progress * 2.4 + time * .015; hub.sweep.rotation.z = -time * .35 - info.progress * 6;
      peers.forEach(function (h, i) { h.g.position.set(i ? FX : -FX, FY * .95, 0); h.g.scale.setScalar(.48); h.set(S.fleet);
        h.ticks.rotation.z = -time * .02 * (i ? 1 : -1); h.sweep.rotation.z = -time * .35 + i * 2; h.g.visible = S.fleet > .01; });
      coreBox.material.opacity = S.fleet; coreBox.visible = S.fleet > .01;

      var N = stations.length, st = .32, fade = 1 - S.fleet;
      stations.forEach(function (s, i) {
        var on = s.agent ? 1 : S.stOther, k = s.link;
        var d = clamp(0, 1, S.draw * (1 + st * (N - 1)) - i * st);
        k.draw = d * on; k.a = fade * on;
        if (s.agent && S.rwAmp > 0) { k.flow = Math.max(S.flow, S.rwAmp); k.dir = S.rw < 1 ? 1 : -1; }
        else { k.flow = S.flow * (1 - .6 * S.rwAmp); k.dir = 1; }
        s.lb.a = fade * on;
        if (s.tagLb) s.tagLb.a = S.tags * clamp(0, 1, d * 1.5 - .5) * fade;
      });
      fleetLinks.forEach(function (k) { k.draw = S.fleet; k.flow = S.fleet * .8; k.dir = 1; k.a = S.fleet; });
      upLink.draw = clamp(0, 1, S.fleet * 2 - 1); upLink.flow = S.fleet; upLink.dir = 1; upLink.a = S.fleet;

      var pi = 0, P = pGeo.attributes.position.array, A = pGeo.attributes.aA.array;
      allLinks.forEach(function (k, li) {
        var m = k.line.material.uniforms;
        m.uDraw.value = k.draw; m.uFlow.value = k.flow; m.uDir.value = k.dir; m.uTime.value = time; m.uA.value = k.a;
        k.line.visible = k.a > .01 && k.draw > .001 && !(mobile && k === upLink);
        for (var j = 0; j < 2; j++) {
          var tt = (time * (.22 + .5 * Math.abs(v)) + j * .5 + li * .137) % 1; if (k.dir < 0) tt = 1 - tt;
          var pt = k.curve.getPoint(tt); P[pi * 3] = pt.x; P[pi * 3 + 1] = pt.y; P[pi * 3 + 2] = pt.z;
          A[pi] = tt < k.draw && k.line.visible ? k.flow * k.a * Math.sin(Math.PI * Math.min(1, tt / Math.max(k.draw, .001))) : 0; pi++;
        }
      });
      pGeo.attributes.position.needsUpdate = true; pGeo.attributes.aA.needsUpdate = true;

      hubLb.pos = new THREE.Vector3(0, S.fleet * FY, 0); hubLb.a = (1 - S.fleet) * (.35 + .65 * S.hub);
      LAYERS.forEach(function (_, i) { var a = rad(45 + i * 90), r = (mobile ? 1.45 : .95) + .75 * (1 - S.sub);
        layerLbs[i].pos = new THREE.Vector3(Math.cos(a) * r * 1.25, Math.sin(a) * r, 0); layerLbs[i].a = S.sub * fade; });
      chaos.forEach(function (c) {
        var g = S.gather;
        c.lb.pos = c.from.clone().multiplyScalar(1 - g).add(new THREE.Vector3(Math.sin(time * .4 + c.seed) * .12, Math.cos(time * .3 + c.seed) * .1, 0));
        c.lb.a = S.chaos * (1 - g) * (1 - g); c.lb.scale = 1 - .6 * g;
      });
      /* read: the files travel from the bridge to Claude Code, one after another */
      var claude = stations[0].link.curve;
      readLbs.forEach(function (o, i) {
        var k = clamp(0, 1, Math.min(S.rw, 1) * 1.9 - i * .3);
        o.pos = claude.getPoint(.06 + .86 * EASE.inOut2(k));
        o.a = S.rw > 1 ? 0 : S.rwAmp * clamp(0, 1, Math.sin(Math.PI * k) * 1.6);
      });
      /* write: one log line travels back into the bridge, then lands in the log */
      var kw = clamp(0, 1, S.log / 1.2);
      writeLb.pos = stations[1].link.curve.getPoint(.92 - .86 * EASE.inOut2(kw));
      writeLb.a = S.rw > 1 ? S.rwAmp * clamp(0, 1, Math.sin(Math.PI * kw) * 1.6) : 0;

      logLb.pos = new THREE.Vector3(mobile ? 0 : side ? .9 : 2.0, mobile ? -3.7 : side ? -3.1 : -.55, .2); logLb.anchor = mobile || side ? "c" : "l";
      logLb.a = clamp(0, 1, S.log * 3) * fade;
      logRows.forEach(function (r, i) { r.style.opacity = clamp(0, 1, S.log - i); });
      fleetLbs.forEach(function (l) { l.a = S.fleet; });
      if (!mobile && side !== scopeSide) {                          // compact fleet labels in the side layout, like on a phone
        scopeSide = side;
        scopeLbs[1].pos = new THREE.Vector3(side ? 0 : 1.35, side ? CY - .95 : (FY - 1.3 + CY + .5) / 2, 0);
        scopeLbs[2].el.style.display = side ? "none" : "";
      }
      emptyLbs.forEach(function (l) { l.a = S.chaos * (1 - S.gather); });
      scopeLbs.forEach(function (l, i) { l.a = clamp(0, 1, S.fleet * 2 - (i === 0 ? 1.2 : .8)); });

      rig.updateMatrixWorld(true); camera.updateMatrixWorld(true);
      var w = canvas.clientWidth, h = canvas.clientHeight;
      L.forEach(function (o) {
        if (o.a < .01) { if (o.last !== "0") { o.el.style.opacity = 0; o.last = "0"; } return; }
        v3.copy(o.pos).applyMatrix4(deck.matrixWorld).project(camera);
        var x = (v3.x * .5 + .5) * w, y = (-v3.y * .5 + .5) * h;
        o.el.style.transform = "translate(" + x.toFixed(1) + "px," + y.toFixed(1) + "px) translate(" + (o.anchor === "l" ? "0%" : "-50%") + ",-50%) scale(" + o.scale.toFixed(3) + ")";
        var a = o.a.toFixed(3); if (a !== o.last) { o.el.style.opacity = a; o.last = a; }
      });
      renderer.render(scene, camera);
    };
    root.classList.add("story-ready");
  }
})();
