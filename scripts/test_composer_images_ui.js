#!/usr/bin/env node
'use strict';
// Run the real page and upload client over loopback HTTP; never contact models or OSS.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const png = fs.readFileSync(path.join(root, 'res/meimei-avatar.png'));
const models = [
  { id: 'vision', name: '图片模型', model: 'fixture-vision', supports_vision: true },
  { id: 'text', name: '文字模型', model: 'fixture-text', supports_vision: false }
].map(model => ({ ...model, provider: 'local', enabled: true }));
const counts = { policies: 0, oss: 0, saved: 0, documents: 0, sends: [], unexpected: [] };
let failOss = false, delayOss = 0, ossGate = null, base;
const conversations = [];
const messages = new Map();
function json(res, body, status = 200) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(body));
}
const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, base), pathname = url.pathname;
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const raw = Buffer.concat(chunks);
    const data = raw.length && req.headers['content-type']?.includes('application/json') ? JSON.parse(raw) : {};
    if (pathname === '/fake-oss') {
      counts.oss++;
      const fail = failOss; failOss = false;
      assert.ok(raw.includes(Buffer.from('name="key"')) && raw.includes(Buffer.from('name="file"')));
      if (delayOss) await new Promise(resolve => setTimeout(resolve, delayOss));
      if (ossGate) await ossGate;
      res.writeHead(fail ? 503 : 200, { 'Content-Type': 'text/html' }); res.end(fail ? '<p>Simulated storage unavailable</p>' : ''); return;
    }
    if (pathname === '/api/chat-images/upload-policy') {
      counts.policies++;
      return json(res, { policy: { host: base + '/fake-oss', max_size: 20 * 1024 * 1024, key_prefix: 'test/images/', access_key_id: 'fixture', policy: 'fixture', signature: 'fixture' } });
    }
    if (pathname === '/api/chat-images') {
      counts.saved++;
      return json(res, { image: { id: 'image-' + counts.saved, filename: data.filename, view_url: base + '/fixture.png' } }, 201);
    }
    if (pathname === '/api/documents/upload-policy') return json(res, { policy: { host: base + '/fake-oss', max_size: 50 * 1024 * 1024, allowed_extensions: ['.txt', '.pdf', '.docx'], key_prefix: 'test/documents/', access_key_id: 'fixture', policy: 'fixture', signature: 'fixture' } });
    if (pathname === '/api/documents' && req.method === 'POST') {
      counts.documents++;
      return json(res, { document: { id: 'document-' + counts.documents, filename: data.filename, status: 'completed', chunk_count: 1, file_size: data.file_size } }, 201);
    }
    if (pathname === '/fixture.png') { res.writeHead(200, { 'Content-Type': 'image/png' }); res.end(png); return; }
    if (pathname === '/api/me') return json(res, { authenticated: true, user: { id: 'paste-fixture', username: 'fixture', display_name: '本地测试', role: 'family' } });
    if (pathname === '/api/models') return json(res, { models });
    if (pathname === '/api/features') return json(res, { features: { selection_quote: true, side_discussion: false, long_text_detection: true } });
    if (pathname === '/api/version') return json(res, { version: fs.readFileSync(path.join(root, 'VERSION'), 'utf8').trim(), build_id: 'clipboard-fixture' });
    if (pathname === '/api/health') return json(res, { status: 'ok' });
    if (pathname === '/api/search-config') return json(res, { search: { enabled: false, mode: 'manual' } });
    if (pathname === '/api/tts/config') return json(res, { tts: { configured: false, enabled: false, voices: [] } });
    if (pathname === '/api/profiles') return json(res, { profiles: [], totals: {} });
    if (pathname === '/api/prompts') return json(res, { prompts: [] });
    if (pathname === '/api/favorites') return json(res, { favorites: [] });
    if (pathname === '/api/sms-login/config') return json(res, { sms_auth: { configured: false } });
    if (pathname === '/api/usage-time/config') return json(res, { server_now_ms: Date.now(), idle_ms: 120000 });
    if (pathname === '/api/usage-time/heartbeat') return json(res, { credited_ms: 0 });
    if (pathname === '/api/conversations') {
      if (req.method === 'POST') {
        const model = models.find(model => model.id === data.model_id);
        const conversation = { ...model, id: 'conversation-' + conversations.length, model_id: model.id, model_name: model.name, title: '本地图片测试', created_at: Date.now() / 1000, updated_at: Date.now() / 1000 };
        conversations.push(conversation); messages.set(conversation.id, []);
        return json(res, { conversation }, 201);
      }
      return json(res, { conversations });
    }
    const match = /^\/api\/conversations\/([^/]+)(.*)$/.exec(pathname);
    if (match) {
      const conversation = conversations.find(item => item.id === match[1]);
      if (req.method === 'PATCH') {
        const model = models.find(model => model.id === data.model_id);
        Object.assign(conversation, { model_id: model.id, model_name: model.name, supports_vision: model.supports_vision });
        return json(res, { conversation });
      }
      if (match[2] === '/messages' && req.method === 'POST') {
        counts.sends.push(data);
        const list = messages.get(conversation.id);
        list.push({ id: list.length + 1, role: 'user', content: data.content, images: (data.image_ids || []).map(id => ({ id, view_url: base + '/fixture.png' })), created_at: Date.now() / 1000 });
        const reply = { id: list.length + 1, role: 'assistant', content: '本地流式回答正常。', generation_status: 'completed', created_at: Date.now() / 1000 };
        res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store' });
        res.write('data: ' + JSON.stringify({ choices: [{ delta: { content: reply.content }, finish_reason: null }] }) + '\n\n');
        await new Promise(resolve => setTimeout(resolve, 250));
        list.push(reply);
        res.end('data: ' + JSON.stringify({ type: 'message_saved', message_id: reply.id, generation_status: 'completed', usage: {}, sources: [] }) + '\n\n'); return;
      }
      if (match[2] === '/messages') return json(res, { messages: messages.get(match[1]) || [] });
      if (match[2] === '/stats') return json(res, { stats: {} });
      if (match[2] === '/documents') return json(res, { documents: [] });
      if (match[2] === '/side-discussions') return json(res, { discussions: [] });
    }
    if (pathname.startsWith('/api/')) {
      if (req.method === 'POST') { counts.unexpected.push(pathname); if (pathname.startsWith('/api/documents')) counts.documents++; }
      return json(res, { error: 'Fixture endpoint not defined' }, 501);
    }
    const relative = pathname === '/' ? 'ai.html' : pathname.slice(1);
    const file = path.resolve(root, relative);
    if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) return json(res, {}, 404);
    const types = { '.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2' };
    res.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream' }); fs.createReadStream(file).pipe(res);
  } catch (error) { counts.unexpected.push(String(error)); if (!res.headersSent) json(res, { error: 'Fixture failure' }, 500); else res.end(); }
});

async function paste(page, options = {}) {
  return page.evaluate(({ image, options }) => {
    const data = new DataTransfer();
    if (options.text) data.setData('text/plain', options.text);
    for (let i = 0; i < (options.count ?? 1); i++) {
      const bytes = options.oversized ? new Uint8Array(20 * 1024 * 1024 + 1) : Uint8Array.from(atob(image), ch => ch.charCodeAt(0));
      data.items.add(new File([bytes], options.name ?? 'clipboard.png', { type: options.type || 'image/png' }));
    }
    const clipboard = options.filesOnly ? { files: data.files, items: [], getData: key => data.getData(key) } : data;
    const event = new ClipboardEvent('paste', { bubbles: true, cancelable: true });
    Object.defineProperty(event, 'clipboardData', { value: clipboard });
    document.querySelector(options.target || '#prompt').dispatchEvent(event);
    return event.defaultPrevented;
  }, { image: png.toString('base64'), options });
}
async function ready(page, count = 1) {
  await page.waitForFunction(count => state.attachments.length === count && state.attachments.every(item => item.status === 'ready') && !state.uploadingImages, count);
}
async function clear(page) { await page.evaluate(() => clearAttachments()); }
async function model(page, id) { await page.evaluate(id => chooseModel(id), id); }

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve)); base = 'http://127.0.0.1:' + server.address().port;
  const output = fs.mkdtempSync(path.join(os.tmpdir(), 'aimeimei-clipboard-'));
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const checks = [];
  try {
    for (const width of [1440, 390]) {
      const context = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 960 }, isMobile: width === 390, hasTouch: width === 390 });
      await context.route('https://**', route => route.abort());
      const page = await context.newPage(), errors = [];
      page.on('pageerror', error => errors.push(String(error)));
      await page.goto(base); await page.waitForFunction(() => state.authed && state.models.length === 2);
      await page.waitForFunction(() => document.querySelector('#appView').hidden === false);
      await page.evaluate(() => {
        const upload = handleImageFiles;
        window.clipboardUploadTasks = [];
        handleImageFiles = (...args) => { const pending = upload(...args); window.clipboardUploadTasks.push(pending); return pending; };
      });
      const start = counts.saved;
      await page.locator('#prompt').fill('原草稿');
      assert.equal(await paste(page, { count: 0, text: '普通文字' }), false);
      assert.equal(counts.saved, start);
      await model(page, 'text');
      assert.equal(await page.locator('#attachImage').isEnabled(), true);
      assert.equal(await paste(page), true); await ready(page);
      assert.equal(counts.saved, start + 1, 'items/files must not upload the same image twice');
      assert.equal(await page.locator('#send').isDisabled(), true);
      if (!await page.locator('#imageModelWarning').isVisible()) console.log('warning geometry', width, await page.locator('#imageModelWarning').evaluate(node => ({ hidden: node.hidden, text: node.textContent, display: getComputedStyle(node).display, height: node.getBoundingClientRect().height, parent: node.parentElement.className })));
      assert.equal(await page.locator('#imageModelWarning').isVisible(), true);
      assert.equal(await page.locator('#prompt').inputValue(), '原草稿');
      const sent = counts.sends.length;
      await page.locator('#prompt').press('Enter');
      await page.evaluate(() => sendMessage());
      assert.equal(counts.sends.length, sent, 'hotkey/programmatic send must still be blocked');
      await page.screenshot({ path: path.join(output, `nonvision-${width}.png`) });
      await model(page, 'vision');
      assert.equal(await page.locator('#send').isEnabled(), true);
      assert.equal(await page.locator('#imageModelWarning').isVisible(), false);
      await page.locator('#send').click();
      await page.waitForFunction(() => state.sending);
      assert.equal(await page.locator('#send').isEnabled(), true, 'stop remains available');
      await page.waitForFunction(() => !state.sending && !state.sendAttempt);
      assert.equal(counts.sends.length, sent + 1);
      assert.equal(counts.sends.at(-1).image_ids.length, 1);
      assert.equal(await page.locator('#attachmentPreviewRow').isVisible(), false);
      checks.push(`paste/block/model-switch/stream-${width}`);
      // Start a fresh draft, so model switching does not require confirmation about history.
      await page.evaluate(async () => { await newConversation('text'); });
      const chooser = page.waitForEvent('filechooser'); await page.locator('#attachImage').click();
      await (await chooser).setFiles({ name: 'picker.png', mimeType: 'image/png', buffer: png }); await ready(page);
      await page.locator('#attachmentPreviewRow .attachment-remove').click();
      assert.equal(await page.locator('#send').isEnabled(), true);
      const uploads = counts.policies;
      await paste(page, { count: 6 }); await paste(page, { oversized: true }); await paste(page, { name: 'bad.gif', type: 'image/gif' });
      assert.equal(counts.policies, uploads); assert.equal(await page.evaluate(() => state.attachments.length), 0);
      delayOss = 250;
      await paste(page, { count: 2 }); await paste(page, { count: 2 });
      await ready(page, 4); delayOss = 0;
      const limited = counts.policies;
      await paste(page, { count: 2 });
      assert.equal(counts.policies, limited);
      await paste(page); await ready(page, 5);
      assert.equal(await page.locator('#attachmentPreviewRow .attachment-preview').count(), 5);
      assert.equal(await page.locator('#send').isDisabled(), true);
      await clear(page);
      failOss = true; await paste(page);
      await page.waitForFunction(() => state.attachments[0]?.status === 'error' && !state.uploadingImages);
      await clear(page); await paste(page, { filesOnly: true, name: '' }); await ready(page);
      assert.match(await page.evaluate(() => state.attachments[0].filename), /\.png$/);
      await clear(page);
      const saved = counts.saved; let releaseOss; ossGate = new Promise(resolve => { releaseOss = resolve; });
      await paste(page); await page.locator('#attachmentPreviewRow .attachment-remove').click();
      assert.equal(await page.evaluate(() => state.uploadingImages), false);
      releaseOss(); ossGate = null;
      await page.evaluate(() => Promise.all(window.clipboardUploadTasks));
      assert.equal(counts.saved, saved); assert.equal(await page.evaluate(() => state.attachments.length), 0);
      checks.push(`picker/limits/concurrency/failure/remove-${width}`);
      if (width === 1440) {
        await page.locator('#prompt').fill('前文 后文');
        await page.locator('#openFullComposer').click();
        await page.locator('#fullComposerPrompt').evaluate(input => input.setSelectionRange(3, 3));
        await paste(page, { target: '#fullComposerPrompt', text: '插入文字', name: '' }); await ready(page);
        assert.equal(await page.locator('#fullComposerPrompt').inputValue(), '前文 插入文字后文');
        assert.equal(await page.locator('#fullComposerAttachmentPreviewRow .attachment-preview').count(), 1);
        assert.equal(await page.locator('#fullComposerImageWarning').isVisible(), true);
        await page.waitForTimeout(250);
        await page.screenshot({ path: path.join(output, 'full-composer.png') });
        await page.locator('#closeFullComposer').click();
        assert.equal(await page.locator('#prompt').inputValue(), '前文 插入文字后文');
        await clear(page);
        const old = await page.evaluate(() => state.user);
        const previousSaved = counts.saved; ossGate = new Promise(resolve => { releaseOss = resolve; }); await paste(page);
        await page.waitForFunction(() => state.uploadingImages);
        await page.evaluate(() => { state.user = { id: 'another-fixture' }; clearAttachments(); });
        releaseOss(); ossGate = null;
        await page.evaluate(() => Promise.all(window.clipboardUploadTasks));
        assert.equal(counts.saved, previousSaved);
        await page.evaluate(user => { state.user = user; }, old);
        checks.push('full-composer/mixed-text/account-isolation');
      }
      const previousDocuments = counts.documents;
      await page.evaluate(image => {
        const data = new DataTransfer();
        data.items.add(new File([Uint8Array.from(atob(image), ch => ch.charCodeAt(0))], 'dropped.png', { type: 'image/png' }));
        document.querySelector('#composerBox').dispatchEvent(new DragEvent('drop', { dataTransfer: data, bubbles: true, cancelable: true }));
      }, png.toString('base64'));
      await ready(page);
      assert.equal(counts.documents, previousDocuments, 'dropped images must not silently use OCR');
      await page.evaluate(() => {
        const first = document.querySelector('#messages').firstElementChild;
        window.clipboardHistoryNode = first;
      });
      await paste(page); await ready(page, 2);
      assert.equal(await page.evaluate(() => document.querySelector('#messages').firstElementChild === window.clipboardHistoryNode), true);
      await clear(page);
      await page.locator('#documentInput').setInputFiles({ name: 'existing.txt', mimeType: 'text/plain', buffer: Buffer.from('原材料上传保持可用') });
      await page.waitForFunction(() => !state.uploadingDocuments && state.documentAttachments.length === 1);
      assert.equal(counts.documents, previousDocuments + 1);
      checks.push(`drag/material/history-node-${width}`);
      await page.locator('#themeToggle').click();
      await page.locator('#prompt').fill('AA BB');
      await page.locator('#prompt').evaluate(input => input.setSelectionRange(2, 2));
      await paste(page, { text: '插入', name: '', type: 'image/jpeg' }); await ready(page);
      assert.equal(await page.locator('#prompt').inputValue(), 'AA插入 BB');
      assert.match(await page.evaluate(() => state.attachments[0].filename), /\.jpg$/);
      assert.equal(await page.locator('#imageModelWarning').isVisible(), true);
      await page.screenshot({ path: path.join(output, `nonvision-dark-${width}.png`) });
      const sendBounds = await page.locator('#send').boundingBox();
      assert.ok(sendBounds.x >= 0 && sendBounds.x + sendBounds.width <= width);
      await clear(page);
      checks.push(`mixed-text/jpeg-name/dark-${width}`);
      const intercepted = await page.evaluate(() => {
        const data = new DataTransfer(); data.items.add(new File(['x'], 'outside.png', { type: 'image/png' }));
        const event = new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true });
        document.querySelector('#globalSearchInput').dispatchEvent(event); return event.defaultPrevented;
      });
      assert.equal(intercepted, false);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
      assert.equal(overflow, false);
      assert.deepEqual(errors, []);
      await context.close();
    }
    assert.equal(counts.documents, 2, 'only the two explicit material selections should use document parsing');
    assert.deepEqual(counts.unexpected, []);
    console.log(JSON.stringify({ checks, counts, screenshots: output }, null, 2));
  } finally { await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); process.exitCode = 1; server.closeAllConnections(); server.close(); });
