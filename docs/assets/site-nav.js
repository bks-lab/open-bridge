/* The shared site nav: the Features disclosure, and the sideways row on
   narrow screens.

   Features groups four pages under one button. Without this script the panel
   opens on hover and on keyboard focus (brand.css), so the links stay
   reachable. With it, the button is a disclosure: click or Enter toggles,
   ArrowDown opens onto the first link, arrows move between links, Escape
   closes and returns focus, a click or tap outside closes, and so does
   tabbing out of the group. */
(function(){
  var nav = document.querySelector(".site-nav");
  if(!nav) return;

  var groups = [].slice.call(nav.querySelectorAll(".nav-group"));
  groups.forEach(function(g){
    var btn = g.querySelector(".nav-group-btn");
    var panel = g.querySelector(".nav-panel");
    if(!btn || !panel) return;
    g.classList.add("nd-js");
    function links(){ return [].slice.call(panel.querySelectorAll("a")); }
    function isOpen(){ return g.classList.contains("open"); }
    function set(open){
      g.classList.toggle("open", open);
      nav.classList.toggle("nd-open", open);
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    }
    function focusAt(i){
      var l = links(); if(!l.length) return;
      l[(i + l.length) % l.length].focus();
    }
    btn.addEventListener("click", function(){ set(!isOpen()); });
    btn.addEventListener("keydown", function(e){
      if(e.key === "ArrowDown"){ e.preventDefault(); set(true); focusAt(0); }
      else if(e.key === "ArrowUp"){ e.preventDefault(); set(true); focusAt(-1); }
    });
    panel.addEventListener("keydown", function(e){
      var l = links(), i = l.indexOf(document.activeElement);
      if(e.key === "ArrowDown"){ e.preventDefault(); focusAt(i + 1); }
      else if(e.key === "ArrowUp"){ e.preventDefault(); focusAt(i - 1); }
      else if(e.key === "Home"){ e.preventDefault(); focusAt(0); }
      else if(e.key === "End"){ e.preventDefault(); focusAt(-1); }
    });
    g.addEventListener("keydown", function(e){
      if(e.key === "Escape" && isOpen()){
        e.preventDefault(); e.stopPropagation(); set(false); btn.focus();
      }
    });
    g.addEventListener("focusout", function(e){
      if(isOpen() && e.relatedTarget && !g.contains(e.relatedTarget)) set(false);
    });
    document.addEventListener("pointerdown", function(e){
      if(isOpen() && !g.contains(e.target)) set(false);
    });
    /* a page that scrolls the row sideways moves the button away from the
       panel; close rather than leave the panel hanging under nothing */
    nav.addEventListener("scroll", function(){ if(isOpen() && nav.scrollWidth > nav.clientWidth) set(false); }, { passive:true });
  });

  /* On narrow screens the site links sit in a row that scrolls sideways
     (brand.css). Bring the current page's entry into view once, without moving
     the page itself: scrollLeft on the row, never scrollIntoView. A page inside
     the Features group is represented by the group's button. */
  var cur = nav.querySelector('[aria-current="page"]');
  if(cur && cur.closest && cur.closest(".nav-panel")){
    var g = cur.closest(".nav-group");
    cur = g && g.querySelector(".nav-group-btn");
  }
  if(!cur || nav.scrollWidth <= nav.clientWidth) return;
  var left = cur.offsetLeft - (nav.clientWidth - cur.offsetWidth) / 2;
  nav.scrollLeft = Math.max(0, left - nav.offsetLeft);
})();
