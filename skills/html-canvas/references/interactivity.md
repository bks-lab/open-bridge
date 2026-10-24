---
summary: "Optional vanilla-JS behaviours for html-canvas: scroll reveal, count-up, filtering, data hydration, scrollspy; decks live in html-slides"
type: reference
last_updated: 2026-10-24
related:
  - skills/html-canvas/SKILL.md
  - skills/html-canvas/assets/animations.css
  - skills/html-slides/SKILL.md
---

# html-canvas: Interactivity

The shell already ships the **theme** and **language** controllers. Everything
here is *optional enhancement*: paste only what a deliverable needs, at the end
of `<body>`. Two non-negotiables, because the page must read with JS or motion off:

- **Graceful degradation:** if `IntersectionObserver` is missing or
  `prefers-reduced-motion` is set, reveal everything immediately. Never leave
  content stuck at `opacity:0`.
- **Print safety:** observers don't fire for print. Every reveal helper
  force-shows its content on `beforeprint`.

All snippets are vanilla, dependency-free, single-file.

---

## Scroll reveal (long pages)
Pairs with the `.reveal` rule in `animations.css`. One-shot (unobserves after first show).
```html
<script>
(function(){
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var nodes = document.querySelectorAll('.reveal');
  function showAll(){ nodes.forEach(function(el){ el.classList.add('visible'); }); }
  if (reduce || !('IntersectionObserver' in window)) { showAll(); return; }
  var obs = new IntersectionObserver(function(es){
    es.forEach(function(e){ if(e.isIntersecting){ e.target.classList.add('visible'); obs.unobserve(e.target); } });
  }, { threshold:0.08 });
  nodes.forEach(function(el){ obs.observe(el); });
  window.addEventListener('beforeprint', showAll);
  if (window.matchMedia){ var mq=matchMedia('print'); if(mq.matches) showAll();
    if(mq.addEventListener) mq.addEventListener('change',function(e){ if(e.matches) showAll(); }); }
})();
</script>
```

## Count-up KPI
Animate `[data-count-to="N"]` from 0→N when revealed. Snaps to target under reduced-motion.
Call `animateCounters(document)` on load, or from the reveal observer.
```html
<script>
function animateCounters(scope){
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  scope.querySelectorAll('[data-count-to]').forEach(function(el){
    if(el.dataset.counted==='1') return;
    var target=parseInt(el.getAttribute('data-count-to'),10)||0;
    if(reduce){ el.textContent=target; el.dataset.counted='1'; return; }
    var dur=1100,start=null;
    function step(ts){ if(!start)start=ts; var p=Math.min(1,(ts-start)/dur),e=1-Math.pow(1-p,3);
      el.textContent=Math.round(target*e); if(p<1)requestAnimationFrame(step); else el.dataset.counted='1'; }
    requestAnimationFrame(step);
  });
}
document.addEventListener('DOMContentLoaded',function(){ animateCounters(document); });
</script>
```

## Filter bar (toggle cards by attribute)
Findings/issues/tasks. Buttons carry `data-filter`; cards carry `data-cat`/`data-sev`.
```html
<script>
(function(){
  var bar=document.getElementById('filter-bar'); if(!bar) return;
  var cards=document.querySelectorAll('[data-filterable]');
  bar.addEventListener('click',function(e){
    var b=e.target.closest('.filter-btn'); if(!b) return;
    bar.querySelectorAll('.filter-btn').forEach(function(x){ x.classList.toggle('active',x===b); });
    var f=b.dataset.filter;
    cards.forEach(function(c){ var show=f==='all'||c.dataset.sev===f||c.dataset.cat===f; c.classList.toggle('hidden',!show); });
  });
})();
/* CSS: .hidden{display:none} .filter-btn.active{background:var(--accent-soft);color:var(--accent-text)} */
</script>
```

## Data-attribute hydration (timestamps + sparklines)
Keep the template data-agnostic; hydrate at load. `[data-timestamp]` ISO → relative
time; `<svg class="sparkline" data-values="1,3,5">` → themed bars.
```html
<script>
document.querySelectorAll('[data-timestamp]').forEach(function(el){
  var ts=new Date(el.getAttribute('data-timestamp')); if(isNaN(ts)) return;
  var m=Math.floor((Date.now()-ts)/6e4),h=Math.floor(m/60),d=Math.floor(h/24);
  el.textContent = m<1?'just now':m<60?m+'min ago':h<24?h+'h ago':d<7?d+'d ago':ts.toLocaleDateString(undefined,{day:'2-digit',month:'2-digit'});
});
document.querySelectorAll('.sparkline[data-values]').forEach(function(svg){
  var v=(svg.getAttribute('data-values')||'').split(',').map(Number).filter(function(n){return !isNaN(n);});
  if(!v.length) return;
  var w=80,h=20,g=1,mx=Math.max.apply(null,v.concat([1])),bw=Math.max(1,(w-g*(v.length-1))/v.length);
  svg.setAttribute('viewBox','0 0 '+w+' '+h);
  svg.innerHTML=v.map(function(x,i){ var bh=Math.max(1,x/mx*(h-2));
    return '<rect x="'+i*(bw+g)+'" y="'+(h-bh)+'" width="'+bw+'" height="'+bh+'" rx="1" fill="var(--accent)"><title>'+x+'</title></rect>'; }).join('');
});
</script>
```

---

## Section scrollspy (highlight the active ToC link)
Pairs with the sticky `.secnav` block in `sections.md`: it adds `.active` to the link of the
section currently in view. Pure anchor links still work with this off.
```html
<script>
(function(){
  var links=[].slice.call(document.querySelectorAll('.secnav a[href^="#"]'));
  if(!links.length || !('IntersectionObserver' in window)) return;
  var map={};
  links.forEach(function(a){ var el=document.getElementById(a.getAttribute('href').slice(1)); if(el) map[el.id]=a; });
  var obs=new IntersectionObserver(function(es){
    es.forEach(function(e){ if(e.isIntersecting){ links.forEach(function(x){x.classList.remove('active');}); if(map[e.target.id]) map[e.target.id].classList.add('active'); } });
  },{ rootMargin:'-40% 0px -55% 0px' });
  Object.keys(map).forEach(function(id){ obs.observe(document.getElementById(id)); });
})();
</script>
```

## Slides: use html-slides

A presentation is not a page behaviour. This file used to carry a small copy of a
slide engine; it is gone, because a second engine drifts from the real one and
misses what decks need (tracks, notes, deep links, print, the live stage). Build
decks with the `html-slides` skill: `html-slides/scripts/new-deck.py` splices its
engine, `html-slides/reference/slide-types.md` § Engine Contract documents it, and
`scripts/verify-page.py --deck` checks the result.

A page that should end in a few present-mode panels links to a deck built that
way (the engine's `data-back-href` gives the deck a way back), instead of growing
an engine of its own. To count up numbers on a slide, call
`animateCounters(e.slide)` from `SlideDeck.on('slidechange', function (e) { ... })`.
