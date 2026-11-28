const CHECK_INTERVAL = 60_000;
const SNOOZE_INTERVAL = 10 * 60_000;
const FETCH_TIMEOUT = 8_000;
const releasesUrl = new URL('./releases.js', import.meta.url);
const releaseHeader = /^\s*export\s+const\s+releases\s*=\s*\[\s*\{\s*version\s*:\s*['"]([0-9]+\.[0-9]+\.[0-9]+)['"]/;

function isNewerVersion(latest, current) {
  const latestParts = latest.split('.').map(Number);
  const currentParts = current.split('.').map(Number);
  for (let index = 0; index < currentParts.length; index += 1) {
    if (latestParts[index] !== currentParts[index]) return latestParts[index] > currentParts[index];
  }
  return false;
}

export function watchVersionUpdates(currentVersion) {
  const notice = document.getElementById('sroom-update-notice');
  const text = document.getElementById('sroom-update-version');
  const refresh = document.getElementById('sroom-update-refresh');
  const snooze = document.getElementById('sroom-update-snooze');
  if (!notice || !text || !refresh || !snooze) return;
  let checking = false;
  let availableVersion = '';
  let snoozedVersion = '';
  let snoozedUntil = 0;

  async function check() {
    if (checking || document.hidden) return;
    checking = true;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), FETCH_TIMEOUT);
    try {
      const response = await fetch(releasesUrl, { cache: 'no-store', signal: controller.signal });
      if (!response.ok) return;
      const version = (await response.text()).match(releaseHeader)?.[1];
      if (!version) return;
      if (!isNewerVersion(version, currentVersion)) {
        availableVersion = '';
        notice.hidden = true;
        return;
      }
      if (availableVersion === version && !notice.hidden) return;
      availableVersion = version;
      if (snoozedVersion === version && Date.now() < snoozedUntil) return;
      text.textContent = `v${currentVersion} → v${version}`;
      notice.hidden = false;
    } catch {
      // 网络恢复后会重新检查版本。
    } finally {
      window.clearTimeout(timeout);
      checking = false;
    }
  }

  refresh.addEventListener('click', () => {
    const portForm = document.querySelector('#drawer[open] .port-editor, #page .port-editor');
    if (portForm && !window.confirm('端口表单仍在编辑。刷新会清除本次填写，确定刷新吗？')) return;
    window.location.reload();
  });
  snooze.addEventListener('click', () => {
    snoozedVersion = availableVersion;
    snoozedUntil = Date.now() + SNOOZE_INTERVAL;
    notice.hidden = true;
  });
  document.addEventListener('visibilitychange', check);
  window.addEventListener('focus', check);
  window.addEventListener('online', check);
  window.setInterval(check, CHECK_INTERVAL);
  void check();
}
