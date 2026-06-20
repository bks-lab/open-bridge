---
summary: "Optional vanilla-JS behaviours for html-canvas — scroll reveal, slide deck, count-up, filtering, data hydration"
type: reference
last_updated: 2026-06-01
related:
  - skills/html-canvas/SKILL.md
  - skills/html-canvas/assets/animations.css
---

# html-canvas — Interactivity

The shell already ships the **theme** and **language** controllers. Everything
here is *optional enhancement* — paste only what a deliverable needs, at the end
of `<body>`. Two non-negotiables, because the page must read with JS or motion off:

- **Graceful degradation** — if `IntersectionObserver` is missing or
  `prefers-reduced-motion` is set, reveal everything immediately. Never leave
  content stuck at `opacity:0`.
- **Print safety** — observers don't fire for print. Every reveal/deck helper
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
Call `animateCounters(document)` on load, or from the reveal observer / SlideEngine.
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
Pairs with the sticky `.secnav` block in `sections.md` — adds `.active` to the link of the
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

## Slide-deck engine (when the deliverable is a presentation)
Turns `.deck > .slide` markup into a vertical scroll-snap deck: progress bar,
clickable dot rail, mono counter, keyboard (↑↓ Space PageUp/Dn Home End) + swipe,
and an IntersectionObserver that adds `.visible` to the on-screen slide (drives the
`.slide` entrance + counters). `beforeprint` force-shows every slide.

> For a full keyboard-driven slide deck specifically, prefer a dedicated
> slide-deck skill if your Bridge ships one. Use this engine when slides are one
> mode *inside* an html-canvas document (e.g. an explainer that ends in a few
> present-mode panels).

```html
<script>
function SlideEngine(){this.slides=[].slice.call(document.querySelectorAll('.slide'));this.total=this.slides.length;this.current=0;this.buildChrome();this.bind();this.observe();this.update();}
SlideEngine.prototype.buildChrome=function(){var b=document.createElement('div');b.className='deck-progress';this.bar=document.createElement('span');b.appendChild(this.bar);document.body.appendChild(b);
  var c=document.createElement('div');c.className='deck-counter';this.counter=c;document.body.appendChild(c);
  var r=document.createElement('div');r.className='deck-dots';var self=this;this.dots=this.slides.map(function(s,i){var d=document.createElement('button');d.setAttribute('aria-label','Slide '+(i+1));d.addEventListener('click',function(){self.goTo(i);});r.appendChild(d);return d;});document.body.appendChild(r);};
SlideEngine.prototype.bind=function(){var self=this;document.addEventListener('keydown',function(e){var _t=e.target||{};if(_t.isContentEditable||/^(input|textarea|select)$/i.test(_t.tagName||''))return;if(e.key==='ArrowDown'||e.key==='PageDown'||e.key===' '){e.preventDefault();self.next();}else if(e.key==='ArrowUp'||e.key==='PageUp'){e.preventDefault();self.prev();}else if(e.key==='Home'){self.goTo(0);}else if(e.key==='End'){self.goTo(self.total-1);}});
  var y0=null;document.addEventListener('touchstart',function(e){y0=e.touches[0].clientY;},{passive:true});document.addEventListener('touchend',function(e){if(y0==null)return;var dy=e.changedTouches[0].clientY-y0;if(Math.abs(dy)>50){dy<0?self.next():self.prev();}y0=null;});};
SlideEngine.prototype.observe=function(){var self=this;var obs=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){e.target.classList.add('visible');self.current=self.slides.indexOf(e.target);self.update();if(typeof animateCounters==='function')animateCounters(e.target);}});},{threshold:0.5});this.slides.forEach(function(s){obs.observe(s);});
  var fv=function(){self.slides.forEach(function(s){s.classList.add('visible');});};window.addEventListener('beforeprint',fv);if(window.matchMedia){var mq=matchMedia('print');if(mq.matches)fv();if(mq.addEventListener)mq.addEventListener('change',function(e){if(e.matches)fv();});}};
SlideEngine.prototype.goTo=function(i){this.slides[Math.max(0,Math.min(i,this.total-1))].scrollIntoView({behavior:'smooth'});};
SlideEngine.prototype.next=function(){if(this.current<this.total-1)this.goTo(this.current+1);};
SlideEngine.prototype.prev=function(){if(this.current>0)this.goTo(this.current-1);};
SlideEngine.prototype.update=function(){this.bar.style.width=((this.current+1)/this.total*100)+'%';var c=this.current;this.dots.forEach(function(d,i){d.classList.toggle('active',i===c);});this.counter.textContent=(this.current+1)+' / '+this.total;};
document.addEventListener('DOMContentLoaded',function(){ if(document.querySelector('.deck')) new SlideEngine(); });
</script>
```
Deck CSS (scroll-snap container + 16:9 print) lives with the slide entrance in
`animations.css`; add:
```css
.deck{height:100vh;overflow-y:scroll;scroll-snap-type:y mandatory}
.slide{min-height:100vh;scroll-snap-align:start;display:flex;flex-direction:column;justify-content:center}
.deck-progress{position:fixed;top:0;left:0;right:0;height:3px;z-index:60}
.deck-progress span{display:block;height:100%;background:var(--accent);width:0;transition:width .3s}
.deck-dots{position:fixed;right:18px;top:50%;transform:translateY(-50%);display:flex;flex-direction:column;gap:8px;z-index:60}
.deck-dots button{width:9px;height:9px;border-radius:50%;border:1px solid var(--line);background:var(--surface);cursor:pointer}
.deck-dots button.active{background:var(--accent);border-color:var(--accent)}
.deck-counter{position:fixed;bottom:16px;right:18px;font-family:var(--font-mono);font-size:12px;color:var(--muted);z-index:60}
@media print{.deck{height:auto;overflow:visible;scroll-snap-type:none}.slide{min-height:auto;page-break-after:always}.deck-progress,.deck-dots,.deck-counter{display:none}}
```
