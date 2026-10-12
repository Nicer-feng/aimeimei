const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const ai = process.env.USAGE_TEST_URL, cloud = process.env.CLOUD_TEST_URL;
  for (const url of [ai, cloud]) assert.match(url || '', /^http:\/\/127\.0\.0\.1:\d+$/);
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
    await context.addCookies([{ name: 'ap_session', value: 'usage-admin', url: ai }]);
    const page = await context.newPage(), errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    await page.goto(ai);await page.waitForFunction(() => state.authed && window.MeimeiMotion);
    const reports = await page.evaluate(async () => {
      const ids = ['promptDialog','favoriteDialog','profileDialog','mediaDialog','ocrDialog','copyDialog','confirmDialog','shareDialog','accentDialog','tokenActivityDialog','globalSearchDialog','changelogDialog','modelPickerDialog','conversationFilesDialog','imagePreviewDialog','interfacePopover','profilePopover','settingsDrawer','readerLibrary','writingDialog'];
      const result = [];
      for (const id of ids) {
        const surface = document.getElementById(id);
        const actor = surface.querySelector('.ui-motion-managed') || surface;
        const paths = new Set(), opacity = [];
        if (surface.tagName === 'DIALOG') surface.showModal();else surface.classList.add('show');
        const start = performance.now();
        while (performance.now() - start < 420) {
          await new Promise(requestAnimationFrame);
          opacity.push(Number(getComputedStyle(actor).opacity));
          actor.getAnimations().forEach(a => { if (a.effect.getKeyframes().some(k => k.opacity !== undefined)) paths.add(a); });
        }
        result.push({ id, paths: paths.size, drops: opacity.filter((v,i) => i && opacity[i-1] - v > .06).length });
        if (surface.tagName === 'DIALOG') surface.close();else surface.classList.remove('show');
        await new Promise(resolve => setTimeout(resolve, 190));
      }
      return result;
    });
    console.log(JSON.stringify({ aiOverlays: reports }));
    reports.forEach(r => { assert.equal(r.paths, 1, r.id); assert.equal(r.drops, 0, r.id); });
    await page.evaluate(() => openSettings());await page.waitForTimeout(350);
    await page.evaluate(() => switchAdminSection('usage'));await page.waitForTimeout(350);
    const idleNav = await page.evaluate(() => {
      const thumb = document.querySelector('.admin-nav-list .ui-motion-thumb');
      MeimeiMotion.admin();MeimeiMotion.admin();return thumb.getAnimations().length;
    });
    assert.equal(idleNav, 0);
    assert.deepEqual(errors, []);await context.close();

    const cc = await browser.newContext();
    const captcha = await (await cc.request.get(cloud + '/api/captcha')).json();
    const answer = [...captcha.image_svg.matchAll(/<text[^>]*>(.*?)<\/text>/g)].map(m => m[1]).join('');
    assert.equal((await cc.request.post(cloud + '/api/login', { data: { username: 'admin', password: 'test-password', captcha_id: captcha.captcha_id, captcha: answer } })).status(), 200);
    const cp = await cc.newPage();await cp.goto(cloud + '/admin/share');await cp.waitForSelector('#nav button.active');
    const flow = await cp.evaluate(async () => {
      const opens = [], saved = CloudMotion.open;
      CloudMotion.open = (panel, preview) => { opens.push(Boolean(preview)); return saved(panel, preview); };
      FS.dialog('首次打开', '<p>正在读取</p>');
      await new Promise(resolve => setTimeout(resolve, 300));
      FS.dialog('更新内容', '<p>内容就绪</p>');
      const updates = opens.length;
      FS.close();await new Promise(resolve => setTimeout(resolve, 200));opens.length = 0;
      await FS.preview({ filename: 'audit.txt', file_type: 'TEXT' }, 'data:text/plain,local-audit-text');
      const preview = opens.slice();FS.close();await new Promise(resolve => setTimeout(resolve, 200));CloudMotion.open = saved;
      const host = document.createElement('div');host.innerHTML = '<section class="panel"><div class="stat">nested</div></section><section class="panel">later</section>';
      document.getElementById('content').append(host);CloudMotion.reveal(host);
      const panel = host.children[1], nested = host.querySelector('.stat');
      const delayedOpacity = Number(getComputedStyle(panel).opacity), nestedAnimations = nested.getAnimations().length;
      await new Promise(resolve => setTimeout(resolve, 400));host.remove();
      CloudMotion.nav();CloudMotion.nav();
      return { updates, preview, delayedOpacity, nestedAnimations, navAnimations: document.querySelector('#nav .ui-motion-thumb').getAnimations().length };
    });
    assert.equal(flow.updates, 1);assert.deepEqual(flow.preview, [true]);assert.equal(flow.delayedOpacity, 0);
    assert.equal(flow.nestedAnimations, 0);assert.equal(flow.navAnimations, 0);
    let revealCalls = 0;
    await cp.evaluate(() => { window.auditRevealCalls = 0; const original = CloudMotion.reveal; CloudMotion.reveal = (...args) => { auditRevealCalls++;return original(...args); }; });
    await cp.locator('#nav [data-section="files"]').click();await cp.waitForTimeout(450);
    revealCalls = await cp.evaluate(() => auditRevealCalls);assert.equal(revealCalls, 0);
    await cp.locator('#nav [data-section="overview"]').click();await cp.waitForTimeout(450);
    assert.equal(await cp.evaluate(() => auditRevealCalls), 1);
    await cc.close();console.log(JSON.stringify({ cloudFlow: flow, result: 'PASS: overlay ownership, preview, delayed/nested cards, unchanged navigation, same-page refresh' }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error);process.exitCode = 1; });
