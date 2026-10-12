const { chromium } = require('playwright');
const assert = require('node:assert/strict');

(async () => {
  const ai = process.env.USAGE_TEST_URL;
  const cloud = process.env.CLOUD_TEST_URL;
  for (const url of [ai, cloud]) assert.match(url || '', /^http:\/\/127\.0\.0\.1:\d+$/);
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const results = [];
  try {
    for (const width of [1440, 390]) {
      const context = await browser.newContext({ viewport: { width, height: 960 } });
      await context.addCookies([{ name: 'ap_session', value: 'usage-admin', url: ai }]);
      const page = await context.newPage(), errors = [];
      page.on('pageerror', e => errors.push(String(e)));
      await page.goto(ai);
      await page.waitForFunction(() => state.authed && window.UIMotion);
      await page.evaluate(() => openSettings());
      await page.waitForTimeout(400);
      await page.evaluate(() => switchAdminSection('usage'));
      await page.waitForTimeout(350);
      const geometry = await page.evaluate(() => {
        const active = document.querySelector('.admin-nav-item.active').getBoundingClientRect();
        const thumb = document.querySelector('.admin-nav-list .ui-motion-thumb').getBoundingClientRect();
        return Math.max(Math.abs(active.x - thumb.x), Math.abs(active.y - thumb.y), Math.abs(active.width - thumb.width));
      });
      assert.ok(geometry < 1, `navigation geometry: ${geometry}`);
      await page.screenshot({ path: `/private/tmp/motion-ai-${width}.png` });
      await page.evaluate(() => closeSettings());
      await page.locator('#prompt').fill('主输入框草稿保留');
      await page.evaluate(() => openProfiles());
      await page.waitForTimeout(300);
      await page.locator('#profileTitle').fill('本地动效验证');
      await page.evaluate(() => closeProfiles());
      await page.waitForTimeout(250);
      assert.equal(await page.locator('#profileDialog').isVisible(), false);
      await page.evaluate(() => openProfiles());
      await page.waitForTimeout(300);
      assert.equal(await page.locator('#prompt').inputValue(), '主输入框草稿保留');
      await page.evaluate(() => closeProfiles());
      assert.deepEqual(errors, []);
      if (width === 1440) {
        for (const mode of ['off', 'on']) {
          if (mode === 'off') {
            await page.route('**/res/ui-motion.js*', route => route.fulfill({ body: '', contentType: 'application/javascript' }));
            await page.route('**/res/ai-motion.js*', route => route.fulfill({ body: '', contentType: 'application/javascript' }));
          } else {
            await page.unroute('**/res/ui-motion.js*');
            await page.unroute('**/res/ai-motion.js*');
          }
          await page.reload();
          await page.waitForFunction(() => state.authed);
          const result = await page.evaluate(async mode => {
            let opens = 0;
            const originalOpen = window.UIMotion?.open;
            if (originalOpen) UIMotion.open = (...args) => { opens++; return originalOpen(...args); };
            const frames = [], tasks = [];
            const observer = new PerformanceObserver(list => list.getEntries().forEach(e => tasks.push(e.duration)));
            observer.observe({ type: 'longtask', buffered: false });
            state.followOutput = false;
            const message = { id: 'motion-stream-test', role: 'assistant', content: '', created_at: Date.now() / 1000, generation_status: 'generating' };
            state.messages = [message]; renderMessages();
            let previous = performance.now();
            for (let i = 0; i < 90; i++) {
              await new Promise(requestAnimationFrame);
              const time = performance.now(); frames.push(time - previous); previous = time;
              message.content += '这是一段用于本地流式渲染回归的内容。'.repeat(5);
              updateStreamingMessage(message, { stream: true });
            }
            await new Promise(resolve => setTimeout(resolve, 400));
            observer.disconnect();if (originalOpen) UIMotion.open = originalOpen;
            frames.sort((a, b) => a - b);
            return { mode, p95: frames[Math.floor(frames.length * .95)], longTasks: tasks.length, opens,
              messageAnimations: document.querySelector('#messages').getAnimations({ subtree: true }).length };
          }, mode);
          assert.equal(result.opens, 0);
          assert.equal(result.messageAnimations, 0);
          results.push(result);
        }
      }
      await context.close();
    }
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
    const captcha = await (await context.request.get(cloud + '/api/captcha')).json();
    const answer = [...captcha.image_svg.matchAll(/<text[^>]*>(.*?)<\/text>/g)].map(m => m[1]).join('');
    const login = await context.request.post(cloud + '/api/login', { data: { username: 'admin', password: 'test-password', captcha_id: captcha.captcha_id, captcha: answer } });
    assert.equal(login.status(), 200);
    const page = await context.newPage(), errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    await page.goto(cloud + '/admin/share');
    await page.waitForSelector('#nav button.active');
    await page.locator('#fileInput').setInputFiles({ name: 'motion-test.txt', mimeType: 'text/plain', buffer: Buffer.from('本地模拟OSS文件，验证动效不影响上传。') });
    await page.waitForFunction(() => document.querySelector('#content').textContent.includes('motion-test.txt'));
    await page.locator('#createShare').click();
    await page.waitForSelector('#shareForm');
    await page.waitForTimeout(300);
    await page.locator('#expiry + .select-trigger').click();
    await page.locator('.select-popup:not([inert]) .select-option').filter({ hasText: '24 小时' }).click();
    assert.equal(await page.locator('#expiry').inputValue(), '86400');
    await page.waitForTimeout(200);
    await page.screenshot({ path: '/private/tmp/motion-cloud-share.png' });
    await page.locator('#shareForm [name="title"]').fill('动效回归分享');
    await page.locator('#shareForm [name="file_ids"]').first().check();
    await page.locator('#passwordMode + .select-trigger').click();
    await page.locator('.select-popup:not([inert]) .select-option').filter({ hasText: /^关闭$/ }).click();
    await page.locator('#shareForm button[type="submit"]').click();
    await page.waitForFunction(() => document.querySelector('#dialogTitle').textContent === '分享详情');
    const shareUrl = await page.locator('.share-link').textContent();
    assert.ok(shareUrl.startsWith(cloud + '/share/'));
    const publicContext = await browser.newContext();
    const publicPage = await publicContext.newPage();
    await publicPage.goto(shareUrl);
    await publicPage.locator('[data-action="preview"]').first().click();
    await publicPage.waitForFunction(() => document.querySelector('#dialogBody').textContent.includes('验证动效不影响上传'));
    await publicPage.keyboard.press('Escape');
    await publicPage.waitForTimeout(250);
    assert.equal(await publicPage.locator('#dialog').evaluate(el => el.open), false);
    await publicContext.close();
    // Closing followed immediately by opening must never close the new dialog.
    await page.evaluate(() => { FS.close(); FS.dialog('新弹窗', '<input id="motionDraft" value="内容保留">'); });
    await page.waitForTimeout(400);
    assert.equal(await page.locator('#dialog').evaluate(el => el.open), true);
    assert.equal(await page.locator('#motionDraft').inputValue(), '内容保留');
    await page.keyboard.press('Escape');
    await page.waitForTimeout(250);
    assert.equal(await page.locator('#dialog').evaluate(el => el.open), false);
    for (const section of ['overview', 'files', 'shares', 'logs', 'trash', 'settings', 'platform']) {
      await page.locator(`#nav [data-section="${section}"]`).click();
      await page.waitForTimeout(450);
      assert.equal(await page.locator(`#nav [data-section="${section}"]`).getAttribute('aria-current'), 'page');
      assert.ok(await page.evaluate(() => {
        const a = document.querySelector('#nav button.active').getBoundingClientRect();
        const b = document.querySelector('#nav .ui-motion-thumb').getBoundingClientRect();
        return Math.abs(a.x - b.x) < 1 && Math.abs(a.y - b.y) < 1 && Math.abs(a.width - b.width) < 1;
      }), `cloud nav ${section}`);
    }
    await page.screenshot({ path: '/private/tmp/motion-cloud-desktop.png' });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(350);
    await page.screenshot({ path: '/private/tmp/motion-cloud-mobile.png' });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.evaluate(() => FS.dialog('减少动态效果', '<p>仍可正常打开</p>'));
    assert.equal(await page.locator('#dialog').evaluate(el => el.getAnimations().length), 0);
    await page.evaluate(() => FS.close());
    assert.equal(await page.locator('#dialog').evaluate(el => el.open), false);
    assert.deepEqual(errors, []);
    await context.close();
    console.log(JSON.stringify({ result: 'PASS', syntheticStreaming: results, coverage: 'desktop/mobile, navigation, modal races, upload, dropdown, reduced motion' }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
