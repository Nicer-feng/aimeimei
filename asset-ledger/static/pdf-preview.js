const VENDOR = new URL('./vendor/pdfjs/', import.meta.url);
const MAX_CANVAS_SIDE = 3200;
const MAX_CANVAS_PIXELS = 4_000_000;
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
  const canvas = element('canvas', 'pdf-page-canvas');
  canvas.setAttribute('role', 'img');
  canvas.hidden = true;
  stage.append(canvas);
  host.replaceChildren(toolbar, stage);

  let disposed = false;
  let loadingTask;
  let rendering;
  let pdf;
  let current = 0;
  const requested = Number(startPage);

  function setBusy(busy) {
    previous.disabled = busy || current <= 1;
    next.disabled = busy || !pdf || current >= pdf.numPages;
    stage.setAttribute('aria-busy', String(busy));
  }

  function setStatus(message, error = false) {
    status.textContent = message;
    status.classList.toggle('pdf-page-error', error);
  }

  async function showPage(number, fallback = false) {
    if (disposed || !pdf || number < 1 || number > pdf.numPages) return;
    current = number;
    setBusy(true);
    setStatus(`正在渲染第 ${number} 页…`);
    canvas.hidden = true;
    try {
      const page = await pdf.getPage(number);
      if (disposed) return;
      const original = page.getViewport({ scale: 1 });
      const contentWidth = Math.max(100, Math.min((stage.clientWidth || 720) - 24, 1000));
      const displayScale = contentWidth / original.width;
      const scale = Math.min(
        displayScale * Math.min(window.devicePixelRatio || 1, 2),
        MAX_CANVAS_SIDE / Math.max(original.width, original.height),
        Math.sqrt(MAX_CANVAS_PIXELS / (original.width * original.height)),
      );
      const viewport = page.getViewport({ scale });
      canvas.width = Math.max(1, Math.floor(viewport.width));
      canvas.height = Math.max(1, Math.floor(viewport.height));
      canvas.style.width = `${Math.min(contentWidth, canvas.width)}px`;
      rendering = page.render({ canvas, viewport });
      await rendering.promise;
      if (disposed) return;
      canvas.setAttribute('aria-label', `PDF 第 ${number} 页，共 ${pdf.numPages} 页`);
      canvas.dataset.pageNumber = String(number);
      canvas.hidden = false;
      stage.scrollTop = 0;
      const position = `第 ${number} 页 / 共 ${pdf.numPages} 页`;
      setStatus(fallback ? `参考页码超出范围，已显示${position}` : position, fallback);
    } catch {
      if (!disposed) setStatus(`第 ${number} 页渲染失败，请打开原件或下载后查看。`, true);
    } finally {
      rendering = undefined;
      if (!disposed) setBusy(false);
    }
  }

  async function load() {
    try {
      const fileUrl = new URL(url, window.location.href);
      if (fileUrl.origin !== window.location.origin) throw new Error(LOAD_ERROR);
      fileUrl.hash = '';
      const pdfjs = await import('./vendor/pdfjs/pdf.min.mjs');
      if (disposed) return;
      pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdf.worker.min.mjs', VENDOR).href;
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
      await showPage(valid ? requested : 1, !valid && startPage != null);
    } catch {
      if (!disposed) {
        setStatus(LOAD_ERROR, true);
        setBusy(false);
      }
    }
  }

  previous.addEventListener('click', () => showPage(current - 1));
  next.addEventListener('click', () => showPage(current + 1));
  setBusy(true);
  load();

  return () => {
    if (disposed) return;
    disposed = true;
    rendering?.cancel();
    loadingTask?.destroy().catch(() => {});
    canvas.width = canvas.height = 0;
    toolbar.remove();
    stage.remove();
  };
}
