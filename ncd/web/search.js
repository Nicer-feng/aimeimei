"use strict";

(() => {
  const form = document.getElementById("searchForm");
  const input = document.getElementById("query");
  const results = document.getElementById("results");
  const status = document.getElementById("searchStatus");
  const moreRow = document.getElementById("moreRow");
  const moreButton = document.getElementById("loadMore");
  let timer;
  let controller;
  let revision = 0;
  let composing = false;
  let activeQuery = "";
  let page = 0;
  let count = 0;
  let pending = false;

  function showStatus(message) {
    status.textContent = message;
    status.hidden = !message;
  }

  function cancelRequest() {
    clearTimeout(timer);
    revision += 1;
    if (controller) controller.abort();
    controller = undefined;
    pending = false;
    moreButton.disabled = false;
    results.setAttribute("aria-busy", "false");
  }

  function resetResults() {
    results.replaceChildren();
    moreRow.hidden = true;
    activeQuery = "";
    page = 0;
    count = 0;
    showStatus("");
  }

  function paragraph(className, text) {
    const element = document.createElement("p");
    element.className = className;
    element.textContent = text;
    return element;
  }

  function renderItem(item) {
    const article = document.createElement("article");
    article.className = "result";
    const suffix = item.type === "multiple" ? "（多选）" : "";
    article.append(paragraph("question", `${++count}. ${item.question}${suffix}`));
    const options = document.createElement("ul");
    options.className = "options";
    for (const option of item.options) {
      const row = document.createElement("li");
      row.className = "option";
      const key = document.createElement("span");
      key.className = "option-key";
      key.textContent = `${option.key}.`;
      const text = document.createElement("span");
      text.className = "option-text";
      text.textContent = option.text;
      row.append(key, text);
      options.append(row);
    }
    article.append(options);
    const answerText = item.answer_text.filter(Boolean).join("；");
    const detail = answerText ? `（${answerText}）` : "";
    article.append(paragraph("answer", `答案：${item.answer.join("、")}${detail}`));
    return article;
  }

  async function search(append = false) {
    const query = input.value.trim();
    if (composing || (append && pending)) return;
    cancelRequest();
    if (!query) {
      resetResults();
      return;
    }
    if (append && query !== activeQuery) append = false;
    const nextPage = append ? page + 1 : 1;
    if (!append) resetResults();
    const requestRevision = revision;
    controller = new AbortController();
    pending = true;
    moreButton.disabled = true;
    results.setAttribute("aria-busy", "true");
    showStatus("正在搜索…");
    try {
      const params = new URLSearchParams({ q: query, page: String(nextPage) });
      const response = await fetch(`/ncd/api/search?${params}`, {
        credentials: "same-origin",
        cache: "no-store",
        signal: controller.signal
      });
      if (requestRevision !== revision) return;
      if (response.status === 401) {
        window.location.replace("/ncd/");
        return;
      }
      const data = await response.json();
      if (requestRevision !== revision) return;
      if (!response.ok) throw new Error(data.error || "搜索失败，请稍后重试。");
      const fragment = document.createDocumentFragment();
      for (const item of data.items) fragment.append(renderItem(item));
      results.append(fragment);
      activeQuery = query;
      page = data.page;
      moreRow.hidden = !data.has_more;
      showStatus(count ? "" : "未找到匹配题目，请换一段题目或补充选项。");
    } catch (error) {
      if (requestRevision !== revision || error.name === "AbortError") return;
      showStatus(error instanceof TypeError ? "连接失败，请稍后重试。" : error.message);
    } finally {
      if (requestRevision === revision) {
        pending = false;
        moreButton.disabled = false;
        results.setAttribute("aria-busy", "false");
      }
    }
  }

  function scheduleSearch() {
    // 输入一变就撤销旧查询，避免上一道题的答案误留在新题目下。
    cancelRequest();
    resetResults();
    if (!composing && input.value.trim()) timer = setTimeout(() => search(), 300);
  }

  input.addEventListener("compositionstart", () => {
    composing = true;
    cancelRequest();
    resetResults();
  });
  input.addEventListener("compositionend", () => {
    composing = false;
    scheduleSearch();
  });
  input.addEventListener("paste", event => {
    const text = event.clipboardData?.getData("text/plain");
    if (!text) return;
    // 单行输入框默认会删除换行，先替换为空格，保留题干和各选项的分隔。
    event.preventDefault();
    const start = input.selectionStart ?? input.value.length;
    const end = input.selectionEnd ?? start;
    const capacity = Math.max(0, input.maxLength - (input.value.length - end + start));
    const pasted = text.replace(/\r\n?|\n/g, " ").slice(0, capacity);
    input.value = input.value.slice(0, start) + pasted + input.value.slice(end);
    input.setSelectionRange(start + pasted.length, start + pasted.length);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  input.addEventListener("input", scheduleSearch);
  form.addEventListener("submit", event => {
    event.preventDefault();
    if (!composing) search();
  });
  moreButton.addEventListener("click", () => search(true));
  window.addEventListener("pagehide", cancelRequest);
  input.focus();
})();
