const VENDOR = new URL('./vendor/pdfjs/', import.meta.url);
const PDFJS_VERSION = '6.5.438';
const MAX_CANVAS_SIDE = 3200;
const MAX_CANVAS_PIXELS = 4_000_000;
const MAX_ACTIVE_PAGES = 6;
const LOAD_ERROR = '无法预览 PDF，请打开原件或下载后查看。';

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

export function mountPdfPreview(host, { url, startPage }) {
  const toolbar = element('div', 'pdf-page-toolbar');
  const previous = element('button', 'button small', '上一页');
  const next = element('button', 'button small', '下一页');
  previous.type = next.type = 'button';
  const status = element('p', 'pdf-page-status', '正在读取 PDF…');
  status.setAttribute('role', 'status');
  toolbar.append(previous, status, next);

  const stage = element('div', 'pdf-page-stage');
  stage.tabIndex = 0;
  stage.setAttribute('role', 'region');
  stage.setAttribute('aria-label', 'PDF 页面');
  stage.setAttribute('aria-busy', 'true');
  const list = element('div', 'pdf-page-list');
  stage.append(list);
  host.replaceChildren(toolbar, stage);

  let disposed = false;
  let loadingTask;
  let pdf;
  let current = 0;
  let targetUnavailable = false;
  let layoutWidth = 0;
  let layoutHeight = 0;
  let insetTop = 0;
  let pendingFrame = 0;
  let activeRender;
  let preferredPages = [];
  const slots = [];
  const canvases = new Map();
  const requested = Number(startPage);

  function setStatus(message, error = false) {
    if (status.textContent !== message) status.textContent = message;
    status.classList.toggle('pdf-page-error', error);
  }

  function topOf(number) {
    return slots[number - 1].node.offsetTop;
  }

  function pageAt(offset) {
    let first = 1;
    let last = slots.length;
    while (first < last) {
      const middle = Math.ceil((first + last) / 2);
      if (topOf(middle) <= offset) first = middle;
      else last = middle - 1;
    }
    return first;
  }

  function keepScrollAnchor(update) {
    if (!slots.length) {
      update();
      return;
    }
    // 估算页高替换成实际页高时，以当前页为锚，避免前页增高造成跳页。
    const anchorPosition = stage.scrollTop + insetTop;
    const anchor = pageAt(anchorPosition + 1);
    const page = slots[anchor - 1].node;
    const offset = anchorPosition - page.offsetTop;
    const oldHeight = page.offsetHeight;
    update();
    const newHeight = page.offsetHeight;
    const retainedOffset = oldHeight === newHeight || offset <= 0
      ? offset
      : Math.min(newHeight - 1, offset * newHeight / oldHeight);
    stage.scrollTop = page.offsetTop - insetTop + retainedOffset;
  }

  function syncDimensions() {
    const width = Math.max(1, list.clientWidth);
    const style = getComputedStyle(stage);
    const paddingTop = parseFloat(style.paddingTop) || 0;
    const height = Math.max(1, stage.clientHeight - paddingTop - (parseFloat(style.paddingBottom) || 0));
    if (width === layoutWidth && height === layoutHeight) return;
    keepScrollAnchor(() => {
      layoutWidth = width;
      layoutHeight = height;
      insetTop = paddingTop;
      list.style.setProperty('--pdf-page-width', `${width}px`);
      list.style.setProperty('--pdf-visible-height', `${height}px`);
    });
  }

  function releaseCanvas(number, canvas) {
    canvas.width = canvas.height = 0;
    canvas.remove();
    canvases.delete(number);
    delete slots[number - 1].node.dataset.rendered;
  }

  function queueViewportUpdate() {
    if (disposed || pendingFrame) return;
    pendingFrame = requestAnimationFrame(() => {
      pendingFrame = 0;
      updateViewport();
    });
  }

  function updateViewport() {
    if (disposed || !slots.length) return;
    current = pageAt(stage.scrollTop + insetTop + 1);
    const last = pageAt(stage.scrollTop + stage.clientHeight - 1);
    preferredPages = [current];
    for (let number = current + 1; number <= last && preferredPages.length < MAX_ACTIVE_PAGES; number += 1) {
      preferredPages.push(number);
    }
    for (const number of [current - 1, last + 1]) {
      if (number >= 1 && number <= slots.length && preferredPages.length < MAX_ACTIVE_PAGES) preferredPages.push(number);
    }
    for (const [number, canvas] of canvases) {
      if (!preferredPages.includes(number)) releaseCanvas(number, canvas);
    }
    if (activeRender && !preferredPages.includes(activeRender.number)) activeRender.task?.cancel();

    stage.dataset.currentPage = String(current);
    previous.disabled = current <= 1;
    next.disabled = current >= slots.length;
    const position = `第 ${current} 页 / 共 ${slots.length} 页`;
    const failed = slots[current - 1].failed;
    stage.setAttribute('aria-busy', String(!failed && !canvases.has(current)));
    if (failed) setStatus(`第 ${current} 页渲染失败，请打开原件或下载后查看。`, true);
    else if (targetUnavailable && current === 1) setStatus(`参考页码超出范围，已定位到${position}`, true);
    else setStatus(position);

    const unrendered = preferredPages.find((number) => !canvases.has(number) && !slots[number - 1].failed);
    if (!activeRender && unrendered) void paintPage(unrendered);
  }

  async function paintPage(number) {
    const render = { number, task: null };
    activeRender = render;
    const slot = slots[number - 1];
    let canvas;
    try {
      const page = slot.preloaded || await pdf.getPage(number);
      slot.preloaded = null;
      if (disposed || !preferredPages.includes(number)) return;
      const original = page.getViewport({ scale: 1 });
      const ratio = original.height / original.width;
      if (slot.ratio !== ratio) {
        keepScrollAnchor(() => {
          slot.ratio = ratio;
          slot.node.style.setProperty('--pdf-page-ratio', ratio);
          if (number === slots.length) list.style.setProperty('--pdf-last-page-ratio', ratio);
        });
      }
      const displayScale = layoutWidth / original.width;
      const scale = Math.min(
        displayScale * Math.min(window.devicePixelRatio || 1, 2),
        MAX_CANVAS_SIDE / Math.max(original.width, original.height),
        Math.sqrt(MAX_CANVAS_PIXELS / (original.width * original.height)),
      );
      const viewport = page.getViewport({ scale });
      canvas = element('canvas', 'pdf-page-canvas');
      canvas.setAttribute('role', 'img');
      canvas.width = Math.max(1, Math.floor(viewport.width));
      canvas.height = Math.max(1, Math.floor(viewport.height));
      render.task = page.render({ canvas, viewport });
      await render.task.promise;
      if (disposed || !preferredPages.includes(number)) return;
      canvas.setAttribute('aria-label', `PDF 第 ${number} 页，共 ${slots.length} 页`);
      canvas.dataset.pageNumber = String(number);
      slot.node.dataset.rendered = 'true';
      slot.node.append(canvas);
      canvases.set(number, canvas);
    } catch (error) {
      if (!disposed && error?.name !== 'RenderingCancelledException') {
        slot.failed = true;
        slot.node.dataset.failed = 'true';
      }
    } finally {
      if (canvas && !canvases.has(number)) canvas.width = canvas.height = 0;
      activeRender = undefined;
      queueViewportUpdate();
    }
  }

  function goToPage(number) {
    if (number < 1 || number > slots.length) return;
    stage.scrollTop = topOf(number) - insetTop;
    updateViewport();
  }

  function buildPages(initialPage, initialNumber) {
    const viewport = initialPage?.getViewport({ scale: 1 });
    const ratio = viewport ? viewport.height / viewport.width : Math.SQRT2;
    list.style.setProperty('--pdf-page-ratio', ratio);
    list.style.setProperty('--pdf-last-page-ratio', ratio);
    const fragment = document.createDocumentFragment();
    for (let number = 1; number <= pdf.numPages; number += 1) {
      const node = element('div', 'pdf-page-slot');
      node.dataset.pageNumber = String(number);
      const isInitial = number === initialNumber;
      const failed = isInitial && !initialPage;
      if (failed) node.dataset.failed = 'true';
      slots.push({ node, ratio, preloaded: isInitial ? initialPage : null, failed });
      fragment.append(node);
    }
    list.append(fragment);
    syncDimensions();
    goToPage(initialNumber);
  }

  async function load() {
    try {
      const fileUrl = new URL(url, window.location.href);
      if (fileUrl.origin !== window.location.origin) throw new Error(LOAD_ERROR);
      fileUrl.hash = '';
      const pdfjs = await import(new URL(`pdf.min.mjs?v=${PDFJS_VERSION}`, VENDOR).href);
      if (disposed) return;
      pdfjs.GlobalWorkerOptions.workerSrc = new URL(`pdf.worker.min.mjs?v=${PDFJS_VERSION}`, VENDOR).href;
      loadingTask = pdfjs.getDocument({
        url: fileUrl.href,
        cMapUrl: new URL('cmaps/', VENDOR).href,
        cMapPacked: true,
        standardFontDataUrl: new URL('standard_fonts/', VENDOR).href,
        // PDF.js 也从此目录加载 JBIG2 和 JPEG 2000 的纯 JavaScript 解码器。
        wasmUrl: new URL('image_decoders/', VENDOR).href,
        enableXfa: false,
        useWasm: false,
        disableWorkerRendering: true,
        canvasMaxAreaInBytes: MAX_CANVAS_PIXELS * 4,
      });
      pdf = await loadingTask.promise;
      if (disposed) return;
      const valid = Number.isSafeInteger(requested) && requested >= 1 && requested <= pdf.numPages;
      const start = valid ? requested : 1;
      targetUnavailable = !valid && startPage != null;
      const initialPage = await pdf.getPage(start).catch(() => null);
      if (!disposed) buildPages(initialPage, start);
    } catch {
      if (!disposed) {
        setStatus(LOAD_ERROR, true);
        stage.setAttribute('aria-busy', 'false');
      }
    }
  }

  const resize = new ResizeObserver(() => {
    if (!slots.length || disposed) return;
    syncDimensions();
    queueViewportUpdate();
  });
  resize.observe(stage);
  stage.addEventListener('scroll', queueViewportUpdate, { passive: true });
  previous.disabled = next.disabled = true;
  previous.addEventListener('click', () => goToPage(current - 1));
  next.addEventListener('click', () => goToPage(current + 1));
  load();

  return () => {
    if (disposed) return;
    disposed = true;
    resize.disconnect();
    stage.removeEventListener('scroll', queueViewportUpdate);
    if (pendingFrame) cancelAnimationFrame(pendingFrame);
    activeRender?.task?.cancel();
    loadingTask?.destroy().catch(() => {});
    for (const [number, canvas] of canvases) releaseCanvas(number, canvas);
    toolbar.remove();
    stage.remove();
  };
}
