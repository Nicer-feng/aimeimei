const { chromium } = require('playwright');
const assert = require('node:assert/strict');

(async () => {
  const base = process.env.USAGE_TEST_URL;
  assert.match(base || '', /^http:\/\/127\.0\.0\.1:\d+$/);
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
    await context.addCookies([{ name: 'ap_session', value: 'reader-a', url: base }]);
    const page = await context.newPage(), errors = [];
    page.on('pageerror', err => errors.push(String(err)));
    let pageRequests = 0;
    page.on('request', r => { if (r.url().includes('/pages?')) pageRequests++; });
    await page.addInitScript(() => {
      Object.defineProperty(crypto, 'randomUUID', { value: undefined, configurable: true });
    });
    await page.goto(base);
    await page.waitForFunction(() => state.authed && typeof MeimeiUsage !== 'undefined');
    await page.evaluate(async () => {
      const response = await fetch('/api/reading/books?filename=reader-usage-regression.txt', {
        method: 'POST', body: '这是长篇小说的回归测试正文。继续阅读与滚动。\n'.repeat(100000)
      });
      if (!response.ok) throw new Error('Fixture book upload failed');
      const { book } = await response.json();
      const active = await fetch(`/api/reading/books/${book.id}/active`, { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: '{}' });
      if (!active.ok) throw new Error('Fixture activation failed');
    });
    await page.waitForTimeout(1000);
    await page.locator('#prompt').click();
    await page.waitForTimeout(500);
    const ready = () => page.waitForFunction(() => MeimeiReader.active &&
      !document.querySelector('#readerMessages').hidden &&
      document.querySelectorAll('#readerPages .reader-text').length > 0);
    const enter = async () => {
      const start = Date.now();
      await page.locator('#readerToggle').click(); await ready();
      return Date.now() - start;
    };
    const timings = [await enter()];
    assert.ok(pageRequests > 0, 'Must actually fetch and render pages, not just flip active');
    for (let i = 0; i < 4; i++) {
      await page.locator('#readerToggle').click();
      await page.waitForFunction(() => !MeimeiReader.active && !document.querySelector('#messages').inert);
      timings.push(await enter());
    }
    await page.evaluate(() => {
      window.readerLongTasks = [];
      new PerformanceObserver(list => readerLongTasks.push(...list.getEntries().map(e => e.duration)))
        .observe({ type: 'longtask', buffered: false });
    });
    await page.locator('#readerMessages').hover();
    for (let i = 0; i < 12; i++) { await page.mouse.wheel(0, 900); await page.waitForTimeout(100); }
    assert.ok(await page.locator('#readerPages .reader-text').count() <= 7);
    const longTasks = await page.evaluate(() => readerLongTasks);
    assert.ok(!longTasks.some(ms => ms > 250), JSON.stringify(longTasks));
    await page.screenshot({ path: '/private/tmp/reader-usage-fixed.png' });

    // A pending statistics request must not delay content requests or rendering.
    await page.locator('#readerToggle').click();
    let heartbeats = 0;
    await page.route('**/api/usage-time/heartbeat', async r => {
      heartbeats++; await new Promise(resolve => setTimeout(resolve, 2000)); await r.continue();
    });
    const slowStatsTime = await enter(); timings.push(slowStatsTime);
    assert.ok(slowStatsTime < 1500, 'Reader waited for analytics');
    await page.waitForTimeout(2200);
    assert.ok(heartbeats > 0);
    await page.unroute('**/api/usage-time/heartbeat');

    // Analytics exceptions must not abort enter OR exit (the original regression).
    await page.evaluate(() => { window.oldUsageStep = UsageClock.prototype.step; UsageClock.prototype.step = () => { throw new Error('simulated tracking failure'); }; });
    await page.locator('#readerToggle').click();
    assert.equal(await page.locator('#readerMessages').isVisible(), false);
    timings.push(await enter());
    await page.evaluate(() => { UsageClock.prototype.step = oldUsageStep; });

    // A slow statistics server must not delay the first page.
    await page.locator('#readerToggle').click();
    await page.route('**/api/usage-time/**', r => r.abort());
    timings.push(await enter());
    await page.unroute('**/api/usage-time/**');

    // Failed page requests leave a recoverable UI, never a permanent placeholder.
    await page.locator('#readerToggle').click();
    await page.route('**/api/reading/books/*/pages?*', r => r.fulfill({ status: 503,
      contentType: 'application/json', body: JSON.stringify({ error: '测试加载失败' }) }));
    await page.locator('#readerToggle').click();
    await page.waitForFunction(() => document.querySelector('#readerLibrary').open &&
      document.querySelector('#readerLibraryStatus').textContent.includes('测试加载失败'));
    assert.equal(await page.locator('#readerMessages').isVisible(), false);
    await page.unroute('**/api/reading/books/*/pages?*');
    await page.locator('#readerLibraryClose').click();
    timings.push(await enter());

    await page.locator('#readerToggle').click();
    await page.route('**/api/reading/books/*/pages?*', async r => {
      await new Promise(resolve => setTimeout(resolve, 13000));
      await r.abort().catch(() => {});
    });
    await page.locator('#readerToggle').click();
    await page.waitForFunction(() => document.querySelector('#readerLibrary').open &&
      document.querySelector('#readerLibraryStatus').textContent.includes('加载超时'), { timeout: 16000 });
    assert.equal(await page.locator('#readerMessages').isVisible(), false);
    await page.unrouteAll({ behavior: 'wait' });
    await page.locator('#readerLibraryClose').click();
    timings.push(await enter());
    await page.locator('#readerToggle').click();
    // A telemetry-only 401 cannot log the user out or reset the conversation.
    await page.route('**/api/usage-time/config', r => r.fulfill({ status: 401,
      contentType: 'application/json', body: '{}' }));
    await page.reload();
    await page.waitForFunction(() => state.authed);
    await page.waitForTimeout(1200);
    assert.equal(await page.evaluate(() => state.authed), true);
    timings.push(await enter());
    await page.locator('#readerToggle').click();
    await page.locator('#prompt').fill('退出阅读后仍可正常编辑草稿');
    assert.equal(await page.locator('#prompt').inputValue(), '退出阅读后仍可正常编辑草稿');
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ timings, pageRequests, longTasks, errors }));
  } finally { await browser.close(); }
})().catch(err => { console.error(err); process.exitCode = 1; });
