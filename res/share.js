(() => {
  const $ = (id) => document.getElementById(id);
  const token = decodeURIComponent(location.pathname.split("/").filter(Boolean).pop() || "");

  function formatTime(value) {
    const date = new Date(Number(value || 0) * 1000);
    if (Number.isNaN(date.getTime())) return "";
    return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(date);
  }

  function formatExpiry(value) {
    const remain = Number(value || 0) * 1000 - Date.now();
    if (remain <= 0) return "已过期";
    if (remain >= 86400000) return `还有 ${Math.ceil(remain / 86400000)} 天失效`;
    if (remain >= 3600000) return `还有 ${Math.ceil(remain / 3600000)} 小时失效`;
    return `还有 ${Math.max(1, Math.ceil(remain / 60000))} 分钟失效`;
  }

  function renderMarkdown(root, content) {
    const text = String(content || "");
    try {
      if (window.AIMarkdown?.isReady?.()) {
        const html = window.AIMarkdown.render(text);
        if (html || !text.trim()) {
          root.innerHTML = html;
          window.AIMarkdown.enhance(root, { imagePreview: true });
          return;
        }
      }
    } catch {
      // Keep a malformed message readable instead of blanking the shared page.
    }
    root.classList.add("is-markdown-fallback");
    root.textContent = text;
  }

  function renderMessage(message) {
    const article = document.createElement("article");
    article.className = `share-message ${message.role === "assistant" ? "assistant" : "user"}`;
    const role = document.createElement("div");
    role.className = "share-message-role";
    if (message.role === "assistant") {
      const avatar = document.createElement("img");
      avatar.src = "/res/meimei-avatar.png";
      avatar.alt = "";
      role.append(avatar, document.createTextNode("槑槑"));
    } else {
      role.textContent = "提问";
    }
    const body = document.createElement("div");
    body.className = "share-message-body markdown";
    if (Array.isArray(message.images) && message.images.length) {
      const images = document.createElement("div");
      images.className = "share-images";
      message.images.forEach((image) => {
        const img = document.createElement("img");
        img.src = image.view_url;
        img.alt = image.filename || "对话图片";
        img.loading = "lazy";
        img.addEventListener("click", () => window.open(image.view_url, "_blank", "noopener"));
        images.appendChild(img);
      });
      body.appendChild(images);
    }
    const content = document.createElement("div");
    content.className = "share-message-content";
    renderMarkdown(content, message.content);
    body.appendChild(content);
    if (Array.isArray(message.sources) && message.sources.length) {
      const sources = document.createElement("div");
      sources.className = "share-sources";
      const label = document.createElement("strong");
      label.textContent = "参考来源";
      sources.appendChild(label);
      message.sources.forEach((source, index) => {
        let safeUrl = "";
        try {
          const parsed = new URL(String(source.url || ""));
          if (["http:", "https:"].includes(parsed.protocol)) safeUrl = parsed.href;
        } catch {}
        if (!safeUrl) return;
        const link = document.createElement("a");
        link.href = safeUrl;
        link.target = "_blank";
        link.rel = "noopener noreferrer nofollow";
        link.textContent = `${index + 1}. ${source.title || source.url}`;
        sources.appendChild(link);
      });
      body.appendChild(sources);
    }
    const time = document.createElement("div");
    time.className = "share-message-time";
    time.textContent = formatTime(message.created_at);
    article.append(role, body, time);
    return article;
  }

  async function load() {
    try {
      const response = await fetch(`/api/public/shares/${encodeURIComponent(token)}`, { cache: "no-store" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "链接可能已过期或被关闭。 ");
      const share = data.share || {};
      const snapshot = share.snapshot || {};
      $("shareTitle").textContent = share.title || "一段对话";
      $("shareMeta").textContent = `${snapshot.model_name || snapshot.model || "AI槑槑"} · ${formatTime(snapshot.snapshot_at || share.created_at)} 创建快照`;
      $("shareExpiry").querySelector("span").textContent = formatExpiry(share.expires_at);
      const box = $("shareMessages");
      (snapshot.messages || []).forEach((message) => box.appendChild(renderMessage(message)));
      $("shareLoading").hidden = true;
      $("shareConversation").hidden = false;
      window.lucide?.createIcons?.({ attrs: { "stroke-width": 2, "aria-hidden": "true" } });
    } catch (error) {
      $("shareLoading").hidden = true;
      $("shareErrorText").textContent = error.message || "链接可能已过期或被关闭。";
      $("shareError").hidden = false;
    }
  }
  load();
})();
