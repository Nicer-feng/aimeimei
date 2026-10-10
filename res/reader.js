/* Reading owns its DOM and progress; chat data never includes book text. */
(() => {
  const el = (id) => document.getElementById(id);
  const root = el('readerMessages'), container = el('readerPages'), library = el('readerLibrary');
  const desktop = matchMedia('(min-width: 1024px) and (hover: hover) and (pointer: fine)');
  let active = false, opening = false, book = null, pages = [], mode = 'scroll';
  let epoch = 0, loading = false, chatSnapshot = null, position = 0, pageNumber = 0;
  let saveTimer = 0, frame = 0, resizeTimer = 0, stamp = 0, owner = '', lastCapture = 0;
  let enterSerial = 0, librarySerial = 0;
  const key = (uid, id) => `aiReader:${uid}:${id}`;
  const icons = () => queueLucideRefresh();
  const status = (message = '') => { el('readerLibraryStatus').textContent = message; };
  const error = (err) => { status(err.message || '暂时无法读取，请稍后重试'); };
  const valid = (ticket, user) => ticket === epoch && state.user === user;
  async function json(path, options) {
    const res = await api('/api/reading/' + path, options);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '请求失败，请重试');
    return data;
  }
  function controls() {
    if (!book) return;
    const percent = Math.min(100, 100 * position / Math.max(1, book.total_chars)).toFixed(1);
    const label = `${book.title} · 第 ${pageNumber + 1}/${book.page_count} 页 · ${percent}%`;
    el('readerProgress').textContent = `${pageNumber + 1}/${book.page_count} · ${percent}%`;
    el('readerProgress').title = label + ' · 点击管理';
    el('readerToggle').title = active ? label + ' · 点击退出摸鱼模式' : '摸鱼模式';
    el('readerPrevious').disabled = pageNumber <= 0;
    el('readerNext').disabled = pageNumber >= book.page_count - 1;
    el('readerPageInput').max = book.page_count;
    el('readerPageInput').placeholder = `1–${book.page_count}`;
    library.querySelectorAll('[data-reader-mode]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.readerMode === mode)));
  }
  function progressAtTop() {
    const top = root.getBoundingClientRect().top + 36;
    const nodes = [...container.querySelectorAll('[data-reader-page]')];
    const node = nodes.find(n => n.getBoundingClientRect().bottom > top) || nodes.at(-1);
    if (!node) return;
    const text = node.querySelector('.reader-text'), rect = text.getBoundingClientRect();
    let offset = 0;
    if (rect.top < top) {
      const x = rect.left + 2;
      const caret = document.caretPositionFromPoint?.(x, top);
      const range = !caret && document.caretRangeFromPoint?.(x, top);
      const target = caret?.offsetNode || range?.startContainer;
      const index = caret?.offset ?? range?.startOffset;
      if (target === text.firstChild) offset = Array.from(text.textContent.slice(0, index)).length;
      else offset = Math.floor(Array.from(text.textContent).length * Math.max(0, Math.min(1, (top - rect.top) / rect.height)));
    }
    position = Math.min(book.total_chars, Number(node.dataset.start) + offset);
    pageNumber = Number(node.dataset.readerPage);
    if (pageNumber === book.page_count - 1 && root.scrollHeight - root.clientHeight - root.scrollTop < 4) position = book.total_chars;
  }
  function capture() {
    if (!active || !book || !pages.length || loading || library.open) return;
    progressAtTop();
    rememberPosition();
  }
  function rememberPosition() {
    if (!book || !owner) return;
    stamp = Math.max(Date.now(), stamp + 1);
    const value = { position, mode, saved_at: stamp };
    try { localStorage.setItem(key(owner, book.id), JSON.stringify(value)); } catch {}
    controls();
  }
  function save(keepalive = false) {
    clearTimeout(saveTimer); saveTimer = 0;
    if (!book || !owner || !stamp || owner !== String(state.user?.id)) return;
    const uid = owner, id = book.id, ticket = epoch;
    const body = JSON.stringify({ position, mode, saved_at: stamp });
    // The payload is captured before changing book/account; late responses cannot change the reader.
    json(`books/${encodeURIComponent(id)}/progress`, { method: 'POST', body, keepalive }).catch(() => {
      if (owner === uid && epoch === ticket) el('readerProgress').title = '进度已保存在本机，网络恢复后会再次同步';
    });
  }
  function scheduleSave() {
    if (performance.now() - lastCapture > 300) { capture(); lastCapture = performance.now(); }
    if (!saveTimer) saveTimer = setTimeout(() => { capture(); save(); }, 2500);
  }
  function pageNode(page) {
    const article = document.createElement('article');
    article.className = 'bubble assistant reader-page';
    article.dataset.readerPage = page.page; article.dataset.start = page.start_offset;
    const role = document.createElement('div'); role.className = 'role';
    const avatar = document.createElement('img'); avatar.src = '/res/meimei-avatar.png'; avatar.alt = ''; avatar.width = 24; avatar.height = 24;
    role.append(avatar, document.createTextNode('槑槑'));
    const text = document.createElement('p'); text.className = 'markdown reader-text'; text.textContent = page.content;
    article.append(role, text);
    return article;
  }
  function restorePosition() {
    const page = pages.find(p => position >= p.start_offset && position < p.start_offset + Array.from(p.content).length) || pages.at(-1);
    if (!page) return;
    const node = container.querySelector(`[data-reader-page="${page.page}"] .reader-text`);
    const index = Array.from(page.content).slice(0, Math.max(0, position - page.start_offset)).join('').length;
    const range = document.createRange();
    range.setStart(node.firstChild, Math.min(index, Math.max(0, node.textContent.length - 1)));
    range.setEnd(node.firstChild, Math.min(index + 1, node.textContent.length));
    root.scrollTop += range.getBoundingClientRect().top - root.getBoundingClientRect().top - 36;
    pageNumber = page.page; controls();
  }
  async function loadWindow(params, selected = book) {
    const ticket = ++epoch, user = state.user;
    loading = true;
    try {
      const data = await json(`books/${encodeURIComponent(selected.id)}/pages?${params}&radius=${mode === 'page' ? 0 : 2}`);
      if (!valid(ticket, user) || !active) return;
      pages = data.pages; pageNumber = data.page;
      if (params.startsWith('page=')) position = pages.find(p => p.page === data.page).start_offset;
      container.replaceChildren(...pages.map(pageNode));
      restorePosition();
      status();
    } finally { if (ticket === epoch) loading = false; }
  }
  async function extend() {
    if (loading || !active || mode !== 'scroll' || !pages.length) return;
    const before = root.scrollTop < 600 && pages[0].page > 0;
    const after = root.scrollHeight - root.clientHeight - root.scrollTop < 1000 && pages.at(-1).page < book.page_count - 1;
    if (!before && !after) return;
    const next = before ? pages[0].page - 1 : pages.at(-1).page + 1;
    const ticket = epoch, user = state.user;
    loading = true;
    let extended = false;
    try {
      const data = await json(`books/${encodeURIComponent(book.id)}/pages?page=${next}&radius=0`);
      if (!valid(ticket, user) || !active) return;
      // Preserve a visible element's screen position while trimming the distant edge.
      const anchor = [...container.children].find(n => n.getBoundingClientRect().bottom > root.getBoundingClientRect().top + 36);
      const y = anchor?.getBoundingClientRect().top;
      const item = data.pages[0];
      if (before) { pages.unshift(item); container.prepend(pageNode(item)); }
      else { pages.push(item); container.append(pageNode(item)); }
      if (pages.length > 7) {
        if (before) { pages.pop(); container.lastElementChild.remove(); }
        else { pages.shift(); container.firstElementChild.remove(); }
      }
      if (anchor?.isConnected) root.scrollTop += anchor.getBoundingClientRect().top - y;
      extended = true;
    } catch (err) {
      if (valid(ticket, user)) {
        status(err.message); el('readerProgress').title = '下一段加载失败，继续滚动可重试';
      }
    } finally {
      if (ticket === epoch) {
        loading = false;
        if (extended) requestAnimationFrame(extend);
      }
    }
  }
  async function enter(selected) {
    if (!desktop.matches || !state.authed) return;
    capture(); save();
    const operation = ++enterSerial;
    const ticket = ++epoch, user = state.user;
    opening = true;
    try {
      if (!selected) {
        const data = await json('books');
        if (!valid(ticket, user)) return;
        selected = data.books.find(b => b.active);
        if (!selected) { await openLibrary(); return; }
      }
      await json(`books/${encodeURIComponent(selected.id)}/active`, { method: 'POST', body: '{}' });
      if (!valid(ticket, user)) return;
      book = selected; owner = String(user.id); mode = book.mode; position = book.position; stamp = book.progress_at;
      pages = []; container.textContent = '正在准备内容…';
      try {
        const local = JSON.parse(localStorage.getItem(key(owner, book.id)) || 'null');
        if (local && Number.isFinite(local.position) && local.saved_at > stamp) {
          position = Math.max(0, Math.min(book.total_chars, local.position));
          mode = local.mode === 'page' ? 'page' : 'scroll'; stamp = local.saved_at;
        }
      } catch {}
      if (!active) chatSnapshot = { top: el('messages').scrollTop, follow: state.followOutput };
      active = true; state.followOutput = false;
      document.body.classList.add('reading-mode'); root.hidden = false; el('messages').inert = true;
      el('readerControls').hidden = false; el('readerToggle').setAttribute('aria-pressed', 'true');
      hideSelectionToolbar();
      library.close();
      await loadWindow(`offset=${position}`);
      if (active) { root.focus({ preventScroll: true }); save(); }
    } catch (err) {
      if (state.user === user && operation === enterSerial) { exit(); await openLibrary(); error(err); }
    } finally { if (operation === enterSerial) opening = false; }
  }
  function exit() {
    capture(); save(true);
    ++epoch; ++enterSerial; opening = false; loading = false;
    if (!active) return;
    active = false;
    document.body.classList.remove('reading-mode'); root.hidden = true; el('messages').inert = false;
    el('readerControls').hidden = true; el('readerToggle').setAttribute('aria-pressed', 'false');
    el('readerToggle').title = '摸鱼模式';
    if (chatSnapshot) { el('messages').scrollTop = chatSnapshot.top; state.followOutput = chatSnapshot.follow; }
    updateScrollLatestButton();
  }
  function reset() {
    exit(); library.close(); book = null; pages = []; stamp = 0; owner = '';
    container.replaceChildren(); el('readerLibraryList').replaceChildren(); status();
  }
  async function openLibrary() {
    if (!desktop.matches || !state.authed) return;
    capture(); save();
    const requestId = ++librarySerial;
    const user = state.user;
    if (!library.open) library.showModal();
    status('正在读取…');
    try {
      const data = await json('books');
      if (state.user !== user || !library.open || requestId !== librarySerial) return;
      const list = el('readerLibraryList'); list.replaceChildren();
      if (!data.books.length) status('还没有小说，上传 TXT 后即可开始阅读。'); else status();
      data.books.forEach(item => {
        const row = document.createElement('div'); row.className = 'reader-book';
        const open = document.createElement('button'); open.type = 'button'; open.className = 'reader-book-open';
        const title = document.createElement('strong'); title.textContent = item.title;
        const meta = document.createElement('small');
        meta.textContent = `${item.active ? '当前 · ' : ''}${item.page_count} 页 · ${(100 * item.position / item.total_chars).toFixed(1)}%`;
        open.append(title, meta); open.addEventListener('click', () => enter(item));
        const remove = document.createElement('button'); remove.className = 'ui-icon-btn'; remove.type = 'button';
        remove.title = '删除小说'; remove.setAttribute('aria-label', '删除 ' + item.title);
        const icon = document.createElement('i'); icon.dataset.lucide = 'trash-2'; remove.append(icon);
        remove.addEventListener('click', async () => {
          if (!confirm(`删除《${item.title}》及其阅读进度？`)) return;
          remove.disabled = true;
          if (book?.id === item.id) exit();
          try {
            await json(`books/${encodeURIComponent(item.id)}`, { method: 'DELETE' });
            localStorage.removeItem(key(String(user.id), item.id));
            if (book?.id === item.id) { book = null; pages = []; container.replaceChildren(); }
            await openLibrary();
          } catch (err) { error(err); remove.disabled = false; }
        });
        row.append(open, remove); list.append(row);
      });
      el('readerJump').hidden = !book;
      controls(); icons();
    } catch (err) { if (state.user === user) error(err); }
  }
  async function turn(delta) {
    if (!active || loading) return;
    capture();
    try {
      await loadWindow(`page=${Math.max(0, Math.min(book.page_count - 1, pageNumber + delta))}`);
      capture(); save();
    } catch (err) { error(err); }
  }
  el('readerToggle').addEventListener('click', () => active || opening ? exit() : enter());
  el('readerToggle').addEventListener('contextmenu', event => { event.preventDefault(); openLibrary(); });
  el('readerProgress').addEventListener('click', openLibrary);
  el('readerPrevious').addEventListener('click', () => turn(-1));
  el('readerNext').addEventListener('click', () => turn(1));
  el('readerLibraryClose').addEventListener('click', () => library.close());
  library.addEventListener('click', event => { if (event.target === library) { const r = library.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) library.close(); } });
  el('readerUpload').addEventListener('click', () => el('readerFile').click());
  el('readerFile').addEventListener('change', async () => {
    const file = el('readerFile').files[0], user = state.user; el('readerFile').value = '';
    if (!file) return;
    if (!/\.txt$/i.test(file.name) || !file.size || file.size > 20 * 1024 * 1024) { status('请选择 20MB 以内的 TXT 文件'); return; }
    el('readerUpload').disabled = true; status('正在上传并整理文本…');
    try {
      await json('books?filename=' + encodeURIComponent(file.name), { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file });
      if (state.user === user) await openLibrary();
    } catch (err) { if (state.user === user) error(err); }
    finally { el('readerUpload').disabled = false; }
  });
  library.querySelectorAll('[data-reader-mode]').forEach(button => button.addEventListener('click', async () => {
    if (!active || loading) { status('请先选择一本小说开始阅读'); return; }
    capture(); mode = button.dataset.readerMode;
    try { await loadWindow(`offset=${position}`); rememberPosition(); save(); controls(); } catch (err) { error(err); }
  }));
  el('readerJump').addEventListener('submit', async event => {
    event.preventDefault(); if (!active || loading) return;
    const page = Number(el('readerPageInput').value) - 1;
    if (!Number.isInteger(page) || page < 0 || page >= book.page_count) return;
    try { await loadWindow(`page=${page}`); rememberPosition(); save(); library.close(); } catch (err) { error(err); }
  });
  root.addEventListener('scroll', () => {
    if (frame) return;
    frame = requestAnimationFrame(() => { frame = 0; if (!active) return; scheduleSave(); extend(); });
  }, { passive: true });
  root.addEventListener('keydown', event => {
    if (!active || mode !== 'page' || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') { event.preventDefault(); turn(event.key === 'ArrowRight' ? 1 : -1); }
  });
  desktop.addEventListener('change', () => { if (!desktop.matches) { exit(); library.close(); } });
  window.addEventListener('pagehide', () => { capture(); save(true); });
  window.addEventListener('online', () => { if (active) save(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) { capture(); save(true); } });
  let observedWidth = 0;
  new ResizeObserver(entries => {
    const width = entries[0].contentRect.width, oldWidth = observedWidth;
    observedWidth = width;
    if (!active || !oldWidth || !width || width === oldWidth) return;
    clearTimeout(resizeTimer);
    const savedStamp = stamp;
    resizeTimer = setTimeout(() => { if (active && !loading && stamp === savedStamp) restorePosition(); }, 180);
  }).observe(root);
  el('fontSizeToggle').addEventListener('click', () => { if (active) requestAnimationFrame(restorePosition); });
  window.MeimeiReader = { get active() { return active; }, exit, reset, openLibrary };
})();
