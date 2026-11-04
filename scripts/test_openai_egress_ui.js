#!/usr/bin/env node
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), http = require('node:http'), path = require('node:path');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const models = [
  { id: 'qwen', name: '现有 Qwen', model: 'qwen-fixture', provider: 'Qwen', supports_reasoning_control: true },
  { id: 'official', name: 'OpenAI 测试模型', model: 'gpt-6.1-sol', provider: 'OpenAI', uses_openai_egress: true, has_api_key: true, supports_reasoning_control: true,
    reasoning_mode_options: { fast: { title: '快速：低思考强度（low）', description: '低思考强度，不完全关闭思考' }, balanced: { title: '平衡（medium）', description: '中等思考强度' }, deep: { title: '深度（high）', description: '高思考强度' } } },
  { id: 'other', name: '另一个 OpenAI', model: 'gpt-6.1-terra', provider: 'OpenAI', uses_openai_egress: true, supports_reasoning_control: true,
    reasoning_mode_options: { fast: { title: '快速：关闭思考（none）', description: '关闭思考，优先响应速度' } } }
];
const counts = { check: 0, test: [], saves: [] };
let budget = { enabled: true, limit_usd: 50, cny_per_usd: 6.718, period: '2026-11', spent_usd: 12.5, reserved_usd: .1, remaining_usd: 37.4, exhausted: false, warning: false, uncertain_requests: 0 };
const budgetSaves = [];
let base, reachable = true, cfg = { installed: true, enabled: false, subscription_configured: false, selected_node: '' };
const json = (res, data, status = 200) => { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(data)); };
const server = http.createServer(async (req, res) => {
  const p = new URL(req.url, base).pathname, chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const body = chunks.length ? JSON.parse(Buffer.concat(chunks)) : {};
  if (p === '/api/admin/openai-budget') {
    if (req.method === 'POST') {
      budgetSaves.push(body); budget = { ...budget, ...body };
      budget.exhausted = budget.enabled && budget.spent_usd >= budget.limit_usd;
      budget.warning = budget.enabled && budget.spent_usd >= budget.limit_usd * .8;
      budget.remaining_usd = Math.max(0, budget.limit_usd - budget.spent_usd - budget.reserved_usd);
    }
    return json(res, { budget });
  }
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
    const reasoningButton = page.locator('#reasoningPickerButton');
    async function assertReasoningOpen(open, label, target = page) {
      const actual = await target.evaluate(() => ({
        state: state.reasoningPickerOpen,
        hidden: document.querySelector('#reasoningPickerMenu').hidden,
        expanded: document.querySelector('#reasoningPickerButton').getAttribute('aria-expanded')
      }));
      assert.deepEqual(actual, { state: open, hidden: !open, expanded: String(open) }, label);
    }
    await reasoningButton.click(); await assertReasoningOpen(true, 'first open');
    await reasoningButton.click(); await assertReasoningOpen(false, 'same button closes the menu');
    await reasoningButton.click(); await page.locator('#prompt').click({ position: { x: 12, y: 12 } }); await assertReasoningOpen(false, 'outside composer click closes');
    await reasoningButton.click(); await page.locator('.empty-copy h2').click(); await assertReasoningOpen(false, 'outside chat click closes');
    await page.evaluate(() => document.querySelector('#prompt').addEventListener('pointerdown', event => event.stopPropagation(), { once: true }));
    await reasoningButton.click(); await page.locator('#prompt').click({ position: { x: 12, y: 12 } }); await assertReasoningOpen(false, 'outside click still closes when target stops bubbling');
    await reasoningButton.click(); await page.keyboard.press('Escape'); await assertReasoningOpen(false, 'Escape closes');
    for (let i = 0; i < 4; i++) {
      await reasoningButton.click(); await assertReasoningOpen(true, 'repeat open');
      await reasoningButton.click(); await assertReasoningOpen(false, 'repeat close');
    }
    await reasoningButton.focus(); await page.keyboard.press('Enter'); await assertReasoningOpen(true, 'keyboard open');
    await page.keyboard.press('Enter'); await assertReasoningOpen(false, 'keyboard toggle closes');
    await reasoningButton.click();
    await page.locator('[data-reasoning-mode="balanced"]').click(); await assertReasoningOpen(false, 'select current mode closes');
    await page.locator('#prompt').fill('菜单开关不应清空的草稿');
    await page.evaluate(() => { state.sending = true; });
    await reasoningButton.click(); await assertReasoningOpen(true, 'menu can open while generating');
    await reasoningButton.click(); await assertReasoningOpen(false, 'menu can close while generating');
    await page.evaluate(() => { state.sending = false; });
    assert.equal(await page.locator('#prompt').inputValue(), '菜单开关不应清空的草稿');
    await page.locator('#prompt').fill('');
    await reasoningButton.click(); await page.evaluate(() => openModelPicker());
    await assertReasoningOpen(false, 'opening model picker closes reasoning menu');
    await page.evaluate(() => closeModelPicker());
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
    await page.waitForFunction(() => !document.querySelector('#openaiBudgetSave').disabled);
    assert.equal(await page.locator('#openaiBudgetSpent').textContent(), '$12.50');
    assert.equal(await page.locator('#openaiBudgetLimit').inputValue(), '50');
    await page.locator('#openaiBudgetLimit').fill('10'); await page.locator('#openaiBudgetSave').click();
    await page.waitForFunction(() => document.querySelector('#openaiBudgetSummary').textContent.includes('新请求已暂停'));
    assert.equal(budgetSaves.length, 1);
    assert.equal(await page.locator('#openaiBudgetProgress').getAttribute('data-exhausted'), 'true');
    await page.screenshot({ path: '/private/tmp/meimei-openai-budget-exhausted.png' });
    await page.locator('#openaiBudgetLimit').fill('50'); await page.locator('#openaiBudgetSave').click();
    await page.waitForFunction(() => document.querySelector('#openaiBudgetSummary').textContent.includes('额度正常'));
    await page.locator('#openaiBudgetTitle').scrollIntoViewIfNeeded();
    await page.screenshot({ path: '/private/tmp/meimei-openai-budget-desktop.png' });
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
    await page.getByRole('option', { name: 'OpenAI 测试模型 · gpt-6.1-sol', exact: true }).click();
    await page.locator('#openaiModelTest').click();
    await page.waitForTimeout(200); assert.deepEqual(counts.test.map(item => item.kind), ['proxy', 'model']);
    await page.screenshot({ path: '/private/tmp/meimei-openai-egress-desktop.png' });
    await page.evaluate(() => applyTheme('dark'));
    await page.waitForTimeout(250);
    await page.screenshot({ path: '/private/tmp/meimei-openai-egress-dark.png' });
    await page.locator('#openaiBudgetTitle').scrollIntoViewIfNeeded();
    await page.screenshot({ path: '/private/tmp/meimei-openai-budget-dark.png' });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => { closeSidebar(); openSettings(); switchAdminSection('egress'); });
    await page.waitForTimeout(350);
    await page.screenshot({ path: '/private/tmp/meimei-openai-egress-mobile.png' });
    await page.locator('#openaiBudgetTitle').scrollIntoViewIfNeeded();
    const amounts = await page.locator('.openai-budget-summary dd').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().y));
    assert.ok(Math.max(...amounts) - Math.min(...amounts) < 2, 'mobile budget amounts align');
    await page.screenshot({ path: '/private/tmp/meimei-openai-budget-mobile.png' });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.evaluate(() => switchAdminSection('keys'));
    await page.waitForFunction(() => document.querySelectorAll('.admin-key-row [data-egress-action]').length === 2);
    const card = page.locator('.admin-key-card').filter({ hasText: 'gpt-6.1-sol' });
    await card.locator('input').fill('sk-local-fixture'); await card.locator('[data-egress-action]').click();
    await page.waitForFunction(() => document.querySelector('.openai-key-status')?.textContent.includes('模拟连接通过'));
    await page.screenshot({ path: '/private/tmp/meimei-openai-egress-key-mobile.png' });
    await page.setViewportSize({ width: 1440, height: 960 });
    await page.evaluate(() => { closeSidebar(); openSettings(); switchAdminSection('keys'); });
    await page.waitForFunction(() => document.querySelectorAll('.openai-key-row').length === 2);
    const actions = card.locator('.openai-key-row > button'), first = await actions.first().boundingBox();
    for (let i = 1; i < 3; i++) assert.ok(Math.abs((await actions.nth(i).boundingBox()).y - first.y) < 2);
    await page.screenshot({ path: '/private/tmp/meimei-openai-egress-key-desktop.png' });
    await page.evaluate(async () => { closeSettings(); await chooseModel('official'); await chooseReasoningMode('fast'); });
    assert.match(await page.locator('#reasoningPickerButton').getAttribute('title'), /low/);
    assert.match(await page.locator('[data-reasoning-mode="fast"] small').textContent(), /不完全关闭/);
    assert.equal(await page.locator('#reasoningPickerIcon [data-lucide="zap"]').count(), 1);
    await page.locator('#reasoningPickerButton').click(); await page.waitForTimeout(200);
    await page.screenshot({ path: '/private/tmp/meimei-openai-sol-reasoning.png' });
    await page.locator('#reasoningPickerButton').click();
    await page.evaluate(() => chooseReasoningMode('deep'));
    assert.match(await page.locator('#reasoningPickerButton').getAttribute('title'), /high/);
    await page.evaluate(async () => { await chooseModel('other'); await chooseReasoningMode('fast'); });
    assert.match(await page.locator('#reasoningPickerButton').getAttribute('title'), /none/);
    await page.evaluate(async () => { await chooseModel('qwen'); await chooseReasoningMode('fast'); });
    assert.match(await page.locator('#reasoningPickerButton').getAttribute('title'), /关闭思考/);
    assert.equal(counts.test.at(-1).api_key, 'sk-local-fixture'); assert.deepEqual(errors, []);
    const touch = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
    await touch.route('https://**', route => route.abort());
    const phone = await touch.newPage();
    phone.on('pageerror', error => errors.push(String(error)));
    await phone.goto(base); await phone.waitForFunction(() => state.authed && state.models.length === 3);
    await phone.evaluate(() => closeSidebar());
    const touchButton = phone.locator('#reasoningPickerButton');
    await touchButton.tap(); await assertReasoningOpen(true, 'touch open', phone);
    await phone.waitForTimeout(220);
    const touchMenu = await phone.locator('#reasoningPickerMenu').boundingBox();
    assert.ok(touchMenu && touchMenu.y >= 0 && touchMenu.y + touchMenu.height <= 844, 'touch menu stays in viewport');
    await phone.screenshot({ path: '/private/tmp/meimei-reasoning-menu-touch-open.png' });
    await touchButton.tap(); await assertReasoningOpen(false, 'touch same button closes', phone);
    await touchButton.tap(); await phone.locator('.empty-copy h2').tap(); await assertReasoningOpen(false, 'touch outside closes', phone);
    await touchButton.tap(); await phone.locator('[data-reasoning-mode="fast"]').tap();
    await assertReasoningOpen(false, 'touch selection closes', phone);
    assert.equal(await phone.locator('#reasoningPickerLabel').textContent(), '快速');
    assert.equal(await phone.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await touch.close(); assert.deepEqual(errors, []);
    console.log(JSON.stringify({ passed: true, availability_checks: counts.check, tests: counts.test.length, automatic_polling: false }));
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
