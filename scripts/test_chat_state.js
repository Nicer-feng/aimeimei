#!/usr/bin/env node
'use strict';
// Exercise the actual frontend functions with deterministic network ordering, without accounts or models.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../res/ai.js'), 'utf8');
const functions = [
  'conversationContext', 'isCurrentConversation', 'beginConversationTransition', 'isCurrentGeneration',
  'newConversation', 'selectConversation', 'loadConversations', 'loadConversationStats',
  'loadConversationDocuments', 'loadSideDiscussions', 'sendMessage', 'stopGeneration',
  'readChatEvents', 'generationStatusLabel', 'generationEmptyText', 'resetStreamState',
  'resolveStreamDrain', 'drainAssistantQueue', 'enqueueAssistantText', 'scheduleStreamTick',
  'streamTick', 'streamChunkSize', 'setSendingUI', 'logout', 'closeSideDiscussion',
  'openSideDiscussion', 'sendSideDiscussionMessage', 'readChatFailure', 'createSideDiscussionFromSelection'
];
function extract(name) {
  const match = new RegExp('(?:async )?function ' + name + '\\(').exec(source);
  assert.ok(match, name + ' exists');
  const tail = source.slice(match.index);
  const next = /\n[\t ]*(?:async )?function \w+\(/.exec(tail.slice(1));
  return tail.slice(0, next ? next.index + 1 : undefined);
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((a, b) => { resolve = a; reject = b; });
  return { promise, resolve, reject };
}
const tick = () => new Promise(resolve => setImmediate(resolve));
const response = data => ({ ok: true, json: async () => data });
function harness() {
  const elements = new Map();
  const state = {
    user: { id: 'test-user' }, authed: true, conversationEpoch: 0, conversationListSeq: 0,
    currentConversation: { id: 'A', model_id: 'model' }, conversations: [
      { id: 'A', model_id: 'model' }, { id: 'B', model_id: 'model' }
    ], models: [{ id: 'model' }], messages: [], pendingQuotes: [], attachments: [],
    documentAttachments: [], persistentDocuments: [], sideDiscussions: [], sideDiscussionMessages: [], streamQueue: '',
    profiles: [], profileDisabledByConversation: {}, searchConfig: {}, streamTimer: null
  };
  const calls = [], paints = [], statuses = [];
  const context = { state, console, setTimeout, clearTimeout, AbortController, DOMException,
    TextDecoder, TextEncoder, performance, Date, Map, Set, Promise, Number,
    document: { hidden: false, body: { classList: { add() {}, remove() {} } } }, localStorage: { removeItem() {} },
    requestAnimationFrame: fn => setTimeout(fn, 0), cancelAnimationFrame: clearTimeout,
    $: id => {
      if (!elements.has(id)) elements.set(id, { value: '', textContent: '', checked: false,
        disabled: false, style: {}, classList: { toggle() {}, add() {}, remove() {} },
        setAttribute() {}, focus() {}, replaceChildren() {} });
      return elements.get(id);
    }
  };
  for (const name of ['saveCurrentDraft', 'restoreCurrentDraft', 'clearCurrentDraft', 'stopCurrentTts',
    'closeSideDiscussion', 'closeReferenceSources', 'updateSideDiscussionEntry', 'renderDocumentPreviews',
    'renderConversationFilesButton', 'renderConversations', 'renderMessages', 'renderEmpty',
    'renderConversationLoading', 'renderConversationError', 'setUserStorage', 'updateChatHeader',
    'renderProfileStatus', 'renderProfilePopover', 'closeSidebar', 'hideConversationMinimap',
    'closeConversationFiles', 'stopReasoningClock', 'stopAssistantActivityClock', 'completeReasoning',
    'renderWritingMode', 'queueLucideRefresh', 'updateVisionUI', 'pollDocumentAttachments',
    'renderComposerQuotes', 'autosizePrompt', 'clearAttachments', 'appendMessageElements',
    'ensureAssistantActivityClock', 'renderSearchToggle', 'updateScrollLatestButton', 'updateChatUsage',
    'closeProfilePopover', 'closeProfiles', 'showLogin', 'sortConversations', 'syncComposerLayout',
    'queueConversationMinimap', 'applySideDiscussionWidth', 'renderSideDiscussionHeader',
    'renderSideDiscussionMessages', 'updateSideDiscussionStream', 'hideSelectionToolbar']) context[name] = () => {};
  context.applyCurrentUser = user => { state.user = user; };
  context.friendlyError = value => value?.message || String(value);
  context.readError = async () => '请求失败';
  context.setStatus = (id, text) => statuses.push(text);
  context.updateStreamingMessage = message => paints.push({ id: state.currentConversation?.id, content: message.content, status: message.generation_status });
  context.splitThinkContent = value => ({ content: value, reasoning: '' });
  context.isNearBottom = () => true;
  context.sideDiscussionEnabled = () => true;
  context.sideDiscussionAvailable = () => true;
  context.iconMarkup = name => name;
  context.getUserStorage = () => '0';
  context.userStorageKey = key => key;
  context.quoteDraftStorageKey = key => key;
  context.profileDisabledForConversation = () => false;
  context.selectedModelSupportsVision = () => true;
  context.api = async (url, options = {}) => {
    calls.push({ url, options });
    return response(url === '/api/conversations' ? { conversations: state.conversations } :
      url.endsWith('/stats') ? { stats: { id: url.split('/')[3] } } :
      url.includes('/side-discussions') ? { discussions: [] } :
      url.endsWith('/documents') ? { documents: [] } : { messages: [{ role: 'user', content: url }] });
  };
  context.request = (...args) => context.api(...args);
  vm.createContext(context);
  vm.runInContext(functions.map(extract).join('\n'), context);
  context.$('modelSelect').value = 'model';
  context.$('prompt').value = '测试消息';
  return { context, state, calls, paints, statuses, finish() { context.beginConversationTransition(); } };
}
function streaming(h, options = {}) {
  let controller;
  const stream = new ReadableStream({ start(value) { controller = value; } });
  const base = h.context.api;
  h.context.api = async (url, request = {}) => {
    if (url.endsWith('/messages') && request.method === 'POST') {
      if (options.abort !== false) request.signal.addEventListener('abort', () => {
        try { controller.error(new DOMException('Aborted', 'AbortError')); } catch {}
      });
      return { ok: true, body: stream };
    }
    return base(url, request);
  };
  return {
    event(value) { controller.enqueue(new TextEncoder().encode('data: ' + JSON.stringify(value) + '\n\n')); },
    end() { controller.close(); },
    error(error) { controller.error(error); }
  };
}
const tests = [];
function test(name, run) { tests.push([name, run]); }
test('rapid A/B selection ignores A messages arriving last', async h => {
  const pending = new Map(), base = h.context.api;
  h.context.api = (url, options) => {
    if (url.endsWith('/messages')) { const item = deferred(); pending.set(url, item); return item.promise; }
    return base(url, options);
  };
  const a = h.context.selectConversation('A'), b = h.context.selectConversation('B');
  pending.get('/api/conversations/B/messages').resolve(response({ messages: [{ content: 'B正文' }] }));
  await b;
  pending.get('/api/conversations/A/messages').resolve(response({ messages: [{ content: 'A正文' }] }));
  await a;
  assert.equal(h.state.currentConversation.id, 'B');
  assert.equal(h.state.messages[0].content, 'B正文');
});
test('old document/stat success and side-discussion failure cannot replace B state', async h => {
  const pending = new Map();
  h.context.api = url => { const item = deferred(); pending.set(url, item); return item.promise; };
  const docs = h.context.loadConversationDocuments('A'), stats = h.context.loadConversationStats('A'), side = h.context.loadSideDiscussions('A');
  h.context.beginConversationTransition(); h.state.currentConversation = { id: 'B' };
  h.state.persistentDocuments = [{ id: 'B-doc' }]; h.state.conversationStats = { id: 'B-stats' }; h.state.sideDiscussions = [{ id: 'B-side' }];
  pending.get('/api/conversations/A/documents').resolve(response({ documents: [{ id: 'A-doc' }] }));
  pending.get('/api/conversations/A/stats').resolve(response({ stats: { id: 'A-stats' } }));
  pending.get('/api/side-discussions?session_id=A').reject(new Error('Old failure'));
  await Promise.all([docs, stats, side]);
  assert.equal(h.state.persistentDocuments[0].id, 'B-doc');
  assert.equal(h.state.conversationStats.id, 'B-stats');
  assert.equal(h.state.sideDiscussions[0].id, 'B-side');
});
test('switching conversation aborts the old stream and ignores late events', async h => {
  const stream = streaming(h, { abort: false });
  const send = h.context.sendMessage(); await tick();
  stream.event({ choices: [{ delta: { content: 'A收到的正文' } }] }); await tick();
  const old = h.state.activeGeneration;
  await h.context.selectConversation('B');
  const count = h.paints.length;
  stream.event({ choices: [{ delta: { content: 'A迟到的正文' } }] }); stream.end();
  await send;
  assert.equal(old.controller.signal.aborted, true);
  assert.equal(old.message.content, 'A收到的正文');
  assert.equal(h.state.currentConversation.id, 'B');
  assert.equal(h.paints.length, count);
  assert.equal(h.state.sending, false);
});
test('stale new-conversation response cannot reopen after selecting B', async h => {
  const pending = deferred(), base = h.context.api;
  h.context.api = (url, options) => url === '/api/conversations' && options?.method === 'POST' ? pending.promise : base(url, options);
  const created = h.context.newConversation('model');
  await h.context.selectConversation('B');
  pending.resolve(response({ conversation: { id: 'C', model_id: 'model' } }));
  assert.equal(await created, null);
  assert.equal(h.state.currentConversation.id, 'B');
});
test('new conversation invalidates the previous stream', async h => {
  const stream = streaming(h), base = h.context.api;
  h.context.api = (url, options) => url === '/api/conversations' && options?.method === 'POST' ? Promise.resolve(response({ conversation: { id: 'C', model_id: 'model' } })) : base(url, options);
  const send = h.context.sendMessage(); await tick();
  await h.context.newConversation('model'); await send;
  assert.equal(h.state.currentConversation.id, 'C');
  assert.equal(h.state.messages.length, 0);
  assert.equal(h.state.sending, false);
});
test('logout aborts the stream without repopulating cleared messages', async h => {
  streaming(h);
  const send = h.context.sendMessage(); await tick();
  const old = h.state.activeGeneration;
  await h.context.logout(); await send;
  assert.equal(old.controller.signal.aborted, true);
  assert.equal(h.state.messages.length, 0);
  assert.equal(h.state.currentConversation, null);
});
test('stop preserves buffered partial text and marks interrupted', async h => {
  const stream = streaming(h);
  const send = h.context.sendMessage(); await tick();
  stream.event({ choices: [{ delta: { content: '已经收到的部分正文' } }] }); await tick();
  h.context.stopGeneration(); await send;
  assert.equal(h.state.messages[1].content, '已经收到的部分正文');
  assert.equal(h.state.messages[1].generation_status, 'interrupted');
  assert.equal(h.state.sending, false);
});
test('message.failed escapes the parser and keeps the partial answer', async h => {
  const stream = streaming(h);
  const send = h.context.sendMessage(); await tick();
  stream.event({ choices: [{ delta: { content: '部分内容' } }] });
  stream.event({ type: 'message.failed', status: 'failed', message: '模型服务失败', message_id: 8 });
  stream.end(); await send;
  assert.equal(h.state.messages[1].content, '部分内容');
  assert.equal(h.state.messages[1].generation_status, 'failed');
  assert.equal(h.state.messages[1].id, 8);
  assert.ok(h.statuses.includes('模型服务失败'));
});
test('EOF without message_saved is interrupted; empty failures have visible fallback', async h => {
  const stream = streaming(h);
  const send = h.context.sendMessage(); await tick(); stream.end(); await send;
  assert.equal(h.state.messages[1].generation_status, 'interrupted');
  assert.match(h.context.generationEmptyText(h.state.messages[1]), /尚未收到正文/);
});
test('confirmed completion remains completed and drains text', async h => {
  const stream = streaming(h);
  const send = h.context.sendMessage(); await tick();
  stream.event({ choices: [{ delta: { content: '完整回答' } }] });
  stream.event({ type: 'message_saved', message_id: 9, generation_status: 'completed' });
  stream.end(); await send;
  assert.equal(h.state.messages[1].content, '完整回答');
  assert.equal(h.state.messages[1].generation_status, 'completed');
  assert.equal(h.state.sending, false);
});
test('read failure after completed message_saved cannot downgrade completion', async h => {
  const stream = streaming(h);
  const send = h.context.sendMessage(); await tick();
  stream.event({ choices: [{ delta: { content: '已保存的完整回答' } }] });
  stream.event({ type: 'message_saved', message_id: 10, generation_status: 'completed' });
  await tick(); stream.error(new TypeError('Network closed after completion')); await send;
  assert.equal(h.state.messages[1].content, '已保存的完整回答');
  assert.equal(h.state.messages[1].generation_status, 'completed');
  assert.equal(h.state.sending, false);
});
test('reselecting the same conversation releases side sending and permits another send', async h => {
  const oldStream = streaming(h, { abort: false });
  h.state.activeSideDiscussion = { id: 'S1', session_id: 'A' };
  h.context.$('sideDiscussionPrompt').value = '旧讨论';
  const oldSend = h.context.sendSideDiscussionMessage(); await tick();
  const oldController = h.state.sideDiscussionAbortController;
  await h.context.selectConversation('A');
  assert.equal(oldController.signal.aborted, true);
  assert.equal(h.state.sideDiscussionSending, false);
  assert.equal(h.state.sideDiscussionAbortController, null);
  assert.equal(h.context.$('sideDiscussionSend').title, '发送');
  streaming(h);
  h.context.$('sideDiscussionPrompt').value = '新的讨论';
  const newSend = h.context.sendSideDiscussionMessage(); await tick();
  const newController = h.state.sideDiscussionAbortController;
  assert.equal(h.state.sideDiscussionSending, true);
  oldStream.event({ choices: [{ delta: { content: '迟到内容' } }] }); oldStream.end();
  await oldSend;
  assert.equal(h.state.sideDiscussionAbortController, newController);
  assert.equal(h.state.sideDiscussionSending, true);
  h.context.closeSideDiscussion(); await newSend;
  assert.equal(h.state.sideDiscussionSending, false);
});
test('opening another side discussion cancels the old controller and resets the send button', async h => {
  const oldStream = streaming(h, { abort: false });
  h.state.activeSideDiscussion = { id: 'S1', session_id: 'A' };
  h.context.$('sideDiscussionPrompt').value = '旧讨论';
  const oldSend = h.context.sendSideDiscussionMessage(); await tick();
  const oldController = h.state.sideDiscussionAbortController, base = h.context.api;
  h.context.api = (url, options) => url === '/api/side-discussions/S2'
    ? Promise.resolve(response({ discussion: { id: 'S2', session_id: 'A' }, messages: [] })) : base(url, options);
  await h.context.openSideDiscussion('S2');
  assert.equal(oldController.signal.aborted, true);
  assert.equal(h.state.activeSideDiscussion.id, 'S2');
  assert.equal(h.state.sideDiscussionSending, false);
  assert.equal(h.context.$('sideDiscussionSend').title, '发送');
  streaming(h); h.context.$('sideDiscussionPrompt').value = '新讨论';
  const newSend = h.context.sendSideDiscussionMessage(); await tick();
  const newController = h.state.sideDiscussionAbortController;
  oldStream.event({ choices: [{ delta: { content: '旧结果' } }] }); oldStream.end(); await oldSend;
  assert.equal(h.state.sideDiscussionAbortController, newController);
  assert.equal(h.state.sideDiscussionSending, true);
  assert.equal(h.state.sideDiscussionMessages.at(-1).content, '');
  h.context.closeSideDiscussion(); await newSend;
});
test('side discussion keeps partial text and a failed saved marker', async h => {
  const stream = streaming(h);
  h.state.activeSideDiscussion = { id: 'S1', session_id: 'A' };
  h.context.$('sideDiscussionPrompt').value = '提问';
  const send = h.context.sendSideDiscussionMessage(); await tick();
  stream.event({ choices: [{ delta: { content: '已收到的侧边回复' } }] });
  stream.event({ type: 'message_saved', message_id: 21, generation_status: 'failed' });
  stream.event({ type: 'message.failed', message_id: 21, status: 'failed', message: '生成失败' });
  stream.end(); await send;
  assert.equal(h.state.sideDiscussionMessages[1].content, '已收到的侧边回复');
  assert.equal(h.state.sideDiscussionMessages[1].generation_status, 'failed');
  assert.equal(h.state.sideDiscussionMessages[1].id, 21);
  assert.equal(h.state.sideDiscussionSending, false);
});
test('empty side EOF remains visible as interrupted instead of disappearing', async h => {
  const stream = streaming(h);
  h.state.activeSideDiscussion = { id: 'S1', session_id: 'A' };
  h.context.$('sideDiscussionPrompt').value = '提问';
  const send = h.context.sendSideDiscussionMessage(); await tick(); stream.end(); await send;
  assert.equal(h.state.sideDiscussionMessages.length, 2);
  assert.equal(h.state.sideDiscussionMessages[1].generation_status, 'interrupted');
  assert.match(h.context.generationEmptyText(h.state.sideDiscussionMessages[1]), /尚未收到正文/);
});
test('stopping a side discussion preserves its received text and interrupted state', async h => {
  const stream = streaming(h);
  h.state.activeSideDiscussion = { id: 'S1', session_id: 'A' };
  h.context.$('sideDiscussionPrompt').value = '提问';
  const send = h.context.sendSideDiscussionMessage(); await tick();
  stream.event({ choices: [{ delta: { content: '停止前正文' } }] }); await tick();
  await h.context.sendSideDiscussionMessage(); await send;
  assert.equal(h.state.sideDiscussionMessages[1].content, '停止前正文');
  assert.equal(h.state.sideDiscussionMessages[1].generation_status, 'interrupted');
  assert.equal(h.context.$('sideDiscussionSend').title, '发送');
});
test('confirmed side completion survives a later transport failure', async h => {
  const stream = streaming(h);
  h.state.activeSideDiscussion = { id: 'S1', session_id: 'A' };
  h.context.$('sideDiscussionPrompt').value = '提问';
  const send = h.context.sendSideDiscussionMessage(); await tick();
  stream.event({ choices: [{ delta: { content: '完整侧边回复' } }] });
  stream.event({ type: 'message_saved', message_id: 22, generation_status: 'completed' });
  await tick(); stream.error(new TypeError('Connection closed')); await send;
  assert.equal(h.state.sideDiscussionMessages[1].generation_status, 'completed');
  assert.equal(h.state.sideDiscussionMessages[1].thinking, false);
});
test('main and side connection errors retain the persisted failed message id', async h => {
  const base = h.context.api;
  h.context.api = async (url, options) => url.endsWith('/messages') && options?.method === 'POST'
    ? { ok: false, json: async () => ({ error: 'upstream request failed', message_id: 23, generation_status: 'failed' }) }
    : base(url, options);
  await h.context.sendMessage();
  assert.equal(h.state.messages[1].id, 23);
  assert.equal(h.state.messages[1].generation_status, 'failed');
  h.state.activeSideDiscussion = { id: 'S1', session_id: 'A' };
  h.context.$('sideDiscussionPrompt').value = '提问';
  await h.context.sendSideDiscussionMessage();
  assert.equal(h.state.sideDiscussionMessages[1].id, 23);
  assert.equal(h.state.sideDiscussionMessages[1].generation_status, 'failed');
});
test('late side-panel opens cannot replace a newer selection or reopen a closed panel', async h => {
  const pending = new Map();
  h.context.api = url => { const item = deferred(); pending.set(url, item); return item.promise; };
  const a = h.context.openSideDiscussion('S1'), b = h.context.openSideDiscussion('S2');
  pending.get('/api/side-discussions/S2').resolve(response({ discussion: { id: 'S2', session_id: 'A' }, messages: [] }));
  await b;
  pending.get('/api/side-discussions/S1').resolve(response({ discussion: { id: 'S1', session_id: 'A' }, messages: [] }));
  await a;
  assert.equal(h.state.activeSideDiscussion.id, 'S2');
  const c = h.context.openSideDiscussion('S3');
  h.context.closeSideDiscussion();
  pending.get('/api/side-discussions/S3').resolve(response({ discussion: { id: 'S3', session_id: 'A' }, messages: [] }));
  await c;
  assert.equal(h.context.$('sideDiscussionPanel').hidden, true);
  assert.equal(h.state.activeSideDiscussion.id, 'S2');
});
test('creating a discussion from selected text opens it and ignores a stale creation', async h => {
  h.state.activeTextSelection = { session_id: 'A', message_id: 1, selected_text: '引用' };
  const discussion = { id: 'S1', session_id: 'A' };
  h.context.api = async () => response({ discussion, messages: [] });
  await h.context.createSideDiscussionFromSelection();
  assert.equal(h.state.activeSideDiscussion.id, 'S1');
  assert.equal(h.context.$('sideDiscussionPanel').hidden, false);
  const pending = deferred();
  h.context.api = () => pending.promise;
  const creating = h.context.createSideDiscussionFromSelection();
  h.context.beginConversationTransition(); h.state.currentConversation = { id: 'B' };
  h.state.sideDiscussions = [{ id: 'B-side' }];
  pending.resolve(response({ discussion: { id: 'S2', session_id: 'A' } }));
  await creating;
  assert.equal(h.state.sideDiscussions[0].id, 'B-side');
  assert.equal(h.context.$('sideDiscussionPanel').hidden, true);
});
test('stream parser handles split UTF-8 and a final event without newline', async h => {
  const bytes = new TextEncoder().encode('data: {"text":"中文🙂"}\n\ndata: {"type":"message_saved","message_id":1}');
  const events = [];
  const body = new ReadableStream({ start(controller) { for (const byte of bytes) controller.enqueue(Uint8Array.of(byte)); controller.close(); } });
  await h.context.readChatEvents({ body }, event => events.push(event), () => true);
  assert.equal(events[0].text, '中文🙂'); assert.equal(events[1].message_id, 1);
});
(async () => {
  for (const [name, run] of tests) {
    const h = harness();
    try { await run(h); console.log('PASS ' + name); }
    finally { h.finish(); }
  }
  console.log(tests.length + ' frontend state regressions passed (mock network, no external APIs).');
})().catch(error => { console.error(error); process.exitCode = 1; });
