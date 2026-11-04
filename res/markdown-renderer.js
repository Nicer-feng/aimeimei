(function () {
  "use strict";

  const supportedMermaid = /^(?:graph\s+(?:TD|TB|BT|RL|LR)|flowchart\s+(?:TD|TB|BT|RL|LR)|mindmap\b|sequenceDiagram\b|classDiagram\b)/i;
  let markdown = null;
  let mermaidInitializedTheme = "";
  let mermaidLoadPromise = null;

  function currentTheme() {
    return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  }

  function encodeText(value) {
    return encodeURIComponent(String(value || ""));
  }

  function decodeText(value) {
    try {
      return decodeURIComponent(value || "");
    } catch {
      return "";
    }
  }

  function normalizeLanguage(value) {
    const language = String(value || "text").trim().toLowerCase().split(/\s+/)[0];
    const aliases = {
      sh: "bash",
      shell: "bash",
      zsh: "bash",
      yml: "yaml",
      js: "javascript",
      ts: "typescript",
      py: "python",
      golang: "go",
      cxx: "cpp",
      md: "markdown",
      docker: "dockerfile",
      plaintext: "text",
      txt: "text"
    };
    return aliases[language] || language || "text";
  }

  function highlightCode(code, language) {
    if (!window.hljs || language === "text") return markdown.utils.escapeHtml(code);
    try {
      if (window.hljs.getLanguage(language)) {
        return window.hljs.highlight(code, { language, ignoreIllegals: true }).value;
      }
    } catch {
      // Invalid or incomplete streaming code falls back to escaped text.
    }
    return markdown.utils.escapeHtml(code);
  }

  function renderFence(tokens, index) {
    const token = tokens[index];
    const language = normalizeLanguage(token.info);
    const code = token.content || "";
    if (language === "mermaid" && supportedMermaid.test(code.trim())) {
      const escaped = markdown.utils.escapeHtml(code);
      return '<section class="mermaid-block" data-mermaid-source="' + encodeText(code) + '">' +
        '<header class="code-head"><span class="code-language">mermaid</span>' +
        '<button class="code-copy ui-icon-btn" type="button" title="复制 Mermaid 源码" aria-label="复制 Mermaid 源码"><i data-lucide="copy" aria-hidden="true"></i></button></header>' +
        '<div class="mermaid-diagram">' + escaped + '</div>' +
        '<pre class="mermaid-fallback"><code class="hljs language-mermaid">' + escaped + '</code></pre>' +
        '</section>\n';
    }
    const highlighted = highlightCode(code, language);
    return '<section class="code-block" data-language="' + markdown.utils.escapeHtml(language) + '">' +
      '<header class="code-head"><span class="code-language">' + markdown.utils.escapeHtml(language) + '</span>' +
      '<button class="code-copy ui-icon-btn" type="button" title="复制代码" aria-label="复制代码"><i data-lucide="copy" aria-hidden="true"></i></button></header>' +
      '<pre tabindex="0"><code class="hljs language-' + markdown.utils.escapeHtml(language) + '">' + highlighted + '</code></pre>' +
      '</section>\n';
  }

  function installMathPlaceholder(md) {
    md.inline.ruler.after("escape", "math_inline_placeholder", function (state, silent) {
      if (state.src[state.pos] !== "$" || state.src[state.pos + 1] === "$") return false;
      const end = state.src.indexOf("$", state.pos + 1);
      if (end < 0 || end === state.pos + 1) return false;
      if (!silent) {
        const token = state.push("math_inline_placeholder", "span", 0);
        token.content = state.src.slice(state.pos + 1, end);
      }
      state.pos = end + 1;
      return true;
    });
    md.inline.ruler2.push("math_inline_placeholder", function () { return true; });
    md.renderer.rules.math_inline_placeholder = function (tokens, index) {
      const value = md.utils.escapeHtml(tokens[index].content);
      return '<span class="math-placeholder math-inline" data-math-source="' + encodeText(tokens[index].content) + '">' + value + '</span>';
    };

    md.block.ruler.before("fence", "math_block_placeholder", function (state, startLine, endLine, silent) {
      const start = state.bMarks[startLine] + state.tShift[startLine];
      const max = state.eMarks[startLine];
      if (state.src.slice(start, max).trim() !== "$$") return false;
      let nextLine = startLine + 1;
      while (nextLine < endLine) {
        const lineStart = state.bMarks[nextLine] + state.tShift[nextLine];
        const lineEnd = state.eMarks[nextLine];
        if (state.src.slice(lineStart, lineEnd).trim() === "$$") break;
        nextLine += 1;
      }
      if (nextLine >= endLine) return false;
      if (silent) return true;
      const token = state.push("math_block_placeholder", "div", 0);
      token.block = true;
      token.map = [startLine, nextLine + 1];
      token.content = state.getLines(startLine + 1, nextLine, state.tShift[startLine], false).trim();
      state.line = nextLine + 1;
      return true;
    });
    md.renderer.rules.math_block_placeholder = function (tokens, index) {
      const value = md.utils.escapeHtml(tokens[index].content);
      return '<div class="math-placeholder math-block" data-math-source="' + encodeText(tokens[index].content) + '">' + value + '</div>\n';
    };
  }

  function installCjkEmphasis(md) {
    const cjk = /[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\uf900-\ufaff]/;
    const punctuation = function (char) {
      return Boolean(char && (md.utils.isPunctChar(char) || md.utils.isMdAsciiPunct(char.charCodeAt(0))));
    };
    md.inline.ruler.before("emphasis", "cjk_strong", function (state, silent) {
      if (silent || state.src.slice(state.pos, state.pos + 2) !== "**") return false;
      const scan = state.scanDelims(state.pos, true);
      const before = state.src[state.pos - 1] || "";
      const after = state.src[state.pos + scan.length] || "";
      const open = scan.can_open || (cjk.test(before) && punctuation(after));
      const close = scan.can_close || (punctuation(before) && cjk.test(after));
      if (open === scan.can_open && close === scan.can_close) return false;
      // Reuse markdown-it's delimiter balancing; never rewrite source/code text.
      for (let i = 0; i < scan.length; i += 1) {
        state.push("text", "", 0).content = "*";
        state.delimiters.push({ marker: 42, length: scan.length, token: state.tokens.length - 1, end: -1, open, close });
      }
      state.pos += scan.length;
      return true;
    });
  }

  function citationSources(sources) {
    const items = new Map();
    (Array.isArray(sources) ? sources : []).forEach(function (raw, offset) {
      if (!raw) return;
      const index = Number(raw.citationIndex || raw.citation_index || raw.position || offset + 1);
      if (!Number.isSafeInteger(index) || index < 1 || items.has(index)) return;
      try {
        const url = new URL(typeof raw === "string" ? raw : (raw.url || raw.link || raw.href || ""));
        if (!["https:", "http:"].includes(url.protocol)) return;
        items.set(index, { url: url.href, title: String(raw.title || raw.name || url.hostname) });
      } catch {}
    });
    return items;
  }

  function installCitations(md) {
    function inLiteralHtml(state) {
      const tags = state._citationHtmlTags || (state._citationHtmlTags = []);
      for (let i = state._citationHtmlCursor || 0; i < state.tokens.length; i += 1) {
        const token = state.tokens[i];
        if (token.type !== "html_inline") continue;
        const tag = /^<(\/?)(a|code|pre|kbd|samp|script|style|textarea)(?:\s[^>]*|)>$/i.exec(token.content);
        if (!tag) continue;
        if (tag[1]) {
          const index = tags.lastIndexOf(tag[2].toLowerCase());
          if (index >= 0) tags.splice(index);
        } else if (!/\/\s*>$/.test(token.content)) tags.push(tag[2].toLowerCase());
      }
      state._citationHtmlCursor = state.tokens.length;
      return tags.length > 0;
    }
    md.inline.ruler.before("link", "source_citation", function (state, silent) {
      if (!state.env.citationSources?.size || state.linkLevel > 0 || state.src[state.pos] !== "[") return false;
      const match = /^\[([1-9]\d{0,5})\]/.exec(state.src.slice(state.pos));
      if (!match) return false;
      const end = state.pos + match[0].length;
      // Existing Markdown links, reference links and footnotes keep their semantics.
      const reference = /^\[([^\]]*)\]/.exec(state.src.slice(end));
      if (state.src[end] === "(" || state.env.references?.[match[1]] ||
          (reference && state.env.references?.[md.utils.normalizeReference(reference[1] || match[1])]) || inLiteralHtml(state)) return false;
      const index = Number(match[1]);
      const source = state.env.citationSources.get(index);
      if (!source) return false;
      if (!silent) {
        const token = state.push("source_citation", "a", 0);
        token.meta = { index, source };
      }
      state.pos = end;
      return true;
    });
    md.renderer.rules.source_citation = function (tokens, index) {
      const item = tokens[index].meta;
      const title = md.utils.escapeHtml("参考来源 " + item.index + "：" + item.source.title);
      return '<a class="md-citation" data-citation-index="' + item.index + '" href="' + md.utils.escapeHtml(item.source.url) +
        '" target="_blank" rel="noopener noreferrer nofollow" title="' + title + '" aria-label="' + title + '">' + item.index + '</a>';
    };
  }

  function createMarkdown() {
    if (!window.markdownit || !window.DOMPurify) return null;
    const md = window.markdownit({
      html: true,
      linkify: true,
      breaks: true,
      typographer: false
    });
    if (window.markdownitFootnote) md.use(window.markdownitFootnote);
    if (window.markdownitTaskLists) md.use(window.markdownitTaskLists, { enabled: false, label: true, labelAfter: true });
    installMathPlaceholder(md);
    installCjkEmphasis(md);
    installCitations(md);
    md.renderer.rules.fence = renderFence;

    const defaultLinkOpen = md.renderer.rules.link_open || function (tokens, index, options, env, self) {
      return self.renderToken(tokens, index, options);
    };
    md.renderer.rules.link_open = function (tokens, index, options, env, self) {
      const token = tokens[index];
      const href = token.attrGet("href") || "";
      if (!href.startsWith("#")) {
        token.attrSet("target", "_blank");
        token.attrSet("rel", "noopener noreferrer nofollow");
      }
      return defaultLinkOpen(tokens, index, options, env, self);
    };

    md.renderer.rules.image = function (tokens, index) {
      const token = tokens[index];
      const src = md.utils.escapeHtml(md.normalizeLink(token.attrGet("src") || ""));
      const alt = md.utils.escapeHtml(token.content || "图片");
      const title = token.attrGet("title");
      return '<span class="markdown-image" role="button" tabindex="0" aria-label="放大图片">' +
        '<img src="' + src + '" alt="' + alt + '" loading="lazy" decoding="async"' +
        (title ? ' title="' + md.utils.escapeHtml(title) + '"' : "") + '></span>';
    };

    md.renderer.rules.table_open = function () {
      return '<div class="table-wrapper" role="region" tabindex="0" aria-label="表格，可左右滑动查看"><table>\n';
    };
    md.renderer.rules.table_close = function () {
      return '</table><span class="table-scroll-hint" aria-hidden="true">← 左右滑动查看 →</span></div>\n';
    };
    return md;
  }

  function sanitize(html) {
    return window.DOMPurify.sanitize(html, {
      USE_PROFILES: { html: true },
      ALLOW_DATA_ATTR: true,
      ADD_ATTR: ["target", "rel", "loading", "decoding", "checked", "disabled", "aria-label", "aria-hidden", "role", "tabindex"],
      FORBID_TAGS: ["script", "style", "iframe", "object", "embed", "form"],
      FORBID_ATTR: ["style"]
    });
  }

  function render(source, options = {}) {
    if (!markdown) markdown = createMarkdown();
    if (!markdown) return "";
    return sanitize(markdown.render(String(source || ""), { citationSources: citationSources(options.sources) }));
  }

  function initializeMermaid() {
    if (!window.mermaid) return false;
    const theme = currentTheme();
    if (mermaidInitializedTheme === theme) return true;
    window.mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: theme === "dark" ? "dark" : "neutral",
      fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, sans-serif",
      flowchart: { htmlLabels: false, curve: "basis" },
      suppressErrorRendering: true
    });
    mermaidInitializedTheme = theme;
    return true;
  }

  function loadMermaid() {
    if (window.mermaid) return Promise.resolve(true);
    if (mermaidLoadPromise) return mermaidLoadPromise;
    mermaidLoadPromise = new Promise(function (resolve) {
      const script = document.createElement("script");
      script.src = "/res/vendor/mermaid-11.16.0.min.js";
      script.async = true;
      script.onload = function () { resolve(Boolean(window.mermaid)); };
      script.onerror = function () { resolve(false); };
      document.head.appendChild(script);
    });
    return mermaidLoadPromise;
  }

  async function renderMermaid(root) {
    const scope = root || document;
    const nodes = Array.from(scope.querySelectorAll(".mermaid-diagram:not([data-mermaid-rendered])"));
    if (!nodes.length || !(await loadMermaid()) || !initializeMermaid()) return;
    for (const node of nodes) node.dataset.mermaidRendered = "pending";
    try {
      await window.mermaid.run({ nodes, suppressErrors: true });
      for (const node of nodes) {
        const wrapper = node.closest(".mermaid-block");
        const rendered = Boolean(node.querySelector("svg"));
        node.dataset.mermaidRendered = rendered ? "true" : "error";
        if (wrapper) wrapper.classList.toggle("is-rendered", rendered);
      }
    } catch {
      for (const node of nodes) {
        node.dataset.mermaidRendered = "error";
        node.closest(".mermaid-block")?.classList.add("has-error");
      }
    }
  }

  function refreshOverflow(root) {
    const scope = root || document;
    scope.querySelectorAll(".table-wrapper").forEach(function (wrapper) {
      const table = wrapper.querySelector("table");
      const overflowing = Boolean(table && table.scrollWidth > wrapper.clientWidth + 2);
      wrapper.classList.toggle("is-overflowing", overflowing);
      wrapper.classList.toggle("is-scrolled", wrapper.scrollLeft > 8);
      if (!wrapper.dataset.scrollHintBound) {
        wrapper.dataset.scrollHintBound = "1";
        wrapper.addEventListener("scroll", function () {
          wrapper.classList.toggle("is-scrolled", wrapper.scrollLeft > 8);
        }, { passive: true });
      }
    });
  }

  function enhance(root, options) {
    const scope = root || document;
    const settings = Object.assign({ mermaid: true, icons: true }, options || {});
    requestAnimationFrame(function () { refreshOverflow(scope); });
    if (settings.mermaid) renderMermaid(scope);
    if (settings.icons && window.lucide?.createIcons) requestAnimationFrame(function () { window.lucide.createIcons(); });
  }

  function rerenderMermaid(root) {
    const scope = root || document;
    mermaidInitializedTheme = "";
    scope.querySelectorAll(".mermaid-block").forEach(function (wrapper) {
      const source = decodeText(wrapper.dataset.mermaidSource);
      const target = wrapper.querySelector(".mermaid-diagram");
      if (!target || !source) return;
      target.textContent = source;
      delete target.dataset.mermaidRendered;
      delete target.dataset.processed;
      wrapper.classList.remove("is-rendered", "has-error");
    });
    renderMermaid(scope);
  }

  async function copyText(value) {
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(value);
        return;
      } catch {
        // Some embedded browsers expose Clipboard API but deny it at runtime.
      }
    }
    const area = document.createElement("textarea");
    area.value = value;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }

  function copiedFeedback(button) {
    if (!button) return;
    const original = button.innerHTML;
    button.classList.add("is-copied");
    button.title = "已复制";
    button.innerHTML = '<span aria-hidden="true">✓</span>';
    window.setTimeout(function () {
      button.classList.remove("is-copied");
      button.title = "复制代码";
      button.innerHTML = original;
    }, 1400);
  }

  document.addEventListener("click", function (event) {
    const copyButton = event.target.closest(".code-copy");
    if (copyButton) {
      event.preventDefault();
      const block = copyButton.closest(".code-block, .mermaid-block");
      const value = block?.classList.contains("mermaid-block")
        ? decodeText(block.dataset.mermaidSource)
        : (block?.querySelector("pre code")?.textContent || "");
      copyText(value).then(function () { copiedFeedback(copyButton); }).catch(function () {});
      return;
    }
    const image = event.target.closest(".markdown-image img");
    if (image) {
      event.preventDefault();
      document.dispatchEvent(new CustomEvent("aimarkdown:image", { detail: { src: image.currentSrc || image.src, alt: image.alt || "" } }));
    }
  });

  document.addEventListener("keydown", function (event) {
    const image = event.target.closest?.(".markdown-image");
    if (!image || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    const img = image.querySelector("img");
    if (img) document.dispatchEvent(new CustomEvent("aimarkdown:image", { detail: { src: img.currentSrc || img.src, alt: img.alt || "" } }));
  });

  window.AIMarkdown = {
    render,
    enhance,
    refreshOverflow,
    renderMermaid,
    rerenderMermaid,
    isReady: function () { return Boolean(markdown || createMarkdown()); }
  };
})();
