#!/usr/bin/env node
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), http = require('node:http'), path = require('node:path');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const sources = Array.from({ length: 8 }, (_, i) => ({ position: i + 1, url: `https://source-${i + 1}.example/article`, title: `参考网页 ${i + 1}`, snippet: '这是一段用于验证来源定位的正文摘要。'.repeat(5) }));
const content = '**我的判断是：这里是中文。**你说的情况需要核实。[1][2][4][5]\n\n先说明：**资料不足。**我不能下结论。[7]\n\n## 影响因素\n\n- **利率与国债收益率：**如果上升，需要注意。\n- **盈利预期：**市场关注后续增长。\n\n1. **第一项**\n2. 第二项\n\n> 引用内容，保留加粗：**中文。**后续文字。[4]\n\n| 层次 | 说明 |\n| --- | --- |\n| 来源 | 中文长段落与正文引用。[2] |\n\n```bash\necho "**中文。**原文 [1][2]"\n```\n\n普通链接：[1](https://direct.example)；代码：`[1]`；不存在的来源：[99]。';
const messages = [
  { id: 1, role: 'user', content: '保留用户原文 [1]，不要转成来源。', created_at: 1793760000 },
  { id: 2, role: 'assistant', content, sources, created_at: 1793760001 }
];
let base;
const json = (res, data, status = 200) => { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(data)); };
const server = http.createServer((req, res) => {
  const p = new URL(req.url, base).pathname;
  const fixtures = {
    '/api/me': { authenticated: true, user: { id: 'markdown-fixture', username: 'fixture', role: 'admin' } },
    '/api/models': { models: [{ id: 'fixture', name: '本地测试模型', model: 'fixture', provider: 'fixture' }] },
    '/api/features': { features: {} }, '/api/version': { version: fs.readFileSync(path.join(root, 'VERSION'), 'utf8').trim(), build_id: 'fixture' },
    '/api/search-config': { search: { enabled: false } }, '/api/tts/config': { tts: { enabled: false } },
    '/api/usage-time/config': { server_now_ms: Date.now(), idle_ms: 120000 }, '/api/usage-time/heartbeat': { credited_ms: 0 },
    '/api/conversations': { conversations: [] }, '/api/profiles': { profiles: [], totals: {} }, '/api/prompts': { prompts: [] },
    '/api/favorites': { favorites: [] }, '/api/sms-login/config': { sms_auth: { configured: false } },
    '/api/session/device-info': { ok: true },
    '/api/public/shares/fixture': { share: { title: '本地 Markdown 分享', expires_at: Date.now() / 1000 + 86400, snapshot: { messages } } }
  };
  if (fixtures[p]) return json(res, fixtures[p]);
  if (p.startsWith('/api/')) return json(res, { error: 'undefined fixture' }, 501);
  const file = path.resolve(root, p === '/' ? 'ai.html' : p === '/ai/share/fixture' ? 'share.html' : p.slice(1));
  if (!file.startsWith(root + '/') || !fs.existsSync(file) || !fs.statSync(file).isFile()) return json(res, {}, 404);
  res.writeHead(200, { 'Content-Type': ({ '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.png': 'image/png', '.svg': 'image/svg+xml' })[path.extname(file)] || 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  base = 'http://127.0.0.1:' + server.address().port;
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    await context.route('https://**', route => route.abort());
    const page = await context.newPage(), errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto(base); await page.waitForFunction(() => state.authed && state.models.length);
    const cases = await page.evaluate((sources) => {
      const render = (text, items = sources) => {
        const root = document.createElement('div');
        root.innerHTML = AIMarkdown.render(text, { sources: items });
        return { html: root.innerHTML, text: root.textContent, bold: [...root.querySelectorAll('strong')].map(n => n.textContent), citations: [...root.querySelectorAll('.md-citation')].map(n => n.dataset.citationIndex) };
      };
      return {
        cjk: render('**判断：中文。**后续\n\n说明：**资料。**我理解\n\n- **收益率：**如果上升'),
        ordinary: render('**bold** and **normal.**Next; a_b_c; ** 未配对'),
        quoted: render('中文**“观点”**继续；***中文。***继续'),
        adjacent: render('[1][2][4][5] [99]'),
        links: render('[1](https://direct.example) [1][reference]\n\n[reference]: https://reference.example'),
        protected: render('`[1] **中文。**内容`\n\n```text\n[1] **中文。**内容\n```\n\n\\[1] <code>[1]</code> <a href="https://direct.example">[1]</a> $[1]$'),
        footnote: render('正文[^1]\n\n[^1]: 脚注内容。'),
        none: render('[1][2]', []),
        unsafe: render('[1][2]', [{ url: 'javascript:alert(1)' }, { url: 'data:text/html,xxx' }]),
        escape: render('[1]', [{ url: 'https://safe.example', title: '\"><img src=x onerror=alert(1)>' }]),
        html: render('<script>window.markdownXss = true</script>\n\n<img src=x onerror="window.markdownXss = true">'),
        gaps: render('[4][1][2]', [sources[3], sources[0]]),
        tasks: render('- [x] 完成\n- [ ] 未完成')
      };
    }, sources);
    assert.deepEqual(cases.cjk.bold, ['判断：中文。', '资料。', '收益率：']);
    assert.ok(!cases.cjk.text.includes('**'));
    assert.deepEqual(cases.ordinary.bold, ['bold']); assert.ok(cases.ordinary.text.includes('**normal.**Next'));
    assert.ok(cases.quoted.bold.length === 2 && !cases.quoted.text.includes('*'));
    assert.deepEqual(cases.adjacent.citations, ['1', '2', '4', '5']); assert.ok(cases.adjacent.text.includes('[99]'));
    assert.deepEqual(cases.links.citations, []); assert.match(cases.links.html, /reference\.example/);
    assert.deepEqual(cases.protected.citations, []); assert.ok(cases.protected.text.includes('**中文。**内容'));
    assert.match(cases.footnote.html, /footnote-ref/);
    assert.deepEqual(cases.none.citations, []); assert.deepEqual(cases.unsafe.citations, []);
    assert.ok(!cases.escape.html.includes('<img')); assert.ok(!cases.html.html.includes('onerror') && !cases.html.html.includes('<script'));
    assert.deepEqual(cases.gaps.citations, ['4', '1']); assert.match(cases.tasks.html, /task-list-item-checkbox/);
    await page.evaluate((messages) => {
      state.currentConversation = { id: 'fixture', title: 'Markdown 回归', model_id: 'fixture' };
      state.messages = messages; state.followOutput = false; renderMessages(); closeSidebar();
    }, messages);
    const answer = page.locator('.bubble.assistant .message-content');
    assert.equal(await answer.locator('a.md-citation').count(), 7);
    assert.equal(await page.locator('.bubble.user a.md-citation').count(), 0);
    assert.equal(await page.locator('.sources-entry-count').textContent(), '8 个网页');
    assert.equal(await answer.locator('ul').first().evaluate(n => getComputedStyle(n).listStyleType), 'disc');
    assert.equal(await answer.locator('ol').first().evaluate(n => getComputedStyle(n).listStyleType), 'decimal');
    await page.locator('#prompt').fill('引用来源操作不能清空的草稿');
    await answer.locator('[data-citation-index="7"]').click();
    await page.waitForFunction(() => state.referenceHighlightIndex === 7 && !document.querySelector('#referenceSourcesPanel').hidden);
    await page.waitForTimeout(380);
    assert.equal(await page.locator('#referenceSourcesList .reference-source-item').count(), 8);
    assert.equal(await page.locator('#reference-source-7.is-highlighted').count(), 1);
    assert.equal(await page.locator('#reference-source-7').getAttribute('href'), sources[6].url);
    const target = await page.locator('#reference-source-7').boundingBox(), list = await page.locator('#referenceSourcesList').boundingBox();
    assert.ok(target.y >= list.y - 1 && target.y + target.height <= list.y + list.height + 1, 'matching source is visible');
    await page.screenshot({ path: '/private/tmp/meimei-markdown-citations-desktop.png' });
    await page.evaluate(() => applyTheme('dark')); await page.waitForTimeout(200);
    await page.screenshot({ path: '/private/tmp/meimei-markdown-citations-dark.png' });
    await page.locator('#closeReferenceSources').click(); await page.waitForTimeout(260);
    assert.equal(await page.locator('#prompt').inputValue(), '引用来源操作不能清空的草稿');
    const cache = await page.evaluate(() => {
      const message = state.messages[1];
      let calls = 0; const original = AIMarkdown.render;
      AIMarkdown.render = (...args) => { calls++; return original(...args); };
      renderMessageMarkdown(message, displayMessageContent(message));
      renderMessageMarkdown(message, displayMessageContent(message));
      const unchanged = calls;
      message.sources[0].title = '修改后的来源标题';
      const changed = renderMessageMarkdown(message, displayMessageContent(message));
      const history = message._contentMarkdownHtml;
      const live = { role: 'assistant', thinking: true, content: '[1]', sources: message.sources };
      const node = document.createElement('div');
      document.body.appendChild(node);
      for (let i = 0; i < 30; i++) renderStreamingMarkdown(node, live, '流式正文 [1] ' + i);
      const liveLinks = node.querySelectorAll('.md-citation').length;
      live.thinking = false; renderStreamingMarkdown(node, live, '[1]', { final: true });
      const finalLinks = node.querySelectorAll('.md-citation').length;
      node.remove(); AIMarkdown.render = original;
      return { unchanged, updated: changed.includes('修改后的来源标题'), historyUnchanged: history === message._contentMarkdownHtml, liveLinks, finalLinks };
    });
    assert.deepEqual(cache, { unchanged: 0, updated: true, historyUnchanged: true, liveLinks: 0, finalLinks: 1 });
    await page.evaluate(() => applyTheme('light')); await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => { closeSidebar(); document.querySelector('#messages').scrollTop = 0; });
    await answer.locator('[data-citation-index="1"]').first().click(); await page.waitForTimeout(300);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    const panel = await page.locator('#referenceSourcesPanel').boundingBox();
    assert.ok(panel.x >= -1 && panel.x + panel.width <= 391);
    await page.screenshot({ path: '/private/tmp/meimei-markdown-citations-mobile.png' });
    await page.goto(base + '/ai/share/fixture'); await page.waitForSelector('.share-message-content .md-citation');
    assert.equal(await page.locator('.share-message-content .md-citation').count(), 7);
    assert.equal(await page.locator('.md-citation').first().getAttribute('href'), sources[0].url);
    assert.equal(await page.locator('.md-citation').first().getAttribute('target'), '_blank');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ passed: true, syntaxCases: Object.keys(cases).length, historicalCitations: 7, cache, desktopMobileAndShare: true }));
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
