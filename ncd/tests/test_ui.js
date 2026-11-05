const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { chromium } = require('playwright');

const webDir = path.resolve(__dirname, '../web');
const outputDir = process.env.NCD_UI_OUTPUT || '/private/tmp/ncd-ui-check';
const requests = [];
const examples = [
  { id: '1', type: 'single', question: '收费员着装规定标准统一穿（ ）鞋子，光亮、清洁并和袜子颜色协调。', options: [{ key: 'A', text: '白色' }, { key: 'B', text: '深色' }, { key: 'C', text: '浅色' }, { key: 'D', text: '棕色' }], answer: ['B'], answer_text: ['深色'] },
  { id: '2', type: 'multiple', question: '收费应急处置原则包括？', options: [{ key: 'A', text: '预防为主' }, { key: 'B', text: '以人为本' }, { key: 'C', text: '迅速自救' }, { key: 'D', text: '统一协调' }], answer: ['A', 'B', 'C', 'D'], answer_text: ['预防为主', '以人为本', '迅速自救', '统一协调'] }
];

function json(response, status, data) {
  response.writeHead(status, { 'Content-Type': 'application/json' });
  response.end(JSON.stringify(data));
}

const server = http.createServer(async (request, response) => {
  const url = new URL(request.url, 'http://localhost');
  if (url.pathname === '/ncd/api/login') {
    const parts = [];
    for await (const part of request) parts.push(part);
    const body = JSON.parse(Buffer.concat(parts));
    if (body.password === 'test-only-passphrase') {
      response.setHeader('Set-Cookie', 'ncd_ui_session=fixture; Path=/ncd/; HttpOnly; SameSite=Lax');
      return json(response, 200, { ok: true });
    }
    return json(response, 401, { error: '密码不正确' });
  }
  if (url.pathname === '/ncd/api/search') {
    const query = url.searchParams.get('q');
    const page = Number(url.searchParams.get('page'));
    requests.push({ query, page });
    if (query === '会话过期') return json(response, 401, { error: '请先输入密码' });
    if (query === '无结果') return json(response, 200, { query, page, total: 0, page_size: 20, has_more: false, items: [] });
    if (query === '失败') return json(response, 429, { error: '请稍后重试' });
    if (query === '旧题') await new Promise(resolve => setTimeout(resolve, 900));
    let items = examples;
    if (query === '旧题' || query === '新题') items = [{ ...examples[0], question: query }];
    if (query === '注入') items = [{ ...examples[0], question: '<img src=x onerror="window.injected=true">', options: [{ key: 'A', text: '<script>window.injected=true</script>' }], answer: ['A'], answer_text: ['<b>普通文本</b>'] }];
    if (query === '分页') items = page === 1 ? [examples[0]] : [examples[1]];
    return json(response, 200, { query, page, total: 2, page_size: 20, has_more: query === '分页' && page === 1, items });
  }
  if (url.pathname === '/ncd/') {
    const file = (request.headers.cookie || '').includes('ncd_ui_session=fixture') ? 'index.html' : 'login.html';
    response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    return response.end(fs.readFileSync(path.join(webDir, file)));
  }
  const filename = url.pathname.replace('/ncd/assets/', '');
  if (['ncd.css', 'login.js', 'search.js'].includes(filename)) {
    response.writeHead(200, { 'Content-Type': filename.endsWith('.css') ? 'text/css' : 'text/javascript' });
    return response.end(fs.readFileSync(path.join(webDir, filename)));
  }
  response.writeHead(404);
  response.end();
});

(async () => {
  fs.mkdirSync(outputDir, { recursive: true });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1487, height: 1058 } });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto(`${base}/ncd/`);
    await page.screenshot({ path: path.join(outputDir, 'login.png') });
    await page.locator('#password').fill('wrong-password');
    await page.locator('#loginButton').click();
    await page.waitForFunction(() => document.querySelector('#loginStatus').textContent === '密码不正确');
    assert.equal(await page.locator('#password').inputValue(), '');
    await page.locator('#password').fill('test-only-passphrase');
    await page.locator('#password').press('Enter');
    await page.locator('#query').waitFor();
    assert.equal(await page.locator('h1, h2, header, nav').count(), 0);

    await page.locator('#query').fill('收费');
    await page.waitForFunction(() => document.querySelectorAll('.result').length === 2);
    assert.match(await page.locator('.answer').first().textContent(), /答案：B（深色）/);
    await page.screenshot({ path: path.join(outputDir, 'search-desktop.png') });
    assert.equal(await page.evaluate(() => localStorage.length + sessionStorage.length), 0);

    // 连续查询时慢响应不能把已经出现的新结果覆盖掉。
    await page.locator('#query').fill('旧题');
    await page.waitForTimeout(380);
    await page.locator('#query').fill('新题');
    await page.waitForFunction(() => document.querySelector('.question')?.textContent.includes('新题'));
    await page.waitForTimeout(1000);
    assert.match(await page.locator('.question').textContent(), /新题/);

    await page.locator('#query').fill('');
    assert.equal(await page.locator('.result').count(), 0);
    const beforeComposition = requests.length;
    await page.locator('#query').dispatchEvent('compositionstart');
    await page.locator('#query').fill('收费');
    await page.waitForTimeout(400);
    assert.equal(requests.length, beforeComposition);
    await page.locator('#query').dispatchEvent('compositionend');
    await page.waitForFunction(() => document.querySelectorAll('.result').length === 2);

    // 粘贴多行题目时保留选项分隔，替换当前选区并把光标放到插入文字后。
    await page.locator('#query').fill('前缀旧内容后缀');
    const pastedValue = '前缀题干 A. 甲 B. 乙后缀';
    await page.locator('#query').evaluate(input => {
      input.setSelectionRange(2, 5);
      const clipboardData = new DataTransfer();
      clipboardData.setData('text/plain', '题干\r\nA. 甲\nB. 乙');
      input.dispatchEvent(new ClipboardEvent('paste', { clipboardData, bubbles: true, cancelable: true }));
    });
    assert.equal(await page.locator('#query').inputValue(), pastedValue);
    assert.equal(await page.locator('#query').evaluate(input => input.selectionStart), pastedValue.indexOf('后缀'));
    await page.waitForTimeout(400);
    assert.equal(requests.at(-1).query, pastedValue);
    assert.equal(await page.locator('#query').getAttribute('maxlength'), '1000');
    await page.locator('#query').fill('');
    await page.locator('#query').evaluate(input => {
      const clipboardData = new DataTransfer();
      clipboardData.setData('text/plain', '甲'.repeat(1001));
      input.dispatchEvent(new ClipboardEvent('paste', { clipboardData, bubbles: true, cancelable: true }));
    });
    assert.equal((await page.locator('#query').inputValue()).length, 1000);
    assert.equal(await page.locator('#query').evaluate(input => input.selectionStart), 1000);

    await page.locator('#query').fill('分页');
    await page.locator('#loadMore').waitFor({ state: 'visible' });
    assert.equal(await page.locator('.result').count(), 1);
    await page.locator('#loadMore').click();
    await page.waitForFunction(() => document.querySelectorAll('.result').length === 2);
    assert.equal(await page.locator('#loadMore').isVisible(), false);
    assert.match(await page.locator('.question').last().textContent(), /^2\./);

    await page.locator('#query').fill('注入');
    await page.waitForFunction(() => document.querySelector('.question')?.textContent.includes('<img'));
    assert.equal(await page.locator('#results img, #results script, #results b').count(), 0);
    assert.equal(await page.evaluate(() => window.injected), undefined);

    await page.locator('#query').fill('无结果');
    await page.waitForFunction(() => document.querySelector('#searchStatus').textContent.startsWith('未找到'));
    assert.equal(await page.locator('.result').count(), 0);
    await page.locator('#query').fill('失败');
    await page.waitForFunction(() => document.querySelector('#searchStatus').textContent === '请稍后重试');

    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('#query').fill('收费');
    await page.waitForFunction(() => document.querySelectorAll('.result').length === 2);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: path.join(outputDir, 'search-mobile.png'), fullPage: true });

    await context.clearCookies();
    await page.locator('#query').fill('会话过期');
    await page.locator('#password').waitFor();
    assert.deepEqual(errors, []);
    console.log('通过：登录错误提示、搜索、输入法、多行粘贴、旧请求取消、分页、空结果、XSS 文本、移动布局及过期登录。');
    console.log(`截图目录：${outputDir}`);
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => {
  console.error(error);
  server.close();
  process.exitCode = 1;
});
