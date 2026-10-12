const { chromium } = require('playwright');
const assert = require('node:assert/strict');

// Run against the isolated fixture: python3 scripts/test_usage_time.py --serve.
(async () => {
  const base = process.env.USAGE_TEST_URL;
  assert.match(base || '', /^http:\/\/127\.0\.0\.1:\d+$/);
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    for (const width of [1440, 1280, 768, 390]) {
      const context = await browser.newContext({ viewport: { width, height: 960 } });
      await context.addCookies([{ name: 'ap_session', value: 'usage-admin', url: base }]);
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', e => errors.push(String(e)));
      await page.goto(base);
      await page.waitForFunction(() => state.authed);
      await page.evaluate(() => openSettings());
      for (const section of ['usage', 'tokens', 'costs', 'system']) {
        await page.evaluate(name => switchAdminSection(name), section);
        await page.waitForTimeout(250);
        const rows = await page.locator('.usage-time-filter:visible,.token-filter-row:visible,.form-control-row:visible').evaluateAll(nodes => nodes.map(node =>
          [...node.querySelectorAll('input:not(.admin-native-control),.admin-control-trigger,.ui-btn')]
            .filter(el => el.getClientRects().length)
            .map(el => { const r = el.getBoundingClientRect(); return { id: el.id, x: r.x, y: r.y, height: r.height, bottom: r.bottom }; })
        ));
        for (const row of rows) for (const control of row) {
          assert.ok(Math.abs(control.height - 44) < 1, `${width}/${section}: ${JSON.stringify(control)}`);
          for (const peer of row) if (Math.abs(peer.y - control.y) < 25) {
            assert.ok(Math.abs(peer.y - control.y) < 1, `${width}/${section}: misaligned controls`);
          }
        }
        await page.screenshot({ path: `/private/tmp/alignment-${width}-${section}.png` });
      }
      await page.goto(base);
      await page.waitForFunction(() => state.authed);
      await page.evaluate(() => openTokenActivity());
      await page.waitForTimeout(300);
      const tabs = await page.locator('.activity-tabs').boundingBox();
      assert.ok(tabs.height >= 46, `${width}: ${JSON.stringify(tabs)}`);
      await page.locator('[data-activity-tab="usage"]').click();
      await page.waitForSelector('#personalUsageTime .usage-time-filter');
      assert.equal(await page.locator('#tokenActivityContent').isVisible(), false);
      await page.locator('[data-activity-tab="tokens"]').click();
      assert.equal(await page.locator('#tokenActivityContent').isVisible(), true);
      assert.equal(await page.locator('#personalUsageTime').isVisible(), false);
      await page.screenshot({ path: `/private/tmp/alignment-${width}-activity.png` });
      assert.deepEqual(errors, []);
      await context.close();
    }
    console.log('PASS: four viewport sizes, filter alignment, activity tab layout and switching');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
