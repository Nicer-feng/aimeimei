const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { chromium } = require('playwright');

// Run against the isolated fixture from scripts/test_usage_time.py --serve.
const base = process.env.USAGE_TEST_URL;
assert.match(base || '', /^http:\/\/127\.0\.0\.1:\d+$/);
const output = fs.mkdtempSync(path.join(os.tmpdir(), 'aimeimei-surfaces-'));

async function screenshot(page, name) {
  await page.screenshot({ path: path.join(output, name + '.png'), animations: 'disabled' });
}

async function checkViewport(page, selector, width) {
  const box = await page.locator(selector).boundingBox();
  assert.ok(box && box.x >= -1 && box.x + box.width <= width + 1, selector + ' fits the viewport');
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
}

async function checkPublicShare(page, suffix, width, scheme) {
  const now = Date.now() / 1000;
  const token = 'visual-test-public-share-fixture';
  const paragraph = '长段落用于测试窄屏阅读，文字应换行，表格在自己的区域内滚动。';
  const code = '\x60\x60\x60js\nconst longValue = "' + 'a'.repeat(420) + '";\n\x60\x60\x60';
  await page.route('**/api/public/shares/' + token, route => route.fulfill({ json: {
    share: { title: '长文写作与资料整理', created_at: now, expires_at: now + 7200,
      snapshot: { model_name: '本地测试', messages: [
        { role: 'user', content: '请用表格与代码演示这段资料。', created_at: now },
        { role: 'assistant', content: '## 核对说明\n\n' + paragraph.repeat(4) +
          '\n\n| 项目 | 说明 |\n| --- | --- |\n| 资料 | ' + paragraph.repeat(4) +
          ' |\n\n' + code + '\n\n最后一段内容。', created_at: now,
          sources: [{ url: 'https://example.com/' + 'a'.repeat(256), title: '测试参考来源' }] }
      ] }
    }
  } }));
  await page.goto(base + '/ai/share/' + token);
  await page.locator('#shareConversation').waitFor({ state: 'visible' });
  assert.equal(await page.locator('html').getAttribute('data-theme'), scheme);
  await checkViewport(page, '.share-main', width);
  assert.equal(await page.locator('.table-wrapper').count(), 1);
  assert.equal(await page.locator('.code-block').count(), 1);
  assert.equal(await page.locator('.share-sources a').getAttribute('target'), '_blank');
  await screenshot(page, 'share-' + suffix);
  await page.route('**/api/public/shares/**', route => route.fulfill({ status: 410, json: { error: '链接已过期。' } }));
  await page.reload();
  await page.locator('#shareError').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#shareErrorText').textContent(), '链接已过期。');
}

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    for (const [width, scheme] of [[1440, 'light'], [390, 'dark'], [320, 'light']]) {
      const suffix = width + '-' + scheme;
      const context = await browser.newContext({
        viewport: { width, height: width > 600 ? 900 : 640 },
        colorScheme: scheme, reducedMotion: 'reduce', hasTouch: width < 600
      });
      await context.route('**/*', route => route.request().url().startsWith(base + '/') ? route.continue() : route.abort());
      const page = await context.newPage();
      page.setDefaultTimeout(12000);
      const errors = [];
      page.on('pageerror', error => errors.push(String(error)));
      await page.goto(base);
      await page.locator('#loginForm').waitFor({ state: 'visible' });
      await checkViewport(page, '#loginForm', width);
      assert.equal(await page.locator('#loginUsername').evaluate(el => getComputedStyle(el).paddingLeft), '12px');
      const captcha = page.waitForResponse(response => new URL(response.url()).pathname === '/api/captcha');
      await page.locator('#refreshCaptcha').click();
      assert.ok((await captcha).ok());
      await screenshot(page, 'login-' + suffix);
      await checkPublicShare(page, suffix, width, scheme);

      await context.addCookies([{ name: 'ap_session', value: 'usage-admin', url: base }]);
      await page.goto(base);
      await page.waitForFunction(() => state.authed);
      const openSidebar = async () => {
        if (width < 600 && !await page.evaluate(() => document.body.classList.contains('sidebar-open'))) {
          await page.locator('#openSide').click();
        }
      };
      const openTools = async () => {
        await openSidebar();
        const trigger = page.locator('#toggleSidebarTools');
        if (await trigger.getAttribute('aria-expanded') === 'false') await trigger.click();
      };
      await openSidebar();
      await page.locator('#openGlobalSearch').click();
      await checkViewport(page, '.global-search-panel', width);
      await page.keyboard.press('Escape');
      await page.locator('.global-search-panel').waitFor({ state: 'hidden' });
      await openTools();
      await checkViewport(page, '#sidebarToolsPopover', width);
      await screenshot(page, 'tools-' + suffix);
      for (const [trigger, dialog, close] of [
        ['openPromptLibrary', 'promptDialog', 'closePromptDialog'],
        ['openFavorites', 'favoriteDialog', 'closeFavoriteDialog'],
        ['openProfiles', 'profileDialog', 'closeProfileDialog'],
        ['openMediaAnalysis', 'mediaDialog', 'closeMediaDialog'],
        ['openHandwritingOcr', 'ocrDialog', 'closeOcrDialog']
      ]) {
        await openTools();
        await page.locator('#' + trigger).click();
        const panel = '#' + dialog + ' .ui-modal';
        await page.locator(panel).waitFor({ state: 'visible' });
        await checkViewport(page, panel, width);
        await page.locator('#' + close).click();
      }
      await openTools();
      await page.locator('#openSettings').click();
      await checkViewport(page, '#settingsDrawer', width);
      const sections = await page.locator('.admin-nav-item').evaluateAll(items => items.map(item => item.dataset.adminSection));
      for (const section of sections) {
        await page.locator('.admin-nav-item[data-admin-section="' + section + '"]').click();
        await page.locator('.admin-page[data-admin-page="' + section + '"]').waitFor({ state: 'visible' });
        assert.equal(await page.locator('.admin-content').evaluate(el => el.scrollWidth > el.clientWidth + 1), false, section + ' does not overflow');
        if (['overview', 'tokens', 'usage'].includes(section)) await screenshot(page, 'admin-' + section + '-' + suffix);
      }
      await page.locator('#closeSettings').click();
      assert.deepEqual(errors, []);
      await context.close();
    }
    console.log('PASS: login/captcha, share/expired, search, five tool dialogs, 13 admin sections. Screenshots: ' + output);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
