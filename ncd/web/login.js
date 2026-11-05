"use strict";

(() => {
  const form = document.getElementById("loginForm");
  const input = document.getElementById("password");
  const button = document.getElementById("loginButton");
  const status = document.getElementById("loginStatus");
  let pending = false;

  function showStatus(message) {
    status.textContent = message;
    status.hidden = !message;
  }

  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (pending || !input.value) return;
    pending = true;
    button.disabled = true;
    showStatus("");
    try {
      const response = await fetch("/ncd/api/login", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: input.value })
      });
      // 密码只在本次请求中使用，提交后不留在输入框或浏览器存储中。
      input.value = "";
      const data = await response.json();
      if (response.ok && data.ok) {
        window.location.replace("/ncd/");
        return;
      }
      showStatus(data.error || "暂时无法进入，请稍后重试。");
    } catch (_error) {
      input.value = "";
      showStatus("连接失败，请稍后重试。");
    } finally {
      pending = false;
      button.disabled = false;
      input.focus();
    }
  });

  input.focus();
})();
