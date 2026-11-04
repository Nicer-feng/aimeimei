#!/usr/bin/env node
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), http = require('node:http'), path = require('node:path');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const models = [
  { id: 'qwen', name: '现有 Qwen', model: 'qwen-fixture', provider: 'Qwen' },
  { id: 'official', name: 'OpenAI 测试模型', model: 'gpt-fixture', provider: 'OpenAI', uses_openai_egress: true, has_api_key: true },
  { id: 'other', name: '另一个 OpenAI', model: 'gpt-other', provider: 'OpenAI', uses_openai_egress: true }
];
const counts = { check: 0, test: [], saves: [] };
let base, reachable = true, cfg = { installed: true, enabled: false, subscription_configured: false, selected_node: '' };
const json = (res, data, status = 200) => { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(data)); };
const server = http.createServer(async (req, res) => {
  const p = new URL(req.url, base).pathname, chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const body = chunks.length ? JSON.parse(Buffer.concat(chunks)) : {};
  if (/^\/api\/models\/[^/]+\/availability$/.test(p)) {
    counts.check++; await new Promise(resolve => setTimeout(resolve, 100));
    return json(res, { status: reachable ? 'reachable' : 'unavailable', message: '本地模拟检查', checked_at: Date.now() / 1000, expires_at: Date.now() / 1000 + 90 });
  }
  if (p === '/api/admin/openai-egress/test') { counts.test.push(body); return json(res, { status: 'reachable', message: '本地模拟连接通过，未执行生成' }); }
  if (p === '/api/admin/openai-egress') {
    if (req.method === 'POST') { counts.saves.push(body); cfg = { ...cfg, enabled: body.enabled, subscription_configured: true, selected_node: body.selected_node }; }
    return json(res, { egress: cfg, nodes: ['节点 A', '节点 B'] });
  }
  const fixtures = {
    '/api/me': { authenticated: true, user: { id: 'egress-fixture', username: 'fixture', role: 'admin' } },
    '/api/models': { models }, '/api/admin/models': { models }, '/api/features': { features: {} },
    '/api/version': { version: fs.readFileSync(path.join(root, 'VERSION'), 'utf8').trim(), build_id: 'fixture' },
    '/api/search-config': { search: { enabled: false } }, '/api/tts/config': { tts: { enabled: false } },
    '/api/usage-time/config': { server_now_ms: Date.now(), idle_ms: 120000 }, '/api/usage-time/heartbeat': { credited_ms: 0 },
    '/api/conversations': { conversations: [] }, '/api/profiles': { profiles: [], totals: {} }, '/api/prompts': { prompts: [] },
    '/api/favorites': { favorites: [] }, '/api/sms-login/config': { sms_auth: { configured: false } }, '/api/admin/overview': { overview: {} },
    '/api/session/device-info': { ok: true }
  };
  if (fixtures[p]) return json(res, fixtures[p]);
  if (p.startsWith('/api/')) return json(res, { error: 'undefined fixture' }, 501);
  const file = path.resolve(root, p === '/' ? 'ai.html' : p.slice(1));
  if (!file.startsWith(root + '/') || !fs.existsSync(file) || !fs.statSync(file).isFile()) return json(res, {}, 404);
  res.writeHead(200, { 'Content-Type': ({ '.html':'text/html', '.js':'application/javascript', '.css':'text/css', '.png':'image/png', '.svg':'image/svg+xml' })[path.extname(file)] || 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve)); base = 'http://127.0.0.1:' + server.address().port;
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
    await context.route('https://**', route => route.abort());
    const page = await context.newPage(), errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto(base); await page.waitForFunction(() => state.authed && state.models.length === 3);
    assert.equal(counts.check, 0); await page.evaluate(() => openModelPicker());
    await page.waitForTimeout(200); assert.equal(counts.check, 0);
    assert.equal(await page.locator('#modelPickerList [data-openai-health]').count(), 2);
    await page.evaluate(() => chooseModel('official'));
    await page.waitForFunction(() => document.querySelector('#openaiCurrentHealth')?.dataset.health === 'reachable');
    assert.equal(counts.check, 1);
    for (let i = 0; i < 10; i++) await page.evaluate(() => { syncModelPickerButton(); renderModelPickerList(); });
    await page.evaluate(() => document.querySelector('#prompt').focus()); await page.waitForTimeout(300); assert.equal(counts.check, 1);
    await page.evaluate(() => { window.originalDateNow = Date.now; Date.now = () => originalDateNow() + 95000; });
    reachable = false; await page.waitForTimeout(200); assert.equal(counts.check, 1);
    await page.evaluate(() => MeimeiOpenAIEgress.check());
    await page.waitForFunction(() => document.querySelector('#openaiCurrentHealth')?.dataset.health === 'unavailable');
    assert.equal(counts.check, 2);
    await page.evaluate(() => { Date.now = originalDateNow; openSettings(); switchAdminSection('egress'); });
    await page.waitForFunction(() => document.querySelector('#openaiTestModel').options.length === 3);
    await page.locator('#openaiSubscription').fill('https://subscription.example/fixture-only'); await page.locator('#openaiEgressReload').click();
    await page.waitForFunction(() => document.querySelector('#openaiEgressStatus').textContent.includes('订阅已更新'));
    assert.equal(await page.locator('#openaiSubscription').inputValue(), '');
    await page.getByRole('button', { name: /^当前节点：/ }).click();
    await page.getByRole('option', { name: '节点 A', exact: true }).click();
    await page.locator('#openaiEgressEnabled').check(); await page.locator('#openaiEgressSave').click();
    await page.waitForFunction(() => document.querySelector('#openaiEgressStatus').textContent === '已保存');
    await page.locator('#openaiProxyTest').click();
    await page.waitForFunction(() => document.querySelector('#openaiEgressStatus').textContent.includes('模拟连接通过'));
    await page.getByRole('button', { name: /^API 测试模型：/ }).click();
    await page.getByRole('option', { name: 'OpenAI 测试模型 · gpt-fixture', exact: true }).click();
    await page.locator('#openaiModelTest').click();
    await page.waitForTimeout(200); assert.deepEqual(counts.test.map(item => item.kind), ['proxy', 'model']);
    await page.screenshot({ path: '/private/tmp/meimei-openai-egress-desktop.png' });
    await page.evaluate(() => applyTheme('dark'));
    await page.waitForTimeout(250);
    await page.screenshot({ path: '/private/tmp/meimei-openai-egress-dark.png' });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => { closeSidebar(); openSettings(); switchAdminSection('egress'); });
    await page.waitForTimeout(350);
    await page.screenshot({ path: '/private/tmp/meimei-openai-egress-mobile.png' });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.evaluate(() => switchAdminSection('keys'));
    await page.waitForFunction(() => document.querySelectorAll('.admin-key-row [data-egress-action]').length === 2);
    const card = page.locator('.admin-key-card').filter({ hasText: 'gpt-fixture' });
    await card.locator('input').fill('sk-local-fixture'); await card.locator('[data-egress-action]').click();
    await page.waitForFunction(() => document.querySelector('.openai-key-status')?.textContent.includes('模拟连接通过'));
    assert.equal(counts.test.at(-1).api_key, 'sk-local-fixture'); assert.deepEqual(errors, []);
    console.log(JSON.stringify({ passed: true, availability_checks: counts.check, tests: counts.test.length, automatic_polling: false }));
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
