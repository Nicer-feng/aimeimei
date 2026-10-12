'use strict';
/* Interaction patterns adapted from scaffold-master; see vendor/scaffold-master.LICENSE. */
window.UIMotion = (() => {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const running = new Map();
  const thumbs = new WeakMap();
  const pressed = new Set();
  const ease = 'cubic-bezier(.16,1,.3,1)';
  let pointer = null;
  const enabled = () => !reduced.matches && !document.hidden;

  function cancel(element) {
    running.get(element)?.cancel();
    running.delete(element);
  }
  function animate(element, frames, options = {}) {
    if (!element) return null;
    cancel(element);
    if (!enabled() || !element.animate) return null;
    let animation;
    try { animation = element.animate(frames, { duration: 220, easing: ease, ...options }); }
    catch { return null; }
    running.set(element, animation);
    animation.finished.then(() => {
      if (running.get(element) !== animation) return;
      running.delete(element);
      animation.cancel();
    }, () => { if (running.get(element) === animation) running.delete(element); });
    return animation;
  }
  function open(panel, kind = 'modal') {
    if (!panel) return;
    const rect = panel.getBoundingClientRect();
    const point = pointer && performance.now() - pointer.at < 600 ? pointer : null;
    const origin = point && kind === 'modal'
      ? `${Math.max(0, Math.min(rect.width, point.x - rect.left))}px ${Math.max(0, Math.min(rect.height, point.y - rect.top))}px`
      : kind === 'pop' ? '50% 100%' : '50% 50%';
    animate(panel, [
      { opacity: 0, scale: kind === 'drawer' ? '1' : '.965', translate: kind === 'drawer' ? '28px 0' : '0 8px', transformOrigin: origin },
      { opacity: 1, scale: '1', translate: '0 0', transformOrigin: origin }
    ], { duration: kind === 'pop' ? 190 : 240 });
  }
  function leave(panel, done, kind = 'modal') {
    const animation = animate(panel, [
      { opacity: getComputedStyle(panel).opacity, scale: '1', translate: '0 0' },
      { opacity: 0, scale: kind === 'drawer' ? '1' : '.98', translate: kind === 'drawer' ? '22px 0' : '0 5px' }
    ], { duration: 160 });
    if (!animation) { done(); return; }
    animation.finished.then(done, () => {});
  }
  function reveal(container, selector) {
    if (!container || !enabled()) return;
    const nodes = [...container.querySelectorAll(selector)].filter(n => n.getClientRects().length).slice(0, 10);
    nodes.forEach((node, index) => animate(node, [
      { opacity: 0, translate: '0 7px' }, { opacity: 1, translate: '0 0' }
    ], { duration: 220, delay: Math.min(index * 18, 90) }));
  }
  function nav(parent, selector) {
    if (!parent) return;
    const active = parent.querySelector(selector);
    if (!active || !active.getClientRects().length || !parent.getClientRects().length) return;
    let entry = thumbs.get(parent);
    if (!entry || entry.thumb.parentElement !== parent) {
      const thumb = document.createElement('span');
      thumb.className = 'ui-motion-thumb';
      thumb.setAttribute('aria-hidden', 'true');
      parent.classList.add('ui-motion-nav');
      parent.prepend(thumb);
      entry = { thumb, rect: null };
      thumbs.set(parent, entry);
    }
    const box = parent.getBoundingClientRect(), target = active.getBoundingClientRect();
    const sx = box.width / parent.offsetWidth || 1, sy = box.height / parent.offsetHeight || 1;
    // Direct navigation children use layout coordinates, unaffected by press/hover transforms.
    const direct = active.offsetParent === parent;
    const rect = { x: direct ? active.offsetLeft : (target.left - box.left) / sx + parent.scrollLeft - parent.clientLeft,
      y: direct ? active.offsetTop : (target.top - box.top) / sy + parent.scrollTop - parent.clientTop,
      width: active.offsetWidth, height: active.offsetHeight };
    const previous = entry.rect;
    Object.assign(entry.thumb.style, { left: `${rect.x}px`, top: `${rect.y}px`, width: `${rect.width}px`, height: `${rect.height}px` });
    entry.rect = rect;
    if (previous) animate(entry.thumb, [
      { translate: `${previous.x - rect.x}px ${previous.y - rect.y}px` }, { translate: '0 0' }
    ], { duration: 260 });
  }
  // Watch only fixed overlay state attributes, never message/content mutations.
  function watch(surface, panel = surface, kind = 'modal') {
    if (!surface || !panel) return;
    panel.classList.add('ui-motion-managed');
    const visible = () => !surface.hidden && (surface.tagName === 'DIALOG' ? surface.open : surface.classList.contains('show'));
    let wasVisible = visible();
    new MutationObserver(() => {
      const next = visible();
      if (next === wasVisible) return;
      wasVisible = next;
      if (next) open(panel, kind);
      else cancel(panel);
    }).observe(surface, { attributes: true, attributeFilter: ['class', 'open', 'hidden'] });
  }
  function release() {
    pressed.forEach(element => {
      const current = getComputedStyle(element).scale;
      animate(element, [{ scale: current === 'none' ? '.97' : current }, { scale: '1.015', offset: .6 }, { scale: '1' }], { duration: 210 });
    });
    pressed.clear();
  }
  const buttons = 'button.ui-btn,button.ui-icon-btn,.sidebar-action,.sidebar-tool-card,.admin-nav-item,.token-tab,body.cloud-admin button,body.public-body button';
  document.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    pointer = { x: event.clientX, y: event.clientY, at: performance.now() };
    const button = event.target.closest?.(buttons);
    if (!button || button.disabled || button.closest('#messages,#sideMessages,#officeMount,.pdf-page-grid') || !enabled()) return;
    pressed.add(button);
    animate(button, [{ scale: '1' }, { scale: '.97' }], { duration: 100, fill: 'forwards' });
  }, { passive: true });
  document.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') pointer = null; }, { passive: true });
  window.addEventListener('pointerup', release, { passive: true });
  window.addEventListener('pointercancel', release, { passive: true });
  window.addEventListener('blur', release);
  const stop = () => { running.forEach(animation => animation.finish()); pressed.clear(); };
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
  reduced.addEventListener('change', () => { if (reduced.matches) stop(); });
  // A visual enhancement must never interrupt a business event handler.
  const safe = fn => (...args) => { try { return fn(...args); } catch { return null; } };
  return { animate: safe(animate), cancel: safe(cancel), open: safe(open),
    leave(panel, done, kind) { try { leave(panel, done, kind); } catch { done(); } },
    reveal: safe(reveal), nav: safe(nav), watch: safe(watch) };
})();
