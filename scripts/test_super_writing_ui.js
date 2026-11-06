#!/usr/bin/env node
'use strict';
// 使用本地接口和文件解析替身验证超能模式，不调用真实模型或 OSS。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const now = Math.floor(Date.now() / 1000);
const model = { id: 'mock', name: '本地模型', model: 'qwen-fixture', provider: 'mock', supports_vision: true };
let base, created = 0, versionId = 0, conflict = false, delayPatch = 0;
const counts = { super: 0, final: [], create: [], bind: 0, document: 0 };
const conversations = ['a', 'b'].map((id, index) => ({ id, title: `任务${id}`, model_id: 'mock', model_name: model.name, model: model.model, super_mode: false, writing_mode: false, context_mode: 'smart', created_at: now - index, updated_at: now - index }));
const records = new Map();
const workspace = id => {
  if (!records.has(id)) records.set(id, { eligible: true, enabled: false, revision: 0, delivery: id === 'a' ? { id: 'inferred-a', content: '正文：这是根据历史交流提取的候选稿。', label: '历史推定', source: 'inferred', updated_at: now } : null, versions: [], reference_status: { confirmed_count: 0, fallback_count: 2, threshold: 10 } });
  return records.get(id);
};
const json = (res, data, status = 200) => { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(data)); };
const server = http.createServer(async (req, res) => {
  const p = new URL(req.url, base).pathname, chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const raw = Buffer.concat(chunks), body = String(req.headers['content-type'] || '').includes('application/json') && raw.length ? JSON.parse(raw) : {};
  let match;
  if ((match = p.match(/^\/api\/conversations\/([^/]+)\/super-writing$/))) {
    counts.super++;
    const data = workspace(match[1]);
    if (req.method === 'PATCH') {
      if (delayPatch) await new Promise(resolve => setTimeout(resolve, delayPatch));
      if (body.revision !== data.revision) return json(res, { error: '版本已更新' }, 409);
      data.enabled = body.enabled; data.revision++;
      conversations.find(c => c.id === match[1]).super_mode = data.enabled;
    }
    return json(res, data);
  }
  if ((match = p.match(/^\/api\/conversations\/([^/]+)\/final-deliveries$/))) {
    counts.final.push({ id: match[1], body });
    const data = workspace(match[1]);
    if (conflict) { conflict = false; data.revision++; return json(res, { error: '版本已更新' }, 409); }
    if (body.revision !== data.revision) return json(res, { error: '版本已更新' }, 409);
    const delivery = { id: String(++versionId), content: body.document_id ? '客户已接受的 Word 终稿正文。' : body.content, filename: body.filename || '', label: body.label, source: 'customer', created_at: now, updated_at: now };
    data.delivery = delivery; data.versions.unshift(delivery); data.revision++; data.reference_status.confirmed_count++;
    return json(res, data, 201);
  }
  if (p === '/api/conversations') {
    if (req.method === 'POST') {
      counts.create.push(body);
      const conversation = { ...conversations[0], id: 'created-' + (++created), title: '新对话', super_mode: Boolean(body.super_mode), updated_at: now + created };
      conversations.unshift(conversation); workspace(conversation.id).enabled = conversation.super_mode;
      return json(res, { conversation }, 201);
    }
    return json(res, { conversations });
  }
  if (/^\/api\/conversations\/[^/]+\/messages$/.test(p)) {
    if (req.method === 'POST') {
      res.writeHead(200, { 'Content-Type': 'text/event-stream' });
      res.write('data: ' + JSON.stringify({ type: 'super_status', status: 'checking', message: '正在核对本单要求与交付稿。' }) + '\n\n');
      await new Promise(resolve => setTimeout(resolve, 350));
      const events = [
        { choices: [{ delta: { content: '正文：核对完成后交付的本地模拟稿件。' } }] },
        { type: 'message_saved', message_id: 21, generation_status: 'completed', usage: { prompt_tokens: 30, completion_tokens: 20, total_tokens: 50 }, super_check: { status: 'failed', notice: '部分辅助调用未返回用量。', issues: [], repaired: false, usage_unknown: true } }
      ];
      return res.end(events.map(event => 'data: ' + JSON.stringify(event) + '\n\n').join('') + 'data: [DONE]\n\n');
    }
    return json(res, { messages: [{ id: 20, role: 'assistant', content: '正文：本地口播稿，展示客户终稿保存入口。', created_at: now, usage: { total_tokens: 80 }, super_check: { status: 'passed', notice: '本地模拟校验完成。', issues: [], repaired: false } }] });
  }
  if (/^\/api\/conversations\/[^/]+\/stats$/.test(p)) return json(res, { stats: { total_tokens: 80, prompt_tokens: 50, completion_tokens: 30 } });
  if (/^\/api\/conversations\/[^/]+\/documents$/.test(p)) { if (req.method !== 'GET') counts.bind++; return json(res, { documents: [] }); }
  if (p === '/api/side-discussions') return json(res, { discussions: [] });
  if (p === '/api/documents/upload-policy') return json(res, { policy: { allowed_extensions: ['.docx', '.doc', '.pdf'], max_size: 50 * 1024 * 1024, key_prefix: 'fixture/', access_key_id: 'fake', policy: 'fake', signature: 'fake', host: base + '/fake-oss' } });
  if (p === '/fake-oss') { res.writeHead(200); return res.end(); }
  if (p === '/api/documents' && req.method === 'POST') { counts.document++; return json(res, { document: { id: 'local-document', status: 'processing' } }, 201); }
  if (p === '/api/documents/local-document/refresh') return json(res, { document: { id: 'local-document', status: 'completed' } });
  const fixtures = {
    '/api/me': { authenticated: true, user: { id: 'default', username: 'admin', role: 'admin' } },
    '/api/models': { models: [model] }, '/api/features': { features: {} }, '/api/health': { ok: true },
    '/api/version': { version: fs.readFileSync(path.join(root, 'VERSION'), 'utf8').trim(), build_id: 'fixture' },
    '/api/search-config': { search: { enabled: false } }, '/api/tts/config': { tts: { enabled: false } },
    '/api/usage-time/config': { server_now_ms: Date.now(), idle_ms: 120000 }, '/api/usage-time/heartbeat': { credited_ms: 0 },
    '/api/profiles': { profiles: [], totals: {} }, '/api/prompts': { prompts: [] }, '/api/favorites': { favorites: [] },
    '/api/sms-login/config': { sms_auth: { configured: false } }, '/api/session/device-info': { ok: true }
  };
  if (fixtures[p]) return json(res, fixtures[p]);
  if (p.startsWith('/api/')) return json(res, { error: 'undefined fixture' }, 501);
  const file = path.resolve(root, p === '/' ? 'ai.html' : p.slice(1));
  if (!file.startsWith(root + '/') || !fs.existsSync(file) || !fs.statSync(file).isFile()) return json(res, {}, 404);
  res.writeHead(200, { 'Content-Type': ({ '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.png': 'image/png', '.svg': 'image/svg+xml' })[path.extname(file)] || 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  base = 'http://127.0.0.1:' + server.address().port;
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
    await context.route('https://**', route => route.abort());
    const page = await context.newPage(), errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto(base);
    try { await page.waitForFunction(() => state.currentConversation?.id === 'a' && !document.querySelector('#superModeToggle').disabled, null, { timeout: 12000 }); }
    catch (error) { console.error('启动状态', await page.evaluate(() => ({ authed: state.authed, user: state.user?.id, conversation: state.currentConversation?.id, super: typeof MeimeiSuper, body: document.querySelector('#chatStatus')?.textContent })), errors); throw error; }
    const mode = page.locator('#superModeToggle');
    assert.equal(await mode.getAttribute('aria-pressed'), 'false');
    assert.equal(await page.locator('.super-writing-check').count(), 1);
    const renderedChecks = await page.evaluate(() => {
      const wrap = document.createElement('div');
      wrap.innerHTML = '<div class="bubble-shell"></div>';
      document.body.append(wrap);
      const checks = [
        { status: 'passed', deterministic_issues: ['正文超过要求字数。', '正文超过要求字数。'], issues: ['正文超过要求字数。', { reason: '正文超过要求字数。' }, { quote: '原句', reason: '需要核对本单条件', source_quote: '仅限指定版本' }] },
        { status: 'failed', deterministic_issues: ['正文超过要求字数。'], issues: [] },
        { status: 'reviewed', deterministic_issues: [], issues: [], body_status: 'recognized', body_scope: 'body', body_chars: [710, 878], sections: [{ kind: 'cover' }, { kind: 'publication' }, { kind: 'body' }, { kind: 'body' }], length_requirement: { mode: 'approx', target_chars: 750, source_quote: '正文约750字' } },
        { status: 'issues', repaired: true, deterministic_issues: ['仍有待补数据。'], issues: [] },
        { status: 'reviewed', deterministic_issues: [], issues: [], body_status: 'unrecognized', body_chars: [], count_notice: '正文边界不明确，本轮未检查正文字数。' },
        { status: 'reviewed', deterministic_issues: [], issues: [], body_status: 'plain', body_chars: [710], length_requirement: { mode: 'approx', min_chars: 650, max_chars: 700, target_chars: 0 } },
        { status: 'reviewed', deterministic_issues: [], issues: [], body_status: 'recognized', body_scope: 'dialogue', body_chars: [100, 200], count_notice: '按表统计台词；未执行单篇字数范围检查。' },
        { status: 'issues', deterministic_issues: [], issues: [{ kind: 'added_claim', quote: '维修师傅家里都用它。', reason: '新增第三方自用背书。', evidence_status: 'not_in_material', source_quote: '额定容量8L。', grounded: false }], coverage: { covered_units: 3, total_units: 4 }, secondary_review: { attempted: true, status: 'completed' } },
        { status: 'failed', issues: [], deterministic_issues: [], secondary_review: { attempted: true, status: 'failed' }, usage_unknown: true },
        { status: 'issues', issues: [{ quote: '购买后就能免费更换。', reason: '遗漏30天内且有质量问题的条件。', source_quote: '购买后30天内质量问题可免费更换。' }], deterministic_issues: [], review_complete: false, secondary_review: { attempted: true, status: 'incomplete' } },
        { status: 'reviewed', issues: [], deterministic_issues: [], review_complete: true, review_method: 'single_pass' },
        { status: 'failed', issues: [], deterministic_issues: [], review_complete: false, review_method: 'single_pass', usage_unknown: true }
      ];
      const results = checks.map(check => {
        MeimeiSuper.renderCheck(wrap, { super_check: check });
        return { summary: wrap.querySelector('summary').textContent, issues: [...wrap.querySelectorAll('li')].map(line => line.textContent),
          count: wrap.querySelector('.super-writing-count')?.textContent || '', sections: wrap.querySelector('.super-writing-sections')?.textContent || '', scope: wrap.querySelector('.super-writing-scope')?.textContent || '', coverage: wrap.querySelector('.super-writing-coverage')?.textContent || '', secondary: wrap.querySelector('.super-writing-secondary')?.textContent || '', single: wrap.querySelector('.super-writing-single')?.textContent || '' };
      });
      wrap.remove();
      return results;
    });
    assert.match(renderedChecks[0].summary, /有待确认内容/);
    assert.deepEqual(renderedChecks[0].issues, ['规则检查：正文超过要求字数。', '模型待核对：原句；需要核对本单条件；依据：仅限指定版本']);
    assert.match(renderedChecks[1].summary, /本轮未完成检查/);
    assert.match(renderedChecks[2].summary, /本轮有限检查已完成/);
    assert.doesNotMatch(renderedChecks[2].summary, /通过|验收/);
    assert.match(renderedChecks[2].count, /第1篇 710 字；第2篇 878 字/);
    assert.match(renderedChecks[2].count, /目标约750字，仅作参考/);
    assert.match(renderedChecks[2].sections, /封面\/标题 1 项 · 发布文案 1 项 · 正文 2 项/);
    assert.match(renderedChecks[2].scope, /自然度、观点和广告感不作代码判定/);
    assert.match(renderedChecks[3].summary, /已作局部修复，仍有待确认内容/);
    assert.match(renderedChecks[4].summary, /正文计数未完成/);
    assert.match(renderedChecks[4].count, /未检查正文字数/);
    assert.match(renderedChecks[5].count, /参考约650–700字，不按固定上下限判定/);
    assert.doesNotMatch(renderedChecks[5].count, /约0字/);
    assert.match(renderedChecks[6].count, /第1表 100 字；第2表 200 字/);
    assert.match(renderedChecks[6].count, /未执行单篇字数范围检查/);
    assert.match(renderedChecks[7].issues[0], /模型未在本单材料中找到该主张的依据，需确认/);
    assert.match(renderedChecks[7].issues[0], /这不等于事实虚假/);
    assert.doesNotMatch(renderedChecks[7].issues[0], /依据：/);
    assert.match(renderedChecks[7].issues[0], /相关材料：额定容量8L/);
    assert.match(renderedChecks[7].coverage, /覆盖记录：3\/4/);
    assert.match(renderedChecks[7].coverage, /不代表判断正确/);
    assert.match(renderedChecks[7].secondary, /二次事实复核已结束，模型判断仍待核对/);
    assert.match(renderedChecks[7].secondary, /两阶段已返回的模型用量均计入当前对话/);
    assert.match(renderedChecks[8].secondary, /未完整完成/);
    assert.match(renderedChecks[8].secondary, /未返回的用量会标记未知/);
    assert.match(renderedChecks[9].summary, /有待确认内容/);
    assert.match(renderedChecks[9].issues[0], /遗漏30天内且有质量问题的条件/);
    assert.match(renderedChecks[9].secondary, /未完整完成/);
    assert.doesNotMatch(renderedChecks[9].summary + renderedChecks[9].secondary, /全部正确|已验收|检查已完成/);
    assert.match(renderedChecks[10].summary, /本次复检已返回/);
    assert.match(renderedChecks[10].single, /一次 Flash 复检/);
    assert.match(renderedChecks[10].single, /不代表逐句覆盖或事实全部正确/);
    assert.match(renderedChecks[10].single, /模型用量计入当前对话/);
    assert.equal(renderedChecks[10].coverage, '');
    assert.equal(renderedChecks[10].secondary, '');
    assert.match(renderedChecks[11].summary, /未完成检查/);
    assert.match(renderedChecks[11].single, /一次 Flash 复检/);
    assert.equal(renderedChecks[11].secondary, '');
    await page.locator('#prompt').fill('开关不能清空的草稿');
    await mode.click();
    await page.waitForFunction(() => document.querySelector('#superModeToggle').getAttribute('aria-pressed') === 'true' && !document.querySelector('#superModeToggle').disabled);
    assert.equal(await page.locator('#prompt').inputValue(), '开关不能清空的草稿');
    await page.evaluate(() => selectConversation('b'));
    await page.waitForFunction(() => state.currentConversation?.id === 'b' && !document.querySelector('#superModeToggle').disabled);
    assert.equal(await mode.getAttribute('aria-pressed'), 'false');
    await page.evaluate(() => selectConversation('a'));
    await page.waitForFunction(() => state.currentConversation?.id === 'a' && !document.querySelector('#superModeToggle').disabled);
    assert.equal(await mode.getAttribute('aria-pressed'), 'true');
    await page.reload();
    await page.waitForFunction(() => state.currentConversation?.id === 'a' && !document.querySelector('#superModeToggle').disabled);
    assert.equal(await mode.getAttribute('aria-pressed'), 'true');
    await page.locator('#openFinalDelivery').click();
    await page.waitForFunction(() => document.querySelector('#finalDeliveryDialog').open);
    assert.match(await page.locator('#finalDeliverySource').textContent(), /历史推定稿/);
    assert.match(await page.locator('#finalDeliveryReferenceNote').textContent(), /本单版本管理与复盘，暂不自动参考其他任务/);
    await page.locator('#finalDeliveryContent').fill('客户已通过的第一版终稿。');
    await page.locator('#saveFinalDelivery').click();
    await page.waitForFunction(() => document.querySelector('#finalDeliveryStatus').textContent.includes('客户确认稿已保存'));
    assert.equal(await page.locator('#finalDeliverySource').textContent(), '客户确认稿');
    assert.match(await page.locator('#finalDeliveryReferenceNote').textContent(), /暂不自动参考其他任务/);
    await page.locator('#finalDeliveryContent').fill('客户已通过的第二版终稿。');
    await page.locator('#saveFinalDelivery').click();
    await page.waitForFunction(() => document.querySelector('#finalDeliveryVersions').options.length === 3);
    await page.locator('#finalDeliveryVersions').selectOption('1');
    assert.equal(await page.locator('#finalDeliveryContent').inputValue(), '客户已通过的第一版终稿。');
    assert.equal(workspace('a').delivery.content, '客户已通过的第二版终稿。');
    conflict = true;
    await page.locator('#finalDeliveryContent').fill('冲突之后仍须保留的终稿。');
    await page.locator('#saveFinalDelivery').click();
    await page.waitForFunction(() => document.querySelector('#finalDeliveryStatus').textContent.includes('其他页面更新'));
    assert.equal(await page.locator('#finalDeliveryContent').inputValue(), '冲突之后仍须保留的终稿。');
    await page.locator('#saveFinalDelivery').click();
    await page.waitForFunction(() => document.querySelector('#finalDeliveryStatus').textContent.includes('客户确认稿已保存'));
    await page.locator('#finalDeliveryFile').setInputFiles({ name: '客户终稿.txt', mimeType: 'text/plain', buffer: Buffer.from('从文件导入的客户终稿。') });
    await page.waitForFunction(() => document.querySelector('#finalDeliveryContent').value === '从文件导入的客户终稿。');
    await page.locator('#saveFinalDelivery').click();
    await page.waitForFunction(() => document.querySelector('#finalDeliveryStatus').textContent.includes('客户确认稿已保存'));
    assert.equal(workspace('a').delivery.filename, '客户终稿.txt');
    await page.locator('#finalDeliveryFile').setInputFiles({ name: '客户终稿.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', buffer: Buffer.from('local fixture') });
    await page.waitForFunction(() => document.querySelector('#finalDeliveryStatus').textContent.includes('文件已解析'));
    await page.locator('#saveFinalDelivery').click();
    await page.waitForFunction(() => document.querySelector('#finalDeliveryContent').value === '客户已接受的 Word 终稿正文。');
    assert.equal(counts.document, 1); assert.equal(counts.bind, 0);
    assert.equal(counts.final.at(-1).body.document_id, 'local-document');
    await page.screenshot({ path: '/private/tmp/meimei-super-delivery-desktop.png' });
    await page.locator('#closeFinalDelivery').click();
    await page.locator('#prompt').fill('写一条新的口播稿');
    await page.locator('#send').click();
    await page.waitForFunction(() => document.querySelector('#chatStatus').textContent.includes('正在核对本单要求'));
    await page.waitForFunction(() => !state.sending);
    assert.match(await page.locator('.super-writing-check').last().textContent(), /部分调用未返回用量/);
    await page.evaluate(() => setSendingUI(true));
    assert.equal(await mode.isDisabled(), true); assert.equal(await page.locator('#openFinalDelivery').isDisabled(), true);
    await page.evaluate(() => setSendingUI(false));
    await mode.click(); await page.waitForFunction(() => !document.querySelector('#superModeToggle').disabled && document.querySelector('#superModeToggle').getAttribute('aria-pressed') === 'false');
    assert.match(await page.locator('#chatStatus').textContent(), /原流程/);
    const before = counts.super;
    await page.evaluate(() => { applyCurrentUser({ id: 'other', username: 'other', role: 'admin' }); updateChatHeader(); });
    assert.equal(await mode.isVisible(), false); assert.equal(await page.locator('#openFinalDelivery').isVisible(), false);
    await page.waitForTimeout(100); assert.equal(counts.super, before);
    await page.evaluate(() => { applyCurrentUser({ id: 'default', username: 'admin', role: 'admin' }); updateChatHeader(); });
    await page.waitForFunction(() => !document.querySelector('#superModeToggle').disabled);
    delayPatch = 250;
    await mode.click();
    await page.evaluate(() => selectConversation('b'));
    await page.waitForFunction(() => state.currentConversation?.id === 'b' && !document.querySelector('#superModeToggle').disabled);
    await page.waitForTimeout(350);
    assert.equal(await mode.getAttribute('aria-pressed'), 'false');
    delayPatch = 0;
    await page.evaluate(() => { beginConversationTransition(); state.currentConversation = null; state.messages = []; renderEmpty(); });
    await mode.click(); assert.equal(await mode.getAttribute('aria-pressed'), 'true');
    await page.evaluate(() => newConversation('mock'));
    await page.waitForFunction(() => state.currentConversation?.id?.startsWith('created-') && !document.querySelector('#superModeToggle').disabled);
    assert.equal(counts.create.at(-1).super_mode, true);
    await page.evaluate(() => newConversation('mock'));
    await page.waitForFunction(() => !document.querySelector('#superModeToggle').disabled);
    assert.equal(counts.create.at(-1).super_mode, false);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => closeSidebar());
    await page.waitForTimeout(250);
    await page.screenshot({ path: '/private/tmp/meimei-super-composer-mobile.png' });
    assert.equal(await mode.isVisible(), true);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    assert.equal(overflow, false);
    await page.locator('#openFinalDelivery').click();
    await page.waitForFunction(() => document.querySelector('#finalDeliveryDialog').open);
    await page.screenshot({ path: '/private/tmp/meimei-super-delivery-mobile.png' });
    assert.equal(await page.evaluate(() => document.querySelector('#finalDeliveryDialog').scrollWidth > document.querySelector('#finalDeliveryDialog').clientWidth + 1), false);
    await page.locator('#finalDeliveryContent').fill('手机端回传客户已接受的完整终稿。');
    await page.locator('#saveFinalDelivery').click();
    await page.waitForFunction(() => document.querySelector('#finalDeliveryStatus').textContent.includes('客户确认稿已保存'));
    assert.equal(workspace(conversations[0].id).delivery.content, '手机端回传客户已接受的完整终稿。');
    assert.deepEqual(errors, []);
    console.log('超能模式 UI 回归通过：检查问题合并去重/有限检查状态/本单终稿说明/开关隔离/刷新/原流程/终稿更新/冲突/文本和文档上传/账号隔离/迟到响应/桌面与手机布局。');
  } finally {
    await browser.close(); await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; server.close(); });
