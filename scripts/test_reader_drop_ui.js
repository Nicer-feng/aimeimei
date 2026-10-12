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
    let uploads = 0, otherUploads = 0;
    page.on('pageerror', e => errors.push(String(e)));
    page.on('request', r => {
      if (r.method() === 'POST' && r.url().includes('/reading/books?')) uploads++;
      if (r.method() === 'POST' && /\/api\/(documents|uploads|images)/.test(r.url())) otherUploads++;
    });
    await page.goto(base); await page.waitForFunction(() => state.authed);
    await page.evaluate(() => MeimeiReader.openLibrary());
    const drag = (names, type = 'drop', outside = false) => page.evaluate(({ names, type, outside }) => {
      const d = new DataTransfer();
      names.forEach(name => d.items.add(new File(['拖拽小说正文。\n'.repeat(500)], name, { type: 'text/plain' })));
      const dialog = document.querySelector('#readerLibrary'), rect = dialog.getBoundingClientRect();
      dialog.dispatchEvent(new DragEvent(type, { dataTransfer: d, bubbles: true, cancelable: true,
        clientX: outside ? 0 : rect.left + 50, clientY: outside ? 0 : rect.top + 50 }));
    }, { names, type, outside });
    await drag(['book.txt'], 'dragenter');
    assert.equal(await page.locator('#readerLibrary').evaluate(n => n.classList.contains('is-file-dragover')), true);
    await page.screenshot({ path: '/private/tmp/reader-drop-highlight.png' });
    await drag(['book.txt'], 'dragleave');
    assert.equal(await page.locator('#readerLibrary').evaluate(n => n.classList.contains('is-file-dragover')), false);
    await drag(['bad.pdf']); await drag(['one.txt', 'two.txt']); await drag(['outside.txt'], 'drop', true);
    assert.equal(uploads, 0);
    await page.route('**/api/reading/books?*', async r => { await new Promise(resolve => setTimeout(resolve, 400)); await r.continue(); });
    await drag(['book.txt']); await drag(['book.txt']);
    await page.waitForFunction(() => !document.querySelector('#readerUpload').disabled && document.querySelector('#readerLibraryList .reader-book'));
    assert.equal(uploads, 1); assert.equal(otherUploads, 0);
    await page.unrouteAll({ behavior: 'wait' });
    await page.locator('#readerFile').setInputFiles({ name: 'chosen.txt', mimeType: 'text/plain', buffer: Buffer.from('文件选择仍然可用。'.repeat(400)) });
    await page.waitForFunction(() => !document.querySelector('#readerUpload').disabled && document.querySelectorAll('#readerLibraryList .reader-book').length === 2);
    assert.equal(uploads, 2);
    await page.route('**/api/reading/books?*', r => r.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"测试上传失败"}' }));
    await drag(['retry.txt']);
    await page.waitForFunction(() => document.querySelector('#readerLibraryStatus').textContent.includes('测试上传失败'));
    assert.equal(await page.locator('#readerUpload').isEnabled(), true);
    await page.unrouteAll({ behavior: 'wait' });
    await page.locator('#readerLibraryList .reader-book-open').first().click();
    await page.waitForFunction(() => MeimeiReader.active && document.querySelector('#readerPages .reader-text'));
    await page.locator('#readerToggle').click();
    await page.locator('#prompt').fill('聊天输入正常');
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ uploads, otherUploads, errors, checks: 'highlight, invalid, multiple, backdrop, dedup, picker, retry, read, exit' }));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
