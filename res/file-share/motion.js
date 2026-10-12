'use strict';
/* Progressive motion: no business state, no timers, safe without WAAPI. */
window.CloudMotion = (() => {
  const reduce = matchMedia('(prefers-reduced-motion: reduce)');
  function animate(element, frames, options = {}) {
    return window.UIMotion?.animate(element, frames, options);
  }
  function captureNav() {}
  function nav() {
    const active = document.querySelector('#nav .active');
    document.querySelectorAll('#nav [data-section]').forEach(button => {
      if (button === active) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
    window.UIMotion?.nav(document.getElementById('nav'), 'button.active');
  }
  function reveal(container) {
    window.UIMotion?.reveal(container, '.stat,.panel,.file-tile,.settings-form');
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
  function captureOrigin() {}
  function open(panel, preview = false) {
    panel?.classList.add('ui-motion-managed');
    window.UIMotion?.open(panel, preview ? 'drawer' : 'modal');
  }
  function close(panel, done) {
    if (!window.UIMotion) { done(); return; }
    window.UIMotion.leave(panel, done, panel.classList.contains('document-preview') ? 'drawer' : 'modal');
  }
  document.addEventListener('change', event => {
    if (!event.target.matches('input[type=checkbox][data-select]')) return;
    animate(event.target.closest('tr,.file-tile')?.querySelector('.file-icon'),[{transform:'scale(.88)'},{transform:'scale(1.06)',offset:.65},{transform:'scale(1)'}],{duration:260});
  });
  for (const id of ['officeVersions', 'pdfVersions']) window.UIMotion?.watch(document.getElementById(id));
  for (const id of ['officeEditor', 'pdfPageEditor']) {
    const surface = document.getElementById(id);
    window.UIMotion?.watch(surface, surface?.querySelector('.office-toolbar'));
  }
  const resize = new ResizeObserver(nav);
  const container = document.getElementById('nav');
  if (container) resize.observe(container);
  return {captureNav,nav,reveal,captureOrigin,open,close,positions,rearrange};
})();
