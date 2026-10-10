// Run against scripts/test_reading.py --serve with READER_TEST_URL set.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const base = process.env.READER_TEST_URL;
  assert.match(base || '', /^http:\/\/127\.0\.0\.1:\d+$/);
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    await context.addCookies([{ name: 'ap_session', value: 'reader-a', url: base }]);
    const page = await context.newPage(), errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto(base); await page.waitForFunction(() => state.authed);
    await page.evaluate(async () => {
      const { books } = await (await fetch('/api/reading/books')).json();
      for (const book of books) await fetch('/api/reading/books/' + book.id, { method: 'DELETE' });
    });
    await page.locator('#prompt').fill('保留的聊天草稿');
    await page.locator('#readerToggle').click();
    await page.locator('#readerLibrary').waitFor({ state: 'visible' });
    const text = Array.from({ length: 25000 }, (_, i) => `第${i}段：清晨的风穿过院子，他翻开旧信，沿着熟悉的小路向前走。<script>neverExecute()</script>\n\n`).join('');
    await page.locator('#readerFile').setInputFiles({ name: '测试长篇.txt', mimeType: 'text/plain', buffer: Buffer.from(text) });
    await page.locator('.reader-book-open').first().waitFor();
    await page.locator('.reader-book-open').first().click();
    await page.waitForFunction(() => window.MeimeiReader.active && document.querySelectorAll('.reader-page').length > 0);
    assert.equal(await page.locator('#prompt').inputValue(), '保留的聊天草稿');
    assert.equal(await page.locator('#messages').evaluate(n => getComputedStyle(n).visibility), 'hidden');
    assert.equal(await page.locator('#readerMessages script').count(), 0);
    for (let i = 0; i < 12; i++) {
      const last = await page.locator('.reader-page').last().getAttribute('data-reader-page');
      await page.locator('#readerMessages').evaluate(n => { n.scrollTop = n.scrollHeight; });
      await page.waitForFunction(previous => Number(document.querySelector('.reader-page:last-child')?.dataset.readerPage) > Number(previous), last);
    }
    const windowInfo = await page.locator('.reader-page').evaluateAll(nodes => ({ count: nodes.length, first: +nodes[0].dataset.readerPage, last: +nodes.at(-1).dataset.readerPage }));
    assert.ok(windowInfo.count <= 7 && windowInfo.first > 0);
    await page.locator('#readerMessages').evaluate(n => { n.scrollTop -= 500; });
    await page.waitForTimeout(400);
    await page.locator('#readerProgress').click();
    await page.locator('[data-reader-mode="page"]').click();
    await page.waitForFunction(() => document.querySelectorAll('.reader-page').length === 1);
    await page.locator('#readerLibraryClose').click();
    await page.locator('#readerNext').click();
    await page.waitForTimeout(250);
    await page.locator('#readerProgress').click();
    await page.locator('[data-reader-mode="scroll"]').click();
    await page.waitForFunction(() => document.querySelectorAll('.reader-page').length > 1);
    await page.locator('#readerLibraryClose').click();
    await page.locator('#readerMessages').evaluate(n => { n.scrollTop += 100; });
    await page.waitForTimeout(400);
    await page.screenshot({ path: '/private/tmp/aimeimei-reader-desktop.png' });
    await page.locator('#readerToggle').click();
    await page.waitForTimeout(300);
    const before = await page.evaluate(async () => (await (await fetch('/api/reading/books')).json()).books[0].position);
    assert.ok(before > 10000);
    assert.equal(await page.locator('#prompt').inputValue(), '保留的聊天草稿');
    assert.equal(await page.locator('#messages').evaluate(n => getComputedStyle(n).visibility), 'visible');
    await page.reload(); await page.waitForFunction(() => state.authed);
    await page.locator('#readerToggle').click();
    await page.waitForFunction(() => window.MeimeiReader.active && document.querySelectorAll('.reader-page').length > 0);
    await page.waitForTimeout(300);
    const restored = await page.locator('.reader-page').evaluateAll(nodes => nodes.map(n => +n.dataset.start));
    assert.ok(restored[0] <= before && restored.at(-1) > before);
    await page.setViewportSize({ width: 1100, height: 750 });
    await page.waitForTimeout(400);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.evaluate(() => document.documentElement.dataset.theme = 'dark');
    await page.screenshot({ path: '/private/tmp/aimeimei-reader-dark.png' });
    await page.locator('#readerToggle').click();
    await page.evaluate(() => {
      const original = window.fetch;
      window.readerTestRequests = [];
      window.fetch = (url, options = {}) => {
        if (options.method === 'POST' && /\/api\/conversations\/[^/]+\/messages$/.test(String(url))) {
          window.readerTestRequests.push(JSON.parse(options.body));
          return Promise.resolve(new Response(new ReadableStream({ start(controller) {
            const encoder = new TextEncoder();
            window.readerTestEvent = event => controller.enqueue(encoder.encode('data: ' + JSON.stringify(event) + '\n\n'));
            window.readerTestFinish = () => {
              window.readerTestEvent({ type: 'message_saved', message_id: 999999, generation_status: 'completed' });
              controller.close();
            };
          } }), { headers: { 'Content-Type': 'text/event-stream' } }));
        }
        return original(url, options);
      };
      void sendMessage('隔离流式回归测试');
    });
    await page.waitForFunction(() => state.sending && window.readerTestEvent);
    await page.locator('#readerToggle').click();
    await page.waitForFunction(() => window.MeimeiReader.active);
    await page.evaluate(() => window.readerTestEvent({ choices: [{ delta: { content: '后台继续生成的回答。' } }] }));
    await page.waitForTimeout(500);
    assert.equal(await page.evaluate(() => state.sending && !state.activeGeneration.controller.signal.aborted), true);
    await page.evaluate(() => window.readerTestFinish());
    await page.waitForFunction(() => !state.sending);
    assert.equal(await page.evaluate(() => window.MeimeiReader.active), true);
    await page.locator('#readerToggle').click();
    assert.ok(await page.evaluate(() => state.messages.at(-1).content.includes('后台继续生成')));
    await page.locator('#readerToggle').click();
    await page.waitForFunction(() => window.MeimeiReader.active);
    await page.evaluate(() => { window.readerTestEvent = null; void sendMessage('只发送我的问题'); });
    await page.waitForFunction(() => !window.MeimeiReader.active && !!window.readerTestEvent);
    assert.equal(await page.evaluate(() => window.readerTestRequests.at(-1).content), '只发送我的问题');
    await page.evaluate(() => window.readerTestFinish());
    await page.waitForFunction(() => !state.sending);
    await page.locator('#readerToggle').click();
    await page.waitForFunction(() => window.MeimeiReader.active);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(100);
    assert.equal(await page.locator('#readerToggle').isVisible(), false);
    assert.equal(await page.evaluate(() => window.MeimeiReader.active), false);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ windowInfo, savedPosition: before, restoredPages: restored, mobileHidden: true, errors }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
