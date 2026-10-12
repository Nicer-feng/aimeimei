'use strict';
(() => {
  const motion = window.UIMotion;
  if (!motion) return;
  const overlays = ['promptDialog','favoriteDialog','profileDialog','mediaDialog','ocrDialog','copyDialog','confirmDialog','shareDialog','accentDialog','tokenActivityDialog','globalSearchDialog','changelogDialog','modelPickerDialog','conversationFilesDialog','imagePreviewDialog'];
  for (const id of overlays) {
    const surface = document.getElementById(id);
    if (surface) motion.watch(surface, surface.firstElementChild);
  }
  for (const id of ['interfacePopover','profilePopover']) motion.watch(document.getElementById(id), undefined, 'pop');
  const drawer = document.getElementById('settingsDrawer');
  motion.watch(drawer);
  for (const id of ['readerLibrary','writingDialog']) motion.watch(document.getElementById(id));
  document.querySelectorAll('.token-tabs').forEach(parent => {
    const update = () => motion.nav(parent, '.active,[aria-selected="true"]');
    [...parent.children].forEach(button => new MutationObserver(update).observe(button, { attributes: true, attributeFilter: ['class','aria-selected'] }));
  });
  window.MeimeiMotion = {
    admin() { motion.nav(document.querySelector('.admin-nav-list'), '.admin-nav-item.active'); }
  };
  const resize = new ResizeObserver(() => {
    window.MeimeiMotion.admin();
    document.querySelectorAll('.token-tabs').forEach(parent => motion.nav(parent, '.active,[aria-selected="true"]'));
  });
  if (drawer) resize.observe(drawer);
})();
