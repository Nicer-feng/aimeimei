'use strict';
/* Progressive motion: no business state, no timers, safe without WAAPI. */
window.CloudMotion = (() => {
  const reduce = matchMedia('(prefers-reduced-motion: reduce)');
  const running = new Set();
  let navRect, origin;
  function animate(element, frames, options = {}) {
    if (!element || reduce.matches || !element.animate) return;
    const animation = element.animate(frames, {duration:320,easing:'cubic-bezier(.2,.75,.2,1)',...options});
    running.add(animation);
    animation.finished.catch(() => {}).finally(() => running.delete(animation));
    return animation;
  }
  reduce.addEventListener('change', () => { if (reduce.matches) running.forEach(a => a.cancel()); });
  function captureNav() { navRect = document.querySelector('#nav .active')?.getBoundingClientRect(); }
  function nav() {
    const active = document.querySelector('#nav .active');
    document.querySelectorAll('#nav [data-section]').forEach(button => {
      if (button === active) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
    if (navRect && active) {
      const next = active.getBoundingClientRect();
      // Move only the destination icon, keeping its hit target and label steady.
      animate(active.querySelector('svg'), [{transform:`translate(${(navRect.x-next.x)*.15}px,${(navRect.y-next.y)*.15}px)`,opacity:.4},{transform:'translate(0,0)',opacity:1}]);
    }
    navRect = null;
  }
  function reveal(container) {
    if (reduce.matches || !container) return;
    const items = [...container.querySelectorAll('.stat,.panel,tbody tr,.file-tile,.settings-form')].slice(0,16);
    if (!items.length) items.push(container);
    items.forEach((item,index) => animate(item,[{opacity:0,transform:'translateY(10px)'},{opacity:1,transform:'translateY(0)'}],{delay:Math.min(index*24,168),duration:360}));
  }
  function positions(container) {
    if (reduce.matches || !container) return new Map();
    return new Map([...container.children].map(node => [node,node.getBoundingClientRect()]));
  }
  function rearrange(container, previous) {
    if (reduce.matches || !container) return;
    [...container.children].forEach(node => {
      const before = previous.get(node), after = node.getBoundingClientRect();
      if (before && (before.x !== after.x || before.y !== after.y)) {
        animate(node,[{transform:`translate(${before.x-after.x}px,${before.y-after.y}px)`},{transform:'translate(0,0)'}],{duration:300});
      } else if (!before) {
        animate(node,[{opacity:0,transform:'scale(.94)'},{opacity:1,transform:'scale(1)'}]);
      }
    });
  }
  function captureOrigin() {
    const target = document.activeElement;
    origin = target && target !== document.body ? target.getBoundingClientRect() : null;
  }
  function open(panel, preview = false) {
    if (reduce.matches) return;
    panel.getAnimations().forEach(animation => animation.cancel());
    const box = panel.getBoundingClientRect();
    const x = origin ? Math.max(-90,Math.min(90,origin.x+origin.width/2-box.x-box.width/2)) : 0;
    const y = origin ? Math.max(-45,Math.min(45,origin.y+origin.height/2-box.y-box.height/2)) : 16;
    animate(panel,[{opacity:0,transform:`translate(${preview?36:x}px,${preview?0:y}px) scale(${preview ? .98 : .96})`},{opacity:1,transform:'translate(0,0) scale(1)'}],{duration:preview?400:280});
  }
  document.addEventListener('change', event => {
    if (!event.target.matches('input[type=checkbox][data-select]')) return;
    animate(event.target.closest('tr,.file-tile')?.querySelector('.file-icon'),[{transform:'scale(.88)'},{transform:'scale(1.06)',offset:.65},{transform:'scale(1)'}],{duration:260});
  });
  return {captureNav,nav,reveal,captureOrigin,open,positions,rearrange};
})();
