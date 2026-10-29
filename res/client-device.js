(() => {
  let ephemeral = '', lastUser = '', lastReport = 0;
  function installationID() {
    try {
      const saved = localStorage.getItem('aimeimei-installation-id');
      if (/^[A-Za-z0-9-]{16,80}$/.test(saved || '')) return saved;
    } catch (_) {}
    if (!ephemeral) {
      if (globalThis.crypto?.randomUUID) ephemeral = crypto.randomUUID();
      else if (globalThis.crypto?.getRandomValues) {
        const bytes = crypto.getRandomValues(new Uint8Array(16));
        ephemeral = Array.from(bytes, n => n.toString(16).padStart(2, '0')).join('');
      }
    }
    try { if (ephemeral) localStorage.setItem('aimeimei-installation-id', ephemeral); } catch (_) {}
    return ephemeral;
  }
  function metadata() {
    const permission = typeof Notification === 'undefined' ? 'not_supported' :
      ({ granted: 'authorized', denied: 'denied', default: 'not_determined' }[Notification.permission] || 'unknown');
    return { installation_id: installationID(), platform: 'web', notification_authorization: permission };
  }
  async function report(user) {
    if (!user || document.hidden || (lastUser === user && Date.now() - lastReport < 60000)) return;
    lastUser = user; lastReport = Date.now();
    try {
      await fetch('/api/session/device-info', { method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(metadata()) });
    } catch (_) {}
  }
  globalThis.MeimeiClientDevice = { metadata, report };
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && typeof state !== 'undefined' && state.authed) report(state.user?.id);
  });
})();
