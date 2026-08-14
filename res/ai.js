    const $ = (id) => document.getElementById(id);
    const state = {
	      authed: false,
	      user: null,
	      models: [],
	      prompts: [],
	      profiles: [],
	      profileTotals: null,
	      editingProfileId: null,
	      profileDragId: "",
	      profileDisabledByConversation: {},
	      favorites: [],
	      selectedFavoriteId: null,
	      mediaTasks: [],
	      selectedMediaTaskId: null,
	      mediaTab: "summary",
	      mediaUploading: false,
	      mediaPollTimer: null,
	      conversations: [],
	      currentConversation: null,
	      conversationStats: null,
	      messages: [],
	      attachments: [],
	      uploadingImages: false,
	      sending: false,
	      editingConversationId: null,
	      streamMessage: null,
	      streamQueue: "",
	      streamTimer: null,
      streamResolve: null,
	      reasoningClockTimer: 0,
	      activeReasoningMessage: null,
	      newConversationPromise: null,
	      newConversationModelId: "",
	      firstTokenAt: null,
	      abortController: null,
	      userStopped: false,
	      followOutput: true,
	      hasNewWhilePaused: false,
	      programmaticScroll: false,
	      minimapQueued: false,
	      minimapLayoutTimer: 0,
	      lastStreamMinimapAt: 0,
	      messageScrollFrame: 0,
	      pendingMessageScroll: null,
	      messagesScrollFrame: 0,
	      minimapFadeTimer: 0,
	      minimapCollapseTimer: 0,
	      minimapTooltipTimer: 0,
	      chatSelectionActive: false,
	      chatSelectionStartedInMessages: false,
	      activeTextSelection: null,
	      selectionToolbarTimer: 0,
	      pendingQuotes: [],
	      sideDiscussions: [],
	      activeSideDiscussion: null,
	      sideDiscussionMessages: [],
	      sideDiscussionSending: false,
	      sideDiscussionAbortController: null,
	      sideDiscussionWidth: 440,
	      sideDiscussionResize: null,
	      sideDiscussionSeq: 0,
	      globalSearchResults: [],
	      globalSearchQuery: "",
	      globalSearchSelected: 0,
	      globalSearchLoading: false,
	      globalSearchError: "",
	      globalSearchTimer: 0,
	      globalSearchSeq: 0,
	      adminSection: "overview",
	      adminOverview: null,
	      adminModels: [],
	      adminUsers: [],
	      adminSearch: null,
	      tokenStats: null,
	      tokenStatsTab: "users",
	      tokenStatsExpandedUserId: "",
	      tokenStatsExpandedModelId: "",
	      tokenStatsTimer: 0,
	      costStats: null,
	      tokenActivity: null,
	      changelogEntries: [],
	      changelogVersion: "",
	      changelogHasMore: false,
	      changelogFull: false,
	      changelogAnchor: null,
	      versionInfo: null,
	      initialBuildId: "",
	      pendingBuildId: "",
	      versionCheckTimer: 0,
	      versionCheckInFlight: false,
	      versionToastHideTimer: 0,
	      versionSnoozedBuildId: "",
	      versionSnoozedUntil: 0,
	      versionChannel: null,
	      modelPickerFilter: "",
	      modelPickerSelectedIndex: 0,
	      isComposing: false,
	      lastCompositionEndAt: 0,
	      messageSeq: 0,
	      searchConfig: null,
		      adminKey: localStorage.getItem("aiPlatformAdminKey") || "",
		      theme: localStorage.getItem("aiPlatformTheme") || "",
		      accent: localStorage.getItem("aiPlatformAccent") || "pink",
		      fontSize: localStorage.getItem("aiPlatformFontSize") || "medium",
	      composerOpacity: localStorage.getItem("aiPlatformComposerOpacity") || "80",
	      composerBlur: localStorage.getItem("aiPlatformComposerBlur") || "18",
	      sidebarWidth: localStorage.getItem("aiPlatformSidebarWidth") || "322",
	      sidebarToolsOpen: false,
	      petEnabled: false,
	      petAnimationEnabled: true,
	      petPositionX: null,
	      petPositionY: null,
	      petSide: "right",
	      petDragging: false,
	      petPointerId: null,
	      petDragMoved: false,
	      petDragStartX: 0,
	      petDragStartY: 0,
	      petStartX: 0,
	      petStartY: 0,
	      petSuppressClickUntil: 0,
	      petCorrectionFrame: 0
	    };
	    let lucideRefreshQueued = false;
	    $("adminKey").value = state.adminKey;

	    function renderLucideIcons() {
	      if (!window.lucide || typeof window.lucide.createIcons !== "function") return;
	      window.lucide.createIcons({
	        attrs: {
	          "stroke-width": 2,
	          "aria-hidden": "true"
	        }
	      });
	      document.documentElement.classList.add("lucide-ready");
	    }

	    function queueLucideRefresh() {
	      if (lucideRefreshQueued) return;
	      lucideRefreshQueued = true;
	      requestAnimationFrame(() => {
	        lucideRefreshQueued = false;
	        renderLucideIcons();
	      });
	    }

	    function iconMarkup(name, fallback = "") {
	      return '<i data-lucide="' + escapeHTML(name) + '" aria-hidden="true"></i>' + (fallback ? '<span class="icon-fallback">' + escapeHTML(fallback) + '</span>' : "");
	    }

	    function iconLabel(name, label, fallback = "") {
	      return iconMarkup(name, fallback) + '<span>' + escapeHTML(label) + '</span>';
	    }

	    function createIconButton(name, label, options = {}) {
	      const button = document.createElement("button");
	      button.type = "button";
	      const tone = options.primary ? "primary ui-btn ui-btn-primary" : "ui-btn ui-btn-secondary";
	      button.className = tone + (options.danger ? " danger" : "") + " inline-flex items-center gap-2";
	      button.innerHTML = iconLabel(name, label, options.fallback || "");
	      return button;
	    }

	    function createIconOnlyButton(name, title, options = {}) {
	      const button = document.createElement("button");
	      button.type = "button";
	      button.className = (options.className || "ui-icon-btn") + (options.danger ? " danger" : "");
	      button.title = title;
	      button.setAttribute("aria-label", title);
	      button.innerHTML = iconMarkup(name, options.fallback || "");
	      return button;
	    }

	    function createEmptyState(icon, title, description = "", options = {}) {
	      const node = document.createElement("div");
	      node.className = "empty-state" + (options.compact ? " compact" : "");
	      node.innerHTML = iconMarkup(icon, options.fallback || "") + '<strong>' + escapeHTML(title) + '</strong>' + (description ? '<p>' + escapeHTML(description) + '</p>' : "");
	      return node;
	    }

	    window.addEventListener("load", renderLucideIcons, { once: true });

	    function userStorageKey(key) {
	      return state.user?.id ? `aiPlatform:${state.user.id}:${key}` : key;
	    }

	    function getUserStorage(key, fallback = null) {
	      const value = localStorage.getItem(userStorageKey(key));
	      return value === null ? fallback : value;
	    }

	    function setUserStorage(key, value) {
	      localStorage.setItem(userStorageKey(key), value);
	    }

	    function draftStorageKey(conversationId = state.currentConversation?.id || "new") {
	      return userStorageKey("chatDraft:" + String(conversationId || "new"));
	    }

	    function quoteDraftStorageKey(conversationId = state.currentConversation?.id || "new") {
	      return userStorageKey("chatQuotes:" + String(conversationId || "new"));
	    }

	    function normalizedDraftQuote(value) {
	      if (!value || typeof value !== "object") return null;
	      const selectedText = String(value.selected_text || "").trim();
	      const role = value.role === "assistant" ? "assistant" : "user";
	      if (!selectedText) return null;
	      return {
	        session_id: String(value.session_id || state.currentConversation?.id || ""),
	        message_id: Number(value.message_id || 0),
	        message_key: String(value.message_key || ""),
	        role,
	        selected_text: selectedText.slice(0, 12000),
	        created_at: Number(value.created_at || 0)
	      };
	    }

	    function saveCurrentQuotes() {
	      if (!state.user) return;
	      const key = quoteDraftStorageKey();
	      if (state.pendingQuotes.length) {
	        localStorage.setItem(key, JSON.stringify(state.pendingQuotes.slice(0, 3)));
	      } else {
	        localStorage.removeItem(key);
	      }
	    }

	    function restoreCurrentQuotes() {
	      state.pendingQuotes = [];
	      if (!state.user) return renderComposerQuotes();
	      try {
	        const values = JSON.parse(localStorage.getItem(quoteDraftStorageKey()) || "[]");
	        if (Array.isArray(values)) {
	          state.pendingQuotes = values.map(normalizedDraftQuote).filter(Boolean).slice(0, 3);
	        }
	      } catch {}
	      renderComposerQuotes();
	    }

	    function clearCurrentQuotes() {
	      if (state.user) localStorage.removeItem(quoteDraftStorageKey());
	      state.pendingQuotes = [];
	      renderComposerQuotes();
	    }

	    function saveCurrentDraft() {
	      if (!state.user) return;
	      const prompt = $("prompt");
	      if (!prompt) return;
	      const key = draftStorageKey();
	      if (prompt.value) localStorage.setItem(key, prompt.value);
	      else localStorage.removeItem(key);
	      if (state.currentConversation?.id) {
	        setUserStorage("lastConversationId", state.currentConversation.id);
	      }
	      saveCurrentQuotes();
	    }

	    function restoreCurrentDraft() {
	      const prompt = $("prompt");
	      if (!prompt || !state.user) return;
	      prompt.value = localStorage.getItem(draftStorageKey()) || "";
	      restoreCurrentQuotes();
	      autosizePrompt();
	    }

	    function clearCurrentDraft() {
	      if (!state.user) return;
	      localStorage.removeItem(draftStorageKey());
	    }

	    function quoteRoleLabel(role) {
	      return role === "assistant" ? "槑槑回复" : "用户消息";
	    }

	    function removePendingQuote(index) {
	      if (index < 0 || index >= state.pendingQuotes.length) return;
	      state.pendingQuotes.splice(index, 1);
	      saveCurrentQuotes();
	      renderComposerQuotes();
	    }

	    function findQuoteMessage(quote) {
	      if (!quote) return null;
	      if (quote.message_id) {
	        const byId = state.messages.find((item) => Number(item.id || 0) === Number(quote.message_id));
	        if (byId) return byId;
	      }
	      if (quote.message_key) {
	        return state.messages.find((item) => messageKey(item) === quote.message_key) || null;
	      }
	      return null;
	    }

	    function viewPendingQuote(index) {
	      const quote = state.pendingQuotes[index];
	      const message = findQuoteMessage(quote);
	      if (!message) {
	        setStatus("chatStatus", "原消息暂时无法定位，引用内容仍可正常使用。", "");
	        return;
	      }
	      scrollToMessageId(message.id || 0, messageKey(message));
	    }

	    function renderComposerQuotes() {
	      const box = $("composerQuoteList");
	      if (!box) return;
	      box.replaceChildren();
	      box.hidden = !state.pendingQuotes.length;
	      state.pendingQuotes.forEach((quote, index) => {
	        const card = document.createElement("article");
	        card.className = "composer-quote-card";
	        const copy = document.createElement("div");
	        copy.className = "composer-quote-copy";
	        const meta = document.createElement("div");
	        meta.className = "composer-quote-meta";
	        meta.textContent = `${quoteRoleLabel(quote.role)} · ${formatMessageTime(quote.created_at)}`;
	        const text = document.createElement("div");
	        text.className = "composer-quote-text";
	        text.textContent = quote.selected_text;
	        copy.append(meta, text);
	        const actions = document.createElement("div");
	        actions.className = "composer-quote-actions";
	        const view = createIconOnlyButton("locate-fixed", "查看原文", { className: "ui-icon-btn", fallback: "↗" });
	        view.addEventListener("click", () => viewPendingQuote(index));
	        const remove = createIconOnlyButton("x", "移除引用", { className: "ui-icon-btn", fallback: "×" });
	        remove.addEventListener("click", () => removePendingQuote(index));
	        actions.append(view, remove);
	        card.append(copy, actions);
	        box.appendChild(card);
	      });
	      if (state.pendingQuotes.length) {
	        const limit = document.createElement("div");
	        limit.className = "composer-quote-limit";
	        limit.textContent = `${state.pendingQuotes.length}/3 段引用`;
	        box.appendChild(limit);
	      }
	      queueLucideRefresh();
	      syncComposerLayout();
	    }

	    function buildQuotedMessage(question, quotes = state.pendingQuotes) {
	      const cleanQuestion = String(question || "").trim() || "请基于以上引用内容进行分析。";
	      if (!quotes.length) return cleanQuestion;
	      const blocks = quotes.map((quote) => {
	        const body = String(quote.selected_text || "").split(/\r?\n/).map((line) => "> " + line).join("\n");
	        return `【来源：${quoteRoleLabel(quote.role)}】\n${body}\n【引用结束】`;
	      });
	      return `以下是用户从当前会话中引用的内容：\n\n${blocks.join("\n\n")}\n\n用户的新问题：\n${cleanQuestion}`;
	    }

	    function handlePromptInput() {
	      autosizePrompt();
	      saveCurrentDraft();
	    }

	    function applyCurrentUser(user) {
	      state.user = user || null;
	      const label = $("currentUserLabel");
	      if (label) {
	        label.textContent = state.user ? (state.user.display_name || state.user.username) : "未登录";
	      }
	      const role = $("currentUserRole");
	      if (role) role.textContent = state.user?.role === "admin" ? "管理员" : "家庭成员";
	      const meta = $("currentUserMeta");
	      if (meta) {
	        const userName = state.user ? (state.user.display_name || state.user.username) : "未登录";
	        meta.title = `${userName} · ${state.user?.role === "admin" ? "管理员" : "家庭成员"}`;
	      }
	    }

	    function loadUserPreferences() {
	      state.theme = getUserStorage("aiPlatformTheme", localStorage.getItem("aiPlatformTheme") || "");
	      state.accent = getUserStorage("aiPlatformAccent", localStorage.getItem("aiPlatformAccent") || "pink");
	      state.fontSize = getUserStorage("aiPlatformFontSize", localStorage.getItem("aiPlatformFontSize") || "medium");
	      state.composerOpacity = getUserStorage("aiPlatformComposerOpacity", localStorage.getItem("aiPlatformComposerOpacity") || "80");
	      state.composerBlur = getUserStorage("aiPlatformComposerBlur", localStorage.getItem("aiPlatformComposerBlur") || "18");
	      state.sidebarWidth = getUserStorage("aiPlatformSidebarWidth", localStorage.getItem("aiPlatformSidebarWidth") || "322");
	      state.sidebarToolsOpen = getUserStorage("sidebar_tools_open", "0") === "1";
	      const savedPetEnabled = getUserStorage("pet_enabled", null);
	      state.petEnabled = savedPetEnabled === null ? !isSmallScreen() : savedPetEnabled === "1";
	      state.petAnimationEnabled = getUserStorage("pet_animation_enabled", "1") !== "0";
	      const savedPetX = getUserStorage("pet_position_x", "");
	      const savedPetY = getUserStorage("pet_position_y", "");
	      state.petPositionX = savedPetX !== "" && Number.isFinite(Number(savedPetX)) ? Number(savedPetX) : null;
	      state.petPositionY = savedPetY !== "" && Number.isFinite(Number(savedPetY)) ? Number(savedPetY) : null;
	      state.petSide = getUserStorage("pet_side", "right") === "left" ? "left" : "right";
	      loadProfileSessionPrefs();
	      applyInterfaceSettings({ save: false });
	      applyFontSize(state.fontSize);
	      applyTheme(preferredTheme());
	      applySidebarWidth(state.sidebarWidth, false);
	      applySidebarToolsState(state.sidebarToolsOpen, { save: false });
	      applyDesktopPetSettings({ save: false });
	    }

    const accentPresets = {
      pink: {
        label: "马卡龙粉",
        light: {
          accent: "#E9AFC0",
          accentStrong: "#D98FA8",
          accentSoft: "#FCE8EF",
          accentShadow: "rgba(217, 143, 168, .22)",
          focusRing: "rgba(217, 143, 168, .18)",
          userBg: "#fff1f5",
          userLine: "#edc0cd",
          userShadow: "rgba(217, 143, 168, .12)"
        },
        dark: {
          accent: "#f0b9c8",
          accentStrong: "#ffcbd7",
          accentSoft: "#3b2630",
          accentShadow: "rgba(240, 185, 200, .22)",
          focusRing: "rgba(240, 185, 200, .22)",
          userBg: "#3a2632",
          userLine: "#674055",
          userShadow: "rgba(0, 0, 0, .2)"
        }
      },
      mint: {
        label: "薄荷绿",
        light: {
          accent: "#5bb7a8",
          accentStrong: "#318779",
          accentSoft: "#e6f6f2",
          accentShadow: "rgba(91, 183, 168, .2)",
          focusRing: "rgba(91, 183, 168, .18)",
          userBg: "#e9f8f5",
          userLine: "#b9ded7",
          userShadow: "rgba(91, 183, 168, .12)"
        },
        dark: {
          accent: "#83d2c5",
          accentStrong: "#a4e2d9",
          accentSoft: "#203936",
          accentShadow: "rgba(131, 210, 197, .22)",
          focusRing: "rgba(131, 210, 197, .22)",
          userBg: "#203633",
          userLine: "#3f665f",
          userShadow: "rgba(0, 0, 0, .2)"
        }
      },
      sky: {
        label: "天空蓝",
        light: {
          accent: "#76a9e8",
          accentStrong: "#4f80c3",
          accentSoft: "#eaf3ff",
          accentShadow: "rgba(118, 169, 232, .2)",
          focusRing: "rgba(118, 169, 232, .18)",
          userBg: "#edf5ff",
          userLine: "#bdd6f5",
          userShadow: "rgba(118, 169, 232, .12)"
        },
        dark: {
          accent: "#93c3ff",
          accentStrong: "#b5d6ff",
          accentSoft: "#23334a",
          accentShadow: "rgba(147, 195, 255, .22)",
          focusRing: "rgba(147, 195, 255, .22)",
          userBg: "#22324a",
          userLine: "#405d88",
          userShadow: "rgba(0, 0, 0, .2)"
        }
      },
      lavender: {
        label: "薰衣草紫",
        light: {
          accent: "#aa94df",
          accentStrong: "#8068ba",
          accentSoft: "#f2edff",
          accentShadow: "rgba(170, 148, 223, .2)",
          focusRing: "rgba(170, 148, 223, .18)",
          userBg: "#f5f0ff",
          userLine: "#d5c8f1",
          userShadow: "rgba(170, 148, 223, .12)"
        },
        dark: {
          accent: "#c4b3f2",
          accentStrong: "#dbcfff",
          accentSoft: "#312944",
          accentShadow: "rgba(196, 179, 242, .22)",
          focusRing: "rgba(196, 179, 242, .22)",
          userBg: "#302842",
          userLine: "#5a4a7a",
          userShadow: "rgba(0, 0, 0, .2)"
        }
      },
      peach: {
        label: "蜜桃橙",
        light: {
          accent: "#e9a16f",
          accentStrong: "#c87945",
          accentSoft: "#fff0e5",
          accentShadow: "rgba(233, 161, 111, .2)",
          focusRing: "rgba(233, 161, 111, .18)",
          userBg: "#fff4ec",
          userLine: "#efcaad",
          userShadow: "rgba(233, 161, 111, .12)"
        },
        dark: {
          accent: "#f1b98f",
          accentStrong: "#ffd2b5",
          accentSoft: "#3b2c24",
          accentShadow: "rgba(241, 185, 143, .22)",
          focusRing: "rgba(241, 185, 143, .22)",
          userBg: "#3a2b24",
          userLine: "#68503f",
          userShadow: "rgba(0, 0, 0, .2)"
        }
      }
    };

    function preferredTheme() {
      if (state.theme === "light" || state.theme === "dark") return state.theme;
      return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }

    function normalizeHex(value) {
      const match = String(value || "").trim().match(/^#?([0-9a-f]{6})$/i);
      return match ? "#" + match[1].toLowerCase() : "";
    }

    function hexToRgb(hex) {
      const clean = normalizeHex(hex).slice(1);
      return {
        r: parseInt(clean.slice(0, 2), 16),
        g: parseInt(clean.slice(2, 4), 16),
        b: parseInt(clean.slice(4, 6), 16)
      };
    }

    function rgbToHex(rgb) {
      return "#" + [rgb.r, rgb.g, rgb.b].map((value) => {
        return Math.max(0, Math.min(255, Math.round(value))).toString(16).padStart(2, "0");
      }).join("");
    }

    function mixHex(base, target, weight) {
      const a = hexToRgb(base);
      const b = hexToRgb(target);
      return rgbToHex({
        r: a.r * (1 - weight) + b.r * weight,
        g: a.g * (1 - weight) + b.g * weight,
        b: a.b * (1 - weight) + b.b * weight
      });
    }

    function rgbaFromHex(hex, alpha) {
      const rgb = hexToRgb(hex);
      return `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${alpha})`;
    }

    function normalizeAccent(value) {
      if (accentPresets[value]) return value;
      const hex = normalizeHex(value);
      return hex || "pink";
    }

    function accentBaseColor(value = state.accent) {
      const accent = normalizeAccent(value);
      return accentPresets[accent]?.light.accent || accent;
    }

    function buildCustomAccent(hex, theme) {
      const base = normalizeHex(hex) || accentPresets.pink.light.accent;
      if (theme === "dark") {
        return {
          accent: mixHex(base, "#ffffff", .22),
          accentStrong: mixHex(base, "#ffffff", .36),
          accentSoft: mixHex(base, "#151817", .78),
          accentShadow: rgbaFromHex(base, .24),
          focusRing: rgbaFromHex(base, .22),
          userBg: mixHex(base, "#151817", .72),
          userLine: mixHex(base, "#151817", .45),
          userShadow: "rgba(0, 0, 0, .2)"
        };
      }
      return {
        accent: base,
        accentStrong: mixHex(base, "#111827", .22),
        accentSoft: mixHex(base, "#ffffff", .86),
        accentShadow: rgbaFromHex(base, .2),
        focusRing: rgbaFromHex(base, .18),
        userBg: mixHex(base, "#ffffff", .9),
        userLine: mixHex(base, "#ffffff", .58),
        userShadow: rgbaFromHex(base, .12)
      };
    }

    function accentValues(value = state.accent, theme = preferredTheme()) {
      const accent = normalizeAccent(value);
      return accentPresets[accent]?.[theme] || buildCustomAccent(accent, theme);
    }

    function applyAccent(value = state.accent || "pink") {
	      const accent = normalizeAccent(value);
	      state.accent = accent;
	      setUserStorage("aiPlatformAccent", accent);
      const values = accentValues(accent, preferredTheme());
      const root = document.documentElement;
      root.style.setProperty("--accent", values.accent);
      root.style.setProperty("--accent-strong", values.accentStrong);
      root.style.setProperty("--accent-soft", values.accentSoft);
      root.style.setProperty("--accent-shadow", values.accentShadow);
      root.style.setProperty("--focus-ring", values.focusRing);
      root.style.setProperty("--user-bg", values.userBg);
      root.style.setProperty("--user-line", values.userLine);
      root.style.setProperty("--user-shadow", values.userShadow);
      const color = accentBaseColor(accent);
      const button = $("accentToggle");
      if (button) {
        button.style.color = color;
        button.title = "主色调：" + (accentPresets[accent]?.label || "自定义");
      }
      const picker = $("customAccentColor");
      if (picker) picker.value = color;
      renderAccentOptions();
    }

    function applyTheme(theme = preferredTheme()) {
	      state.theme = theme;
	      document.documentElement.dataset.theme = theme;
	      setUserStorage("aiPlatformTheme", theme);
      const button = $("themeToggle");
      if (button) {
        const icon = theme === "dark" ? "sun" : "moon";
        const fallback = theme === "dark" ? "☀" : "◐";
        button.innerHTML = `<i data-lucide="${icon}" aria-hidden="true"></i><span class="icon-fallback">${fallback}</span>`;
        button.setAttribute("aria-label", theme === "dark" ? "切换到浅色模式" : "切换到深色模式");
        button.title = theme === "dark" ? "切换到浅色模式" : "切换到深色模式";
        queueLucideRefresh();
      }
      applyAccent(state.accent || "pink");
      window.AIMarkdown?.rerenderMermaid(document);
    }

    function toggleTheme() {
      applyTheme(preferredTheme() === "dark" ? "light" : "dark");
    }

    const fontSizeOptions = ["small", "medium", "large"];
    const fontSizeLabels = {
      small: "小",
      medium: "中",
      large: "大"
    };
    const fontSizeNames = {
      small: "小",
      medium: "中",
      large: "大"
    };

    function normalizeFontSize(value) {
      return fontSizeOptions.includes(value) ? value : "medium";
    }

    function applyFontSize(value = state.fontSize || "medium") {
	      const size = normalizeFontSize(value);
	      state.fontSize = size;
	      document.documentElement.dataset.fontSize = size;
	      setUserStorage("aiPlatformFontSize", size);
      const button = $("fontSizeToggle");
      if (button) {
        button.textContent = fontSizeLabels[size];
        button.title = "字体大小：" + fontSizeNames[size];
      }
      autosizePrompt();
    }

	    function toggleFontSize() {
	      const current = fontSizeOptions.indexOf(normalizeFontSize(state.fontSize));
	      applyFontSize(fontSizeOptions[(current + 1) % fontSizeOptions.length]);
	    }

	    const interfaceDefaults = {
	      composerOpacity: 80,
	      composerBlur: 18
	    };

	    function clampNumber(value, min, max, fallback) {
	      const number = Number(value);
	      if (!Number.isFinite(number)) return fallback;
	      return Math.max(min, Math.min(max, number));
	    }

	    function updateInterfaceControls(opacity, blur) {
	      const opacityRange = $("composerOpacityRange");
	      const blurRange = $("composerBlurRange");
	      const opacityValue = $("composerOpacityValue");
	      const blurValue = $("composerBlurValue");
	      if (opacityRange) opacityRange.value = String(opacity);
	      if (blurRange) blurRange.value = String(blur);
	      if (opacityValue) opacityValue.textContent = opacity + "%";
	      if (blurValue) blurValue.textContent = blur + "px";
	    }

	    function applyInterfaceSettings(options = {}) {
	      const opacity = Math.round(clampNumber(
	        options.opacity ?? state.composerOpacity,
	        0,
	        100,
	        interfaceDefaults.composerOpacity
	      ));
	      const blur = Math.round(clampNumber(
	        options.blur ?? state.composerBlur,
	        0,
	        30,
	        interfaceDefaults.composerBlur
	      ));
	      state.composerOpacity = String(opacity);
	      state.composerBlur = String(blur);
	      const ratio = opacity / 100;
	      const root = document.documentElement;
	      root.style.setProperty("--composer-glass-opacity", ratio.toFixed(2));
	      root.style.setProperty("--composer-field-opacity", (ratio * .48).toFixed(2));
	      root.style.setProperty("--composer-field-focus-opacity", Math.min(1, ratio * .48 + .08).toFixed(2));
	      root.style.setProperty("--composer-control-opacity", (ratio * .55).toFixed(2));
	      root.style.setProperty("--composer-glass-blur", blur + "px");
	      root.style.setProperty("--composer-field-blur", Math.round(blur * .67) + "px");
	      if (options.save !== false) {
		        setUserStorage("aiPlatformComposerOpacity", String(opacity));
		        setUserStorage("aiPlatformComposerBlur", String(blur));
	      }
	      updateInterfaceControls(opacity, blur);
	    }

	    function openInterfaceSettings() {
	      $("interfacePopover").classList.add("show");
	      $("openInterfaceSettings").classList.add("active");
	      document.body.classList.add("interface-open");
	      closeDesktopPetMenu();
	      setStatus("interfaceStatus", "");
	      updateInterfaceControls(Number(state.composerOpacity), Number(state.composerBlur));
	      updatePetSettingControls();
	    }

	    function closeInterfaceSettings() {
	      $("interfacePopover").classList.remove("show");
	      $("openInterfaceSettings").classList.remove("active");
	      document.body.classList.remove("interface-open");
	      schedulePetPositionCorrection();
	    }

	    function toggleInterfaceSettings(event) {
	      event?.stopPropagation();
	      if ($("interfacePopover").classList.contains("show")) closeInterfaceSettings();
	      else openInterfaceSettings();
	    }

	    function resetInterfaceSettings() {
	      applyInterfaceSettings({
	        opacity: interfaceDefaults.composerOpacity,
	        blur: interfaceDefaults.composerBlur
	      });
	      setStatus("interfaceStatus", "已恢复默认设置", "ok");
	    }

	    function handleInterfaceOutsideClick(event) {
	      const popover = $("interfacePopover");
	      if (!popover.classList.contains("show")) return;
	      if (popover.contains(event.target) || $("openInterfaceSettings").contains(event.target)) return;
	      closeInterfaceSettings();
	    }

	    function petViewportBounds() {
	      const viewport = window.visualViewport;
	      const left = Math.round(viewport?.offsetLeft || 0);
	      const top = Math.round(viewport?.offsetTop || 0);
	      const width = Math.round(viewport?.width || window.innerWidth || document.documentElement.clientWidth);
	      const height = Math.round(viewport?.height || window.innerHeight || document.documentElement.clientHeight);
	      const size = isSmallScreen() ? 48 : 68;
	      const margin = isSmallScreen() ? 10 : 16;
	      return {
	        left: left + margin,
	        top: top + margin,
	        right: left + width - margin,
	        bottom: top + height - margin,
	        width,
	        height,
	        size,
	        maxX: left + width - margin - size,
	        maxY: top + height - margin - size
	      };
	    }

	    function petElementIsVisible(element) {
	      if (!element || element.hidden) return false;
	      const style = getComputedStyle(element);
	      if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return false;
	      const rect = element.getBoundingClientRect();
	      return rect.width > 0 && rect.height > 0;
	    }

	    function petObstacleRects() {
	      const obstacles = [];
	      const composer = document.querySelector(".composer");
	      if (petElementIsVisible(composer)) obstacles.push(composer.getBoundingClientRect());
	      const latest = $("scrollLatest");
	      if (latest?.classList.contains("show") && petElementIsVisible(latest)) obstacles.push(latest.getBoundingClientRect());
	      return obstacles;
	    }

	    function petOverlapsRect(x, y, size, rect, padding = 10) {
	      return x < rect.right + padding && x + size > rect.left - padding && y < rect.bottom + padding && y + size > rect.top - padding;
	    }

	    function avoidPetObstacles(position, bounds) {
	      let { x, y } = position;
	      for (const rect of petObstacleRects()) {
	        if (!petOverlapsRect(x, y, bounds.size, rect)) continue;
	        const above = rect.top - bounds.size - 14;
	        const below = rect.bottom + 14;
	        if (above >= bounds.top) y = above;
	        else if (below <= bounds.maxY) y = below;
	      }
	      return {
	        x: clampNumber(x, bounds.left, bounds.maxX, bounds.maxX),
	        y: clampNumber(y, bounds.top, bounds.maxY, bounds.maxY)
	      };
	    }

	    function defaultPetPosition(bounds = petViewportBounds()) {
	      const composer = document.querySelector(".composer");
	      let y = bounds.maxY;
	      if (petElementIsVisible(composer)) {
	        y = Math.min(y, composer.getBoundingClientRect().top - bounds.size - 18);
	      }
	      return {
	        x: state.petSide === "left" ? bounds.left : bounds.maxX,
	        y: clampNumber(y, bounds.top, bounds.maxY, bounds.maxY)
	      };
	    }

	    function persistPetPosition() {
	      if (!state.user || !Number.isFinite(state.petPositionX) || !Number.isFinite(state.petPositionY)) return;
	      setUserStorage("pet_position_x", String(Math.round(state.petPositionX)));
	      setUserStorage("pet_position_y", String(Math.round(state.petPositionY)));
	      setUserStorage("pet_side", state.petSide);
	    }

	    function placeDesktopPet(x = state.petPositionX, y = state.petPositionY, options = {}) {
	      const pet = $("desktopPet");
	      if (!pet || pet.hidden) return;
	      const bounds = petViewportBounds();
	      const fallback = defaultPetPosition(bounds);
	      const hasX = x !== null && x !== "" && Number.isFinite(Number(x));
	      const hasY = y !== null && y !== "" && Number.isFinite(Number(y));
	      let position = {
	        x: hasX ? Number(x) : fallback.x,
	        y: hasY ? Number(y) : fallback.y
	      };
	      position.x = clampNumber(position.x, bounds.left, bounds.maxX, fallback.x);
	      position.y = clampNumber(position.y, bounds.top, bounds.maxY, fallback.y);
	      if (options.snap) {
	        const center = position.x + bounds.size / 2;
	        const viewportCenter = bounds.left + bounds.width / 2;
	        state.petSide = center <= viewportCenter ? "left" : "right";
	        position.x = state.petSide === "left" ? bounds.left : bounds.maxX;
	      }
	      if (options.avoid !== false) position = avoidPetObstacles(position, bounds);
	      state.petPositionX = Math.round(position.x);
	      state.petPositionY = Math.round(position.y);
	      pet.style.left = state.petPositionX + "px";
	      pet.style.top = state.petPositionY + "px";
	      pet.classList.toggle("side-left", state.petSide === "left");
	      pet.classList.toggle("side-right", state.petSide !== "left");
	      pet.classList.toggle("menu-below", state.petPositionY < bounds.top + 220);
	      if (options.save) persistPetPosition();
	    }

	    function schedulePetPositionCorrection(options = {}) {
	      if (state.petCorrectionFrame) cancelAnimationFrame(state.petCorrectionFrame);
	      state.petCorrectionFrame = requestAnimationFrame(() => {
	        state.petCorrectionFrame = 0;
	        placeDesktopPet(state.petPositionX, state.petPositionY, { avoid: true, save: Boolean(options.save) });
	      });
	    }

	    function updatePetSettingControls() {
	      const enabled = $("petEnabledToggle");
	      const animation = $("petAnimationToggle");
	      if (enabled) enabled.checked = Boolean(state.petEnabled);
	      if (animation) {
	        animation.checked = Boolean(state.petAnimationEnabled);
	        animation.disabled = !state.petEnabled;
	      }
	    }

	    function closeDesktopPetMenu() {
	      const pet = $("desktopPet");
	      const handle = $("desktopPetHandle");
	      pet?.classList.remove("menu-open");
	      handle?.setAttribute("aria-expanded", "false");
	    }

	    function updateDesktopPetVisibility() {
	      const pet = $("desktopPet");
	      if (!pet) return;
	      const appVisible = state.authed && $("appView")?.style.display !== "none";
	      pet.hidden = !state.petEnabled || !appVisible;
	      pet.classList.toggle("animation-enabled", Boolean(state.petAnimationEnabled));
	      updatePetSettingControls();
	      if (pet.hidden) {
	        closeDesktopPetMenu();
	        return;
	      }
	      requestAnimationFrame(() => placeDesktopPet(state.petPositionX, state.petPositionY, { avoid: true }));
	    }

	    function applyDesktopPetSettings(options = {}) {
	      if (options.enabled !== undefined) state.petEnabled = Boolean(options.enabled);
	      if (options.animation !== undefined) state.petAnimationEnabled = Boolean(options.animation);
	      if (options.save !== false && state.user) {
	        setUserStorage("pet_enabled", state.petEnabled ? "1" : "0");
	        setUserStorage("pet_animation_enabled", state.petAnimationEnabled ? "1" : "0");
	      }
	      updateDesktopPetVisibility();
	    }

	    function resetDesktopPetPosition() {
	      state.petSide = "right";
	      state.petPositionX = null;
	      state.petPositionY = null;
	      if (state.user) {
	        localStorage.removeItem(userStorageKey("pet_position_x"));
	        localStorage.removeItem(userStorageKey("pet_position_y"));
	        localStorage.removeItem(userStorageKey("pet_side"));
	      }
	      placeDesktopPet(null, null, { avoid: true, snap: true, save: true });
	      setStatus("interfaceStatus", "已恢复宠物默认位置", "ok");
	    }

	    function toggleDesktopPetMenu() {
	      const pet = $("desktopPet");
	      if (!pet || pet.hidden) return;
	      const opening = !pet.classList.contains("menu-open");
	      pet.classList.toggle("menu-open", opening);
	      $("desktopPetHandle")?.setAttribute("aria-expanded", opening ? "true" : "false");
	      pet.classList.remove("is-bouncing");
	      requestAnimationFrame(() => pet.classList.add("is-bouncing"));
	      setTimeout(() => pet.classList.remove("is-bouncing"), 340);
	      if (opening) queueLucideRefresh();
	    }

	    function startDesktopPetDrag(event) {
	      if (!event.isPrimary || (event.pointerType === "mouse" && event.button !== 0)) return;
	      const pet = $("desktopPet");
	      if (!pet || pet.hidden) return;
	      state.petPointerId = event.pointerId;
	      state.petDragMoved = false;
	      state.petDragStartX = event.clientX;
	      state.petDragStartY = event.clientY;
	      state.petStartX = Number.isFinite(state.petPositionX) ? state.petPositionX : pet.getBoundingClientRect().left;
	      state.petStartY = Number.isFinite(state.petPositionY) ? state.petPositionY : pet.getBoundingClientRect().top;
	      $("desktopPetHandle")?.setPointerCapture?.(event.pointerId);
	    }

	    function moveDesktopPet(event) {
	      if (state.petPointerId !== event.pointerId) return;
	      const dx = event.clientX - state.petDragStartX;
	      const dy = event.clientY - state.petDragStartY;
	      if (!state.petDragMoved && Math.hypot(dx, dy) < 6) return;
	      state.petDragMoved = true;
	      state.petDragging = true;
	      closeDesktopPetMenu();
	      $("desktopPet")?.classList.add("is-dragging");
	      event.preventDefault();
	      placeDesktopPet(state.petStartX + dx, state.petStartY + dy, { avoid: false });
	    }

	    function finishDesktopPetDrag(event) {
	      if (state.petPointerId !== event.pointerId) return;
	      const handle = $("desktopPetHandle");
	      if (handle?.hasPointerCapture?.(event.pointerId)) handle.releasePointerCapture(event.pointerId);
	      state.petPointerId = null;
	      if (state.petDragMoved) {
	        state.petSuppressClickUntil = Date.now() + 420;
	        placeDesktopPet(state.petPositionX, state.petPositionY, { snap: true, avoid: true, save: true });
	      }
	      state.petDragging = false;
	      state.petDragMoved = false;
	      $("desktopPet")?.classList.remove("is-dragging");
	    }

	    function handleDesktopPetClick(event) {
	      if (Date.now() < state.petSuppressClickUntil) {
	        event.preventDefault();
	        return;
	      }
	      toggleDesktopPetMenu();
	    }

	    function handleDesktopPetAction(event) {
	      const button = event.target.closest("[data-pet-action]");
	      if (!button) return;
	      const action = button.dataset.petAction;
	      closeDesktopPetMenu();
	      if (action === "new-chat") $("newChat")?.click();
	      if (action === "scroll-bottom") scrollToLatest("smooth");
	      if (action === "prompts") openPromptLibrary();
	      if (action === "profiles") openProfiles();
	      if (action === "hide") {
	        applyDesktopPetSettings({ enabled: false });
	        setStatus("chatStatus", "桌面宠物已隐藏，可在界面设置中重新开启。", "ok");
	      }
	    }

	    function handleDesktopPetOutsidePointer(event) {
	      const pet = $("desktopPet");
	      if (pet?.classList.contains("menu-open") && !pet.contains(event.target)) closeDesktopPetMenu();
	    }

	    function renderAccentOptions() {
      const box = $("accentPresetList");
      if (!box) return;
      box.innerHTML = "";
      for (const [key, preset] of Object.entries(accentPresets)) {
        const button = document.createElement("button");
        button.className = "accent-option" + (state.accent === key ? " active" : "");
        button.type = "button";
        button.style.setProperty("--swatch", preset.light.accent);
        const swatch = document.createElement("span");
        swatch.className = "accent-swatch";
        const label = document.createElement("span");
        label.textContent = preset.label;
        button.append(swatch, label);
        button.addEventListener("click", () => {
          applyAccent(key);
          setStatus("accentStatus", "已切换为" + preset.label, "ok");
        });
        box.appendChild(button);
      }
      const custom = normalizeHex(state.accent);
      if (custom && !accentPresets[state.accent]) {
        const button = document.createElement("button");
        button.className = "accent-option active";
        button.type = "button";
        button.style.setProperty("--swatch", custom);
        const swatch = document.createElement("span");
        swatch.className = "accent-swatch";
        const label = document.createElement("span");
        label.textContent = "自定义";
        button.append(swatch, label);
        box.appendChild(button);
      }
    }

    function openAccentDialog() {
      $("accentDialog").classList.add("show");
      $("customAccentColor").value = accentBaseColor();
      setStatus("accentStatus", "");
      setDialogOpenState();
      renderAccentOptions();
    }

    function closeAccentDialog() {
      $("accentDialog").classList.remove("show");
      setDialogOpenState();
    }

    function applyCustomAccent() {
      const color = normalizeHex($("customAccentColor").value);
      if (!color) {
        setStatus("accentStatus", "请选择一个颜色。", "err");
        return;
      }
      applyAccent(color);
      setStatus("accentStatus", "已应用自定义颜色", "ok");
    }

    function resetAccent() {
      applyAccent("pink");
      setStatus("accentStatus", "已恢复马卡龙粉", "ok");
    }

	    applyInterfaceSettings({ save: false });
	    applyFontSize(state.fontSize);
	    applyTheme(preferredTheme());

    function setStatus(id, text, kind = "") {
      const el = $(id);
      el.textContent = text || "";
      el.className = "status" + (kind ? " " + kind : "");
    }

    function friendlyError(value, fallback = "刚刚没处理成功，可以稍后再试一次。") {
      const text = String(value?.message || value || "").trim();
      if (!text) return fallback;
	      if (/unauthorized|未登录|登录已过期/i.test(text)) return "登录状态过期了，请重新登录。";
	      if (/password incorrect|密码不对/i.test(text)) return "密码不对，再检查一下。";
	      if (/username and password/i.test(text)) return "请输入账号和密码。";
	      if (/username already exists/i.test(text)) return "这个账号已经存在了。";
	      if (/username invalid/i.test(text)) return "账号只能使用 2-32 位字母、数字、下划线或短横线。";
	      if (/at least one active admin/i.test(text)) return "至少要保留一个可用的管理员账号。";
      if (/model not found|先选择模型|暂无可用模型/i.test(text)) return "还没有可用模型，请先在模型管理里配置。";
      if (/title and content are required/i.test(text)) return "标题和内容都要填写。";
      if (/content too long/i.test(text)) return "内容太长了，稍微精简一下再保存。";
	      if (/only assistant messages can be favorited/i.test(text)) return "只能收藏 AI 的回答。";
	      if (/音视频 OSS|OSS 还没有配置/i.test(text)) return "音视频上传存储还没配置好。";
	      if (/通义听悟还没有配置/i.test(text)) return "通义听悟还没配置好。";
	      if (/文件大小超出限制/i.test(text)) return "文件太大了，换个小一点的文件试试。";
	      if (/暂不支持这个文件格式/i.test(text)) return "这个格式暂时不支持，换 mp3、mp4、m4a 或 wav 试试。";
	      if (/favorite not found|prompt not found|message not found/i.test(text)) return "这条内容已经不存在了，刷新后再看看。";
      if (/upstream content rejected|data_inspection_failed|inappropriate content/i.test(text)) return "上游模型的安全策略拒绝了这次内容，换个问法试试。";
      if (/upstream status 400/i.test(text)) return "上游模型拒绝了这次请求，换个问法或关闭联网搜索试试。";
      if (/Failed to fetch|NetworkError|Load failed|网络/i.test(text)) return "网络连接不太顺，稍后再试一下。";
      if (/aborted|AbortError|停止/i.test(text)) return "已停止生成。";
      if (/invalid json|not found|bad request|server|traceback|exception/i.test(text)) return fallback;
      return text.length > 90 ? fallback : text;
    }

    async function readError(res, fallback) {
      try {
        const data = await res.json();
        return friendlyError(data.error || data.detail || JSON.stringify(data), fallback);
      } catch {
        try {
          return friendlyError(await res.text(), fallback);
        } catch {
          return fallback;
        }
      }
    }

    async function request(path, options = {}) {
      const headers = new Headers(options.headers || {});
      if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
      return fetch(path, { credentials: "same-origin", ...options, headers });
    }

    async function api(path, options = {}) {
      const res = await request(path, options);
	      if (res.status === 401) {
	        state.authed = false;
	        applyCurrentUser(null);
	        showLogin();
	        throw new Error("未登录或登录已过期");
	      }
      return res;
    }

	    const versionBroadcastStorageKey = "aiPlatform:versionBroadcast";

	    function updateVersionMetadata(info) {
	      if (!info || typeof info !== "object") return;
	      state.versionInfo = info;
	      const version = $("systemVersionValue");
	      const build = $("systemBuildValue");
	      const updated = $("systemUpdatedValue");
	      if (version && info.version) version.textContent = info.version;
	      if (build) build.textContent = info.build_id || "未知";
	      if (updated) updated.textContent = info.updated_at || "未知";
	    }

	    function hideVersionUpdateToast() {
	      const toast = $("versionUpdateToast");
	      if (!toast) return;
	      toast.classList.remove("show");
	      if (state.versionToastHideTimer) clearTimeout(state.versionToastHideTimer);
	      state.versionToastHideTimer = setTimeout(() => {
	        if (!toast.classList.contains("show")) toast.hidden = true;
	      }, 220);
	    }

	    function snoozeVersionUpdate() {
	      state.versionSnoozedBuildId = state.pendingBuildId;
	      state.versionSnoozedUntil = Date.now() + 10 * 60 * 1000;
	      hideVersionUpdateToast();
	    }

	    function showVersionUpdateToast(info) {
	      const buildId = String(info?.build_id || "").trim();
	      if (!buildId || buildId === state.initialBuildId) return;
	      state.pendingBuildId = buildId;
	      updateVersionMetadata(info);
	      if (state.versionSnoozedBuildId === buildId && Date.now() < state.versionSnoozedUntil) return;
	      const toast = $("versionUpdateToast");
	      if (!toast || (toast.classList.contains("show") && toast.dataset.buildId === buildId)) return;
	      toast.dataset.buildId = buildId;
	      const meta = $("versionUpdateMeta");
	      if (meta) meta.textContent = [info.version, buildId].filter(Boolean).join(" · ") || "新版本已准备好";
	      if (state.versionToastHideTimer) clearTimeout(state.versionToastHideTimer);
	      toast.hidden = false;
	      requestAnimationFrame(() => toast.classList.add("show"));
	      queueLucideRefresh();
	    }

	    function broadcastVersionUpdate(info) {
	      const message = { type: "version-update", info, nonce: Date.now() + ":" + Math.random() };
	      try {
	        state.versionChannel?.postMessage(message);
	      } catch {}
	      try {
	        localStorage.setItem(versionBroadcastStorageKey, JSON.stringify(message));
	      } catch {}
	    }

	    function receiveVersionUpdate(message) {
	      if (message?.type !== "version-update" || !message.info?.build_id) return;
	      if (!state.initialBuildId) return;
	      if (message.info.build_id !== state.initialBuildId) showVersionUpdateToast(message.info);
	    }

	    async function checkAppVersion() {
	      if (state.versionCheckInFlight) return;
	      state.versionCheckInFlight = true;
	      const controller = new AbortController();
	      const timeout = setTimeout(() => controller.abort(), 8000);
	      try {
	        const res = await request("/api/version?_=" + Date.now(), {
	          cache: "no-store",
	          signal: controller.signal
	        });
	        if (!res.ok) return;
	        const info = await res.json();
	        const buildId = String(info?.build_id || "").trim();
	        if (!buildId) return;
	        updateVersionMetadata(info);
	        if (!state.initialBuildId) {
	          state.initialBuildId = buildId;
	          return;
	        }
	        if (buildId === state.initialBuildId) return;
	        const firstDetection = state.pendingBuildId !== buildId;
	        showVersionUpdateToast(info);
	        if (firstDetection) broadcastVersionUpdate(info);
	      } catch {
	        // 网络错误、超时和临时接口失败都不提示更新。
	      } finally {
	        clearTimeout(timeout);
	        state.versionCheckInFlight = false;
	      }
	    }

	    function initializeVersionMonitoring() {
	      if ("BroadcastChannel" in window) {
	        try {
	          state.versionChannel = new BroadcastChannel("ai-meimei-version");
	          state.versionChannel.addEventListener("message", (event) => receiveVersionUpdate(event.data));
	        } catch {
	          state.versionChannel = null;
	        }
	      }
	      window.addEventListener("storage", (event) => {
	        if (event.key !== versionBroadcastStorageKey || !event.newValue) return;
	        try {
	          receiveVersionUpdate(JSON.parse(event.newValue));
	        } catch {}
	      });
	      document.addEventListener("visibilitychange", () => {
	        if (document.visibilityState === "visible") checkAppVersion();
	      });
	      window.addEventListener("focus", checkAppVersion);
	      window.addEventListener("online", checkAppVersion);
	      state.versionCheckTimer = window.setInterval(() => {
	        if (document.visibilityState === "visible") checkAppVersion();
	      }, 60000);
	      checkAppVersion();
	    }

	    function refreshForVersionUpdate() {
	      if (state.sending && !window.confirm("槑槑还在生成回答，刷新会中断本次生成，是否继续？")) return;
	      saveCurrentDraft();
	      window.location.reload();
	    }

	    async function adminApi(path, options = {}) {
	      state.adminKey = $("adminKey").value.trim();
	      localStorage.setItem("aiPlatformAdminKey", state.adminKey);
	      const headers = new Headers(options.headers || {});
	      headers.set("X-Admin-Key", state.adminKey);
	      return request(path, { ...options, headers });
	    }

	    function hasAdminAccess() {
	      return state.user?.role === "admin" || Boolean($("adminKey").value.trim());
	    }

	    function showLogin() {
	      $("loginView").style.display = "grid";
	      $("appView").style.display = "none";
	      updateDesktopPetVisibility();
	      $("loginUsername").focus();
	    }

    function showApp() {
      $("loginView").style.display = "none";
      $("appView").style.display = "grid";
	  updateDesktopPetVisibility();
      requestAnimationFrame(syncComposerLayout);
      $("prompt").focus();
    }

    function syncViewportHeight() {
      const height = Math.round(window.visualViewport?.height || window.innerHeight || document.documentElement.clientHeight);
      if (height > 0) document.documentElement.style.setProperty("--app-height", height + "px");
    }

    var composerLayoutFrame = 0;
    var composerResizeObserver = null;

    function syncComposerLayout() {
      cancelAnimationFrame(composerLayoutFrame);
      composerLayoutFrame = requestAnimationFrame(() => {
        const composer = document.querySelector(".composer");
        if (!composer) return;
        const rect = composer.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return;
        const messages = $("messages");
        const keepAtBottom = Boolean(messages && state.followOutput && isNearBottom(messages));
        const style = getComputedStyle(composer);
        const bottom = Math.max(0, Number.parseFloat(style.bottom) || 0);
        const safeSpace = Math.ceil(rect.height + bottom + 28);
        const floatOffset = Math.ceil(rect.height + bottom + 16);
        const root = document.documentElement;
        root.style.setProperty("--composer-safe-space", safeSpace + "px");
        root.style.setProperty("--composer-float-offset", floatOffset + "px");
	    schedulePetPositionCorrection();
        if (keepAtBottom) {
          requestAnimationFrame(() => {
            messages.scrollTop = messages.scrollHeight;
            updateScrollLatestButton();
            updateConversationMinimapViewport();
          });
        }
      });
    }

    function observeComposerLayout() {
      const composer = document.querySelector(".composer");
      if (!composer || composerResizeObserver) return;
      if (typeof ResizeObserver === "function") {
        composerResizeObserver = new ResizeObserver(syncComposerLayout);
        composerResizeObserver.observe(composer);
      }
      syncComposerLayout();
    }

    function setDialogOpenState() {
	      const open = ["promptDialog", "profileDialog", "favoriteDialog", "mediaDialog", "accentDialog", "copyDialog", "globalSearchDialog", "modelPickerDialog", "changelogDialog", "confirmDialog"].some((id) => {
        const el = $(id);
        return el && el.classList.contains("show");
      });
      document.body.classList.toggle("dialog-open", open);
	  if (open) closeDesktopPetMenu();
	  else schedulePetPositionCorrection();
    }

	    function isSmallScreen() {
	      return window.matchMedia && window.matchMedia("(max-width: 620px)").matches;
	    }

	    const sidebarWidthDefaults = {
	      min: 286,
	      value: 322
	    };

	    function isSidebarResizableViewport() {
	      return window.matchMedia && window.matchMedia("(min-width: 901px)").matches;
	    }

	    function maxSidebarWidth() {
	      return Math.max(sidebarWidthDefaults.min, Math.floor(window.innerWidth * .5));
	    }

	    function normalizeSidebarWidth(value) {
	      return Math.round(clampNumber(value, sidebarWidthDefaults.min, maxSidebarWidth(), sidebarWidthDefaults.value));
	    }

	    function applySidebarWidth(value = state.sidebarWidth, save = true) {
	      if (!isSidebarResizableViewport()) return;
	      const width = normalizeSidebarWidth(value);
	      state.sidebarWidth = String(width);
	      document.documentElement.style.setProperty("--sidebar-width", width + "px");
		      if (save) setUserStorage("aiPlatformSidebarWidth", String(width));
	      if (typeof handleSideDiscussionViewportChange === "function") handleSideDiscussionViewportChange();
	    }

	    function startSidebarResize(event) {
	      if (!isSidebarResizableViewport() || event.button !== 0) return;
	      if (document.body.classList.contains("sidebar-resizing")) return;
	      event.preventDefault();
	      closeInterfaceSettings();
	      document.body.classList.add("sidebar-resizing");
	      const appLeft = $("appView").getBoundingClientRect().left;
	      const moveEvent = event.type === "mousedown" ? "mousemove" : "pointermove";
	      const upEvent = event.type === "mousedown" ? "mouseup" : "pointerup";
	      const cancelEvent = event.type === "mousedown" ? "mouseleave" : "pointercancel";
	      function widthFromEvent(pointerEvent) {
	        return pointerEvent.clientX - appLeft;
	      }
	      function onMove(pointerEvent) {
	        applySidebarWidth(widthFromEvent(pointerEvent), false);
	      }
	      function onUp(pointerEvent) {
	        applySidebarWidth(widthFromEvent(pointerEvent), true);
	        document.body.classList.remove("sidebar-resizing");
	        document.removeEventListener(moveEvent, onMove);
	        document.removeEventListener(upEvent, onUp);
	        document.removeEventListener(cancelEvent, onUp);
	      }
	      document.addEventListener(moveEvent, onMove);
	      document.addEventListener(upEvent, onUp);
	      document.addEventListener(cancelEvent, onUp);
	      onMove(event);
	    }

	    applySidebarWidth(state.sidebarWidth, false);

	    function handlePromptFocus() {
      if (!isSmallScreen()) return;
      setTimeout(() => {
        if (state.messages.length && isNearBottom()) scrollToLatest("auto");
        $("prompt").scrollIntoView({ block: "nearest", behavior: "smooth" });
      }, 120);
    }

    function isImeEnter(event) {
      if (event.isComposing || state.isComposing || event.keyCode === 229) return true;
      return Date.now() - state.lastCompositionEndAt < 160;
    }

	    async function bootstrap() {
	      try {
	        const me = await request("/api/me");
	        const data = await me.json();
	        if (!data.authenticated) return showLogin();
	        applyCurrentUser(data.user || null);
	        loadUserPreferences();
		        state.authed = true;
		        showApp();
		        await Promise.all([loadModels(), loadSearchConfig(), loadPrompts(), loadProfiles(), loadFavorites(), loadConversations(), health()]);
	      } catch {
	        showLogin();
	      }
    }

    async function health() {
      try {
        const res = await request("/api/health");
        $("health").textContent = res.ok ? "在线" : "异常";
		$("healthStatus")?.classList.toggle("is-offline", !res.ok);
      } catch {
        $("health").textContent = "离线";
		$("healthStatus")?.classList.add("is-offline");
      }
    }

    async function login(event) {
	      event.preventDefault();
	      setStatus("loginStatus", "");
	      const username = $("loginUsername").value.trim();
	      const password = $("loginPassword").value;
	      let res;
	      try {
	        res = await request("/api/login", { method: "POST", body: JSON.stringify({ username, password }) });
      } catch (err) {
        setStatus("loginStatus", friendlyError(err, "现在连不上服务，稍后再试一下。"), "err");
        return;
      }
	      if (!res.ok) {
		setStatus("loginStatus", await readError(res, "密码不对，再检查一下。"), "err");
		return;
	      }
	      const data = await res.json();
		      $("loginPassword").value = "";
		      applyCurrentUser(data.user || null);
		      loadUserPreferences();
		      state.authed = true;
	      showApp();
	      await Promise.all([loadModels(), loadSearchConfig(), loadPrompts(), loadProfiles(), loadFavorites(), loadConversations(), health()]);
	    }

    async function logout() {
	  saveCurrentDraft();
      await request("/api/logout", { method: "POST" });
	      state.authed = false;
	      applyCurrentUser(null);
	      state.currentConversation = null;
	      state.conversationStats = null;
	      state.profiles = [];
	      state.profileTotals = null;
	      state.profileDisabledByConversation = {};
      state.messages = [];
      clearAttachments();
	      closeProfilePopover();
	      closeProfiles();
      showLogin();
    }

	    async function loadModels() {
	      try {
	        const res = await api("/api/models");
	        const data = await res.json();
	        state.models = data.models || [];
	        renderModelSelect();
	        if (!state.currentConversation && state.models.length) {
	          $("chatModel").textContent = "准备使用 " + state.models[0].name;
	        }
	      } catch (err) {
	        state.models = [];
	        renderModelSelect();
	        setStatus("chatStatus", friendlyError(err, "模型列表暂时加载失败。"), "err");
	      }
	    }

	    async function loadSearchConfig() {
	      try {
	        const res = await api("/api/search-config");
	        const data = await res.json();
	        state.searchConfig = data.search || null;
	      } catch {
	        state.searchConfig = null;
	      }
	      renderSearchToggle();
	    }

	    function renderSearchToggle() {
	      const config = state.searchConfig || {};
	      const nativeSearch = Boolean(selectedModel()?.supports_native_web_search || state.currentConversation?.supports_native_web_search);
	      const available = Boolean(config.enabled && (config.configured || nativeSearch));
	      const toggle = $("webSearchToggle");
	      const label = $("webSearchLabel");
	      const mode = config.mode || "auto";
	      const text = label.querySelector("span");
	      toggle.disabled = !available || mode === "always";
	      label.classList.toggle("disabled", !available);
	      if (!available) {
	        toggle.checked = false;
	        if (text) text.textContent = "联网搜索";
	        label.title = config.enabled ? "当前模型需要配置平台搜索 API Key" : "后台未启用联网搜索";
	      } else if (mode === "always") {
	        toggle.checked = true;
	        if (text) text.textContent = "强制联网";
	        label.title = "所有问题都会先联网搜索";
	      } else if (mode === "auto") {
	        toggle.checked = false;
	        if (text) text.textContent = "自动联网";
	        label.title = nativeSearch ? "时效性问题使用百炼原生联网；勾选后可强制本条联网" : "时效性问题会自动搜索；勾选后可强制本条联网";
	      } else {
		        const saved = getUserStorage("aiPlatformWebSearch", localStorage.getItem("aiPlatformWebSearch"));
	        toggle.checked = saved === null ? true : saved === "1";
	        if (text) text.textContent = "联网搜索";
	        label.title = "使用 " + config.provider + " 联网搜索";
	      }
	    }

	    function renderModelSelect() {
      const select = $("modelSelect");
      select.innerHTML = "";
      if (!state.models.length) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "暂无可用模型";
        select.appendChild(opt);
        syncModelPickerButton();
        renderModelPickerList();
        return;
      }
      for (const model of state.models) {
        const opt = document.createElement("option");
        opt.value = model.id;
        opt.textContent = model.name + (model.supports_vision ? " · 可看图" : "") + " · " + model.model;
        select.appendChild(opt);
      }
      if (state.currentConversation) {
        select.value = state.currentConversation.model_id;
      }
      updateVisionUI();
      syncModelPickerButton();
      renderModelPickerList();
    }

    function selectedModel() {
      const id = $("modelSelect")?.value || state.currentConversation?.model_id || "";
      return state.models.find((model) => model.id === id) || null;
    }

    function modelProviderLabel(model) {
      const raw = String(model?.provider || model?.name || model?.model || "").trim();
      if (/小米|mimo|MiMo/i.test(raw)) return "小米";
      if (/qwen|通义|aliyun|阿里/i.test(raw)) return "Qwen";
      if (/deepseek|深度求索/i.test(raw)) return "DeepSeek";
      if (/kimi|moonshot|月之暗面/i.test(raw)) return "Kimi";
      if (/openai|gpt/i.test(raw)) return "OpenAI";
      if (/claude|anthropic/i.test(raw)) return "Claude";
      return raw || "模型";
    }

    function modelCapabilityTags(model) {
      const text = [model?.name, model?.provider, model?.model].join(" ").toLowerCase();
      const tags = [];
      if (model?.supports_vision) tags.push({ icon: "image", label: "可看图" });
      if (model?.supports_native_web_search) tags.push({ icon: "globe-2", label: "原生联网" });
      if (/reason|thinking|r1|推理|思考|qwq/.test(text)) tags.push({ icon: "brain", label: "推理" });
      if (/flash|turbo|lite|mini|fast|快速|speed/.test(text)) tags.push({ icon: "zap", label: "快速" });
      if (/max|pro|主力|旗舰|plus/.test(text)) tags.push({ icon: "sparkles", label: "主力" });
      return tags.slice(0, 4);
    }

    function modelSearchText(model) {
      return [model?.name, model?.model, model?.provider, modelProviderLabel(model), ...modelCapabilityTags(model).map((tag) => tag.label)]
        .join(" ")
        .toLowerCase();
    }

    function filteredModels() {
      const query = String(state.modelPickerFilter || "").trim().toLowerCase();
      if (!query) return state.models.slice();
      return state.models.filter((model) => modelSearchText(model).includes(query));
    }

    function syncModelPickerButton() {
      const button = $("modelPickerButton");
      const name = $("modelPickerName");
      const code = $("modelPickerCode");
      if (!button || !name || !code) return;
      const model = selectedModel();
      button.disabled = !state.models.length;
      name.textContent = model ? model.name : "选择模型";
      code.textContent = model ? model.model : (state.models.length ? "请选择一个模型" : "暂无可用模型");
      button.title = model ? `${model.name} · ${modelProviderLabel(model)} · ${model.model}` : "选择模型";
    }

    function positionModelPickerPopover() {
      const popover = $("modelPickerPopover");
      const button = $("modelPickerButton");
      if (!popover || !button || isSmallScreen()) return;
      const rect = button.getBoundingClientRect();
      const width = Math.min(430, window.innerWidth - 24);
      const left = clampNumber(rect.left, 12, Math.max(12, window.innerWidth - width - 12), 12);
      const maxTop = Math.max(12, window.innerHeight - Math.min(560, window.innerHeight * .7) - 12);
      const preferredTop = rect.top - 10 - Math.min(560, window.innerHeight * .7);
      const belowTop = rect.bottom + 10;
      popover.style.width = width + "px";
      popover.style.left = left + "px";
      popover.style.top = (preferredTop > 12 ? preferredTop : Math.min(belowTop, maxTop)) + "px";
      popover.style.bottom = "auto";
    }

    function openModelPicker() {
      if (!state.models.length) return;
      closeInterfaceSettings();
      const dialog = $("modelPickerDialog");
      const button = $("modelPickerButton");
      const search = $("modelPickerSearch");
      if (!dialog || !button || !search) return;
      state.modelPickerFilter = "";
      search.value = "";
      const currentId = $("modelSelect").value;
      const list = filteredModels();
      state.modelPickerSelectedIndex = Math.max(0, list.findIndex((model) => model.id === currentId));
      dialog.classList.add("show");
      button.setAttribute("aria-expanded", "true");
      positionModelPickerPopover();
      renderModelPickerList();
      setDialogOpenState();
      if (!isSmallScreen()) {
        setTimeout(() => search.focus(), 40);
      }
    }

    function closeModelPicker() {
      const dialog = $("modelPickerDialog");
      const button = $("modelPickerButton");
      if (dialog) dialog.classList.remove("show");
      if (button) button.setAttribute("aria-expanded", "false");
      setDialogOpenState();
    }

    function renderModelPickerList() {
      const box = $("modelPickerList");
      if (!box) return;
      const models = filteredModels();
      box.replaceChildren();
      if (!models.length) {
        box.appendChild(createEmptyState("search", "没有找到模型", "换个关键词试试看。", { compact: true }));
        queueLucideRefresh();
        return;
      }
      state.modelPickerSelectedIndex = clampNumber(state.modelPickerSelectedIndex, 0, models.length - 1, 0);
      const currentId = $("modelSelect")?.value || "";
      for (const [index, model] of models.entries()) {
        const selected = model.id === currentId;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "model-option" + (selected ? " selected" : "") + (index === state.modelPickerSelectedIndex ? " active" : "");
        button.setAttribute("role", "option");
        button.setAttribute("aria-selected", selected ? "true" : "false");
        const tags = modelCapabilityTags(model);
        button.innerHTML =
          '<span class="model-option-main">' +
            '<span class="model-option-title"><strong>' + escapeHTML(model.name) + '</strong><span class="model-provider">' + escapeHTML(modelProviderLabel(model)) + '</span></span>' +
            '<span class="model-code-line">' + escapeHTML(model.model) + '</span>' +
            '<span class="model-tags">' + tags.map((tag) => '<span class="model-tag">' + iconMarkup(tag.icon) + '<span>' + escapeHTML(tag.label) + '</span></span>').join("") + '</span>' +
          '</span>' +
          '<span class="model-check">' + iconMarkup("check", "✓") + '</span>';
        button.addEventListener("mouseenter", () => setModelPickerSelectedIndex(index));
        button.addEventListener("click", () => chooseModel(model.id));
        box.appendChild(button);
      }
      queueLucideRefresh();
      scrollActiveModelOptionIntoView();
    }

    function scrollActiveModelOptionIntoView() {
      const active = $("modelPickerList")?.querySelector(".model-option.active");
      if (active) active.scrollIntoView({ block: "nearest" });
    }

    function setModelPickerSelectedIndex(index) {
      const models = filteredModels();
      if (!models.length) return;
      state.modelPickerSelectedIndex = clampNumber(index, 0, models.length - 1, 0);
      const items = $("modelPickerList")?.querySelectorAll(".model-option") || [];
      items.forEach((node, itemIndex) => node.classList.toggle("active", itemIndex === state.modelPickerSelectedIndex));
      scrollActiveModelOptionIntoView();
    }

    function moveModelPickerSelection(delta) {
      const models = filteredModels();
      if (!models.length) return;
      setModelPickerSelectedIndex((state.modelPickerSelectedIndex + delta + models.length) % models.length);
    }

    async function updateCurrentConversationModel(modelId) {
      if (!state.currentConversation) return false;
      const model = state.models.find((item) => item.id === modelId);
      if (!model) return false;
      const res = await api(`/api/conversations/${state.currentConversation.id}`, {
        method: "PATCH",
        body: JSON.stringify({ model_id: modelId })
      });
      if (!res.ok) {
        setStatus("chatStatus", await readError(res, "切换模型失败，稍后再试一下。"), "err");
        return false;
      }
      const data = await res.json();
      state.currentConversation = data.conversation || {
        ...state.currentConversation,
        model_id: model.id,
        model_name: model.name,
        model: model.model,
        supports_vision: Boolean(model.supports_vision),
        supports_native_web_search: Boolean(model.supports_native_web_search)
      };
      upsertConversation(state.currentConversation);
      $("modelSelect").value = state.currentConversation.model_id;
      updateChatHeader();
      await loadConversationStats(state.currentConversation.id);
      updateVisionUI();
      renderSearchToggle();
      return true;
    }

    function hasCurrentConversationHistory() {
      return state.messages.some((message) => message && message.role !== "system" && (message.content || message.id || message.images?.length));
    }

    async function chooseModel(modelId) {
      const select = $("modelSelect");
      const model = state.models.find((item) => item.id === modelId);
      if (!select || !model) return;
      closeModelPicker();
      if (state.sending) {
        setStatus("chatStatus", "槑槑还在回复，等这条生成完再切换模型。", "err");
        return;
      }
      const previousId = select.value || state.currentConversation?.model_id || "";
      if (previousId === modelId) {
        syncModelPickerButton();
        $("prompt").focus();
        return;
      }
      if (state.currentConversation) {
        if (hasCurrentConversationHistory()) {
          const action = await confirmAction({
            title: "切换这个对话的模型？",
            message: "当前对话已有历史内容。可以让 " + model.name + " 读取这段上下文继续聊，也可以新建一个空对话使用它。",
            confirmText: "当前对话继续",
            secondaryText: "新建对话",
            cancelText: "取消"
          });
          if (action === true) {
            if (await updateCurrentConversationModel(modelId)) {
              setStatus("chatStatus", "已切换到 " + model.name + "，会带着当前上下文继续。", "ok");
            }
          } else if (action === "secondary") {
            await newConversation(modelId);
            setStatus("chatStatus", "已新建对话，准备使用 " + model.name + "。", "ok");
          } else {
            select.value = previousId;
            syncModelPickerButton();
            renderModelPickerList();
          }
        } else {
          if (await updateCurrentConversationModel(modelId)) {
            setStatus("chatStatus", "已切换到 " + model.name + "。", "ok");
          }
        }
        if (state.attachments.length && !selectedModelSupportsVision()) {
          setStatus("chatStatus", "当前模型不支持图片理解，请切换支持图片的模型。", "err");
        }
        $("prompt").focus();
        return;
      }
      select.value = modelId;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      if (!state.currentConversation) {
        $("chatModel").textContent = "准备使用 " + model.name;
      }
      setStatus("chatStatus", "已选择 " + model.name + "，新对话会使用它。", "ok");
      $("prompt").focus();
    }

    function handleModelPickerSearchInput() {
      state.modelPickerFilter = $("modelPickerSearch").value.trim();
      const models = filteredModels();
      const currentId = $("modelSelect").value;
      const currentIndex = models.findIndex((model) => model.id === currentId);
      state.modelPickerSelectedIndex = currentIndex >= 0 ? currentIndex : 0;
      renderModelPickerList();
    }

    function handleModelPickerKeydown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeModelPicker();
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        moveModelPickerSelection(1);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        moveModelPickerSelection(-1);
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        const model = filteredModels()[state.modelPickerSelectedIndex];
        if (model) chooseModel(model.id);
      }
    }

    function selectedModelSupportsVision() {
      return Boolean(selectedModel()?.supports_vision);
    }

    function updateVisionUI() {
      const button = $("attachImage");
      if (!button) return;
      const model = selectedModel();
      const supported = Boolean(model?.supports_vision);
      button.disabled = !supported || state.uploadingImages || state.sending;
      button.title = supported ? "上传图片" : "当前模型不支持图片理解，请切换支持图片的模型。";
      button.setAttribute("aria-label", button.title);
    }

	    async function loadPrompts() {
	      try {
	        const res = await api("/api/prompts");
	        const data = await res.json();
	        state.prompts = data.prompts || [];
	        renderPromptLibrary();
	      } catch (err) {
	        state.prompts = [];
	        setStatus("promptLibraryStatus", friendlyError(err, "提示词暂时加载失败。"), "err");
	      }
	    }

	    function insertPromptText(text) {
	      $("prompt").value = String(text || "");
	      autosizePrompt();
	      $("prompt").focus();
	    }

	    function openPromptLibrary() {
	      $("promptDialog").classList.add("show");
	      setDialogOpenState();
	      renderPromptLibrary();
	    }

	    function closePromptLibrary() {
	      $("promptDialog").classList.remove("show");
	      setDialogOpenState();
	    }

	    function renderPromptLibrary() {
	      const box = $("promptLibraryList");
	      if (!box) return;
	      box.innerHTML = "";
	      if (!state.prompts.length) {
	        box.appendChild(createEmptyState("book-open", "还没有提示词", "右侧可以新增一个常用模板。", { compact: true }));
	        queueLucideRefresh();
	        return;
	      }
	      for (const item of state.prompts) {
	        const card = document.createElement("article");
	        card.className = "library-card";
	        const title = document.createElement("strong");
	        title.textContent = item.title;
	        const content = document.createElement("p");
	        content.textContent = item.content;
	        const meta = document.createElement("div");
	        meta.className = "library-card-meta";
	        meta.textContent = "排序 " + item.sort_order + " · " + formatTime(item.updated_at);
	        const actions = document.createElement("div");
	        actions.className = "library-actions";
		        const use = createIconButton("corner-down-left", "填入输入框", { primary: true, fallback: "↵" });
		        use.addEventListener("click", () => {
		          insertPromptText(item.content);
		          closePromptLibrary();
		        });
		        const edit = createIconButton("pencil", "编辑", { fallback: "✎" });
		        edit.addEventListener("click", () => fillPromptForm(item));
		        const del = createIconButton("trash-2", "删除", { danger: true, fallback: "删" });
		        del.addEventListener("click", () => deletePromptTemplate(item.id, item.title));
		        actions.append(use, edit, del);
		        card.append(title, content, meta, actions);
		        box.appendChild(card);
		      }
		      queueLucideRefresh();
		    }

	    function fillPromptForm(item) {
	      $("editingPromptId").value = item.id || "";
	      $("promptTitle").value = item.title || "";
	      $("promptContent").value = item.content || "";
	      $("promptSortOrder").value = item.sort_order ?? 100;
	      setStatus("promptLibraryStatus", "正在编辑：" + (item.title || ""), "");
	    }

	    function resetPromptForm() {
	      $("editingPromptId").value = "";
	      $("promptTitle").value = "";
	      $("promptContent").value = "";
	      $("promptSortOrder").value = "100";
	      setStatus("promptLibraryStatus", "");
	    }

	    async function savePromptTemplate() {
	      const id = $("editingPromptId").value;
	      const body = {
	        title: $("promptTitle").value.trim(),
	        content: $("promptContent").value.trim(),
	        sort_order: Number($("promptSortOrder").value || 100)
	      };
	      if (!body.title || !body.content) {
	        setStatus("promptLibraryStatus", "标题和内容都要填写。", "err");
	        return;
	      }
	      const res = await api(id ? `/api/prompts/${id}` : "/api/prompts", {
	        method: id ? "PUT" : "POST",
	        body: JSON.stringify(body)
	      });
	      if (!res.ok) {
	        setStatus("promptLibraryStatus", await readError(res, "提示词保存失败，稍后再试一下。"), "err");
	        return;
	      }
	      resetPromptForm();
	      setStatus("promptLibraryStatus", "提示词已保存", "ok");
	      await loadPrompts();
	      if (!state.messages.length) renderEmpty();
	    }

	    async function deletePromptTemplate(id, title) {
	      const ok = await confirmAction({
	        title: "删除提示词",
	        message: `确定删除“${title}”吗？`,
	        confirmText: "删除",
	        danger: true
	      });
	      if (!ok) return;
	      const res = await api(`/api/prompts/${id}`, { method: "DELETE" });
	      if (!res.ok) {
	        setStatus("promptLibraryStatus", await readError(res, "删除提示词失败，稍后再试一下。"), "err");
	        return;
	      }
	      setStatus("promptLibraryStatus", "提示词已删除", "ok");
	      await loadPrompts();
	      if (!state.messages.length) renderEmpty();
	    }

	    function estimateClientTokens(text) {
	      const value = String(text || "");
	      let cjk = 0;
	      for (const char of value) {
	        if (char >= "\u4e00" && char <= "\u9fff") cjk++;
	      }
	      const other = Math.max(0, value.length - cjk);
	      return Math.max(0, Math.round(cjk * .8 + other / 4));
	    }

	    function enabledProfiles() {
	      return state.profiles.filter((item) => item.enabled && String(item.content || "").trim());
	    }

	    function profileTextStats(title, content) {
	      const text = [title, content].filter(Boolean).join("\n");
	      return {
	        chars: text.length,
	        tokens: estimateClientTokens(text)
	      };
	    }

	    function currentProfileTotals() {
	      const profiles = enabledProfiles();
	      const text = profiles.map((item) => [item.title, item.content].join("\n")).join("\n");
	      return {
	        enabled_count: profiles.length,
	        total_count: state.profiles.length,
	        char_count: text.length,
	        token_estimate: estimateClientTokens(text)
	      };
	    }

	    function loadProfileSessionPrefs() {
	      try {
	        state.profileDisabledByConversation = JSON.parse(getUserStorage("aiPlatformProfileDisabledByConversation", "{}") || "{}") || {};
	      } catch {
	        state.profileDisabledByConversation = {};
	      }
	    }

	    function saveProfileSessionPrefs() {
	      setUserStorage("aiPlatformProfileDisabledByConversation", JSON.stringify(state.profileDisabledByConversation || {}));
	    }

	    function profileDisabledForConversation(id = state.currentConversation?.id) {
	      return Boolean(id && state.profileDisabledByConversation?.[id]);
	    }

	    function setProfileDisabledForCurrentConversation(disabled) {
	      const id = state.currentConversation?.id;
	      if (!id) {
	        const checkbox = $("disableProfileForConversation");
	        if (checkbox) checkbox.checked = false;
	        setStatus("chatStatus", "先进入一个对话，再设置本次是否加载 AI档案。", "err");
	        return;
	      }
	      if (disabled) state.profileDisabledByConversation[id] = true;
	      else delete state.profileDisabledByConversation[id];
	      saveProfileSessionPrefs();
	      renderProfileStatus();
	      renderProfilePopover();
	    }

	    function updateProfileEditorMeta() {
	      const meta = $("profileEditorMeta");
	      if (!meta) return;
	      const stats = profileTextStats($("profileTitle").value.trim(), $("profileContent").value.trim());
	      meta.textContent = stats.chars + " 字 · 约 " + stats.tokens + " Token";
	    }

	    function updateProfileSummary() {
	      const totals = state.profileTotals || currentProfileTotals();
	      const summary = $("profileSummary");
	      const warning = $("profileWarning");
	      if (summary) {
	        summary.textContent = "当前 Profile：已启用 " + Number(totals.enabled_count || 0) + " 条 · 约 " + Number(totals.token_estimate || 0) + " Token";
	      }
	      if (warning) warning.hidden = Number(totals.token_estimate || 0) <= 1000;
	    }

	    function renderProfileStatus() {
	      const button = $("profileStatus");
	      if (!button) return;
	      const label = button.querySelector("span") || button;
	      const enabledCount = enabledProfiles().length;
	      const disabled = profileDisabledForConversation();
	      button.classList.toggle("disabled", disabled || !enabledCount);
	      if (disabled) {
	        label.textContent = "本次未加载 AI档案";
	        button.title = "当前会话已关闭 AI档案加载";
	      } else if (enabledCount) {
	        label.textContent = "本次已加载 AI档案（" + enabledCount + "条）";
	        button.title = "聊天时会自动参考已启用的 AI档案";
	      } else {
	        label.textContent = "AI档案未设置";
	        button.title = "点击管理长期档案";
	      }
	      queueLucideRefresh();
	    }

	    function renderProfilePopover() {
	      const list = $("profileLoadedList");
	      if (!list) return;
	      const profiles = enabledProfiles();
	      const disabled = profileDisabledForConversation();
	      const checkbox = $("disableProfileForConversation");
	      const meta = $("profilePopoverMeta");
	      list.innerHTML = "";
	      if (checkbox) {
	        checkbox.checked = disabled;
	        checkbox.disabled = !state.currentConversation;
	      }
	      if (meta) {
	        meta.textContent = profiles.length ? (profiles.length + " 条 · 约 " + currentProfileTotals().token_estimate + " Token") : "0 条";
	      }
	      if (!profiles.length) {
	        list.appendChild(createEmptyState("brain", "还没有启用的 AI档案", "可以在左侧菜单的“AI档案”里添加。", { compact: true }));
	      } else {
	        for (const item of profiles) {
	          const row = document.createElement("label");
	          row.className = "profile-switch";
	          const input = document.createElement("input");
	          input.type = "checkbox";
	          input.checked = !disabled;
	          input.disabled = true;
	          const text = document.createElement("span");
	          text.textContent = item.title;
	          row.title = item.content || item.title;
	          row.append(input, text);
	          list.appendChild(row);
	        }
	      }
	      queueLucideRefresh();
	    }

	    function openProfilePopover(event) {
	      event?.stopPropagation();
	      const popover = $("profilePopover");
	      if (!popover) return;
	      renderProfilePopover();
	      popover.classList.add("show");
	      setDialogOpenState();
	    }

	    function closeProfilePopover() {
	      const popover = $("profilePopover");
	      if (!popover) return;
	      popover.classList.remove("show");
	      setDialogOpenState();
	    }

	    function toggleProfilePopover(event) {
	      const popover = $("profilePopover");
	      if (popover?.classList.contains("show")) closeProfilePopover();
	      else openProfilePopover(event);
	    }

	    function handleProfileOutsideClick(event) {
	      const popover = $("profilePopover");
	      if (!popover || !popover.classList.contains("show")) return;
	      if (popover.contains(event.target) || $("profileStatus")?.contains(event.target)) return;
	      closeProfilePopover();
	    }

	    function applyProfilesPayload(data) {
	      state.profiles = data.profiles || [];
	      state.profileTotals = data.totals || currentProfileTotals();
	      renderProfileList();
	      updateProfileSummary();
	      renderProfileStatus();
	      renderProfilePopover();
	    }

	    async function loadProfiles() {
	      try {
	        const res = await api("/api/profiles");
	        const data = await res.json();
	        applyProfilesPayload(data);
	      } catch (err) {
	        state.profiles = [];
	        state.profileTotals = null;
	        renderProfileList(friendlyError(err, "AI档案暂时加载失败。"));
	        renderProfileStatus();
	      }
	    }

	    async function openProfiles() {
	      $("profileDialog").classList.add("show");
	      setDialogOpenState();
	      resetProfileForm(false);
	      await loadProfiles();
	    }

	    function closeProfiles() {
	      $("profileDialog").classList.remove("show");
	      setDialogOpenState();
	    }

	    function renderProfileList(errorText = "") {
	      const box = $("profileList");
	      if (!box) return;
	      box.innerHTML = "";
	      if (errorText) {
	        box.appendChild(createEmptyState("alert-circle", "AI档案加载失败", errorText, { compact: true }));
	        queueLucideRefresh();
	        return;
	      }
	      if (!state.profiles.length) {
	        box.appendChild(createEmptyState("user-round-cog", "还没有 AI档案", "先添加职业、输出风格或常用平台，让槑槑更懂你。", { compact: true }));
	        queueLucideRefresh();
	        return;
	      }
	      for (const item of state.profiles) {
	        const card = document.createElement("article");
	        card.className = "library-card profile-card" + (item.enabled ? "" : " disabled");
	        card.draggable = true;
	        card.dataset.id = item.id;
	        card.addEventListener("dragstart", (event) => {
	          state.profileDragId = item.id;
	          card.classList.add("dragging");
	          event.dataTransfer.effectAllowed = "move";
	          event.dataTransfer.setData("text/plain", item.id);
	        });
	        card.addEventListener("dragend", () => {
	          state.profileDragId = "";
	          card.classList.remove("dragging");
	        });
	        card.addEventListener("dragover", (event) => {
	          event.preventDefault();
	          event.dataTransfer.dropEffect = "move";
	        });
	        card.addEventListener("drop", (event) => {
	          event.preventDefault();
	          moveProfileBefore(item.id);
	        });

	        const head = document.createElement("div");
	        head.className = "profile-card-head";
	        const titleBox = document.createElement("div");
	        titleBox.className = "profile-card-title";
	        const title = document.createElement("strong");
	        title.textContent = item.title || "未命名档案";
	        const stats = profileTextStats(item.title, item.content);
	        const meta = document.createElement("span");
	        meta.className = "library-card-meta";
	        meta.textContent = item.type + " · " + stats.chars + " 字 · 约 " + stats.tokens + " Token";
	        titleBox.append(title, meta);
	        const toggle = document.createElement("label");
	        toggle.className = "profile-switch";
	        const toggleInput = document.createElement("input");
	        toggleInput.type = "checkbox";
	        toggleInput.checked = Boolean(item.enabled);
	        toggleInput.addEventListener("change", () => toggleProfileEnabled(item.id, toggleInput.checked));
	        const toggleText = document.createElement("span");
	        toggleText.textContent = item.enabled ? "启用" : "停用";
	        toggle.append(toggleInput, toggleText);
	        head.append(titleBox, toggle);

	        const content = document.createElement("p");
	        content.className = "profile-card-content";
	        content.textContent = item.content || "";
	        const footer = document.createElement("div");
	        footer.className = "library-actions";
	        const edit = createIconButton("pencil", "编辑", { fallback: "✎" });
	        edit.addEventListener("click", () => fillProfileForm(item));
	        const del = createIconButton("trash-2", "删除", { danger: true, fallback: "删" });
	        del.addEventListener("click", () => deleteProfile(item.id, item.title));
	        const grip = document.createElement("span");
	        grip.className = "library-card-meta";
	        grip.innerHTML = iconLabel("grip-vertical", "拖拽排序");
	        footer.append(edit, del, grip);
	        card.append(head, content, footer);
	        box.appendChild(card);
	      }
	      queueLucideRefresh();
	    }

	    function moveProfileBefore(targetId) {
	      const dragId = state.profileDragId;
	      if (!dragId || dragId === targetId) return;
	      const list = state.profiles.slice();
	      const from = list.findIndex((item) => item.id === dragId);
	      const to = list.findIndex((item) => item.id === targetId);
	      if (from < 0 || to < 0) return;
	      const [dragged] = list.splice(from, 1);
	      const nextTo = list.findIndex((item) => item.id === targetId);
	      list.splice(nextTo, 0, dragged);
	      state.profiles = list;
	      state.profileTotals = currentProfileTotals();
	      renderProfileList();
	      updateProfileSummary();
	      renderProfileStatus();
	      saveProfileOrder();
	    }

	    async function saveProfileOrder() {
	      const res = await api("/api/profiles/reorder", {
	        method: "POST",
	        body: JSON.stringify({ ids: state.profiles.map((item) => item.id) })
	      });
	      if (!res.ok) {
	        setStatus("profileStatusText", await readError(res, "排序保存失败，稍后再试一下。"), "err");
	        await loadProfiles();
	        return;
	      }
	      const data = await res.json();
	      applyProfilesPayload(data);
	      setStatus("profileStatusText", "排序已保存", "ok");
	    }

	    function fillProfileForm(item) {
	      state.editingProfileId = item.id || "";
	      $("editingProfileId").value = item.id || "";
	      $("profileTitle").value = item.title || "";
	      $("profileContent").value = item.content || "";
	      $("profileType").value = item.type || "profile";
	      $("profileSortOrder").value = item.sort_order ?? 100;
	      $("profileEnabled").checked = Boolean(item.enabled);
	      updateProfileEditorMeta();
	      setStatus("profileStatusText", "正在编辑：" + (item.title || ""), "");
	    }

	    function resetProfileForm(clearStatus = true) {
	      state.editingProfileId = null;
	      $("editingProfileId").value = "";
	      $("profileTitle").value = "";
	      $("profileContent").value = "";
	      $("profileType").value = "profile";
	      $("profileSortOrder").value = "100";
	      $("profileEnabled").checked = true;
	      updateProfileEditorMeta();
	      if (clearStatus) setStatus("profileStatusText", "");
	    }

	    async function saveProfile() {
	      const id = $("editingProfileId").value;
	      const body = {
	        title: $("profileTitle").value.trim(),
	        content: $("profileContent").value.trim(),
	        type: $("profileType").value || "profile",
	        sort_order: Number($("profileSortOrder").value || 100),
	        enabled: $("profileEnabled").checked
	      };
	      if (!body.title || !body.content) {
	        setStatus("profileStatusText", "标题和内容都要填写。", "err");
	        return;
	      }
	      const res = await api(id ? `/api/profiles/${id}` : "/api/profiles", {
	        method: id ? "PUT" : "POST",
	        body: JSON.stringify(body)
	      });
	      if (!res.ok) {
	        setStatus("profileStatusText", await readError(res, "AI档案保存失败，稍后再试一下。"), "err");
	        return;
	      }
	      resetProfileForm(false);
	      await loadProfiles();
	      setStatus("profileStatusText", "AI档案已保存", "ok");
	    }

	    async function toggleProfileEnabled(id, enabled) {
	      const item = state.profiles.find((profile) => profile.id === id);
	      if (!item) return;
	      const res = await api(`/api/profiles/${id}`, {
	        method: "PATCH",
	        body: JSON.stringify({ ...item, enabled })
	      });
	      if (!res.ok) {
	        setStatus("profileStatusText", await readError(res, "状态保存失败，稍后再试一下。"), "err");
	        await loadProfiles();
	        return;
	      }
	      await loadProfiles();
	      setStatus("profileStatusText", enabled ? "已启用" : "已停用", "ok");
	    }

	    async function deleteProfile(id, title) {
	      const ok = await confirmAction({
	        title: "删除 AI档案",
	        message: `确定删除“${title || "这条档案"}”吗？删除后后续聊天不会再参考它。`,
	        confirmText: "删除",
	        danger: true
	      });
	      if (!ok) return;
	      const res = await api(`/api/profiles/${id}`, { method: "DELETE" });
	      if (!res.ok) {
	        setStatus("profileStatusText", await readError(res, "删除 AI档案失败，稍后再试一下。"), "err");
	        return;
	      }
	      if ($("editingProfileId").value === id) resetProfileForm(false);
	      await loadProfiles();
	      setStatus("profileStatusText", "AI档案已删除", "ok");
	    }

	    async function loadFavorites() {
	      try {
	        const res = await api("/api/favorites");
	        const data = await res.json();
	        state.favorites = data.favorites || [];
	        updateFavoriteCount();
	        renderFavorites();
	      } catch (err) {
	        state.favorites = [];
	        updateFavoriteCount();
	        renderFavorites(friendlyError(err, "收藏暂时加载失败。"));
	      }
	    }

	    function favoriteSummary(content) {
	      const text = String(content || "").replace(/[>#*_`]/g, "").replace(/\[|\]|\(|\)/g, "").replace(/\s+/g, " ").trim();
	      return text.length > 110 ? text.slice(0, 110) + "..." : text;
	    }

	    async function openFavorites() {
	      $("favoriteDialog").classList.add("show");
	      setDialogOpenState();
	      await loadFavorites();
	    }

	    function closeFavorites() {
	      $("favoriteDialog").classList.remove("show");
	      setDialogOpenState();
	    }

	    function renderFavorites(errorText = "") {
	      const list = $("favoriteList");
	      const detail = $("favoriteDetail");
	      if (!list || !detail) return;
	      list.innerHTML = "";
	      if (errorText) {
	        list.appendChild(createEmptyState("alert-circle", "收藏加载失败", errorText, { compact: true }));
	      } else if (!state.favorites.length) {
	        list.appendChild(createEmptyState("star", "还没有收藏", "看到好用的 AI 回复时，点消息下面的“收藏”。", { compact: true }));
	      } else {
	        for (const item of state.favorites) {
	          const card = document.createElement("article");
	          card.className = "library-card";
	          const title = document.createElement("strong");
	          title.textContent = item.conversation_title || "原会话已删除";
	          const meta = document.createElement("div");
	          meta.className = "library-card-meta";
	          meta.textContent = "收藏于 " + formatTime(item.created_at);
	          const summary = document.createElement("p");
	          summary.textContent = favoriteSummary(item.content);
	          const actions = document.createElement("div");
	          actions.className = "library-actions";
		          const view = createIconButton("eye", "查看", { primary: item.id === state.selectedFavoriteId, fallback: "看" });
		          view.addEventListener("click", () => selectFavorite(item.id));
		          const insert = createIconButton("corner-down-left", "插入输入框", { fallback: "↵" });
		          insert.addEventListener("click", () => {
		            insertPromptText(item.content);
		            closeFavorites();
		          });
		          const copy = createIconButton("copy", "复制", { fallback: "⧉" });
		          copy.addEventListener("click", () => copyText(item.content, copy));
		          const del = createIconButton("trash-2", "删除", { danger: true, fallback: "删" });
		          del.addEventListener("click", () => deleteFavorite(item.id));
	          actions.append(view, insert, copy, del);
	          card.append(title, meta, summary, actions);
	          list.appendChild(card);
	        }
	      }
	      const current = state.favorites.find((item) => item.id === state.selectedFavoriteId) || state.favorites[0];
	      if (current) {
	        state.selectedFavoriteId = current.id;
	        detail.innerHTML = "";
	        const meta = document.createElement("div");
	        meta.className = "library-card-meta";
	        meta.textContent = (current.conversation_title || "原会话已删除") + " · 收藏于 " + formatTime(current.created_at);
	        const content = document.createElement("div");
	        content.className = "markdown";
	        content.innerHTML = renderMarkdown(current.content || "");
		        detail.append(meta, content);
		        enhanceMarkdown(content);
	      } else {
	        state.selectedFavoriteId = null;
	        detail.replaceChildren(createEmptyState("eye", "选择一条收藏", "在左侧选择一条收藏查看完整回答。"));
	      }
	      queueLucideRefresh();
	    }

	    function selectFavorite(id) {
	      state.selectedFavoriteId = id;
	      renderFavorites();
	    }

	    async function deleteFavorite(id) {
	      const ok = await confirmAction({
	        title: "删除收藏",
	        message: "确定删除这条收藏吗？原对话内容不会受影响。",
	        confirmText: "删除",
	        danger: true
	      });
	      if (!ok) return;
	      const res = await api(`/api/favorites/${id}`, { method: "DELETE" });
	      if (!res.ok) {
	        setStatus("chatStatus", await readError(res, "删除收藏失败，稍后再试一下。"), "err");
	        return;
	      }
	      const removed = state.favorites.find((item) => item.id === id);
	      if (removed) {
	        const message = state.messages.find((item) => item.id === removed.message_id);
	        if (message) {
	          message.favorite_id = null;
	          updateStreamingMessage(message, { forceFull: true, final: true });
	        }
	      }
	      if (state.selectedFavoriteId === id) state.selectedFavoriteId = null;
	      await loadFavorites();
	    }

		    async function toggleFavoriteMessage(message, button) {
		      if (!message || message.role !== "assistant" || !message.id) return;
	      button.disabled = true;
	      try {
	        if (message.favorite_id) {
	          const res = await api(`/api/favorites/${message.favorite_id}`, { method: "DELETE" });
	          if (!res.ok) throw new Error(await readError(res, "取消收藏失败，稍后再试一下。"));
	          const oldFavoriteId = message.favorite_id;
	          message.favorite_id = null;
	          if (state.selectedFavoriteId === oldFavoriteId) state.selectedFavoriteId = null;
	          setStatus("chatStatus", "已取消收藏", "");
	        } else {
	          const res = await api("/api/favorites", {
	            method: "POST",
	            body: JSON.stringify({ message_id: message.id })
	          });
	          if (!res.ok) throw new Error(await readError(res, "收藏失败，稍后再试一下。"));
	          const data = await res.json();
	          message.favorite_id = data.favorite?.id || null;
	          setStatus("chatStatus", "已收藏", "ok");
	        }
	        updateStreamingMessage(message, { forceFull: true, final: true });
	        await loadFavorites();
	      } catch (err) {
	        setStatus("chatStatus", friendlyError(err, "收藏操作失败，稍后再试一下。"), "err");
	      } finally {
		        button.disabled = false;
		      }
		    }

	    function formatFileSize(value) {
	      const size = Number(value || 0);
	      if (size >= 1024 * 1024 * 1024) return (size / 1024 / 1024 / 1024).toFixed(1) + " GB";
	      if (size >= 1024 * 1024) return (size / 1024 / 1024).toFixed(1) + " MB";
	      if (size >= 1024) return (size / 1024).toFixed(1) + " KB";
	      return size + " B";
	    }

	    function mediaStatusText(status) {
	      const map = {
	        uploaded: "已上传",
	        submitted: "已提交",
	        processing: "转写中",
	        completed: "已完成",
	        failed: "失败"
	      };
	      return map[status] || status || "处理中";
	    }

	    async function openMediaAnalysis() {
	      $("mediaDialog").classList.add("show");
	      setDialogOpenState();
	      await loadMediaTasks();
	    }

	    function closeMediaAnalysis() {
	      $("mediaDialog").classList.remove("show");
	      setDialogOpenState();
	      if (state.mediaPollTimer) clearTimeout(state.mediaPollTimer);
	      state.mediaPollTimer = null;
	    }

	    async function loadMediaTasks() {
	      try {
	        const res = await api("/api/media/tasks");
	        const data = await res.json();
	        state.mediaTasks = data.tasks || [];
	        if (!state.selectedMediaTaskId && state.mediaTasks[0]) state.selectedMediaTaskId = state.mediaTasks[0].id;
	        renderMediaTasks();
	        renderMediaDetail();
	        scheduleMediaPolling();
	      } catch (err) {
	        state.mediaTasks = [];
	        renderMediaTasks();
	        setStatus("mediaStatus", friendlyError(err, "音视频任务加载失败。"), "err");
	      }
	    }

	    function scheduleMediaPolling() {
	      if (state.mediaPollTimer) clearTimeout(state.mediaPollTimer);
	      state.mediaPollTimer = null;
	      if (!$("mediaDialog").classList.contains("show")) return;
	      const active = state.mediaTasks.some((task) => ["uploaded", "submitted", "processing"].includes(task.status));
	      if (!active) return;
	      state.mediaPollTimer = setTimeout(() => {
	        refreshSelectedMediaTask(true).catch(() => loadMediaTasks());
	      }, 30000);
	    }

	    function renderMediaTasks() {
	      const list = $("mediaTaskList");
	      list.innerHTML = "";
	      if (!state.mediaTasks.length) {
	        list.appendChild(createEmptyState("file-video", "还没有任务", "上传一段音频或视频，槑槑会帮你转写和整理。", { compact: true }));
	        queueLucideRefresh();
	        return;
	      }
	      for (const task of state.mediaTasks) {
	        const card = document.createElement("article");
	        card.className = "library-card" + (task.id === state.selectedMediaTaskId ? " active" : "");
	        const title = document.createElement("strong");
	        title.textContent = task.filename || "音视频文件";
	        const meta = document.createElement("div");
	        meta.className = "library-card-meta";
	        meta.textContent = mediaStatusText(task.status) + " · " + formatFileSize(task.file_size) + " · " + formatTime(task.updated_at) + (task.conversation_id ? " · 已建会话" : "");
	        const summary = document.createElement("p");
	        summary.textContent = task.error_message || task.summary_text || task.outline_text || task.transcript_text || "等待通义听悟处理结果";
	        const actions = document.createElement("div");
	        actions.className = "library-actions";
	        const view = document.createElement("button");
	        view.type = "button";
	        view.className = (task.id === state.selectedMediaTaskId ? "primary ui-btn ui-btn-primary" : "ui-btn ui-btn-secondary") + " inline-flex items-center gap-2";
	        view.innerHTML = iconLabel("eye", "查看", "看");
	        view.addEventListener("click", () => selectMediaTask(task.id));
	        const refresh = document.createElement("button");
	        refresh.type = "button";
	        refresh.className = "ui-btn ui-btn-secondary inline-flex items-center gap-2";
	        refresh.innerHTML = iconLabel("rotate-cw", "刷新", "↻");
	        refresh.addEventListener("click", () => refreshMediaTask(task.id));
	        actions.append(view, refresh);
	        card.append(title, meta, summary, actions);
	        list.appendChild(card);
	      }
	      queueLucideRefresh();
	    }

	    function selectMediaTask(id) {
	      state.selectedMediaTaskId = id;
	      state.mediaTab = "summary";
	      renderMediaTasks();
	      renderMediaDetail();
	      refreshSelectedMediaTask(false).catch(() => {});
	    }

	    function currentMediaTask() {
	      return state.mediaTasks.find((item) => item.id === state.selectedMediaTaskId) || state.mediaTasks[0] || null;
	    }

	    function mediaTabContent(task) {
	      const outputs = mediaAIOutputs(task);
	      const enhanced = [
	        task.enhanced_summary ? "## 深度总结\n" + task.enhanced_summary : "",
	        task.key_points ? "## 核心观点\n" + task.key_points : "",
	        outputs.selling_points ? "## 卖点/爆点\n" + outputs.selling_points : "",
	        outputs.titles ? "## 标题方向\n" + outputs.titles : ""
	      ].filter(Boolean).join("\n\n");
	      const copywriting = [
	        task.copywriting_text ? "## 综合文案\n" + task.copywriting_text : "",
	        outputs.short_video ? "## 短视频文案\n" + outputs.short_video : "",
	        outputs.speech_script ? "## 口播稿\n" + outputs.speech_script : "",
	        outputs.wechat_article ? "## 公众号文章\n" + outputs.wechat_article : "",
	        outputs.xiaohongshu_note ? "## 小红书笔记\n" + outputs.xiaohongshu_note : "",
	        outputs.moments_copy ? "## 朋友圈文案\n" + outputs.moments_copy : ""
	      ].filter(Boolean).join("\n\n");
	      const fields = {
	        summary: task.summary_text || "",
	        outline: task.outline_text || "",
	        transcript: task.transcript_text || "",
	        enhanced,
	        mindmap: task.mindmap_text ? "```mermaid\n" + task.mindmap_text + "\n```" : "",
	        copywriting
	      };
	      return fields[state.mediaTab] || "";
	    }

	    function mediaAIOutputs(task) {
	      if (!task?.ai_outputs_json) return {};
	      try {
	        const data = JSON.parse(task.ai_outputs_json);
	        return data && typeof data === "object" ? data : {};
	      } catch {
	        return {};
	      }
	    }

	    function mediaHasEnhanced(task) {
	      return Boolean(task?.enhanced_summary || task?.key_points || task?.ai_outputs_json);
	    }

	    function mediaHasCopywriting(task) {
	      const outputs = mediaAIOutputs(task);
	      return Boolean(
	        task?.copywriting_text ||
	        outputs.short_video ||
	        outputs.speech_script ||
	        outputs.wechat_article ||
	        outputs.xiaohongshu_note ||
	        outputs.moments_copy ||
	        outputs.copywriting_text
	      );
	    }

	    function mediaTaskReadyForAI(task) {
	      return Boolean(
	        task &&
	        task.status === "completed" &&
	        (task.summary_text || task.outline_text || task.transcript_text || task.mindmap_text || task.copywriting_text)
	      );
	    }

	    function mediaCreativePrompt(type, task) {
	      const filename = task?.filename || "这段音视频";
	      const prompts = {
	        shortVideo: `请基于《${filename}》的音视频分析结果，生成一版适合短视频发布的文案。要求：给出3个标题方向、1段开头钩子、正文分镜/画面建议、结尾引导，语气自然有吸引力。`,
	        speech: `请基于《${filename}》的音视频分析结果，生成一版口播稿。要求：适合真人口播，开头抓人，中间逻辑清楚，结尾有行动引导，语言口语化。`,
	        article: `请基于《${filename}》的音视频分析结果，生成一篇公众号文章。要求：标题、导语、小标题结构、正文、结尾总结都完整，表达清楚，有阅读层次。`,
	        xiaohongshu: `请基于《${filename}》的音视频分析结果，生成一篇小红书笔记。要求：给出标题、正文、分点内容、适合的表情符号和话题标签，语气真诚自然。`,
	        moments: `请基于《${filename}》的音视频分析结果，生成3版朋友圈文案。要求：分别是自然分享版、简短有梗版、正式一点版。`,
	        mindmap: `请基于《${filename}》的音视频分析结果，生成一份 Mermaid mindmap。要求：只输出 Mermaid，使用 mindmap 语法，中文节点，层级不超过4层，节点不要太长，不要输出解释文字。`,
	        sellingPoints: `请基于《${filename}》的音视频分析结果，提取最适合传播的卖点/爆点。要求：分为核心卖点、情绪卖点、标题爆点、可延展选题。`,
	        titles: `请基于《${filename}》的音视频分析结果，生成12个标题。要求：分别覆盖短视频、小红书、公众号和朋友圈语境，标题自然不夸张。`
	      };
	      return prompts[type] || prompts.shortVideo;
	    }

	    function mediaCreativeIcon(type) {
	      const icons = {
	        shortVideo: "video",
	        speech: "mic",
	        article: "file-text",
	        xiaohongshu: "book-open",
	        moments: "share-2",
	        mindmap: "git-branch",
	        sellingPoints: "tag",
	        titles: "type"
	      };
	      return icons[type] || "sparkles";
	    }

	    function mediaTabIcon(key) {
	      const icons = {
	        summary: "file-text",
	        outline: "list",
	        transcript: "align-left",
	        enhanced: "sparkles",
	        mindmap: "git-branch",
	        copywriting: "clipboard"
	      };
	      return icons[key] || "file-text";
	    }

	    function mediaStatusIcon(status) {
	      const icons = {
	        completed: "check-circle",
	        failed: "alert-circle",
	        processing: "loader",
	        uploaded: "clock",
	        pending: "clock"
	      };
	      return icons[status] || "circle";
	    }

	    function upsertMediaConversationTask(task, conversation) {
	      if (!task) return;
	      if (conversation?.id) task.conversation_id = conversation.id;
	      upsertMediaTask(task);
	      renderMediaTasks();
	      renderMediaDetail();
	    }

	    async function ensureMediaConversation(task, options = {}) {
	      if (!mediaTaskReadyForAI(task)) {
	        setStatus("mediaStatus", "分析完成后才能发送到 AI 对话。", "err");
	        return null;
	      }
	      const modelId = $("modelSelect").value || state.currentConversation?.model_id || state.models[0]?.id || "";
	      const res = await api(`/api/media/tasks/${task.id}/conversation`, {
	        method: "POST",
	        body: JSON.stringify({ model_id: modelId })
	      });
	      if (!res.ok) {
	        setStatus("mediaStatus", await readError(res, "创建分析会话失败。"), "err");
	        return null;
	      }
	      const data = await res.json();
	      upsertConversation(data.conversation);
	      upsertMediaConversationTask(data.task, data.conversation);
	      if (options.open) {
	        closeMediaAnalysis();
	        await selectConversation(data.conversation.id);
	        setStatus("chatStatus", "已进入音视频分析会话，可以继续加工内容。", "ok");
	      } else {
	        setStatus("mediaStatus", "分析会话已创建，可以随时进入继续加工。", "ok");
	      }
	      return data.conversation;
	    }

	    async function sendMediaPromptToAI(task, type) {
	      if (state.sending) {
	        setStatus("mediaStatus", "上一条还在生成，先等它完成。", "err");
	        return;
	      }
	      const conversation = await ensureMediaConversation(task, { open: true });
	      if (!conversation) return;
	      await sendMessage(mediaCreativePrompt(type, task), { statusText: "正在基于音视频分析生成内容..." });
	    }

	    async function enhanceMediaTask(task, force = false) {
	      if (!mediaTaskReadyForAI(task)) {
	        setStatus("mediaStatus", "分析完成后才能生成 AI 增强分析。", "err");
	        return;
	      }
	      const modelId = $("modelSelect").value || state.currentConversation?.model_id || state.models[0]?.id || "";
	      setStatus("mediaStatus", force ? "正在重新生成 AI 增强分析..." : "正在生成 AI 增强分析...", "");
	      const res = await api(`/api/media/tasks/${task.id}/enhance`, {
	        method: "POST",
	        body: JSON.stringify({ model_id: modelId, force })
	      });
	      if (!res.ok) {
	        setStatus("mediaStatus", await readError(res, "AI 增强分析失败。"), "err");
	        return;
	      }
	      const data = await res.json();
	      upsertMediaTask(data.task);
	      state.mediaTab = data.task?.mindmap_text ? "mindmap" : "enhanced";
	      renderMediaTasks();
	      renderMediaDetail();
	      setStatus("mediaStatus", data.cached ? "已加载缓存的 AI 增强分析。" : "AI 增强分析已生成。", "ok");
	    }

	    function createMediaAIButtons(task) {
	      const panel = document.createElement("section");
	      panel.className = "media-ai-panel";
	      const title = document.createElement("strong");
	      title.className = "media-ai-title";
	      title.innerHTML = iconLabel("sparkles", "AI 持续加工", "✦");
	      const hint = document.createElement("div");
	      hint.className = "media-ai-hint";
	      hint.textContent = mediaTaskReadyForAI(task)
	        ? "已可把摘要、章节和转写作为上下文，进入专属 AI 会话继续加工。"
	        : "分析完成后，可以一键创建 AI 加工会话，无需重复上传。";
	      const mainActions = document.createElement("div");
	      mainActions.className = "media-ai-actions";
	      const enhance = document.createElement("button");
	      enhance.type = "button";
	      enhance.className = (mediaHasEnhanced(task) ? "ui-btn ui-btn-secondary" : "primary ui-btn ui-btn-primary") + " inline-flex items-center gap-2";
	      enhance.innerHTML = mediaHasEnhanced(task)
	        ? iconLabel("rotate-cw", "重新生成AI增强", "↻")
	        : iconLabel("sparkles", "生成AI增强分析", "✦");
	      enhance.disabled = !mediaTaskReadyForAI(task);
	      enhance.addEventListener("click", () => enhanceMediaTask(task, mediaHasEnhanced(task)).catch((err) => setStatus("mediaStatus", friendlyError(err, "AI 增强分析失败。"), "err")));
	      const send = document.createElement("button");
	      send.type = "button";
	      send.className = (mediaHasEnhanced(task) ? "primary ui-btn ui-btn-primary" : "ui-btn ui-btn-secondary") + " inline-flex items-center gap-2";
	      send.innerHTML = iconLabel("message-square", "发送到AI对话", "↗");
	      send.disabled = !mediaTaskReadyForAI(task);
	      send.addEventListener("click", () => ensureMediaConversation(task, { open: true }).catch((err) => setStatus("mediaStatus", friendlyError(err, "创建分析会话失败。"), "err")));
	      const create = document.createElement("button");
	      create.type = "button";
	      create.className = "ui-btn ui-btn-secondary inline-flex items-center gap-2";
	      create.innerHTML = task.conversation_id ? iconLabel("message-square", "进入分析会话", "↗") : iconLabel("plus", "创建分析会话", "+");
	      create.disabled = !mediaTaskReadyForAI(task);
	      create.addEventListener("click", () => ensureMediaConversation(task, { open: Boolean(task.conversation_id) }).catch((err) => setStatus("mediaStatus", friendlyError(err, "创建分析会话失败。"), "err")));
	      mainActions.append(enhance, send, create);
	      const creativeActions = document.createElement("div");
	      creativeActions.className = "media-ai-actions";
	      const items = [
	        ["shortVideo", "短视频文案"],
	        ["speech", "口播稿"],
	        ["article", "公众号文章"],
	        ["xiaohongshu", "小红书笔记"],
	        ["moments", "朋友圈文案"],
	        ["mindmap", "思维导图"],
	        ["sellingPoints", "提取卖点"],
	        ["titles", "生成标题"]
	      ];
	      for (const [type, label] of items) {
	        const button = document.createElement("button");
	        button.type = "button";
	        button.className = "ui-btn ui-btn-secondary inline-flex items-center gap-2";
	        button.innerHTML = iconLabel(mediaCreativeIcon(type), label, "•");
	        button.disabled = !mediaTaskReadyForAI(task);
	        button.addEventListener("click", () => sendMediaPromptToAI(task, type).catch((err) => setStatus("mediaStatus", friendlyError(err, "发送到 AI 对话失败。"), "err")));
	        creativeActions.appendChild(button);
	      }
	      panel.append(title, hint, mainActions, creativeActions);
	      return panel;
	    }

	    function renderMediaDetail() {
	      const detail = $("mediaTaskDetail");
	      const task = currentMediaTask();
	      if (!task) {
	        detail.replaceChildren(createEmptyState("file-video", "选择或上传任务", "上传音频/视频后，这里会显示转写、摘要和 AI 增强结果。"));
	        queueLucideRefresh();
	        return;
	      }
	      state.selectedMediaTaskId = task.id;
	      const tabs = [
	        ["summary", "智能摘要"],
	        ["outline", "章节要点"],
	        ["transcript", "转写全文"],
	        ["enhanced", "AI增强"]
	      ];
	      if (task.mindmap_text) tabs.push(["mindmap", "思维导图"]);
	      if (mediaHasCopywriting(task)) tabs.push(["copywriting", "可复制文案"]);
	      if (!tabs.some(([key]) => key === state.mediaTab)) {
	        state.mediaTab = mediaHasEnhanced(task) ? "enhanced" : "summary";
	      }
	      detail.innerHTML = "";
	      const head = document.createElement("div");
	      head.className = "media-task-head";
	      const headText = document.createElement("div");
	      const headTitle = document.createElement("strong");
	      headTitle.textContent = task.filename || "音视频文件";
	      const headMeta = document.createElement("div");
	      headMeta.className = "library-card-meta";
	      headMeta.textContent = "创建 " + formatTime(task.created_at) + (task.updated_at ? " · 更新 " + formatTime(task.updated_at) : "");
	      headText.append(headTitle, headMeta);
	      const badge = document.createElement("span");
	      badge.className = "media-task-badge";
	      badge.innerHTML = iconLabel(mediaStatusIcon(task.status), mediaStatusText(task.status), "•");
	      head.append(headText, badge);
	      const tabBar = document.createElement("div");
	      tabBar.className = "media-tabs";
	      for (const [key, label] of tabs) {
	        const button = document.createElement("button");
	        button.type = "button";
	        button.className = "media-tab ui-btn ui-btn-secondary" + (state.mediaTab === key ? " active" : "");
	        button.innerHTML = iconLabel(mediaTabIcon(key), label, "•");
	        button.addEventListener("click", () => {
	          state.mediaTab = key;
	          renderMediaDetail();
	        });
	        tabBar.appendChild(button);
	      }
	      const aiPanel = createMediaAIButtons(task);
	      const content = document.createElement("div");
	      content.className = "media-result markdown";
	      const text = task.error_message || mediaTabContent(task) || (
	        state.mediaTab === "enhanced"
	          ? "还没有生成 AI 增强分析。点上方“生成AI增强分析”，槑槑会基于转写、摘要和章节生成深度总结、观点、文案和思维导图。"
	          : (task.status === "completed" ? "这个部分暂时没有结果，可以刷新状态或生成 AI 增强分析。" : "任务处理中，稍后刷新看看。")
	      );
	      content.innerHTML = renderMarkdown(text);
	      const actions = document.createElement("div");
	      actions.className = "library-actions";
	      const copy = document.createElement("button");
	      copy.type = "button";
	      copy.className = "ui-btn ui-btn-secondary inline-flex items-center gap-2";
	      copy.innerHTML = iconLabel("copy", "复制当前内容", "⧉");
	      copy.addEventListener("click", () => copyText(text, copy));
	      const refresh = document.createElement("button");
	      refresh.type = "button";
	      refresh.className = "ui-btn ui-btn-secondary inline-flex items-center gap-2";
	      refresh.innerHTML = iconLabel("rotate-cw", "刷新状态", "↻");
	      refresh.addEventListener("click", () => refreshMediaTask(task.id));
	      const del = document.createElement("button");
	      del.type = "button";
	      del.className = "danger ui-btn ui-btn-secondary inline-flex items-center gap-2";
	      del.innerHTML = iconLabel("trash-2", "删除任务", "删");
	      del.addEventListener("click", () => deleteMediaTask(task.id));
	      actions.append(copy, refresh, del);
	      detail.append(head, aiPanel, tabBar, content, actions);
	      enhanceMarkdown(content);
	      queueLucideRefresh();
	    }

	    function upsertMediaTask(task) {
	      if (!task) return;
	      const index = state.mediaTasks.findIndex((item) => item.id === task.id);
	      if (index >= 0) state.mediaTasks.splice(index, 1, task);
	      else state.mediaTasks.unshift(task);
	      state.selectedMediaTaskId = task.id;
	    }

	    async function refreshMediaTask(id) {
	      const res = await api(`/api/media/tasks/${id}/refresh`, { method: "POST" });
	      if (!res.ok) {
	        setStatus("mediaStatus", await readError(res, "刷新任务失败。"), "err");
	        return;
	      }
	      const data = await res.json();
	      upsertMediaTask(data.task);
	      renderMediaTasks();
	      renderMediaDetail();
	      scheduleMediaPolling();
	    }

	    async function refreshSelectedMediaTask(silent = false) {
	      const task = currentMediaTask();
	      if (!task) return;
	      const res = await api(`/api/media/tasks/${task.id}`);
	      if (!res.ok) {
	        if (!silent) setStatus("mediaStatus", await readError(res, "刷新任务失败。"), "err");
	        return;
	      }
	      const data = await res.json();
	      upsertMediaTask(data.task);
	      renderMediaTasks();
	      renderMediaDetail();
	      scheduleMediaPolling();
	    }

	    async function deleteMediaTask(id) {
	      const ok = await confirmAction({
	        title: "删除音视频任务",
	        message: "确定删除这个分析任务吗？不会删除 OSS 里的原始文件。",
	        confirmText: "删除",
	        danger: true
	      });
	      if (!ok) return;
	      const res = await api(`/api/media/tasks/${id}`, { method: "DELETE" });
	      if (!res.ok) {
	        setStatus("mediaStatus", await readError(res, "删除任务失败。"), "err");
	        return;
	      }
	      state.mediaTasks = state.mediaTasks.filter((item) => item.id !== id);
	      if (state.selectedMediaTaskId === id) state.selectedMediaTaskId = state.mediaTasks[0]?.id || null;
	      renderMediaTasks();
	      renderMediaDetail();
	    }

	    function safeMediaFilename(name) {
	      return String(name || "media").replace(/[\\/]+/g, "_").replace(/[^\w.\-\u4e00-\u9fa5]+/g, "_").slice(0, 120);
	    }

	    async function uploadMediaTask() {
	      if (state.mediaUploading) return;
	      const file = $("mediaFile").files?.[0];
	      if (!file) {
	        setStatus("mediaStatus", "先选择一个音频或视频文件。", "err");
	        return;
	      }
	      state.mediaUploading = true;
	      $("uploadMediaTask").disabled = true;
	      setStatus("mediaStatus", "正在获取上传凭证...", "");
	      try {
	        const policyRes = await api("/api/media/upload-policy", { method: "POST" });
	        if (!policyRes.ok) throw new Error(await readError(policyRes, "上传配置不可用。"));
	        const { policy } = await policyRes.json();
	        if (file.size > policy.max_size) throw new Error("文件大小超出限制");
	        const key = policy.key_prefix + Date.now() + "-" + Math.random().toString(36).slice(2, 8) + "-" + safeMediaFilename(file.name);
	        const form = new FormData();
	        form.append("key", key);
	        form.append("OSSAccessKeyId", policy.access_key_id);
	        form.append("policy", policy.policy);
	        form.append("Signature", policy.signature);
	        form.append("success_action_status", "200");
	        form.append("Content-Type", file.type || "application/octet-stream");
	        form.append("file", file);
	        setStatus("mediaStatus", "正在上传到 OSS...", "");
	        const uploadRes = await fetch(policy.host, { method: "POST", body: form });
	        if (!uploadRes.ok) throw new Error("上传 OSS 失败");
	        setStatus("mediaStatus", "上传完成，正在创建听悟任务...", "");
	        const createRes = await api("/api/media/tasks", {
	          method: "POST",
	          body: JSON.stringify({
	            filename: file.name,
	            mime_type: file.type || "",
	            file_size: file.size,
	            oss_key: key,
	            source_language: "cn"
	          })
	        });
	        if (!createRes.ok) throw new Error(await readError(createRes, "创建听悟任务失败。"));
	        const data = await createRes.json();
	        upsertMediaTask(data.task);
	        $("mediaFile").value = "";
	        renderMediaTasks();
	        renderMediaDetail();
	        scheduleMediaPolling();
	        setStatus(
	          "mediaStatus",
	          data.task?.status === "failed" ? "任务创建失败，请查看详情。" : "已提交听悟，稍后刷新查看结果。",
	          data.task?.status === "failed" ? "err" : "ok"
	        );
	      } catch (err) {
	        setStatus("mediaStatus", friendlyError(err, "上传或创建任务失败。"), "err");
	      } finally {
	        state.mediaUploading = false;
	        $("uploadMediaTask").disabled = false;
	      }
	    }

		    function toggleReasoning(message) {
	      if (!message) return;
	      message.reasoning_open = !message.reasoning_open;
	      const box = $("messages");
	      const wrap = box?.querySelector(`[data-message-key="${messageKey(message)}"]`);
	      const panel = wrap?.querySelector(".reasoning-panel");
	      if (!panel) return;
	      renderReasoningPanel(panel, message, messageReasoningContent(message), {
	        final: !message.thinking
	      });
	      queueLucideRefresh();
	    }

	    function messageIndexOf(message) {
	      const key = messageKey(message);
	      return state.messages.findIndex((item) => messageKey(item) === key || (message.id && item.id === message.id));
	    }

	    function previousUserMessage(message) {
	      const start = messageIndexOf(message);
	      for (let i = start - 1; i >= 0; i--) {
	        if (state.messages[i]?.role === "user") return state.messages[i];
	      }
	      return null;
	    }

	    async function regenerateFromMessage(message) {
	      const previous = previousUserMessage(message);
	      if (!previous) {
	        setStatus("chatStatus", "没找到上一条问题，可以手动复制后再问一次。", "err");
	        return;
	      }
	      if (state.sending) return setStatus("chatStatus", "上一条还在生成，先等它完成。", "err");
	      setStatus("chatStatus", "正在重新生成...", "");
	      await sendMessage(previous.content || "", { statusText: "正在重新生成..." });
	    }

	    async function continueFromMessage(message) {
	      if (!visibleMessageContent(message)) return;
	      if (state.sending) return setStatus("chatStatus", "上一条还在生成，先等它完成。", "err");
	      await sendMessage("请接着上面的回答继续写，保持原来的语气和结构。", { statusText: "正在继续写..." });
	    }

    async function loadConversations() {
      renderConversationLoading();
      try {
        const res = await api("/api/conversations");
        const data = await res.json();
        state.conversations = data.conversations || [];
        sortConversations();
        renderConversations();
        if (!state.currentConversation && state.conversations.length) {
          const savedId = getUserStorage("lastConversationId", "");
          const initial = state.conversations.find((item) => item.id === savedId) || state.conversations[0];
          await selectConversation(initial.id);
        } else if (!state.conversations.length) {
          renderEmpty();
          restoreCurrentDraft();
        }
      } catch (err) {
        renderConversationError(friendlyError(err, "对话列表暂时加载失败。"));
        if (!state.messages.length) renderEmpty();
      }
    }

	    function conversationGroupLabel(ts) {
	      const value = Number(ts || 0);
	      if (!value) return "更早";
	      const day = new Date(value * 1000);
	      const today = new Date();
	      today.setHours(0, 0, 0, 0);
	      const target = new Date(day);
	      target.setHours(0, 0, 0, 0);
	      const diffDays = Math.floor((today - target) / 86400000);
	      if (diffDays <= 0) return "今天";
	      if (diffDays === 1) return "昨天";
	      if (diffDays < 7) return "最近 7 天";
	      if (diffDays < 30) return "最近 30 天";
	      return "更早";
	    }

	    function renderConversations() {
	      const box = $("conversationList");
	      box.innerHTML = "";
      if (!state.conversations.length) {
        const div = document.createElement("div");
        div.className = "side-empty";
        div.textContent = "还没有对话。点上面的“新对话”，或者直接在右侧输入问题。";
        box.appendChild(div);
        return;
	      }
	      function appendGroup(titleText) {
	        const title = document.createElement("div");
	        title.className = "conversation-group";
	        title.textContent = titleText;
	        box.appendChild(title);
	      }
	      function appendConversation(conv) {
	        const row = document.createElement("div");
	        const active = state.currentConversation?.id === conv.id;
	        const editing = state.editingConversationId === conv.id;
	        row.className = "conv" + (active ? " active" : "") + (editing ? " editing" : "") + (conv.pinned ? " pinned" : "");

	        if (editing) {
	          const input = document.createElement("input");
	          input.className = "conv-rename";
	          input.value = conv.title;
	          input.maxLength = 80;
	          input.addEventListener("keydown", (event) => {
	            if (event.key === "Enter") saveConversationTitle(conv.id, input.value);
	            if (event.key === "Escape") {
	              state.editingConversationId = null;
	              renderConversations();
	            }
	          });

	          const actions = document.createElement("div");
	          actions.className = "conv-actions";
	          const save = createIconOnlyButton("check", "保存", { className: "conv-action ui-icon-btn", fallback: "✓" });
	          save.addEventListener("click", () => saveConversationTitle(conv.id, input.value));
	          const cancel = createIconOnlyButton("x", "取消", { className: "conv-action ui-icon-btn", fallback: "×" });
	          cancel.addEventListener("click", () => {
	            state.editingConversationId = null;
	            renderConversations();
	          });
	          actions.append(save, cancel);
	          row.append(input, actions);
	          setTimeout(() => {
	            input.focus();
	            input.select();
	          }, 0);
	        } else {
		          const main = document.createElement("button");
		          main.className = "conv-main";
		          main.type = "button";
		          main.innerHTML = `<span class="conv-title"><span class="conv-title-text"></span></span><span class="conv-meta"><span class="conv-model"></span><span class="conv-time"></span></span>`;
		          main.querySelector(".conv-title-text").textContent = conv.title;
		          if (conv.pinned) {
		            const pin = document.createElement("span");
		            pin.className = "conv-pin-indicator";
		            pin.title = "已置顶";
		            pin.innerHTML = iconMarkup("pin", "📌");
		            main.querySelector(".conv-title").appendChild(pin);
		          }
		          main.querySelector(".conv-model").textContent = conv.model_name || "未命名模型";
		          main.querySelector(".conv-model").title = conv.model_name || "未命名模型";
		          main.querySelector(".conv-time").textContent = formatTime(conv.updated_at);
		          main.addEventListener("click", () => selectConversation(conv.id));

	          const actions = document.createElement("div");
	          actions.className = "conv-actions";
	          const pinToggle = createIconOnlyButton(conv.pinned ? "pin-off" : "pin", conv.pinned ? "取消置顶" : "置顶", { className: "conv-action pin-action ui-icon-btn", fallback: conv.pinned ? "取" : "置" });
	          pinToggle.addEventListener("click", () => togglePinConversation(conv.id));
	          const edit = createIconOnlyButton("pencil", "重命名", { className: "conv-action ui-icon-btn", fallback: "✎" });
	          edit.addEventListener("click", () => startRenameConversation(conv.id));
	          const del = createIconOnlyButton("trash-2", "删除", { className: "conv-action ui-icon-btn", danger: true, fallback: "⌫" });
	          del.addEventListener("click", () => deleteConversationById(conv.id));
	          actions.append(pinToggle, edit, del);
	          const mobileMore = createIconOnlyButton("ellipsis", "更多会话操作", { className: "conv-mobile-more ui-icon-btn", fallback: "···" });
	          mobileMore.addEventListener("click", (event) => {
	            event.stopPropagation();
	            const willOpen = !row.classList.contains("mobile-actions-open");
	            box.querySelectorAll(".conv.mobile-actions-open").forEach((item) => item.classList.remove("mobile-actions-open"));
	            row.classList.toggle("mobile-actions-open", willOpen);
	            mobileMore.setAttribute("aria-expanded", willOpen ? "true" : "false");
	          });
	          actions.addEventListener("click", () => row.classList.remove("mobile-actions-open"));
	          row.append(main, mobileMore, actions);
	        }
	        box.appendChild(row);
	      }
	      const pinned = state.conversations.filter((conv) => conv.pinned);
	      const normal = state.conversations.filter((conv) => !conv.pinned);
	      if (pinned.length) {
	        appendGroup("置顶");
	        pinned.forEach(appendConversation);
	      }
	      let lastGroup = "";
	      for (const conv of normal) {
	        const group = conversationGroupLabel(conv.updated_at || conv.created_at);
	        if (group !== lastGroup) {
	          appendGroup(group);
	          lastGroup = group;
	        }
	        appendConversation(conv);
	      }
	      queueLucideRefresh();
	    }

	    function renderConversationLoading() {
	      const box = $("conversationList");
	      box.innerHTML = "";
	      for (let i = 0; i < 4; i++) {
	        const item = document.createElement("div");
	        item.className = "side-empty";
	        item.innerHTML = '<div class="loading-line" style="width:' + (78 - i * 9) + '%"></div><div class="loading-line" style="width:' + (46 + i * 8) + '%;margin-top:10px"></div>';
	        box.appendChild(item);
	      }
	    }

	    function renderConversationError(message) {
	      const box = $("conversationList");
	      box.innerHTML = "";
	      const div = document.createElement("div");
	      div.className = "side-empty";
	      div.textContent = message || "对话列表暂时加载失败。";
	      box.appendChild(div);
	    }

	    function startRenameConversation(id) {
	      state.editingConversationId = id;
	      renderConversations();
	    }

	    async function saveConversationTitle(id, title) {
	      const nextTitle = (title || "").trim();
	      if (!nextTitle) {
	        setStatus("chatStatus", "标题不能为空", "err");
	        return;
	      }
	      const res = await api(`/api/conversations/${id}`, {
	        method: "PATCH",
	        body: JSON.stringify({ title: nextTitle })
	      });
	      if (!res.ok) {
	        setStatus("chatStatus", await readError(res, "重命名失败，稍后再试一下。"), "err");
	        return;
	      }
	      state.editingConversationId = null;
	      const currentId = state.currentConversation?.id;
	      await loadConversations();
	      if (currentId) {
	        const updated = state.conversations.find((item) => item.id === currentId);
	        if (updated) {
	          state.currentConversation = updated;
	          updateChatHeader();
	          renderConversations();
	        }
	      }
	      setStatus("chatStatus", "");
	    }

    function formatTime(ts) {
      if (!ts) return "";
      const d = new Date(ts * 1000);
      return d.toLocaleString([], { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
    }

    function sortConversations() {
      state.conversations.sort((a, b) => {
        const pinnedDelta = Number(Boolean(b.pinned)) - Number(Boolean(a.pinned));
        if (pinnedDelta) return pinnedDelta;
        return Number(b.updated_at || 0) - Number(a.updated_at || 0);
      });
    }

    function upsertConversation(conversation) {
      if (!conversation) return;
      const index = state.conversations.findIndex((item) => item.id === conversation.id);
      if (index >= 0) {
        state.conversations.splice(index, 1, conversation);
      } else {
        state.conversations.unshift(conversation);
      }
      sortConversations();
      renderConversations();
    }

	    async function togglePinConversation(id) {
	      const conv = state.conversations.find((item) => item.id === id);
	      if (!conv) return;
	      const action = conv.pinned ? "unpin" : "pin";
	      const res = await api(`/api/conversations/${id}/${action}`, { method: "POST" });
	      if (!res.ok) {
	        setStatus("chatStatus", await readError(res, conv.pinned ? "取消置顶失败，稍后再试一下。" : "置顶失败，稍后再试一下。"), "err");
	        return;
	      }
	      const data = await res.json();
	      upsertConversation(data.conversation);
	      if (state.currentConversation?.id === id) {
	        state.currentConversation = data.conversation;
	        updateChatHeader();
	      }
	      setStatus("chatStatus", conv.pinned ? "已取消置顶" : "已置顶", "ok");
	    }

    async function newConversation(modelId = $("modelSelect").value) {
      if (!modelId && state.models[0]) modelId = state.models[0].id;
      if (!modelId) {
        setStatus("chatStatus", "还没有可用模型，请先在模型管理里配置。", "err");
        return null;
      }
      if (state.newConversationPromise) {
        if (!state.newConversationModelId || state.newConversationModelId === modelId) {
          return state.newConversationPromise;
        }
        await state.newConversationPromise.catch(() => null);
      }
      saveCurrentDraft();
	      const button = $("newChat");
	      if (button) button.disabled = true;
	      state.newConversationModelId = modelId;
	      state.newConversationPromise = (async () => {
	        closeSideDiscussion();
	        state.sideDiscussions = [];
	        state.activeSideDiscussion = null;
	        state.sideDiscussionMessages = [];
	        updateSideDiscussionEntry();
	        const res = await api("/api/conversations", { method: "POST", body: JSON.stringify({ model_id: modelId }) });
        if (!res.ok) throw new Error(await readError(res, "新建对话失败，稍后再试一下。"));
        const data = await res.json();
        state.currentConversation = data.conversation;
	      setUserStorage("lastConversationId", state.currentConversation.id);
        state.conversationStats = null;
        state.messages = [];
        await loadConversations();
        updateChatHeader();
        renderProfileStatus();
        renderProfilePopover();
        renderMessages({ forceScroll: true });
        restoreCurrentDraft();
        return state.currentConversation;
      })();
      try {
        return await state.newConversationPromise;
      } finally {
        state.newConversationPromise = null;
        state.newConversationModelId = "";
        if (button) button.disabled = false;
      }
    }

	    async function selectConversation(id, options = {}) {
	      if (state.currentConversation?.id !== id) {
	        saveCurrentDraft();
	        closeSideDiscussion();
	        state.sideDiscussions = [];
	        state.activeSideDiscussion = null;
	        state.sideDiscussionMessages = [];
	        updateSideDiscussionEntry();
	      }
	      state.editingConversationId = null;
	      const conv = state.conversations.find((item) => item.id === id);
	      if (!conv) return;
      state.currentConversation = conv;
	      setUserStorage("lastConversationId", conv.id);
      $("modelSelect").value = conv.model_id;
      updateChatHeader();
      renderProfileStatus();
      renderProfilePopover();
      renderConversations();
      try {
        const res = await api(`/api/conversations/${id}/messages`);
        if (!res.ok) throw new Error(await readError(res, "消息暂时加载失败。"));
        const data = await res.json();
        state.messages = data.messages || [];
	      restoreCurrentDraft();
        const targetMessageId = Number(options.messageId || 0);
        renderMessages({ forceScroll: !targetMessageId });
	        await Promise.all([loadConversationStats(id), loadSideDiscussions(id)]);
        closeSidebar();
        if (targetMessageId) {
          requestAnimationFrame(() => scrollToMessageId(targetMessageId));
        }
      } catch (err) {
        setStatus("chatStatus", friendlyError(err, "消息暂时加载失败。"), "err");
      }
    }

    function scrollToMessageId(messageId, fallbackMessageKey = "") {
      const box = $("messages");
      if (!box || (!messageId && !fallbackMessageKey)) return false;
      const message = state.messages.find((item) => (
        (messageId && Number(item.id || 0) === Number(messageId)) ||
        (fallbackMessageKey && messageKey(item) === fallbackMessageKey)
      ));
      if (!message) return false;
      const wrap = box.querySelector(`[data-message-key="${messageKey(message)}"]`);
      if (!wrap) return false;
      const target = clampNumber(
        wrap.offsetTop - Math.max(72, box.clientHeight * .18),
        0,
        Math.max(0, box.scrollHeight - box.clientHeight),
        0
      );
      state.programmaticScroll = true;
      box.scrollTo({ top: target, behavior: "smooth" });
      wrap.classList.add("search-hit-highlight");
      setTimeout(() => {
        state.programmaticScroll = false;
        handleMessagesScroll();
      }, 520);
      setTimeout(() => wrap.classList.remove("search-hit-highlight"), 1900);
      queueConversationMinimap();
      return true;
    }

    function updateChatHeader() {
      const conv = state.currentConversation;
      $("chatTitle").textContent = conv ? conv.title : "新对话";
      $("chatModel").textContent = conv ? (conv.model_name + (conv.supports_vision ? " · 可看图" : "") + " · " + conv.model) : "请选择模型";
      updateChatUsage();
      renderProfileStatus();
      renderProfilePopover();
      renderModelSelect();
    }

		    function renderEmpty() {
		      $("chatTitle").textContent = "新对话";
		      $("chatModel").textContent = state.models[0] ? "准备使用 " + state.models[0].name : "请选择模型";
	      state.conversationStats = null;
	      updateChatUsage();
	      renderProfileStatus();
	      renderProfilePopover();
	      hideConversationMinimap();
	      const box = $("messages");
	      box.innerHTML = `
	        <div class="empty">
	          <img class="empty-hero" src="/res/meimei-empty-state.png?v=2.2.13" alt="槑槑欢迎插画">
	          <div class="empty-copy">
	            <div class="empty-kicker">家庭 AI 助手 · 槑槑在这里</div>
	            <h2><span>你好，我是槑槑</span><i data-lucide="paw-print" aria-hidden="true"></i></h2>
	            <p>今天想聊点什么？${state.models[0] ? " " + state.models[0].name + " 已就绪。" : ""}</p>
	          </div>
	          <div class="prompt-grid"></div>
	        </div>`;
	      const quickPrompts = [
	        { title: "润色文案", content: "帮我润色下面这段文字，让它更自然、更正式：" },
	        { title: "深度改写", content: "帮我深度改写下面这段内容，保留原意，但让表达更有条理：" },
	        { title: "工作总结", content: "帮我生成一份工作总结，结构清晰，语气正式：" },
	        { title: "活动宣传", content: "帮我写一段活动宣传文案，有吸引力但不要太夸张：" },
	        { title: "朋友圈文案", content: "帮我写一段朋友圈文案，语气自然一点：" },
	        { title: "整理内容", content: "帮我把下面内容整理成条理清晰的要点：" }
	      ];
	      const grid = box.querySelector(".prompt-grid");
	      for (const item of quickPrompts) {
	        const button = document.createElement("button");
	        button.className = "prompt-card";
	        button.dataset.prompt = item.content;
	        const title = document.createElement("strong");
	        title.textContent = item.title;
	        const summary = document.createElement("span");
	        summary.textContent = item.content;
	        button.append(title, summary);
	        grid.appendChild(button);
	      }
	      grid.querySelectorAll(".prompt-card").forEach((button) => {
	        button.addEventListener("click", () => {
	          insertPromptText(button.dataset.prompt || "");
	        });
		      });
	      queueLucideRefresh();
		    }

	    function escapeHTML(value) {
	      return String(value || "")
	        .replace(/&/g, "&amp;")
	        .replace(/</g, "&lt;")
	        .replace(/>/g, "&gt;")
	        .replace(/"/g, "&quot;")
	        .replace(/'/g, "&#39;");
	    }

	    function safeHref(value) {
	      const href = String(value || "").trim();
	      const lower = href.toLowerCase();
	      if (lower.startsWith("http://") || lower.startsWith("https://") || lower.startsWith("mailto:") || href.startsWith("/") || href.startsWith("#")) {
	        return href;
	      }
	      return "#";
	    }

	    function escapeRegExp(value) {
	      return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
	    }

	    function globalSearchShortcutText() {
	      return /Mac|iPhone|iPad|iPod/i.test(navigator.platform || navigator.userAgent || "") ? "⌘K" : "Ctrl K";
	    }

	    function globalSearchIcon(type, role) {
	      if (type === "conversation") return "messages-square";
	      if (type === "favorite") return "star";
	      if (type === "media") return "file-video";
	      if (role === "user") return "user-round";
	      if (role === "assistant") return "cat";
	      return "message-square";
	    }

	    function globalSearchTypeLabel(item) {
	      if (item.type === "conversation") return "会话";
	      if (item.type === "favorite") return "收藏";
	      if (item.type === "media") return "音视频";
	      if (item.role === "user") return "用户消息";
	      if (item.role === "assistant") return "槑槑回复";
	      return "消息";
	    }

	    function highlightSearchText(value, query = state.globalSearchQuery) {
	      const text = String(value || "");
	      const q = String(query || "").trim();
	      if (!q) return escapeHTML(text);
	      const pattern = new RegExp("(" + escapeRegExp(q) + ")", "ig");
	      return escapeHTML(text).replace(pattern, "<mark>$1</mark>");
	    }

	    function openGlobalSearch() {
	      if (!state.authed) return;
	      const dialog = $("globalSearchDialog");
	      const input = $("globalSearchInput");
	      if (!dialog || !input) return;
	      dialog.classList.add("show");
	      setDialogOpenState();
	      state.globalSearchSelected = 0;
	      state.globalSearchQuery = "";
	      state.globalSearchError = "";
	      input.value = "";
	      renderGlobalSearchResults();
	      runGlobalSearch("");
	      setTimeout(() => {
	        input.focus();
	        input.select();
	      }, 30);
	    }

	    function closeGlobalSearch() {
	      const dialog = $("globalSearchDialog");
	      if (!dialog) return;
	      dialog.classList.remove("show");
	      if (state.globalSearchTimer) {
	        clearTimeout(state.globalSearchTimer);
	        state.globalSearchTimer = 0;
	      }
	      setDialogOpenState();
	    }

	    function versionLabel(version) {
	      const text = String(version || "").trim();
	      return text ? (text.startsWith("v") ? text : "v" + text) : "v";
	    }

	    function renderChangelogLoading() {
	      const box = $("changelogList");
	      if (!box) return;
	      box.replaceChildren(createEmptyState("loader-circle", "槑槑正在翻更新记录...", "稍等一下。", { compact: true }));
	      queueLucideRefresh();
	    }

	    function renderChangelogEntries() {
	      const box = $("changelogList");
	      const more = $("openFullChangelog");
	      const title = $("changelogTitleText");
	      if (!box || !more || !title) return;
	      const entries = state.changelogEntries || [];
	      title.textContent = state.changelogFull ? "完整更新日志" : "最近更新";
	      more.hidden = state.changelogFull || (!state.changelogHasMore && entries.length <= 8);
	      box.replaceChildren();
	      if (!entries.length) {
	        const empty = document.createElement("div");
	        empty.className = "changelog-empty";
	        empty.textContent = "暂无更新日志";
	        box.appendChild(empty);
	        queueLucideRefresh();
	        return;
	      }
	      const current = String(state.changelogVersion || "").replace(/^v/i, "");
	      for (const entry of entries) {
	        const article = document.createElement("article");
	        const isCurrent = String(entry.version || "").replace(/^v/i, "") === current;
	        article.className = "changelog-entry" + (isCurrent ? " is-current" : "");
	        const points = Array.isArray(entry.points) ? entry.points : [];
	        const visiblePoints = state.changelogFull ? points : points.slice(0, 4);
	        article.innerHTML =
	          '<div class="changelog-entry-head">' +
	            '<span class="changelog-version"><span>' + escapeHTML(versionLabel(entry.version)) + '</span>' +
	              (isCurrent ? '<span class="changelog-current">当前版本</span>' : '') +
	            '</span>' +
	            '<span class="changelog-date">' + escapeHTML(entry.date || "") + '</span>' +
	          '</div>' +
	          '<h3>' + escapeHTML(entry.title || "更新内容") + '</h3>' +
	          '<ul class="changelog-points">' + (visiblePoints.length ? visiblePoints.map((point) => '<li>' + escapeHTML(point) + '</li>').join("") : '<li>暂无详细说明。</li>') + '</ul>' +
	          (entry.commit ? '<span class="changelog-commit">' + escapeHTML(entry.commit) + '</span>' : '');
	        box.appendChild(article);
	      }
	      queueLucideRefresh();
	    }

	    function positionChangelogPanel() {
	      const dialog = $("changelogDialog");
	      const panel = $("changelogPanel");
	      const anchor = state.changelogAnchor;
	      if (!dialog || !panel || !anchor || state.changelogFull || isSmallScreen()) return;
	      const rect = anchor.getBoundingClientRect();
	      const width = Math.min(430, window.innerWidth - 24);
	      const height = Math.min(panel.offsetHeight || 520, window.innerHeight - 24);
	      const left = clampNumber(rect.left, 12, Math.max(12, window.innerWidth - width - 12), 12);
	      let top = rect.bottom + 10;
	      if (top + height > window.innerHeight - 12) top = rect.top - height - 10;
	      top = clampNumber(top, 12, Math.max(12, window.innerHeight - height - 12), 12);
	      panel.style.width = width + "px";
	      panel.style.left = left + "px";
	      panel.style.top = top + "px";
	      panel.style.bottom = "auto";
	    }

	    async function openChangelog(event, options = {}) {
	      event?.preventDefault();
	      event?.stopPropagation();
	      const dialog = $("changelogDialog");
	      const panel = $("changelogPanel");
	      if (!dialog || !panel) return;
	      state.changelogFull = Boolean(options.full);
	      if (!state.changelogFull) state.changelogAnchor = event?.currentTarget || state.changelogAnchor;
	      dialog.classList.add("show");
	      dialog.classList.toggle("full", state.changelogFull);
	      panel.setAttribute("aria-modal", state.changelogFull ? "true" : "false");
	      renderChangelogLoading();
	      setDialogOpenState();
	      try {
	        const url = "/api/changelog" + (state.changelogFull ? "" : "?limit=8");
	        const res = await request(url);
	        if (!res.ok) throw new Error(await readError(res, "更新日志暂时加载失败。"));
	        const data = await res.json();
	        state.changelogEntries = data.entries || [];
	        state.changelogVersion = data.version || "";
	        state.changelogHasMore = Boolean(data.has_more);
	        renderChangelogEntries();
	        requestAnimationFrame(positionChangelogPanel);
	      } catch (err) {
	        const box = $("changelogList");
	        if (box) box.replaceChildren(createEmptyState("circle-alert", friendlyError(err, "更新日志暂时加载失败。"), "", { compact: true }));
	        queueLucideRefresh();
	      }
	    }

	    function closeChangelog() {
	      const dialog = $("changelogDialog");
	      if (!dialog) return;
	      dialog.classList.remove("show", "full");
	      state.changelogFull = false;
	      setDialogOpenState();
	    }

	    function handleChangelogOutsideClick(event) {
	      const dialog = $("changelogDialog");
	      const panel = $("changelogPanel");
	      if (!dialog || !panel || !dialog.classList.contains("show")) return;
	      if (panel.contains(event.target) || event.target.closest?.("[data-version-trigger]")) return;
	      closeChangelog();
	    }

	    function scheduleGlobalSearch() {
	      const input = $("globalSearchInput");
	      state.globalSearchQuery = input ? input.value.trim() : "";
	      state.globalSearchLoading = true;
	      state.globalSearchError = "";
	      renderGlobalSearchResults();
	      if (state.globalSearchTimer) clearTimeout(state.globalSearchTimer);
	      state.globalSearchTimer = window.setTimeout(() => {
	        state.globalSearchTimer = 0;
	        runGlobalSearch(state.globalSearchQuery);
	      }, 200);
	    }

	    async function runGlobalSearch(query) {
	      const seq = ++state.globalSearchSeq;
	      state.globalSearchLoading = true;
	      state.globalSearchError = "";
	      renderGlobalSearchResults();
	      try {
	        const res = await api("/api/search?q=" + encodeURIComponent(query || ""));
	        if (!res.ok) throw new Error(await readError(res, "搜索失败，稍后再试一下。"));
	        const data = await res.json();
	        if (seq !== state.globalSearchSeq) return;
	        state.globalSearchResults = data.results || [];
	        state.globalSearchSelected = 0;
	        state.globalSearchLoading = false;
	        renderGlobalSearchResults();
	      } catch (err) {
	        if (seq !== state.globalSearchSeq) return;
	        state.globalSearchResults = [];
	        state.globalSearchLoading = false;
	        state.globalSearchError = friendlyError(err, "搜索暂时不可用，稍后再试一下。");
	        renderGlobalSearchResults();
	      }
	    }

	    function renderGlobalSearchResults() {
	      const box = $("globalSearchResults");
	      if (!box) return;
	      box.replaceChildren();
	      if (state.globalSearchLoading && !state.globalSearchResults.length) {
	        box.appendChild(createEmptyState("loader-circle", "槑槑正在搜索...", "稍等一下，正在翻历史记录。", { compact: true }));
	        queueLucideRefresh();
	        return;
	      }
	      if (state.globalSearchError) {
	        box.appendChild(createEmptyState("circle-alert", state.globalSearchError, "", { compact: true }));
	        queueLucideRefresh();
	        return;
	      }
	      if (!state.globalSearchResults.length) {
	        const title = state.globalSearchQuery ? "槑槑没有找到相关内容" : "输入关键词开始搜索";
	        const desc = state.globalSearchQuery ? "换个关键词试试看。" : "可以搜索会话标题、历史消息、收藏和音视频分析。";
	        box.appendChild(createEmptyState("search", title, desc, { compact: true }));
	        queueLucideRefresh();
	        return;
	      }
	      for (const [index, item] of state.globalSearchResults.entries()) {
	        const button = document.createElement("button");
	        button.type = "button";
	        button.className = "global-search-item" + (index === state.globalSearchSelected ? " active" : "");
	        button.setAttribute("role", "option");
	        button.setAttribute("aria-selected", index === state.globalSearchSelected ? "true" : "false");
	        button.dataset.index = String(index);
	        const roleLabel = item.role ? (item.role === "assistant" ? "槑槑" : (item.role === "user" ? "用户" : item.role)) : globalSearchTypeLabel(item);
	        button.innerHTML =
	          '<span class="global-search-icon">' + iconMarkup(globalSearchIcon(item.type, item.role)) + '</span>' +
	          '<span class="global-search-content">' +
	            '<span class="global-search-title"><span>' + highlightSearchText(item.title || "未命名对话") + '</span><span class="global-search-role">' + escapeHTML(roleLabel) + '</span></span>' +
	            '<span class="global-search-snippet">' + highlightSearchText(item.snippet || "最近对话") + '</span>' +
	          '</span>' +
	          '<span class="global-search-time">' + escapeHTML(formatTime(item.created_at)) + '</span>';
	        button.addEventListener("mouseenter", () => {
	          setGlobalSearchSelected(index);
	        });
	        button.addEventListener("click", () => openGlobalSearchResult(item));
	        box.appendChild(button);
	      }
	      queueLucideRefresh();
	      scrollSelectedGlobalSearchIntoView();
	    }

	    function scrollSelectedGlobalSearchIntoView() {
	      const selected = $("globalSearchResults")?.querySelector(".global-search-item.active");
	      if (selected) selected.scrollIntoView({ block: "nearest" });
	    }

	    function setGlobalSearchSelected(index) {
	      if (!state.globalSearchResults.length) return;
	      state.globalSearchSelected = clampNumber(index, 0, state.globalSearchResults.length - 1, 0);
	      const items = $("globalSearchResults")?.querySelectorAll(".global-search-item") || [];
	      items.forEach((node, itemIndex) => {
	        const active = itemIndex === state.globalSearchSelected;
	        node.classList.toggle("active", active);
	        node.setAttribute("aria-selected", active ? "true" : "false");
	      });
	      scrollSelectedGlobalSearchIntoView();
	    }

	    function moveGlobalSearchSelection(delta) {
	      if (!state.globalSearchResults.length) return;
	      const length = state.globalSearchResults.length;
	      setGlobalSearchSelected((state.globalSearchSelected + delta + length) % length);
	    }

	    function handleGlobalSearchKeydown(event) {
	      if (event.key === "Escape") {
	        event.preventDefault();
	        closeGlobalSearch();
	        return;
	      }
	      if (event.key === "ArrowDown") {
	        event.preventDefault();
	        moveGlobalSearchSelection(1);
	        return;
	      }
	      if (event.key === "ArrowUp") {
	        event.preventDefault();
	        moveGlobalSearchSelection(-1);
	        return;
	      }
	      if (event.key === "Home") {
	        event.preventDefault();
	        setGlobalSearchSelected(0);
	        return;
	      }
	      if (event.key === "End") {
	        event.preventDefault();
	        setGlobalSearchSelected(Math.max(0, state.globalSearchResults.length - 1));
	        return;
	      }
	      if (event.key === "Enter") {
	        event.preventDefault();
	        const item = state.globalSearchResults[state.globalSearchSelected];
	        if (item) openGlobalSearchResult(item);
	      }
	    }

	    async function openGlobalSearchResult(item) {
	      if (!item) return;
	      closeGlobalSearch();
	      const sessionId = item.session_id || "";
	      if (sessionId) {
	        if (!state.conversations.some((conv) => conv.id === sessionId)) {
	          await loadConversations();
	        }
	        await selectConversation(sessionId, { messageId: item.message_id });
	        return;
	      }
	      if (item.type === "favorite") {
	        const favoriteId = String(item.id || "").replace(/^favorite:/, "");
	        await openFavorites();
	        state.selectedFavoriteId = Number(favoriteId || 0) || null;
	        renderFavorites();
	        setStatus("chatStatus", "原会话已删除，已打开收藏内容。", "");
	        return;
	      }
	      if (item.type === "media") {
	        const taskId = String(item.id || "").replace(/^media:/, "");
	        await openMediaAnalysis();
	        state.selectedMediaTaskId = taskId;
	        renderMediaTasks();
	        renderMediaDetail();
	        return;
	      }
	      setStatus("chatStatus", "这条结果暂时无法直接打开。", "err");
	    }

	    function renderInlineMarkdown(value) {
	      const placeholders = [];
	      let text = String(value || "").replace(/`([^`\n]+)`/g, (_, code) => {
	        const token = "\u0000" + placeholders.length + "\u0000";
	        placeholders.push("<code>" + escapeHTML(code) + "</code>");
	        return token;
	      });
	      let html = escapeHTML(text);
	      html = html.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_, alt, href) => {
	        const src = safeHref(href);
	        if (src === "#") return escapeHTML(alt || "");
	        return '<span class="media-wrapper"><img src="' + escapeHTML(src) + '" alt="' + alt + '" loading="lazy"></span>';
	      });
	      html = html.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, href) => {
	        return '<a href="' + escapeHTML(safeHref(href)) + '" target="_blank" rel="noreferrer">' + label + "</a>";
	      });
	      html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
	      html = html.replace(/__([^_]+)__/g, "<strong>$1</strong>");
	      html = html.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
	      html = html.replace(/(^|[^_])_([^_\n]+)_/g, "$1<em>$2</em>");
	      placeholders.forEach((item, index) => {
	        html = html.split("\u0000" + index + "\u0000").join(item);
	      });
	      return html;
	    }

	    function splitTableRow(line) {
	      return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
	    }

	    function isTableDivider(line) {
	      return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line || "");
	    }

	    function legacyRenderMarkdown(source) {
	      const lines = String(source || "").replace(/\r\n/g, "\n").split("\n");
	      const html = [];
	      let paragraph = [];
	      let listType = "";
	      let listItems = [];
	      let codeLang = "";
	      let codeLines = [];

	      function flushParagraph() {
	        if (!paragraph.length) return;
	        html.push("<p>" + renderInlineMarkdown(paragraph.join("\n")).replace(/\n/g, "<br>") + "</p>");
	        paragraph = [];
	      }

	      function flushList() {
	        if (!listItems.length) return;
	        const tag = listType === "ol" ? "ol" : "ul";
	        html.push("<" + tag + ">" + listItems.map((item) => "<li>" + renderInlineMarkdown(item) + "</li>").join("") + "</" + tag + ">");
	        listItems = [];
	        listType = "";
	      }

	      function flushCode() {
	        const className = codeLang ? ' class="language-' + escapeHTML(codeLang) + '"' : "";
	        const lang = escapeHTML(codeLang || "text");
	        html.push('<div class="code-block"><div class="code-head"><span>' + lang + '</span></div><pre><code' + className + ">" + escapeHTML(codeLines.join("\n")) + "</code></pre></div>");
	        codeLines = [];
	        codeLang = "";
	      }

	      for (let i = 0; i < lines.length; i++) {
	        const line = lines[i];
	        const fence = line.match(/^```([A-Za-z0-9_-]+)?\s*$/);
	        if (codeLines.length || codeLang) {
	          if (fence) {
	            flushCode();
	          } else {
	            codeLines.push(line);
	          }
	          continue;
	        }
	        if (fence) {
	          flushParagraph();
	          flushList();
	          codeLang = fence[1] || "text";
	          codeLines = [];
	          continue;
	        }

	        if (!line.trim()) {
	          flushParagraph();
	          flushList();
	          continue;
	        }

	        if (line.includes("|") && i + 1 < lines.length && isTableDivider(lines[i + 1])) {
	          flushParagraph();
	          flushList();
	          const headers = splitTableRow(line);
	          i += 2;
	          const rows = [];
	          while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
	            rows.push(splitTableRow(lines[i]));
	            i++;
	          }
	          i--;
	          html.push(
	            '<div class="table-wrapper" role="region" aria-label="表格，可左右滑动查看"><table><thead><tr>' +
	            headers.map((cell) => "<th>" + renderInlineMarkdown(cell) + "</th>").join("") +
	            "</tr></thead><tbody>" +
	            rows.map((row) => "<tr>" + row.map((cell) => "<td>" + renderInlineMarkdown(cell) + "</td>").join("") + "</tr>").join("") +
	            '</tbody></table><span class="table-scroll-hint">← 左右滑动查看 →</span></div>'
	          );
	          continue;
	        }

	        if (/^\s{0,3}(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$/.test(line)) {
	          flushParagraph();
	          flushList();
	          html.push("<hr>");
	          continue;
	        }

	        const heading = line.match(/^(#{1,6})\s+(.+)$/);
	        if (heading) {
	          flushParagraph();
	          flushList();
	          const level = heading[1].length;
	          html.push("<h" + level + ">" + renderInlineMarkdown(heading[2]) + "</h" + level + ">");
	          continue;
	        }

	        const quote = line.match(/^>\s?(.*)$/);
	        if (quote) {
	          flushParagraph();
	          flushList();
	          const parts = [quote[1]];
	          while (i + 1 < lines.length && /^>\s?/.test(lines[i + 1])) {
	            i++;
	            parts.push(lines[i].replace(/^>\s?/, ""));
	          }
	          html.push("<blockquote>" + renderInlineMarkdown(parts.join("\n")).replace(/\n/g, "<br>") + "</blockquote>");
	          continue;
	        }

	        const unordered = line.match(/^\s*[-*+]\s+(.+)$/);
	        const ordered = line.match(/^\s*\d+\.\s+(.+)$/);
	        if (unordered || ordered) {
	          flushParagraph();
	          const nextType = ordered ? "ol" : "ul";
	          if (listType && listType !== nextType) flushList();
	          listType = nextType;
	          listItems.push((unordered || ordered)[1]);
	          continue;
	        }

	        flushList();
	        paragraph.push(line);
	      }
	      if (codeLines.length || codeLang) flushCode();
	      flushParagraph();
	      flushList();
	      return html.join("");
	    }

	    function renderMarkdown(source) {
	      if (window.AIMarkdown?.isReady()) return window.AIMarkdown.render(source);
	      return legacyRenderMarkdown(source);
	    }

	    function renderMessageMarkdown(message, source, slot = "content") {
	      const value = String(source || "");
	      const sourceKey = slot === "reasoning" ? "_reasoningMarkdownSource" : "_contentMarkdownSource";
	      const htmlKey = slot === "reasoning" ? "_reasoningMarkdownHtml" : "_contentMarkdownHtml";
	      if (message?.[sourceKey] === value && typeof message?.[htmlKey] === "string") return message[htmlKey];
	      const html = renderMarkdown(value);
	      if (message) {
	        message[sourceKey] = value;
	        message[htmlKey] = html;
	      }
	      return html;
	    }

	    function enhanceMarkdown(root, options = {}) {
	      if (window.AIMarkdown?.isReady()) {
	        window.AIMarkdown.enhance(root, options);
	        return;
	      }
	      queueMarkdownOverflowRefresh(root);
	    }

	    function refreshMarkdownOverflow(root = document) {
	      const scope = root || document;
	      scope.querySelectorAll(".table-wrapper").forEach((wrapper) => {
	        const table = wrapper.querySelector("table");
	        const overflowing = Boolean(table && table.scrollWidth > wrapper.clientWidth + 2);
	        wrapper.classList.toggle("is-overflowing", overflowing);
	        wrapper.classList.toggle("is-scrolled", wrapper.scrollLeft > 8);
	        if (!wrapper.dataset.scrollHintBound) {
	          wrapper.dataset.scrollHintBound = "1";
	          wrapper.addEventListener("scroll", () => {
	            wrapper.classList.toggle("is-scrolled", wrapper.scrollLeft > 8);
	          }, { passive: true });
	        }
	      });
	    }

	    function queueMarkdownOverflowRefresh(root = document) {
	      requestAnimationFrame(() => refreshMarkdownOverflow(root));
	    }

	    function splitThinkContent(value) {
	      const reasoning = [];
	      let content = String(value || "").replace(/<think>\s*([\s\S]*?)\s*<\/think>/gi, (_, text) => {
	        const clean = String(text || "").trim();
	        if (clean) reasoning.push(clean);
	        return "";
	      });
	      let reasoningOpen = false;
	      const openIndex = content.toLowerCase().lastIndexOf("<think>");
	      if (openIndex >= 0) {
	        const trailing = content.slice(openIndex + 7).trim();
	        if (trailing) reasoning.push(trailing);
	        content = content.slice(0, openIndex);
	        reasoningOpen = true;
	      }
	      return { content: content.trim(), reasoning: reasoning.join("\n\n"), reasoningOpen };
	    }

	    function visibleMessageContent(message) {
	      return splitThinkContent(message.content || "").content;
	    }

	    function parseQuotedUserContent(source) {
	      const value = String(source || "").trim();
	      const prefix = "以下是用户从当前会话中引用的内容：";
	      if (!value.startsWith(prefix)) return null;
	      const questionMarkers = ["\n\n用户的新问题：", "\n用户的新问题："];
	      let marker = "";
	      let markerIndex = -1;
	      for (const candidate of questionMarkers) {
	        const index = value.lastIndexOf(candidate);
	        if (index > markerIndex) {
	          marker = candidate;
	          markerIndex = index;
	        }
	      }
	      if (markerIndex < prefix.length) return null;
	      const quoteSource = value.slice(prefix.length, markerIndex).trim();
	      const question = value.slice(markerIndex + marker.length).trim();
	      const quotes = [];
	      const quotePattern = /【来源：([^】]+)】\s*([\s\S]*?)\s*【引用结束】/g;
	      let match;
	      while ((match = quotePattern.exec(quoteSource)) !== null) {
	        const text = String(match[2] || "")
	          .split(/\r?\n/)
	          .map((line) => line.replace(/^>\s?/, ""))
	          .join("\n")
	          .trim();
	        if (!text) continue;
	        quotes.push({
	          role: String(match[1] || "引用内容").trim(),
	          text
	        });
	      }
	      if (!quotes.length) return null;
	      return {
	        question: question || "请基于引用内容进行分析。",
	        quotes: quotes.slice(0, 3)
	      };
	    }

	    function quotedUserMessage(message) {
	      if (message?.role !== "user") return null;
	      const source = visibleMessageContent(message);
	      if (message._quotedUserSource === source) return message._quotedUserContent || null;
	      const parsed = parseQuotedUserContent(source);
	      message._quotedUserSource = source;
	      message._quotedUserContent = parsed;
	      return parsed;
	    }

	    function displayMessageContent(message) {
	      return quotedUserMessage(message)?.question || visibleMessageContent(message);
	    }

	    function copyableMessageContent(message) {
	      return displayMessageContent(message);
	    }

	    function closeMessageQuotePreviews(except = null) {
	      document.querySelectorAll(".message-quote-reference.open").forEach((node) => {
	        if (node === except) return;
	        node.classList.remove("open");
	        node.querySelector(".message-quote-trigger")?.setAttribute("aria-expanded", "false");
	      });
	    }

	    function renderMessageQuoteReference(panel, message) {
	      if (!panel) return;
	      const parsed = quotedUserMessage(message);
	      panel.replaceChildren();
	      panel.hidden = !parsed;
	      if (!parsed) return;
	      const trigger = document.createElement("button");
	      trigger.type = "button";
	      trigger.className = "message-quote-trigger";
	      trigger.setAttribute("aria-expanded", "false");
	      trigger.innerHTML = iconMarkup("quote", "⌜") + `<span>${parsed.quotes.length} 个引用</span>`;
	      const preview = document.createElement("div");
	      preview.className = "message-quote-preview";
	      preview.setAttribute("role", "tooltip");
	      parsed.quotes.forEach((quote) => {
	        const item = document.createElement("div");
	        item.className = "message-quote-preview-item";
	        const role = document.createElement("div");
	        role.className = "message-quote-preview-role";
	        role.textContent = quote.role;
	        const text = document.createElement("div");
	        text.className = "message-quote-preview-text";
	        text.textContent = quote.text;
	        item.append(role, text);
	        preview.appendChild(item);
	      });
	      trigger.addEventListener("click", (event) => {
	        event.stopPropagation();
	        const willOpen = !panel.classList.contains("open");
	        closeMessageQuotePreviews(panel);
	        panel.classList.toggle("open", willOpen);
	        trigger.setAttribute("aria-expanded", willOpen ? "true" : "false");
	      });
	      panel.append(trigger, preview);
	    }

	    function messageReasoningContent(message) {
	      const parts = [];
	      if (message.reasoning_content) parts.push(String(message.reasoning_content).trim());
	      const extracted = splitThinkContent(message.content || "");
	      if (extracted.reasoning) parts.push(extracted.reasoning);
	      return parts.filter(Boolean).join("\n\n").trim();
	    }

	    function reasoningPreview(reasoningContent) {
	      const lines = String(reasoningContent || "")
	        .replace(/<\/?(?:think|thinking|reasoning)>/gi, "\n")
	        .split(/\r?\n/)
	        .map((line) => line
	          .replace(/^\s{0,3}(?:#{1,6}|>|[-*+] |\d+[.)] )\s*/, "")
	          .replace(/```[a-z0-9_-]*|```/gi, "")
	          .replace(/[*_~`]+/g, "")
	          .replace(/\s+/g, " ")
	          .trim())
	        .filter((line) => line && /[\p{L}\p{N}]/u.test(line));
	      if (!lines.length) return "正在梳理信息与回答思路…";
	      let preview = lines[lines.length - 1];
	      if (preview.length < 28 && lines.length > 1) {
	        preview = lines.slice(-2).join(" ");
	      }
	      return preview.length > 96 ? preview.slice(-96).replace(/^\S*\s/, "") + "…" : preview;
	    }

	    function reasoningElapsedSeconds(message) {
	      const startedAt = Number(message?._reasoningStartedAt || message?._thinkingStartedAt || 0);
	      if (!startedAt) return 0;
	      const endedAt = Number(message?._reasoningCompletedAt || Date.now());
	      return Math.max(1, Math.round((endedAt - startedAt) / 1000));
	    }

	    function reasoningTokenCount(message) {
	      const usage = message?.usage || {};
	      return Number(
	        usage.reasoning_tokens ||
	        usage.completion_tokens_details?.reasoning_tokens ||
	        usage.output_tokens_details?.reasoning_tokens ||
	        0
	      );
	    }

	    function updateReasoningHeader(panel, message, reasoningContent) {
	      const isLive = Boolean(message.thinking && !message._reasoningCompletedAt);
	      const status = panel.querySelector(".reasoning-status");
	      const duration = panel.querySelector(".reasoning-duration");
	      const preview = panel.querySelector(".reasoning-preview");
	      const cursor = panel.querySelector(".reasoning-cursor");
	      const icon = panel.querySelector(".reasoning-state-icon");
	      if (status) status.textContent = isLive ? "正在思考" : "已思考";
	      if (duration) {
	        const seconds = reasoningElapsedSeconds(message);
	        const tokens = reasoningTokenCount(message);
	        duration.textContent = (seconds ? ` · ${seconds}秒` : "") + (tokens ? ` · ${formatTokens(tokens)}` : "");
	      }
	      if (preview) {
	        const nextPreview = message?._reasoningFrozenPreview || reasoningPreview(reasoningContent);
	        if (preview.textContent !== nextPreview) {
	          preview.classList.add("updating");
	          preview.textContent = nextPreview;
	          requestAnimationFrame(() => requestAnimationFrame(() => preview.classList.remove("updating")));
	        }
	      }
	      if (cursor) cursor.hidden = !isLive;
	      if (icon) {
	        const nextIcon = isLive ? "sparkles" : "check";
	        if (icon.dataset.lucide !== nextIcon) {
	          icon.dataset.lucide = nextIcon;
	          queueLucideRefresh();
	        }
	      }
	    }

	    function renderReasoningPanel(panel, message, reasoningContent, options = {}) {
	      if (!panel) return;
	      if (message.role !== "assistant" || !reasoningContent) {
	        panel.hidden = true;
	        panel.replaceChildren();
	        return;
	      }
	      panel.hidden = false;
	      panel.classList.toggle("open", Boolean(message.reasoning_open));
	      const toggle = document.createElement("button");
	      toggle.className = "reasoning-toggle";
	      toggle.type = "button";
	      toggle.innerHTML = `
	        <i class="reasoning-state-icon" data-lucide="${message.thinking ? "sparkles" : "check"}" aria-hidden="true"></i>
	        <span class="reasoning-status">${message.thinking ? "正在思考" : "已思考"}</span>
	        <span class="reasoning-duration"></span>
	        <span class="reasoning-preview"></span>
	        <span class="reasoning-cursor" aria-hidden="true">▌</span>
	        <i class="reasoning-chevron" data-lucide="chevron-down" aria-hidden="true"></i>`;
	      toggle.title = message.reasoning_open ? "收起思考过程" : "展开思考过程";
	      toggle.addEventListener("click", () => toggleReasoning(message));
	      const body = document.createElement("div");
	      body.className = "reasoning-body";
	      body.hidden = !message.reasoning_open;
	      if (message.reasoning_open) {
	        const markdown = document.createElement("div");
	        markdown.className = "markdown reasoning-markdown";
	        body.appendChild(markdown);
	        renderStreamingMarkdown(markdown, message, reasoningContent, {
	          final: Boolean(options.final || !message.thinking),
	          slot: "reasoning"
	        });
	        const footer = document.createElement("div");
	        footer.className = "reasoning-actions";
	        const copy = document.createElement("button");
	        copy.type = "button";
	        copy.className = "reasoning-action";
	        copy.innerHTML = iconLabel("copy", "复制思考内容", "⧉");
	        copy.addEventListener("click", (event) => {
	          event.stopPropagation();
	          copyText(messageReasoningContent(message), copy);
	        });
	        const collapse = document.createElement("button");
	        collapse.type = "button";
	        collapse.className = "reasoning-action";
	        collapse.innerHTML = iconLabel("chevron-up", "收起", "⌃");
	        collapse.addEventListener("click", (event) => {
	          event.stopPropagation();
	          toggleReasoning(message);
	        });
	        footer.append(copy, collapse);
	        body.appendChild(footer);
	      }
	      panel.replaceChildren(toggle, body);
	      updateReasoningHeader(panel, message, reasoningContent);
	    }

	    function sourceDomain(value) {
	      try {
	        return new URL(value).hostname.replace(/^www\./, "");
	      } catch {
	        return "来源";
	      }
	    }

	    function renderSourcesPanel(panel, sources) {
	      if (!panel) return;
	      const items = Array.isArray(sources) ? sources.filter((item) => item && item.url) : [];
	      panel.hidden = !items.length;
	      panel.innerHTML = "";
	      if (!items.length) return;
	      const title = document.createElement("div");
	      title.className = "sources-title";
	      title.textContent = "参考来源";
	      const list = document.createElement("div");
	      list.className = "sources-list";
	      for (const item of items.slice(0, 6)) {
	        const link = document.createElement("a");
	        link.className = "source-card";
	        link.href = safeHref(item.url);
	        link.target = "_blank";
	        link.rel = "noreferrer";
	        link.title = item.title || item.url;
	        const strong = document.createElement("strong");
	        strong.textContent = (item.position ? item.position + ". " : "") + (item.title || sourceDomain(item.url));
	        const domain = document.createElement("span");
	        domain.textContent = sourceDomain(item.url);
	        link.append(strong, domain);
	        list.appendChild(link);
	      }
	      panel.append(title, list);
	    }

	    function formatMessageTime(value) {
	      const ts = Number(value || 0);
	      const date = ts > 0 ? new Date(ts * 1000) : new Date();
	      const pad = (num) => String(num).padStart(2, "0");
	      return pad(date.getHours()) + ":" + pad(date.getMinutes()) + ":" + pad(date.getSeconds());
	    }

	    function messageTotalTokens(message) {
	      const usage = message?.usage || {};
	      const direct = Number(message?.total_tokens || 0);
	      const total = Number(usage.total_tokens || direct || 0);
	      if (total > 0) return total;
	      const prompt = Number(usage.prompt_tokens || message?.prompt_tokens || 0);
	      const completion = Number(usage.completion_tokens || message?.completion_tokens || 0);
	      return prompt + completion;
	    }

	    function formatTokens(value) {
	      const num = Number(value || 0);
	      if (!num) return "";
	      return num >= 1000 ? (num / 1000).toFixed(num >= 10000 ? 0 : 1) + "k tokens" : num + " tokens";
	    }

	    function currentConversationTokens() {
	      return state.messages.reduce((sum, item) => sum + messageTotalTokens(item), 0);
	    }

	    async function loadConversationStats(id = state.currentConversation?.id) {
	      if (!id) {
	        state.conversationStats = null;
	        updateChatUsage();
	        return;
	      }
	      try {
	        const res = await api(`/api/conversations/${id}/stats`);
	        if (!res.ok) throw new Error(await readError(res, "统计暂时加载失败。"));
	        const data = await res.json();
	        if (state.currentConversation?.id !== id) return;
	        state.conversationStats = data.stats || null;
	      } catch {
	        if (state.currentConversation?.id === id) state.conversationStats = null;
	      }
	      updateChatUsage();
	    }

	    function updateChatUsage() {
	      const el = $("chatUsage");
	      if (!el) return;
	      if (!state.currentConversation) {
	        el.textContent = "";
	        el.title = "";
	        return;
	      }
	      const stats = state.conversationStats || {};
	      const tokens = Math.max(Number(stats.total_tokens || 0), currentConversationTokens());
	      const localTurns = state.messages.filter((item) => item.role === "user").length;
	      const turns = Math.max(Number(stats.turn_count || 0), localTurns);
	      const compactParts = [];
	      if (tokens) compactParts.push(formatTokens(tokens));
	      if (turns) compactParts.push(turns + "轮");
	      const detailParts = [...compactParts];
	      if (stats.web_search_count) detailParts.push(stats.web_search_count + "次联网");
	      if (stats.attachment_count) detailParts.push(stats.attachment_count + "张图片");
	      if (stats.media_task_count) detailParts.push(stats.media_task_count + "个音视频");
	      if (stats.model_code) detailParts.push(stats.model_code);
	      if (stats.updated_at) detailParts.push("更新 " + formatTime(stats.updated_at));
	      const mobile = isSmallScreen();
	      const visibleParts = mobile ? compactParts : detailParts;
	      el.textContent = visibleParts.length ? visibleParts.join(" · ") : "";
	      el.title = detailParts.join(" · ");
	    }

	    function updateFavoriteCount() {
	      const el = $("favoriteCount");
	      if (!el) return;
	      const count = state.favorites.length;
	      el.textContent = String(count);
	      el.hidden = count <= 0;
	    }

	    function minimapAvailable() {
	      return window.matchMedia && window.matchMedia("(min-width: 901px)").matches;
	    }

	    function hideConversationMinimap() {
	      const minimap = $("conversationMinimap");
	      const tooltip = $("minimapTooltip");
	      if (state.minimapFadeTimer) {
	        clearTimeout(state.minimapFadeTimer);
	        state.minimapFadeTimer = 0;
	      }
	      if (state.minimapCollapseTimer) {
	        clearTimeout(state.minimapCollapseTimer);
	        state.minimapCollapseTimer = 0;
	      }
	      if (state.minimapTooltipTimer) {
	        clearTimeout(state.minimapTooltipTimer);
	        state.minimapTooltipTimer = 0;
	      }
	      if (minimap) {
	        minimap.hidden = true;
	        minimap.classList.remove("is-scrolling", "is-expanded");
	      }
	      if (tooltip) tooltip.classList.remove("show");
	    }

	    function expandConversationMinimap() {
	      const minimap = $("conversationMinimap");
	      if (!minimap || minimap.hidden) return;
	      if (state.minimapCollapseTimer) {
	        clearTimeout(state.minimapCollapseTimer);
	        state.minimapCollapseTimer = 0;
	      }
	      minimap.classList.add("is-expanded");
	    }

	    function scheduleCollapseConversationMinimap() {
	      const minimap = $("conversationMinimap");
	      if (!minimap || minimap.hidden) return;
	      if (state.minimapCollapseTimer) clearTimeout(state.minimapCollapseTimer);
	      state.minimapCollapseTimer = window.setTimeout(() => {
	        minimap.classList.remove("is-expanded");
	        hideMinimapTooltip(true);
	        state.minimapCollapseTimer = 0;
	      }, 300);
	    }

	    function handleMinimapOutsidePointer(event) {
	      const minimap = $("conversationMinimap");
	      if (!minimap || minimap.hidden || !minimap.classList.contains("is-expanded")) return;
	      if (minimap.contains(event.target)) return;
	      const active = document.activeElement;
	      if (active && minimap.contains(active) && typeof active.blur === "function") active.blur();
	      scheduleCollapseConversationMinimap();
	    }

	    function pulseConversationMinimap() {
	      const minimap = $("conversationMinimap");
	      if (!minimap || minimap.hidden) return;
	      minimap.classList.add("is-scrolling");
	      if (state.minimapFadeTimer) clearTimeout(state.minimapFadeTimer);
	      state.minimapFadeTimer = window.setTimeout(() => {
	        minimap.classList.remove("is-scrolling");
	        state.minimapFadeTimer = 0;
	      }, 820);
	    }

	    function messageMinimapFlags(message) {
	      const content = String(message?.content || "");
	      const sources = Array.isArray(message?.sources) ? message.sources : [];
	      const images = messageImages(message);
	      return {
	        search: sources.length > 0 || /联网搜索|参考来源|搜索结果/i.test(content),
	        media: /ai-meimei-media-task|音视频分析|通义听悟|转写全文|智能摘要/i.test(content),
	        image: images.length > 0,
	        attachment: images.length > 0 || /附件|文件|图片/i.test(content),
	        favorite: Boolean(message?.favorite_id)
	      };
	    }

	    function messageMinimapTitle(message, flags) {
	      const base = message?.role === "user" ? "用户" : (message?.role === "assistant" ? "槑槑" : "系统");
	      const tags = [];
	      if (flags.search) tags.push("联网搜索");
	      if (flags.media) tags.push("音视频分析");
	      if (flags.image) tags.push("图片");
	      else if (flags.attachment) tags.push("附件");
	      if (flags.favorite) tags.push("已收藏");
	      return tags.length ? base + " · " + tags.join(" · ") : base;
	    }

	    function messageMinimapSummary(message) {
	      const text = visibleMessageContent(message)
	        .replace(/[#>*_`\[\]()]/g, "")
	        .replace(/\s+/g, " ")
	        .trim();
	      if (text) return text.slice(0, 60);
	      if (messageImages(message).length) return "图片消息";
	      if (message?.thinking) return "槑槑正在整理思路...";
	      return "暂无可预览内容";
	    }

	    function minimapMarkerClass(message, flags) {
	      const classes = ["minimap-marker", "is-" + (message?.role || "system")];
	      if (flags.search) classes.push("has-search");
	      if (flags.media) classes.push("has-media");
	      if (flags.image) classes.push("has-image");
	      if (flags.attachment) classes.push("has-attachment");
	      if (flags.favorite) classes.push("has-favorite");
	      return classes.join(" ");
	    }

	    function showMinimapTooltip(message, marker, event) {
	      const tooltip = $("minimapTooltip");
	      const minimap = $("conversationMinimap");
	      if (!tooltip || !minimap || !marker) return;
	      expandConversationMinimap();
	      if (state.minimapTooltipTimer) {
	        clearTimeout(state.minimapTooltipTimer);
	        state.minimapTooltipTimer = 0;
	      }
	      const flags = messageMinimapFlags(message);
	      const tokens = messageTotalTokens(message);
	      const meta = [formatMessageTime(message?.created_at)];
	      if (tokens) meta.push(formatTokens(tokens));
	      tooltip.innerHTML =
	        "<strong>" + escapeHTML(messageMinimapTitle(message, flags)) + "</strong>" +
	        "<span>" + escapeHTML(meta.filter(Boolean).join(" · ")) + "</span>" +
	        "<p>" + escapeHTML(messageMinimapSummary(message)) + "</p>";
	      const pointerY = event?.clientY ? event.clientY - minimap.getBoundingClientRect().top : marker.offsetTop + marker.offsetHeight / 2;
	      const y = clampNumber(pointerY, 34, Math.max(34, minimap.clientHeight - 34), 34);
	      tooltip.style.top = y + "px";
	      tooltip.classList.add("show");
	    }

	    function hideMinimapTooltip(immediate = false) {
	      const tooltip = $("minimapTooltip");
	      if (!tooltip) return;
	      if (state.minimapTooltipTimer) clearTimeout(state.minimapTooltipTimer);
	      if (immediate) {
	        tooltip.classList.remove("show");
	        state.minimapTooltipTimer = 0;
	        return;
	      }
	      state.minimapTooltipTimer = window.setTimeout(() => {
	        tooltip.classList.remove("show");
	        state.minimapTooltipTimer = 0;
	      }, 120);
	    }

	    function updateConversationMinimapViewport() {
	      const box = $("messages");
	      const track = $("minimapTrack");
	      const viewport = $("minimapViewport");
	      const minimap = $("conversationMinimap");
	      if (!box || !track || !viewport || !minimap || minimap.hidden) return;
	      const trackHeight = track.clientHeight;
	      const scrollHeight = Math.max(box.scrollHeight, box.clientHeight, 1);
	      const height = clampNumber((box.clientHeight / scrollHeight) * trackHeight, 18, trackHeight, trackHeight);
	      const top = clampNumber((box.scrollTop / scrollHeight) * trackHeight, 0, Math.max(0, trackHeight - height), 0);
	      viewport.style.height = height + "px";
	      viewport.style.top = top + "px";
	    }

	    function scrollToMinimapMessage(message, behavior = "smooth") {
	      const box = $("messages");
	      const wrap = box?.querySelector(`[data-message-key="${messageKey(message)}"]`);
	      if (!box || !wrap) return;
	      const target = clampNumber(
	        wrap.offsetTop - Math.max(36, (box.clientHeight - wrap.offsetHeight) / 2),
	        0,
	        Math.max(0, box.scrollHeight - box.clientHeight),
	        0
	      );
	      state.programmaticScroll = true;
	      box.scrollTo({ top: target, behavior });
	      pulseConversationMinimap();
	      setTimeout(() => {
	        state.programmaticScroll = false;
	        handleMessagesScroll();
	      }, behavior === "smooth" ? 520 : 0);
	      updateConversationMinimapViewport();
	    }

	    function renderConversationMinimap() {
	      const minimap = $("conversationMinimap");
	      const track = $("minimapTrack");
	      const viewport = $("minimapViewport");
	      const box = $("messages");
	      if (!minimap || !track || !viewport || !box) return;
	      track.querySelectorAll(".minimap-marker").forEach((node) => node.remove());
	      if (!minimapAvailable() || !state.messages.length) {
	        hideConversationMinimap();
	        return;
	      }
	      minimap.hidden = false;
	      const scrollHeight = Math.max(box.scrollHeight, box.clientHeight, 1);
	      const trackHeight = track.clientHeight;
	      if (!trackHeight || !scrollHeight) {
	        hideConversationMinimap();
	        return;
	      }
	      for (const message of state.messages) {
	        const wrap = box.querySelector(`[data-message-key="${messageKey(message)}"]`);
	        if (!wrap) continue;
	        const flags = messageMinimapFlags(message);
	        const marker = document.createElement("button");
	        marker.type = "button";
	        marker.className = minimapMarkerClass(message, flags);
	        marker.dataset.messageKey = messageKey(message);
	        marker.setAttribute("aria-label", messageMinimapTitle(message, flags));
	        marker.style.top = clampNumber((wrap.offsetTop / scrollHeight) * trackHeight, 0, trackHeight - 2, 0) + "px";
	        const rawHeight = (Math.max(wrap.offsetHeight, 24) / scrollHeight) * trackHeight;
	        const minHeight = 2;
	        marker.style.height = clampNumber(rawHeight, minHeight, Math.max(minHeight, Math.min(28, trackHeight)), minHeight) + "px";
	        marker.addEventListener("click", (event) => {
	          event.preventDefault();
	          scrollToMinimapMessage(message, "smooth");
	        });
	        marker.addEventListener("pointerenter", (event) => showMinimapTooltip(message, marker, event));
	        marker.addEventListener("pointermove", (event) => showMinimapTooltip(message, marker, event));
	        marker.addEventListener("pointerleave", hideMinimapTooltip);
	        marker.addEventListener("focus", () => showMinimapTooltip(message, marker));
	        marker.addEventListener("blur", hideMinimapTooltip);
	        track.appendChild(marker);
	      }
	      updateConversationMinimapViewport();
	    }

	    function updateConversationMinimapLayout() {
	      const minimap = $("conversationMinimap");
	      const track = $("minimapTrack");
	      const box = $("messages");
	      if (!minimap || minimap.hidden || !track || !box) return;
	      const scrollHeight = Math.max(box.scrollHeight, box.clientHeight, 1);
	      const trackHeight = track.clientHeight;
	      if (!trackHeight) return;
	      track.querySelectorAll(".minimap-marker[data-message-key]").forEach((marker) => {
	        const key = marker.dataset.messageKey;
	        const wrap = box.querySelector(`[data-message-key="${key}"]`);
	        if (!wrap) return;
	        marker.style.top = clampNumber((wrap.offsetTop / scrollHeight) * trackHeight, 0, trackHeight - 2, 0) + "px";
	        const rawHeight = (Math.max(wrap.offsetHeight, 24) / scrollHeight) * trackHeight;
	        marker.style.height = clampNumber(rawHeight, 2, Math.max(2, Math.min(28, trackHeight)), 2) + "px";
	      });
	      updateConversationMinimapViewport();
	    }

	    function queueConversationMinimap() {
	      if (state.minimapQueued) return;
	      state.minimapQueued = true;
	      requestAnimationFrame(() => {
	        state.minimapQueued = false;
	        renderConversationMinimap();
	      });
	    }

	    function queueConversationMinimapLayout() {
	      if (state.minimapLayoutTimer) return;
	      state.minimapLayoutTimer = window.setTimeout(() => {
	        state.minimapLayoutTimer = 0;
	        requestAnimationFrame(updateConversationMinimapLayout);
	      }, 160);
	    }

	    function isNearBottom(box = $("messages")) {
	      return box.scrollHeight - box.scrollTop - box.clientHeight < 96;
	    }

	    function updateScrollLatestButton() {
	      const button = $("scrollLatest");
	      if (!button) return;
	      const awayFromBottom = !isNearBottom();
	      const label = state.hasNewWhilePaused || state.sending ? "查看新内容" : "回到底部";
	      const shouldShow = awayFromBottom && state.messages.length > 0;
	      const visibilityChanged = button.classList.contains("show") !== shouldShow;
	      button.title = label;
	      button.setAttribute("aria-label", label);
	      button.classList.toggle("show", shouldShow);
	      if (visibilityChanged) schedulePetPositionCorrection();
	    }

	    function scrollToLatest(behavior = "auto") {
	      const box = $("messages");
	      state.followOutput = true;
	      state.hasNewWhilePaused = false;
	      if (behavior === "smooth") {
	        state.programmaticScroll = true;
	        box.scrollTo({ top: box.scrollHeight, behavior: "smooth" });
	        setTimeout(() => {
	          state.programmaticScroll = false;
	          handleMessagesScroll();
	        }, 460);
	      } else {
	        box.scrollTop = box.scrollHeight;
	      }
	      updateScrollLatestButton();
	      updateConversationMinimapViewport();
	      pulseConversationMinimap();
	    }

	    function selectionNodeInside(node, root) {
	      if (!node || !root) return false;
	      const element = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
	      return Boolean(element && root.contains(element));
	    }

	    function editableSelectionNode(node) {
	      const element = node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement;
	      return Boolean(element?.closest("textarea, input, [contenteditable='true']"));
	    }

	    function desktopSelectionToolsEnabled() {
	      return Boolean(
	        window.matchMedia &&
	        window.matchMedia("(min-width: 1024px)").matches &&
	        window.matchMedia("(hover: hover)").matches &&
	        window.matchMedia("(pointer: fine)").matches
	      );
	    }

	    function hideSelectionToolbar(options = {}) {
	      clearTimeout(state.selectionToolbarTimer);
	      state.selectionToolbarTimer = 0;
	      $("selectionToolbar")?.classList.remove("show");
	      state.activeTextSelection = null;
	      if (options.clearSelection) window.getSelection?.()?.removeAllRanges();
	    }

	    function selectedMessageContext() {
	      if (!desktopSelectionToolsEnabled() || document.body.classList.contains("dialog-open")) return null;
	      const selection = window.getSelection?.();
	      if (!selection || selection.rangeCount !== 1 || selection.isCollapsed) return null;
	      const text = selection.toString().replace(/\u00a0/g, " ").trim();
	      if (text.length < 2) return null;
	      const range = selection.getRangeAt(0);
	      const startElement = range.startContainer.nodeType === Node.ELEMENT_NODE ? range.startContainer : range.startContainer.parentElement;
	      const endElement = range.endContainer.nodeType === Node.ELEMENT_NODE ? range.endContainer : range.endContainer.parentElement;
	      const startContent = startElement?.closest(".message-content");
	      const endContent = endElement?.closest(".message-content");
	      if (!startContent || startContent !== endContent || !$("messages")?.contains(startContent)) return null;
	      const bubble = startContent.closest(".bubble");
	      if (!bubble || !["user", "assistant"].some((role) => bubble.classList.contains(role))) return null;
	      const key = bubble.dataset.messageKey || "";
	      const message = state.messages.find((item) => messageKey(item) === key);
	      if (!message) return null;
	      const rect = range.getBoundingClientRect();
	      if (!rect || (!rect.width && !rect.height)) return null;
	      return {
	        session_id: state.currentConversation?.id || "",
	        message_id: Number(message.id || 0),
	        message_key: key,
	        role: message.role === "assistant" ? "assistant" : "user",
	        selected_text: text.slice(0, 12000),
	        created_at: Number(message.created_at || 0),
	        rect: { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, width: rect.width }
	      };
	    }

	    function positionSelectionToolbar(selectionContext) {
	      const toolbar = $("selectionToolbar");
	      if (!toolbar || !selectionContext) return;
	      toolbar.classList.add("show");
	      requestAnimationFrame(() => {
	        if (state.activeTextSelection !== selectionContext) return;
	        const rect = selectionContext.rect;
	        const toolbarRect = toolbar.getBoundingClientRect();
	        const margin = 10;
	        const left = clampNumber(
	          rect.left + rect.width / 2 - toolbarRect.width / 2,
	          margin,
	          Math.max(margin, window.innerWidth - toolbarRect.width - margin),
	          margin
	        );
	        const above = rect.top - toolbarRect.height - 10;
	        const top = above >= margin ? above : Math.min(window.innerHeight - toolbarRect.height - margin, rect.bottom + 10);
	        toolbar.style.left = Math.round(left) + "px";
	        toolbar.style.top = Math.round(top) + "px";
	      });
	    }

	    function showSelectionToolbar() {
	      const context = selectedMessageContext();
	      if (!context) return hideSelectionToolbar();
	      state.activeTextSelection = context;
	      if ($("discussSelection")) $("discussSelection").hidden = !sideDiscussionAvailable();
	      positionSelectionToolbar(context);
	      queueLucideRefresh();
	    }

	    function scheduleSelectionToolbar(delay = 70) {
	      clearTimeout(state.selectionToolbarTimer);
	      state.selectionToolbarTimer = setTimeout(() => {
	        state.selectionToolbarTimer = 0;
	        showSelectionToolbar();
	      }, delay);
	    }

	    function addActiveSelectionQuote() {
	      const context = state.activeTextSelection;
	      if (!context) return;
	      if (state.pendingQuotes.length >= 3) {
	        setStatus("chatStatus", "一条消息最多引用 3 段内容。", "err");
	        return;
	      }
	      const quote = normalizedDraftQuote(context);
	      if (!quote) return;
	      state.pendingQuotes.push(quote);
	      saveCurrentQuotes();
	      renderComposerQuotes();
	      hideSelectionToolbar({ clearSelection: true });
	      $("prompt").focus();
	      setStatus("chatStatus", "已加入引用，可以继续输入问题。", "ok");
	    }

	    async function copyActiveSelection() {
	      const text = state.activeTextSelection?.selected_text || "";
	      if (!text) return;
	      if (await writeClipboard(text) || fallbackCopy(text)) {
	        setStatus("chatStatus", "已复制选中文字", "ok");
	      } else {
	        openManualCopy(text);
	      }
	      hideSelectionToolbar({ clearSelection: true });
	    }

	    function sideDiscussionAvailable() {
	      if (!desktopSelectionToolsEnabled()) return false;
	      const sidebarWidth = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--sidebar-width")) || Number(state.sidebarWidth) || 322;
	      const available = window.innerWidth - sidebarWidth;
	      return window.innerWidth >= 1220 && available >= 920;
	    }

	    function sideDiscussionWidthBounds() {
	      const sidebarWidth = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--sidebar-width")) || Number(state.sidebarWidth) || 322;
	      const available = Math.max(0, window.innerWidth - sidebarWidth);
	      return {
	        min: 360,
	        max: Math.max(360, Math.min(560, available * .5, available - 560))
	      };
	    }

	    function applySideDiscussionWidth(value, options = {}) {
	      const bounds = sideDiscussionWidthBounds();
	      const width = Math.round(clampNumber(Number(value), bounds.min, bounds.max, 440));
	      state.sideDiscussionWidth = width;
	      document.documentElement.style.setProperty("--side-discussion-width", width + "px");
	      if (options.save !== false && state.user) setUserStorage("sideDiscussionWidth", String(width));
	      return width;
	    }

	    function updateSideDiscussionEntry() {
	      const count = state.sideDiscussions.length;
	      const button = $("reopenSideDiscussion");
	      if (!button) return;
	      button.hidden = !count || !sideDiscussionAvailable();
	      $("sideDiscussionCount").textContent = `侧边讨论 (${count})`;
	      button.title = count ? `打开最近的侧边讨论，共 ${count} 个` : "暂无侧边讨论";
	    }

	    async function loadSideDiscussions(sessionId = state.currentConversation?.id || "") {
	      if (!sessionId) {
	        state.sideDiscussions = [];
	        updateSideDiscussionEntry();
	        return [];
	      }
	      try {
	        const res = await api(`/api/side-discussions?session_id=${encodeURIComponent(sessionId)}`);
	        if (!res.ok) throw new Error(await readError(res, "侧边讨论加载失败。"));
	        const data = await res.json();
	        if (state.currentConversation?.id !== sessionId) return [];
	        state.sideDiscussions = data.discussions || [];
	      } catch (err) {
	        state.sideDiscussions = [];
	        console.warn("side discussion list failed", err);
	      }
	      updateSideDiscussionEntry();
	      return state.sideDiscussions;
	    }

	    function sideDiscussionMessageKey(message) {
	      if (!message._sideClientKey) {
	        Object.defineProperty(message, "_sideClientKey", {
	          value: "side_msg_" + (++state.sideDiscussionSeq),
	          enumerable: false
	        });
	      }
	      return message._sideClientKey;
	    }

	    function sideDiscussionScrollBottom(behavior = "auto") {
	      const box = $("sideDiscussionMessages");
	      if (!box) return;
	      if (behavior === "smooth") box.scrollTo({ top: box.scrollHeight, behavior: "smooth" });
	      else box.scrollTop = box.scrollHeight;
	    }

	    function createSideDiscussionMessage(message) {
	      const wrap = document.createElement("article");
	      wrap.className = "side-message " + message.role;
	      wrap.dataset.sideMessageKey = sideDiscussionMessageKey(message);
	      const role = document.createElement("div");
	      role.className = "side-message-role";
	      role.textContent = message.role === "assistant" ? "槑槑" : "你";
	      const content = document.createElement("div");
	      content.className = "side-message-content markdown-body";
	      if (message.thinking && !message.content) {
	        content.innerHTML = '<span class="thinking-dots"><span></span><span></span><span></span></span> 槑槑正在整理思路...';
	      } else {
	        content.innerHTML = renderMarkdown(message.content || "");
	        enhanceMarkdown(content, { mermaid: true, icons: true });
	      }
	      const time = document.createElement("div");
	      time.className = "side-message-time";
	      const tokens = Number(message.usage?.total_tokens || 0);
	      time.textContent = formatMessageTime(message.created_at) + (tokens ? " · " + formatTokens(tokens) : "");
	      wrap.append(role, content, time);
	      return wrap;
	    }

	    function renderSideDiscussionMessages(options = {}) {
	      const box = $("sideDiscussionMessages");
	      if (!box) return;
	      box.replaceChildren();
	      if (!state.sideDiscussionMessages.length) {
	        const empty = document.createElement("div");
	        empty.className = "side-discussion-empty";
	        empty.innerHTML = iconMarkup("messages-square", "") + "<strong>从这段引用开始聊</strong><span>这里的讨论不会写入主会话上下文。</span>";
	        box.appendChild(empty);
	      } else {
	        state.sideDiscussionMessages.forEach((message) => box.appendChild(createSideDiscussionMessage(message)));
	      }
	      queueLucideRefresh();
	      if (options.scroll !== false) requestAnimationFrame(() => sideDiscussionScrollBottom());
	    }

	    function updateSideDiscussionStream(message, options = {}) {
	      const box = $("sideDiscussionMessages");
	      let wrap = box?.querySelector(`[data-side-message-key="${sideDiscussionMessageKey(message)}"]`);
	      if (!wrap) {
	        box?.querySelector(".side-discussion-empty")?.remove();
	        wrap = createSideDiscussionMessage(message);
	        box?.appendChild(wrap);
	      }
	      const content = wrap?.querySelector(".side-message-content");
	      const time = wrap?.querySelector(".side-message-time");
	      if (!content) return;
	      content.className = "side-message-content markdown-body";
	      if (message.thinking && !message.content) {
	        content.innerHTML = '<span class="thinking-dots"><span></span><span></span><span></span></span> 槑槑正在整理思路...';
	      } else {
	        renderStreamingMarkdown(content, message, message.content || "", { final: Boolean(options.final) });
	        if (options.final) enhanceMarkdown(content, { mermaid: true, icons: true });
	      }
	      if (time) {
	        const tokens = Number(message.usage?.total_tokens || 0);
	        time.textContent = formatMessageTime(message.created_at) + (tokens ? " · " + formatTokens(tokens) : "");
	      }
	      sideDiscussionScrollBottom();
	    }

	    function renderSideDiscussionHeader() {
	      const discussion = state.activeSideDiscussion;
	      if (!discussion) return;
	      $("sideDiscussionModel").textContent = [discussion.model_name, discussion.model].filter(Boolean).join(" · ");
	      $("sideDiscussionSourceRole").textContent = discussion.source_role === "assistant" ? "来自槑槑回复" : "来自你的消息";
	      $("sideDiscussionSourceTime").textContent = formatMessageTime(discussion.source_created_at);
	      $("sideDiscussionSourceText").textContent = discussion.selected_text || "";
	    }

	    async function openSideDiscussion(discussionId) {
	      if (!sideDiscussionAvailable()) {
	        setStatus("chatStatus", "请扩大浏览器窗口后使用侧边讨论。", "err");
	        return;
	      }
	      const res = await api(`/api/side-discussions/${encodeURIComponent(discussionId)}`);
	      if (!res.ok) {
	        setStatus("chatStatus", await readError(res, "侧边讨论打开失败。"), "err");
	        return;
	      }
	      const data = await res.json();
	      if (data.discussion?.session_id !== state.currentConversation?.id) return;
	      state.activeSideDiscussion = data.discussion;
	      state.sideDiscussionMessages = data.messages || [];
	      applySideDiscussionWidth(getUserStorage("sideDiscussionWidth", state.sideDiscussionWidth), { save: false });
	      $("sideDiscussionPanel").hidden = false;
	      $("appView").classList.add("side-discussion-open");
	      document.body.classList.add("side-discussion-active");
	      renderSideDiscussionHeader();
	      renderSideDiscussionMessages();
	      updateSideDiscussionEntry();
	      syncComposerLayout();
	      queueConversationMinimap();
	    }

	    function closeSideDiscussion() {
	      if (state.sideDiscussionSending && state.sideDiscussionAbortController) {
	        state.sideDiscussionAbortController.abort();
	      }
	      state.sideDiscussionSending = false;
	      state.sideDiscussionAbortController = null;
	      $("sideDiscussionPanel").hidden = true;
	      $("appView").classList.remove("side-discussion-open");
	      document.body.classList.remove("side-discussion-active");
	      syncComposerLayout();
	      queueConversationMinimap();
	    }

	    async function createSideDiscussionFromSelection() {
	      const context = state.activeTextSelection;
	      if (!context) return;
	      if (!sideDiscussionAvailable()) {
	        setStatus("chatStatus", "请扩大浏览器窗口后使用侧边讨论。", "err");
	        return;
	      }
	      if (!context.message_id) {
	        setStatus("chatStatus", "这条消息还没有保存，完成后再开启侧边讨论。", "err");
	        return;
	      }
	      const res = await api("/api/side-discussions", {
	        method: "POST",
	        body: JSON.stringify({
	          session_id: context.session_id,
	          source_message_id: context.message_id,
	          selected_text: context.selected_text
	        })
	      });
	      if (!res.ok) {
	        setStatus("chatStatus", await readError(res, "创建侧边讨论失败。"), "err");
	        return;
	      }
	      const data = await res.json();
	      state.sideDiscussions = [data.discussion, ...state.sideDiscussions.filter((item) => item.id !== data.discussion.id)];
	      hideSelectionToolbar({ clearSelection: true });
	      updateSideDiscussionEntry();
	      await openSideDiscussion(data.discussion.id);
	      $("sideDiscussionPrompt").focus();
	    }

	    function parseSideDiscussionSSE(buffer, onEvent) {
	      const blocks = buffer.split(/\r?\n\r?\n/);
	      const rest = blocks.pop() || "";
	      for (const block of blocks) {
	        const line = block.split(/\r?\n/).find((item) => item.startsWith("data:"));
	        if (!line) continue;
	        const raw = line.slice(5).trim();
	        if (!raw || raw === "[DONE]") continue;
	        try { onEvent(JSON.parse(raw)); } catch {}
	      }
	      return rest;
	    }

	    async function sendSideDiscussionMessage() {
	      if (!state.activeSideDiscussion) return;
	      if (state.sideDiscussionSending) {
	        state.sideDiscussionAbortController?.abort();
	        return;
	      }
	      const prompt = $("sideDiscussionPrompt");
	      const content = prompt.value.trim();
	      if (!content) return;
	      prompt.value = "";
	      prompt.style.height = "";
	      const userMessage = { role: "user", content, created_at: Math.floor(Date.now() / 1000), usage: {} };
	      const assistant = { role: "assistant", content: "", created_at: Math.floor(Date.now() / 1000), usage: {}, thinking: true };
	      state.sideDiscussionMessages.push(userMessage, assistant);
	      renderSideDiscussionMessages();
	      state.sideDiscussionSending = true;
	      state.sideDiscussionAbortController = new AbortController();
	      $("sideDiscussionSend").innerHTML = iconMarkup("square", "■");
	      $("sideDiscussionSend").title = "停止生成";
	      $("sideDiscussionStatus").textContent = "槑槑正在整理思路...";
	      queueLucideRefresh();
	      let buffer = "";
	      try {
	        const res = await api(`/api/side-discussions/${encodeURIComponent(state.activeSideDiscussion.id)}/messages`, {
	          method: "POST",
	          body: JSON.stringify({ content }),
	          signal: state.sideDiscussionAbortController.signal
	        });
	        if (!res.ok) throw new Error(await readError(res, "侧边讨论发送失败。"));
	        const reader = res.body.getReader();
	        const decoder = new TextDecoder();
	        while (true) {
	          const { value, done } = await reader.read();
	          if (done) break;
	          buffer += decoder.decode(value, { stream: true });
	          buffer = parseSideDiscussionSSE(buffer, (event) => {
	            if (event.type === "message_saved") {
	              assistant.id = event.message_id;
	              assistant.usage = event.usage || {};
	              return;
	            }
	            const choice = (event.choices || [{}])[0];
	            const delta = choice.delta || choice.message || {};
	            const piece = delta.content || "";
	            if (piece) {
	              assistant.content += piece;
	              assistant.thinking = false;
	              updateSideDiscussionStream(assistant);
	            }
	          });
	        }
	        assistant.thinking = false;
	        updateSideDiscussionStream(assistant, { final: true });
	        state.activeSideDiscussion.updated_at = Math.floor(Date.now() / 1000);
	        state.activeSideDiscussion.message_count = state.sideDiscussionMessages.length;
	        state.sideDiscussions = [
	          state.activeSideDiscussion,
	          ...state.sideDiscussions.filter((item) => item.id !== state.activeSideDiscussion.id)
	        ];
	        updateSideDiscussionEntry();
	        $("sideDiscussionStatus").textContent = "";
	      } catch (err) {
	        assistant.thinking = false;
	        if (err?.name === "AbortError") {
	          if (!assistant.content) state.sideDiscussionMessages = state.sideDiscussionMessages.filter((item) => item !== assistant);
	          $("sideDiscussionStatus").textContent = "已停止生成";
	        } else {
	          if (!assistant.content) state.sideDiscussionMessages = state.sideDiscussionMessages.filter((item) => item !== assistant);
	          $("sideDiscussionStatus").textContent = friendlyError(err, "侧边讨论发送失败。");
	        }
	        renderSideDiscussionMessages();
	      } finally {
	        state.sideDiscussionSending = false;
	        state.sideDiscussionAbortController = null;
	        $("sideDiscussionSend").innerHTML = iconMarkup("arrow-up", "↑");
	        $("sideDiscussionSend").title = "发送";
	        queueLucideRefresh();
	      }
	    }

	    function quoteLastSideAnswer() {
	      const message = [...state.sideDiscussionMessages].reverse().find((item) => item.role === "assistant" && String(item.content || "").trim());
	      if (!message) {
	        $("sideDiscussionStatus").textContent = "还没有可以引用的槑槑回答。";
	        return;
	      }
	      if (state.pendingQuotes.length >= 3) {
	        $("sideDiscussionStatus").textContent = "主输入框已经有 3 段引用了。";
	        return;
	      }
	      const quote = normalizedDraftQuote({
	        session_id: state.currentConversation?.id || "",
	        message_id: 0,
	        message_key: "",
	        role: "assistant",
	        selected_text: message.content,
	        created_at: message.created_at
	      });
	      state.pendingQuotes.push(quote);
	      saveCurrentQuotes();
	      renderComposerQuotes();
	      $("prompt").focus();
	      $("sideDiscussionStatus").textContent = "已引用到主输入框。";
	    }

	    async function saveSideDiscussionAsConversation() {
	      if (!state.activeSideDiscussion) return;
	      const button = $("saveSideConversation");
	      button.disabled = true;
	      $("sideDiscussionStatus").textContent = "正在保存为新对话...";
	      try {
	        const res = await api(`/api/side-discussions/${encodeURIComponent(state.activeSideDiscussion.id)}/conversation`, {
	          method: "POST",
	          body: "{}"
	        });
	        if (!res.ok) throw new Error(await readError(res, "保存为新对话失败。"));
	        const data = await res.json();
	        upsertConversation(data.conversation);
	        closeSideDiscussion();
	        await selectConversation(data.conversation.id);
	        setStatus("chatStatus", "侧边讨论已保存为独立会话。", "ok");
	      } catch (err) {
	        $("sideDiscussionStatus").textContent = friendlyError(err, "保存为新对话失败。");
	      } finally {
	        button.disabled = false;
	      }
	    }

	    function handleSideDiscussionResizePointerDown(event) {
	      if (!sideDiscussionAvailable()) return;
	      event.preventDefault();
	      state.sideDiscussionResize = { pointerId: event.pointerId };
	      $("sideDiscussionResizer").setPointerCapture?.(event.pointerId);
	      $("sideDiscussionResizer").classList.add("is-dragging");
	      document.body.style.cursor = "col-resize";
	      document.body.style.userSelect = "none";
	    }

	    function handleSideDiscussionResizePointerMove(event) {
	      if (!state.sideDiscussionResize || event.pointerId !== state.sideDiscussionResize.pointerId) return;
	      applySideDiscussionWidth(window.innerWidth - event.clientX, { save: false });
	    }

	    function handleSideDiscussionResizePointerUp(event) {
	      if (!state.sideDiscussionResize || event.pointerId !== state.sideDiscussionResize.pointerId) return;
	      state.sideDiscussionResize = null;
	      $("sideDiscussionResizer").classList.remove("is-dragging");
	      document.body.style.cursor = "";
	      document.body.style.userSelect = "";
	      applySideDiscussionWidth(state.sideDiscussionWidth, { save: true });
	    }

	    function handleSideDiscussionViewportChange() {
	      updateSideDiscussionEntry();
	      if (!$("sideDiscussionPanel").hidden && !sideDiscussionAvailable()) closeSideDiscussion();
	      else if (!$("sideDiscussionPanel").hidden) applySideDiscussionWidth(state.sideDiscussionWidth, { save: false });
	    }

	    function lastMessageSelectionBoundary() {
	      const box = $("messages");
	      if (!box) return null;
	      const messages = box.querySelectorAll(".bubble");
	      return messages.length ? messages[messages.length - 1] : null;
	    }

	    function clampChatSelectionToMessages() {
	      if (!state.chatSelectionActive && !state.chatSelectionStartedInMessages) return;
	      const selection = window.getSelection?.();
	      if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return;
	      const box = $("messages");
	      const composer = document.querySelector(".composer");
	      const latest = $("scrollLatest");
	      const anchorInMessages = selectionNodeInside(selection.anchorNode, box);
	      const focusInMessages = selectionNodeInside(selection.focusNode, box);
	      if (!anchorInMessages || focusInMessages) return;
	      const focusInBlockedArea =
	        selectionNodeInside(selection.focusNode, composer) ||
	        selectionNodeInside(selection.focusNode, latest) ||
	        !focusInMessages;
	      if (!focusInBlockedArea) return;
	      const boundary = lastMessageSelectionBoundary();
	      if (!boundary) return;
	      const range = document.createRange();
	      try {
	        range.setStart(selection.anchorNode, selection.anchorOffset);
	        range.setEndAfter(boundary);
	        selection.removeAllRanges();
	        selection.addRange(range);
	      } catch {}
	    }

	    function beginChatTextSelection(event) {
	      if (event.button !== undefined && event.button !== 0) return;
	      if (editableSelectionNode(event.target)) return;
	      if (!selectionNodeInside(event.target, $("messages"))) return;
	      hideSelectionToolbar();
	      state.chatSelectionActive = true;
	      state.chatSelectionStartedInMessages = true;
	    }

	    function endChatTextSelection(event) {
	      if (!state.chatSelectionStartedInMessages) return;
	      clampChatSelectionToMessages();
	      if (event?.type === "pointerup" && (!event.pointerType || event.pointerType === "mouse")) {
	        scheduleSelectionToolbar();
	      }
	      setTimeout(() => {
	        state.chatSelectionActive = false;
	        state.chatSelectionStartedInMessages = false;
	      }, 80);
	    }

	    function handleComposerSelectStart(event) {
	      if (event.target === $("prompt")) return;
	      event.preventDefault();
	      if (state.chatSelectionStartedInMessages) clampChatSelectionToMessages();
	    }

	    function handleSelectionChange() {
	      clampChatSelectionToMessages();
	      const selection = window.getSelection?.();
	      if (!selection || selection.isCollapsed) {
	        clearTimeout(state.selectionToolbarTimer);
	        state.selectionToolbarTimer = setTimeout(() => {
	          if (window.getSelection?.()?.isCollapsed) hideSelectionToolbar();
	        }, 80);
	      }
	    }

	    function handleSelectionToolbarOutsidePointer(event) {
	      const toolbar = $("selectionToolbar");
	      if (!toolbar?.classList.contains("show")) return;
	      if (event.target.closest?.("#selectionToolbar")) return;
	      hideSelectionToolbar();
	    }

	    function handleMessageQuoteOutsidePointer(event) {
	      if (event.target.closest?.(".message-quote-reference")) return;
	      closeMessageQuotePreviews();
	    }

	    function flushMessagesScroll() {
	      state.messagesScrollFrame = 0;
	      updateConversationMinimapViewport();
	      pulseConversationMinimap();
	      if (state.programmaticScroll) return;
	      if (isNearBottom()) {
	        state.followOutput = true;
	        state.hasNewWhilePaused = false;
	      } else {
	        state.followOutput = false;
	      }
	      updateScrollLatestButton();
	    }

	    function handleMessagesScroll() {
	      hideSelectionToolbar();
	      if (state.messagesScrollFrame) return;
	      state.messagesScrollFrame = requestAnimationFrame(flushMessagesScroll);
	    }

	    function messageKey(message) {
	      if (!message._clientKey) {
	        Object.defineProperty(message, "_clientKey", {
	          value: "msg_" + (++state.messageSeq),
	          enumerable: false
	        });
	      }
	      return message._clientKey;
	    }

	    function createMessageElement(message) {
	      const wrap = document.createElement("article");
	      wrap.className = "bubble " + message.role;
	      wrap.dataset.messageKey = messageKey(message);

	      const role = document.createElement("div");
	      role.className = "role";
	      const shell = document.createElement("div");
	      shell.className = "bubble-shell";
	      const text = document.createElement("div");
	      text.className = "message-content";
	      const time = document.createElement("div");
	      time.className = "message-time";
	      const actions = document.createElement("div");
	      actions.className = "message-actions";
	      const sourcesPanel = document.createElement("div");
	      sourcesPanel.className = "sources-panel";
	      sourcesPanel.hidden = true;
	      const reasoningPanel = document.createElement("div");
	      reasoningPanel.className = "reasoning-panel";
	      reasoningPanel.hidden = true;
	      const imagePanel = document.createElement("div");
	      imagePanel.className = "message-images";
	      imagePanel.hidden = true;
	      const quotePanel = document.createElement("div");
	      quotePanel.className = "message-quote-reference";
	      quotePanel.hidden = true;
	      const copy = document.createElement("button");
	      copy.className = "copy-btn";
	      copy.type = "button";
	      copy.title = "复制";
	      copy.innerHTML = '<i data-lucide="copy" aria-hidden="true"></i><span class="icon-fallback">⧉</span>';
	      copy.addEventListener("click", () => copyText(copyableMessageContent(message), copy));
	      const copyAction = document.createElement("button");
	      copyAction.className = "message-action copy-action";
	      copyAction.type = "button";
	      copyAction.innerHTML = '<i data-lucide="copy" aria-hidden="true"></i><span class="icon-fallback">⧉</span>';
	      copyAction.setAttribute("aria-label", "复制");
	      copyAction.title = "复制这条消息";
	      copyAction.addEventListener("click", () => copyText(copyableMessageContent(message), copyAction));
	      const favorite = document.createElement("button");
	      favorite.className = "message-action favorite-action";
	      favorite.type = "button";
	      favorite.innerHTML = iconLabel("star", "收藏", "☆");
	      favorite.title = "收藏这条回答";
	      favorite.addEventListener("click", () => toggleFavoriteMessage(message, favorite));
	      const regenerate = document.createElement("button");
	      regenerate.className = "message-action regenerate-action";
	      regenerate.type = "button";
	      regenerate.innerHTML = iconLabel("rotate-cw", "重新生成", "↻");
	      regenerate.title = "把上一条问题放回输入框";
	      regenerate.addEventListener("click", () => regenerateFromMessage(message));
	      const continueWrite = document.createElement("button");
	      continueWrite.className = "message-action continue-action";
	      continueWrite.type = "button";
	      continueWrite.innerHTML = iconLabel("pen-line", "继续写", "✎");
	      continueWrite.title = "基于这条回答继续写";
	      continueWrite.addEventListener("click", () => continueFromMessage(message));
	      const reason = document.createElement("button");
	      reason.className = "message-action reason-action";
	      reason.type = "button";
	      reason.addEventListener("click", () => toggleReasoning(message));
	      actions.append(favorite, regenerate, continueWrite, copyAction);

	      shell.append(reasoningPanel, imagePanel, quotePanel, text, copy);
	      wrap.append(role, shell, sourcesPanel, time, actions);
	      updateMessageElement(wrap, message);
	      return wrap;
	    }

	    function updateMessageElement(wrap, message) {
	      wrap.className = "bubble " + message.role;
	      wrap.dataset.messageKey = messageKey(message);
	      const role = wrap.querySelector(".role");
	      const text = wrap.querySelector(".message-content");
	      const time = wrap.querySelector(".message-time");
	      const copy = wrap.querySelector(".copy-btn");
	      const actions = wrap.querySelector(".message-actions");
	      const sourcesPanel = wrap.querySelector(".sources-panel");
	      const copyAction = wrap.querySelector(".copy-action");
	      const favorite = wrap.querySelector(".favorite-action");
	      const regenerate = wrap.querySelector(".regenerate-action");
	      const continueWrite = wrap.querySelector(".continue-action");
	      const reason = wrap.querySelector(".reason-action");
	      const reasoningPanel = wrap.querySelector(".reasoning-panel");
	      const imagePanel = wrap.querySelector(".message-images");
	      const quotePanel = wrap.querySelector(".message-quote-reference");
	      role.replaceChildren();
	      if (message.role === "user") {
	        role.textContent = "你";
	      } else {
	        const avatar = document.createElement("img");
	        avatar.className = "role-avatar";
	        avatar.src = "/res/meimei-avatar.png";
	        avatar.alt = "";
	        role.append(avatar, document.createTextNode(message.thinking ? "槑槑 · 思考中" : "槑槑"));
	      }
	      renderSourcesPanel(sourcesPanel, message.role === "assistant" ? message.sources : []);
	      if (time) {
	        const tokens = message.role === "assistant" ? messageTotalTokens(message) : 0;
	        time.textContent = formatMessageTime(message.created_at) + (tokens ? " · " + formatTokens(tokens) : "");
	      }

	      const displayContent = displayMessageContent(message);
	      const reasoningContent = messageReasoningContent(message);
	      renderReasoningPanel(reasoningPanel, message, reasoningContent);
	      renderMessageImages(imagePanel, messageImages(message));
	      renderMessageQuoteReference(quotePanel, message);

	      if (message.role === "assistant" && message.thinking && !displayContent) {
	        wrap.dataset.liveState = "thinking";
	        text.className = "message-content";
	        text.hidden = Boolean(reasoningContent);
	        text.innerHTML = `
	          <div class="thinking">
	            <img class="thinking-avatar" src="/res/meimei-avatar.png" alt="">
	            <span class="thinking-dots"><span></span><span></span><span></span></span>
	            <span><strong>槑槑</strong>正在整理思路...</span>
	          </div>`;
	        if (imagePanel) imagePanel.hidden = true;
	        copy.hidden = true;
	        if (actions) actions.hidden = true;
	        return;
	      }

	      wrap.dataset.liveState = "static";
	      text.hidden = false;
	      text.className = "message-content markdown";
	      text.innerHTML = renderMessageMarkdown(message, displayContent || "");
	      enhanceMarkdown(text, { mermaid: !message.thinking });
	      copy.hidden = !displayContent || message.role === "assistant";
	      const canShowAssistantActions = message.role === "assistant" && Boolean(displayContent);
	      const canShowUserActions = message.role === "user" && displayContent;
	      if (actions) actions.hidden = !(canShowAssistantActions || canShowUserActions);
	      if (copyAction) {
	        copyAction.hidden = !((message.role === "assistant" || message.role === "user") && displayContent);
	        copyAction.title = message.role === "assistant" ? "复制这条回答" : "复制这条消息";
	      }
	      if (reason) reason.hidden = true;
	      if (favorite) {
	        favorite.hidden = !(message.role === "assistant" && message.id && displayContent);
	        favorite.innerHTML = message.favorite_id ? iconLabel("star", "已收藏", "★") : iconLabel("star", "收藏", "☆");
	        favorite.classList.toggle("active", Boolean(message.favorite_id));
	        favorite.title = message.favorite_id ? "取消收藏" : "收藏这条回答";
	      }
	      if (regenerate) {
	        regenerate.hidden = !(message.role === "assistant" && displayContent);
	      }
	      if (continueWrite) {
	        continueWrite.hidden = !(message.role === "assistant" && displayContent);
	      }
	    }

	    function updateLiveReasoningPanel(panel, message, reasoningContent, options = {}) {
	      if (!panel) return false;
	      if (!reasoningContent) {
	        panel.hidden = true;
	        return false;
	      }
	      const existingToggle = panel.querySelector(".reasoning-toggle");
	      if (!existingToggle || options.final) {
	        renderReasoningPanel(panel, message, reasoningContent);
	        return true;
	      }
	      panel.hidden = false;
	      panel.classList.toggle("open", Boolean(message.reasoning_open));
	      existingToggle.title = message.reasoning_open ? "收起思考过程" : "展开思考过程";
	      updateReasoningHeader(panel, message, reasoningContent);
	      const body = panel.querySelector(".reasoning-body");
	      if (body) body.hidden = !message.reasoning_open;
	      if (message.reasoning_open) {
	        const markdown = body?.querySelector(".reasoning-markdown");
	        if (markdown) renderStreamingMarkdown(markdown, message, reasoningContent, { slot: "reasoning" });
	      }
	      return false;
	    }

	    function stopReasoningClock(message) {
	      if (message && state.activeReasoningMessage !== message) return;
	      if (state.reasoningClockTimer) clearTimeout(state.reasoningClockTimer);
	      state.reasoningClockTimer = 0;
	      state.activeReasoningMessage = null;
	    }

	    function ensureReasoningClock(message) {
	      state.activeReasoningMessage = message;
	      if (state.reasoningClockTimer) return;
	      const tick = () => {
	        state.reasoningClockTimer = 0;
	        if (state.activeReasoningMessage !== message || !message.thinking || message._reasoningCompletedAt) return;
	        const wrap = $("messages")?.querySelector(`[data-message-key="${messageKey(message)}"]`);
	        const panel = wrap?.querySelector(".reasoning-panel");
	        if (panel && !panel.hidden) updateReasoningHeader(panel, message, messageReasoningContent(message));
	        state.reasoningClockTimer = setTimeout(tick, 1000);
	      };
	      state.reasoningClockTimer = setTimeout(tick, 1000);
	    }

	    function completeReasoning(message) {
	      if (!message || !messageReasoningContent(message)) return;
	      if (message._reasoningPreviewFrozen) {
	        if (message._reasoningUiTimer) clearTimeout(message._reasoningUiTimer);
	        message._reasoningUiTimer = 0;
	        stopReasoningClock(message);
	        return;
	      }
	      if (!message._reasoningCompletedAt) message._reasoningCompletedAt = Date.now();
	      message._reasoningFrozenPreview = reasoningPreview(messageReasoningContent(message));
	      message._reasoningPreviewFrozen = true;
	      stopReasoningClock(message);
	      flushReasoningPreview(message, { final: true });
	    }

	    function flushReasoningPreview(message, options = {}) {
	      if (!message) return;
	      if (message._reasoningUiTimer) {
	        clearTimeout(message._reasoningUiTimer);
	        message._reasoningUiTimer = 0;
	      }
	      message._reasoningLastPaintAt = performance.now();
	      const box = $("messages");
	      const wrap = box?.querySelector(`[data-message-key="${messageKey(message)}"]`);
	      if (!wrap) return;
	      const panel = wrap.querySelector(".reasoning-panel");
	      const layoutMayChange = Boolean(panel?.hidden || message.reasoning_open);
	      const previousTop = layoutMayChange ? box.scrollTop : 0;
	      const shouldFollow = layoutMayChange && (state.followOutput || isNearBottom(box));
	      updateLiveReasoningPanel(panel, message, messageReasoningContent(message), options);
	      const text = wrap.querySelector(".message-content");
	      if (message.thinking && !visibleMessageContent(message) && text) {
	        text.hidden = true;
	      }
	      if (layoutMayChange) settleMessageScroll(previousTop, shouldFollow);
	    }

	    function scheduleReasoningPreview(message) {
	      if (!message || message._reasoningPreviewFrozen || message._reasoningUiTimer) return;
	      const nowValue = performance.now();
	      const elapsed = nowValue - Number(message._reasoningLastPaintAt || 0);
	      if (!message._reasoningLastPaintAt || elapsed >= 90) {
	        flushReasoningPreview(message);
	        ensureReasoningClock(message);
	        return;
	      }
	      message._reasoningUiTimer = setTimeout(() => {
	        message._reasoningUiTimer = 0;
	        flushReasoningPreview(message);
	      }, Math.max(16, 90 - elapsed));
	      ensureReasoningClock(message);
	    }

	    function streamingStableBoundary(source) {
	      const value = String(source || "");
	      let cursor = 0;
	      let boundary = 0;
	      let fenceChar = "";
	      let fenceLength = 0;
	      while (cursor < value.length) {
	        const newline = value.indexOf("\n", cursor);
	        const end = newline < 0 ? value.length : newline + 1;
	        const line = value.slice(cursor, newline < 0 ? end : newline);
	        const trimmed = line.trim();
	        const fence = trimmed.match(/^(`{3,}|~{3,})/);
	        if (fence) {
	          const token = fence[1];
	          if (!fenceChar) {
	            fenceChar = token[0];
	            fenceLength = token.length;
	          } else if (token[0] === fenceChar && token.length >= fenceLength) {
	            fenceChar = "";
	            fenceLength = 0;
	          }
	        } else if (!fenceChar && !trimmed) {
	          boundary = end;
	        }
	        cursor = end;
	      }
	      return boundary;
	    }

	    function resetStreamingMarkdownState(text) {
	      delete text._streamStableLength;
	      delete text._streamStableSource;
	      delete text._streamRenderedSource;
	      delete text._streamStableNode;
	      delete text._streamTailNode;
	    }

	    function ensureStreamingMarkdownNodes(text) {
	      if (text._streamStableNode?.isConnected && text._streamTailNode?.isConnected) return;
	      const stable = document.createElement("div");
	      stable.className = "stream-markdown-stable";
	      const tail = document.createElement("div");
	      tail.className = "stream-markdown-tail";
	      text.replaceChildren(stable, tail);
	      text._streamStableNode = stable;
	      text._streamTailNode = tail;
	      text._streamStableLength = 0;
	      text._streamStableSource = "";
	      text._streamRenderedSource = "";
	    }

	    function renderStreamingMarkdown(text, message, source, options = {}) {
	      const value = String(source || "");
	      if (options.final) {
	        resetStreamingMarkdownState(text);
	        text.innerHTML = renderMessageMarkdown(message, value, options.slot || "content");
	        text._markdownSource = value;
	        enhanceMarkdown(text, { mermaid: true, icons: true });
	        return true;
	      }
	      ensureStreamingMarkdownNodes(text);
	      if (text._streamRenderedSource === value) return false;
	      const boundary = streamingStableBoundary(value);
	      const stableLength = Number(text._streamStableLength || 0);
	      const stableSource = String(text._streamStableSource || "");
	      if (boundary < stableLength || !value.startsWith(stableSource)) {
	        text._streamStableNode.replaceChildren();
	        text._streamStableLength = 0;
	        text._streamStableSource = "";
	      }
	      const nextStableLength = Number(text._streamStableLength || 0);
	      if (boundary > nextStableLength) {
	        const completed = value.slice(nextStableLength, boundary);
	        text._streamStableNode.insertAdjacentHTML("beforeend", renderMarkdown(completed));
	        text._streamStableLength = boundary;
	        text._streamStableSource = value.slice(0, boundary);
	      }
	      const tailSource = value.slice(Number(text._streamStableLength || 0));
	      text._streamTailNode.innerHTML = tailSource ? renderMarkdown(tailSource) : "";
	      text._streamRenderedSource = value;
	      return true;
	    }

	    function updateLiveMessageElement(wrap, message, options = {}) {
	      const role = wrap.querySelector(".role");
	      const text = wrap.querySelector(".message-content");
	      const time = wrap.querySelector(".message-time");
	      const copy = wrap.querySelector(".copy-btn");
	      const actions = wrap.querySelector(".message-actions");
	      const sourcesPanel = wrap.querySelector(".sources-panel");
	      const copyAction = wrap.querySelector(".copy-action");
	      const favorite = wrap.querySelector(".favorite-action");
	      const regenerate = wrap.querySelector(".regenerate-action");
	      const continueWrite = wrap.querySelector(".continue-action");
	      const reasoningPanel = wrap.querySelector(".reasoning-panel");
	      const displayContent = visibleMessageContent(message);
	      const reasoningContent = messageReasoningContent(message);
	      const shouldUpdateReasoning = Boolean(
	        options.reasoning || options.final || !reasoningPanel?.querySelector(".reasoning-toggle")
	      );
	      let iconsChanged = shouldUpdateReasoning
	        ? updateLiveReasoningPanel(reasoningPanel, message, reasoningContent, options)
	        : false;

	      if (options.sources) renderSourcesPanel(sourcesPanel, message.sources || []);
	      if (options.usage || options.final) {
	        const tokens = messageTotalTokens(message);
	        time.textContent = formatMessageTime(message.created_at) + (tokens ? " · " + formatTokens(tokens) : "");
	      }

	      if (message.thinking && !displayContent) {
	        if (wrap.dataset.liveState !== "thinking") {
	          wrap.dataset.liveState = "thinking";
	          text.className = "message-content";
	          text.innerHTML = `
	            <div class="thinking">
	              <img class="thinking-avatar" src="/res/meimei-avatar.png" alt="">
	              <span class="thinking-dots"><span></span><span></span><span></span></span>
	              <span><strong>槑槑</strong>正在整理思路...</span>
	            </div>`;
	        }
	        copy.hidden = true;
	        if (actions) actions.hidden = true;
	        return iconsChanged;
	      }

	      text.hidden = false;
	      if (wrap.dataset.liveState === "thinking" && role) {
	        role.replaceChildren();
	        const avatar = document.createElement("img");
	        avatar.className = "role-avatar";
	        avatar.src = "/res/meimei-avatar.png";
	        avatar.alt = "";
	        role.append(avatar, document.createTextNode("槑槑"));
	      }
	      wrap.dataset.liveState = "streaming";
	      text.className = "message-content markdown";
	      renderStreamingMarkdown(text, message, displayContent, options);
	      copy.hidden = true;
	      const hasContent = Boolean(displayContent);
	      if (actions) actions.hidden = !hasContent;
	      if (copyAction) copyAction.hidden = !hasContent;
	      if (favorite) {
	        favorite.hidden = !(message.id && hasContent);
	        favorite.classList.toggle("active", Boolean(message.favorite_id));
	      }
	      if (regenerate) regenerate.hidden = !hasContent;
	      if (continueWrite) continueWrite.hidden = !hasContent;
	      return iconsChanged;
	    }

	    function settleMessageScroll(previousTop, shouldFollow) {
	      const pending = state.pendingMessageScroll;
	      state.pendingMessageScroll = {
	        previousTop,
	        shouldFollow: Boolean(shouldFollow || pending?.shouldFollow)
	      };
	      if (state.messageScrollFrame) return;
	      state.messageScrollFrame = requestAnimationFrame(() => {
	        state.messageScrollFrame = 0;
	        const next = state.pendingMessageScroll;
	        state.pendingMessageScroll = null;
	        const box = $("messages");
	        if (!box || !next) return;
	        if (next.shouldFollow) {
	          box.scrollTop = box.scrollHeight;
	          state.hasNewWhilePaused = false;
	        } else {
	          state.hasNewWhilePaused = true;
	        }
	        updateScrollLatestButton();
	        updateConversationMinimapViewport();
	      });
	    }

	    function updateStreamingMessage(message, options = {}) {
	      const box = $("messages");
	      let wrap = box.querySelector(`[data-message-key="${messageKey(message)}"]`);
	      if (options.reasoning && wrap) {
	        scheduleReasoningPreview(message);
	        return;
	      }
	      const previousTop = box.scrollTop;
	      const shouldFollow = state.followOutput || isNearBottom(box);
	      let structureChanged = false;
	      let iconsChanged = false;
	      if (!wrap) {
	        wrap = createMessageElement(message);
	        box.appendChild(wrap);
	        structureChanged = true;
	        iconsChanged = true;
	      } else if (options.forceFull) {
	        updateMessageElement(wrap, message);
	        iconsChanged = true;
	      } else {
	        iconsChanged = updateLiveMessageElement(wrap, message, options);
	      }
	      settleMessageScroll(previousTop, shouldFollow);
	      if (options.usage || options.final) updateChatUsage();
	      if (iconsChanged) queueLucideRefresh();
	      if (structureChanged) queueConversationMinimap();
	      else {
	        const now = performance.now();
	        if (options.final || now - state.lastStreamMinimapAt >= 240) {
	          state.lastStreamMinimapAt = now;
	          queueConversationMinimapLayout();
	        }
	      }
	    }

	    function appendMessageElements(messages, options = {}) {
	      const box = $("messages");
	      const fragment = document.createDocumentFragment();
	      for (const message of messages) fragment.appendChild(createMessageElement(message));
	      box.appendChild(fragment);
	      if (options.forceScroll) {
	        state.followOutput = true;
	        state.hasNewWhilePaused = false;
	        box.scrollTop = box.scrollHeight;
	      }
	      updateScrollLatestButton();
	      updateChatUsage();
	      queueLucideRefresh();
	      queueConversationMinimap();
	    }

	    function renderMessages(options = {}) {
	      const box = $("messages");
	      const previousTop = box.scrollTop;
	      const shouldFollow = Boolean(options.forceScroll) || state.followOutput || isNearBottom(box);
	      if (!state.messages.length) {
	        renderEmpty();
	        state.followOutput = true;
	        state.hasNewWhilePaused = false;
	        updateScrollLatestButton();
	        updateChatUsage();
	        hideConversationMinimap();
	        return;
	      }
	      const fragment = document.createDocumentFragment();
	      for (const msg of state.messages) {
	        fragment.appendChild(createMessageElement(msg));
	      }
	      box.replaceChildren(fragment);
	      if (!shouldFollow) box.scrollTop = previousTop;
	      settleMessageScroll(previousTop, shouldFollow);
	      updateChatUsage();
	      queueLucideRefresh();
	      queueConversationMinimap();
	    }

	    async function copyText(text, button) {
	      const value = String(text || "");
	      if (!value) return;
	      if (await writeClipboard(value)) {
	        markCopied(button);
	        setStatus("chatStatus", "已复制", "ok");
	        return;
	      }
	      if (fallbackCopy(value)) {
	        markCopied(button);
	        setStatus("chatStatus", "已复制", "ok");
	        return;
	      }
	      openManualCopy(value);
	      setStatus("chatStatus", "浏览器限制了自动复制", "err");
	    }

	    async function writeClipboard(text) {
	      try {
	        if (!navigator.clipboard || !navigator.clipboard.writeText) return false;
	        await navigator.clipboard.writeText(text);
	        return true;
	      } catch {
	        return false;
	      }
	    }

	    function fallbackCopy(text) {
	      const textarea = document.createElement("textarea");
	      textarea.value = text;
	      textarea.setAttribute("readonly", "");
	      textarea.style.position = "fixed";
	      textarea.style.top = "-1000px";
	      textarea.style.left = "-1000px";
	      textarea.style.width = "1px";
	      textarea.style.height = "1px";
	      textarea.style.opacity = "0";
	      document.body.appendChild(textarea);
	      textarea.focus({ preventScroll: true });
	      textarea.select();
	      textarea.setSelectionRange(0, textarea.value.length);
	      let ok = false;
	      try {
	        ok = document.execCommand("copy");
	      } catch {
	        ok = false;
	      }
	      textarea.remove();
	      return ok;
	    }

	    function markCopied(button) {
	      if (!button) return;
	      const old = button.innerHTML;
	      button.textContent = "✓";
	      setTimeout(() => {
	        button.innerHTML = old;
	      }, 900);
	    }

	    function safeImageFilename(name) {
	      return String(name || "image").replace(/[\\/]+/g, "_").replace(/[^\w.\-\u4e00-\u9fa5]+/g, "_").slice(0, 120);
	    }

	    function attachmentClientId() {
	      if (window.crypto?.randomUUID) return window.crypto.randomUUID();
	      return "img_" + Date.now() + "_" + Math.random().toString(36).slice(2, 8);
	    }

	    function imageDisplayUrl(image) {
	      return image?.preview_url || image?.view_url || image?.oss_url || image?.image_url || "";
	    }

	    function messageImages(message) {
	      return Array.isArray(message?.images) ? message.images : [];
	    }

	    function renderMessageImages(container, images = []) {
	      if (!container) return;
	      container.replaceChildren();
	      container.hidden = !images.length;
	      for (const image of images) {
	        const url = imageDisplayUrl(image);
	        if (!url) continue;
	        const button = document.createElement("button");
	        button.className = "message-image-btn";
	        button.type = "button";
	        button.title = image.filename || "查看图片";
	        const img = document.createElement("img");
	        img.src = url;
	        img.alt = image.filename || "聊天图片";
	        img.loading = "lazy";
	        img.addEventListener("load", queueConversationMinimap, { once: true });
	        button.appendChild(img);
	        button.addEventListener("click", () => openImagePreview(url));
	        container.appendChild(button);
	      }
	      container.hidden = !container.children.length;
	    }

	    function renderAttachmentPreviews() {
	      const row = $("attachmentPreviewRow");
	      if (!row) return;
	      row.replaceChildren();
	      row.hidden = !state.attachments.length;
	      for (const item of state.attachments) {
	        const card = document.createElement("div");
	        card.className = "attachment-preview" + (item.status === "uploading" ? " is-uploading" : "") + (item.status === "error" ? " is-error" : "");
	        card.title = item.filename || "图片";
	        const img = document.createElement("img");
	        img.src = item.preview_url || item.view_url || "";
	        img.alt = item.filename || "待发送图片";
	        card.appendChild(img);
	        if (item.status === "uploading" || item.status === "error" || item.justUploaded) {
	          const ring = document.createElement("div");
	          ring.className = "attachment-ring";
	          ring.style.setProperty("--progress", String(item.status === "error" ? 100 : Math.max(0, Math.min(100, Number(item.progress || 0)))));
	          ring.textContent = item.status === "error" ? "!" : (item.progress >= 100 ? "✓" : Math.round(item.progress || 0) + "%");
	          card.appendChild(ring);
	        }
		        const remove = document.createElement("button");
		        remove.className = "attachment-remove ui-icon-btn";
		        remove.type = "button";
		        remove.title = "移除图片";
		        remove.innerHTML = '<i data-lucide="x" aria-hidden="true"></i><span class="icon-fallback">×</span>';
		        remove.addEventListener("click", () => removeAttachment(item.client_id));
		        card.appendChild(remove);
	        if (item.status !== "ready") {
	          const status = document.createElement("div");
	          status.className = "attachment-progress";
	          status.textContent = item.status === "error" ? "上传失败" : "上传中";
	          card.appendChild(status);
	        }
		        row.appendChild(card);
		      }
		      queueLucideRefresh();
		      syncComposerLayout();
		    }

	    function removeAttachment(clientId) {
	      const item = state.attachments.find((entry) => entry.client_id === clientId);
	      if (item?.preview_url) URL.revokeObjectURL(item.preview_url);
	      state.attachments = state.attachments.filter((entry) => entry.client_id !== clientId);
	      renderAttachmentPreviews();
	      updateVisionUI();
	    }

	    function clearAttachments() {
	      for (const item of state.attachments) {
	        if (item.preview_url) URL.revokeObjectURL(item.preview_url);
	      }
	      state.attachments = [];
	      renderAttachmentPreviews();
	      updateVisionUI();
	    }

	    function openImagePreview(url) {
	      if (!url) return;
	      $("imagePreviewFull").src = url;
	      $("imagePreviewDialog").classList.add("show");
	      setDialogOpenState();
	    }

	    function closeImagePreview() {
	      $("imagePreviewDialog").classList.remove("show");
	      $("imagePreviewFull").src = "";
	      setDialogOpenState();
	    }

	    document.addEventListener("aimarkdown:image", (event) => {
	      openImagePreview(event.detail?.src || "");
	    });

	    function uploadFormWithProgress(url, form, onProgress) {
	      return new Promise((resolve, reject) => {
	        const xhr = new XMLHttpRequest();
	        xhr.open("POST", url);
	        xhr.upload.onprogress = (event) => {
	          if (!event.lengthComputable) return;
	          const percent = Math.max(1, Math.min(96, Math.round((event.loaded / event.total) * 96)));
	          onProgress(percent);
	        };
	        xhr.onload = () => {
	          if (xhr.status >= 200 && xhr.status < 300) {
	            onProgress(98);
	            resolve(xhr);
	          } else {
	            reject(new Error("图片上传 OSS 失败"));
	          }
	        };
	        xhr.onerror = () => reject(new Error("图片上传 OSS 失败"));
	        xhr.ontimeout = () => reject(new Error("图片上传超时"));
	        xhr.timeout = 120000;
	        xhr.send(form);
	      });
	    }

	    async function uploadChatImageAttachment(item) {
	      const policyRes = await api("/api/chat-images/upload-policy", { method: "POST" });
	      if (!policyRes.ok) throw new Error(await readError(policyRes, "图片上传配置不可用。"));
	      const { policy } = await policyRes.json();
	      if (item.file.size > policy.max_size) throw new Error("单张图片不能超过 20MB");
	      const key = policy.key_prefix + Date.now() + "-" + Math.random().toString(36).slice(2, 8) + "-" + safeImageFilename(item.file.name);
	      const form = new FormData();
	      form.append("key", key);
	      form.append("OSSAccessKeyId", policy.access_key_id);
	      form.append("policy", policy.policy);
	      form.append("Signature", policy.signature);
	      form.append("success_action_status", "200");
	      form.append("Content-Type", item.file.type || "application/octet-stream");
	      form.append("file", item.file);
	      await uploadFormWithProgress(policy.host, form, (progress) => {
	        item.progress = progress;
	        renderAttachmentPreviews();
	      });
	      const saveRes = await api("/api/chat-images", {
	        method: "POST",
	        body: JSON.stringify({
	          filename: item.file.name,
	          mime_type: item.file.type || "",
	          file_size: item.file.size,
	          oss_key: key
	        })
	      });
	      if (!saveRes.ok) throw new Error(await readError(saveRes, "图片信息保存失败。"));
	      const data = await saveRes.json();
	      item.progress = 100;
	      return data.image;
	    }

	    async function handleImageFiles(fileList) {
	      const input = $("imageInput");
	      const files = Array.from(fileList || []);
	      if (input) input.value = "";
	      if (!files.length) return;
	      if (!selectedModelSupportsVision()) {
	        setStatus("chatStatus", "当前模型不支持图片理解，请切换支持图片的模型。", "err");
	        return;
	      }
	      if (state.attachments.length + files.length > 5) {
	        setStatus("chatStatus", "单次最多上传 5 张图片。", "err");
	        return;
	      }
	      const allowedTypes = new Set(["image/jpeg", "image/png", "image/webp"]);
	      const allowedExts = [".jpg", ".jpeg", ".png", ".webp"];
	      const items = [];
	      for (const file of files) {
	        const lowerName = file.name.toLowerCase();
	        const extOk = allowedExts.some((ext) => lowerName.endsWith(ext));
	        if (!allowedTypes.has(file.type) && !extOk) {
	          setStatus("chatStatus", "只支持 jpg、jpeg、png、webp 图片。", "err");
	          return;
	        }
	        if (file.size > 20 * 1024 * 1024) {
	          setStatus("chatStatus", "单张图片不能超过 20MB。", "err");
	          return;
	        }
	        items.push({
	          client_id: attachmentClientId(),
	          file,
	          filename: file.name,
	          preview_url: URL.createObjectURL(file),
	          progress: 1,
	          status: "uploading"
	        });
	      }
	      state.attachments.push(...items);
	      state.uploadingImages = true;
	      updateVisionUI();
	      renderAttachmentPreviews();
	      setStatus("chatStatus", "正在上传图片...", "");
	      try {
	        for (const item of items) {
	          try {
	            const image = await uploadChatImageAttachment(item);
	            item.id = image.id;
	            item.view_url = image.view_url;
	            item.filename = image.filename || item.filename;
	            item.progress = 100;
	            item.status = "ready";
	            item.justUploaded = true;
	            setTimeout(() => {
	              item.justUploaded = false;
	              renderAttachmentPreviews();
	            }, 650);
	          } catch (err) {
	            item.status = "error";
	            item.progress = 100;
	            item.error = friendlyError(err, "图片上传失败。");
	          }
	          renderAttachmentPreviews();
	        }
	        const failed = items.filter((item) => item.status === "error");
	        if (failed.length) {
	          setStatus("chatStatus", failed[0].error || "有图片上传失败，请移除后重试。", "err");
	        } else {
	          setStatus("chatStatus", "图片已添加，输入问题后发送。", "ok");
	        }
	      } finally {
	        state.uploadingImages = false;
	        updateVisionUI();
	      }
	    }

	    function openManualCopy(text) {
	      $("manualCopyText").value = text;
	      $("copyDialog").classList.add("show");
	      setDialogOpenState();
	      setTimeout(() => {
	        $("manualCopyText").focus();
	        $("manualCopyText").select();
	      }, 0);
	    }

	    function closeManualCopy() {
	      $("copyDialog").classList.remove("show");
	      $("manualCopyText").value = "";
	      setDialogOpenState();
	    }

	    function confirmAction(options = {}) {
	      const dialog = $("confirmDialog");
	      const ok = $("confirmOk");
	      const cancel = $("cancelConfirm");
	      const secondary = $("secondaryConfirm");
	      $("confirmTitle").textContent = options.title || "确认操作";
	      $("confirmMessage").textContent = options.message || "确定要继续吗？";
	      ok.textContent = options.confirmText || "确定";
	      cancel.textContent = options.cancelText || "取消";
	      secondary.textContent = options.secondaryText || "";
	      secondary.hidden = !options.secondaryText;
	      ok.classList.toggle("danger", Boolean(options.danger));
	      secondary.classList.toggle("danger", Boolean(options.secondaryDanger));
	      dialog.classList.add("show");
	      setDialogOpenState();
	      return new Promise((resolve) => {
	        function cleanup(result) {
	          dialog.classList.remove("show");
	          setDialogOpenState();
	          ok.removeEventListener("click", onOk);
	          cancel.removeEventListener("click", onCancel);
	          secondary.removeEventListener("click", onSecondary);
	          dialog.removeEventListener("click", onBackdrop);
	          document.removeEventListener("keydown", onKey);
	          secondary.hidden = true;
	          secondary.classList.remove("danger");
	          resolve(result);
	        }
	        function onOk() { cleanup(true); }
	        function onCancel() { cleanup(false); }
	        function onSecondary() { cleanup("secondary"); }
	        function onBackdrop(event) {
	          if (event.target === dialog) cleanup(false);
	        }
	        function onKey(event) {
	          if (event.key === "Escape") cleanup(false);
	        }
	        ok.addEventListener("click", onOk);
	        cancel.addEventListener("click", onCancel);
	        secondary.addEventListener("click", onSecondary);
	        dialog.addEventListener("click", onBackdrop);
	        document.addEventListener("keydown", onKey);
	        setTimeout(() => cancel.focus(), 0);
	      });
	    }

	    function resetStreamState() {
	      if (state.streamTimer) clearTimeout(state.streamTimer);
	      state.streamMessage = null;
	      state.streamQueue = "";
	      state.streamTimer = null;
	      state.streamResolve = null;
	      state.firstTokenAt = null;
	      state.lastStreamMinimapAt = 0;
	    }

	    function setSendingUI(isSending) {
	      const send = $("send");
	      state.sending = Boolean(isSending);
	      send.disabled = false;
	      send.classList.toggle("is-stop", state.sending);
	      send.title = state.sending ? "停止生成" : "发送";
	      send.setAttribute("aria-label", send.title);
	      send.innerHTML = state.sending
	        ? '<i data-lucide="square" aria-hidden="true"></i><span class="icon-fallback">■</span>'
	        : '<i data-lucide="arrow-up" aria-hidden="true"></i><span class="icon-fallback">↑</span>';
	      queueLucideRefresh();
	      if (state.sending) $("webSearchToggle").disabled = true;
	      updateVisionUI();
	    }

	    function stopGeneration() {
	      if (!state.sending) return;
	      state.userStopped = true;
	      setStatus("chatStatus", "正在停止...", "");
	      if (state.abortController) state.abortController.abort();
	    }

	    function enqueueAssistantText(message, piece) {
	      const text = String(piece || "");
	      if (!text) return;
	      const pendingContent = String(message.content || "") + (state.streamMessage === message ? state.streamQueue : "") + text;
	      const parsedPending = splitThinkContent(pendingContent);
	      if (message.thinking && parsedPending.reasoning && !message._reasoningStartedAt) {
	        message._reasoningStartedAt = Date.now();
	      }
	      if (message.thinking && parsedPending.content) {
	        completeReasoning(message);
	        message.thinking = false;
	        state.firstTokenAt = Date.now();
	        setStatus("chatStatus", "正在生成...", "");
	      }
	      if (state.streamMessage !== message) {
	        state.streamMessage = message;
	        state.streamQueue = "";
	      }
	      state.streamQueue += text;
	      if (!state.streamTimer) scheduleStreamTick();
	    }

	    function scheduleStreamTick() {
	      state.streamTimer = setTimeout(streamTick, 32);
	    }

	    function streamTick() {
	      const message = state.streamMessage;
	      if (!message) {
	        state.streamTimer = null;
	        resolveStreamDrain();
	        return;
	      }
	      if (!state.streamQueue) {
	        state.streamTimer = null;
	        resolveStreamDrain();
	        return;
	      }
	      const count = streamChunkSize(state.streamQueue.length);
	      message.content += state.streamQueue.slice(0, count);
	      state.streamQueue = state.streamQueue.slice(count);
	      const parsed = splitThinkContent(message.content);
	      if (parsed.reasoning && message.thinking) {
	        scheduleReasoningPreview(message);
	      }
	      updateStreamingMessage(message, { stream: true });
	      if (state.streamQueue) {
	        scheduleStreamTick();
	      } else {
	        state.streamTimer = null;
	        resolveStreamDrain();
	      }
	    }

	    function streamChunkSize(length) {
	      if (length > 4000) return 160;
	      if (length > 1800) return 112;
	      if (length > 800) return 72;
	      if (length > 320) return 44;
	      if (length > 120) return 28;
	      if (length > 40) return 16;
	      if (length > 16) return 10;
	      return length;
	    }

	    function resolveStreamDrain() {
	      if (state.streamResolve) {
	        const resolve = state.streamResolve;
	        state.streamResolve = null;
	        resolve();
	      }
	    }

	    function drainAssistantQueue() {
	      if (!state.streamQueue && !state.streamTimer) return Promise.resolve();
	      return new Promise((resolve) => {
	        state.streamResolve = resolve;
	      });
	    }

	    async function sendMessage(contentOverride = "", options = {}) {
	      const hasOverride = typeof contentOverride === "string" && contentOverride.trim();
	      const rawContent = (hasOverride ? contentOverride : $("prompt").value).trim();
	      const quoteSnapshot = hasOverride ? [] : state.pendingQuotes.map((quote) => ({ ...quote }));
	      const content = quoteSnapshot.length ? buildQuotedMessage(rawContent, quoteSnapshot) : rawContent;
	      const draftConversationId = state.currentConversation?.id || "new";
	      const readyAttachments = hasOverride ? [] : state.attachments.filter((item) => item.status === "ready" && item.id);
	      const failedAttachments = hasOverride ? [] : state.attachments.filter((item) => item.status === "error");
	      const uploadingAttachments = hasOverride ? [] : state.attachments.filter((item) => item.status === "uploading");
	      if (state.sending) return;
	      if (!content && !readyAttachments.length) {
	        if (state.uploadingImages || uploadingAttachments.length) setStatus("chatStatus", "图片还在上传，稍等一下再发送。", "err");
	        else if (failedAttachments.length) setStatus("chatStatus", "有图片上传失败，请移除后重试。", "err");
	        return;
	      }
	      if (state.uploadingImages || uploadingAttachments.length) {
	        setStatus("chatStatus", "图片还在上传，稍等一下再发送。", "err");
	        return;
	      }
	      if (failedAttachments.length) {
	        setStatus("chatStatus", "有图片上传失败，请移除后重试。", "err");
	        return;
	      }
	      if (readyAttachments.length && !selectedModelSupportsVision()) {
	        setStatus("chatStatus", "当前模型不支持图片理解，请切换支持图片的模型。", "err");
	        return;
	      }
	      let selectedModelId = $("modelSelect").value;
	      if (!selectedModelId) return setStatus("chatStatus", "先选择模型", "err");
	      if (state.newConversationPromise) {
	        setStatus("chatStatus", "正在准备新对话...", "");
	        try {
	          await state.newConversationPromise;
	          selectedModelId = $("modelSelect").value || selectedModelId;
	        } catch (err) {
	          setStatus("chatStatus", friendlyError(err, "新建对话失败，稍后再试一下。"), "err");
	          return;
	        }
	      }

	      if (!state.currentConversation) {
	        try {
	          await newConversation(selectedModelId);
	        } catch (err) {
	          setStatus("chatStatus", friendlyError(err, "新建对话失败，稍后再试一下。"), "err");
	          return;
	        }
	      } else if (state.currentConversation.model_id !== selectedModelId) {
	        const switched = await updateCurrentConversationModel(selectedModelId);
	        if (!switched) return;
	      }
	      if (!state.currentConversation) return;
	      if (readyAttachments.length && !state.currentConversation.supports_vision) {
	        setStatus("chatStatus", "当前模型不支持图片理解，请切换支持图片的模型。", "err");
	        return;
	      }

	      setStatus("chatStatus", "");
	      resetStreamState();
	      state.userStopped = false;
	      state.abortController = new AbortController();
	      const mode = state.searchConfig?.mode || "auto";
	      const useWebSearch = $("webSearchToggle").checked && !$("webSearchToggle").disabled;
	      setSendingUI(true);
	      if (!hasOverride) {
	        $("prompt").value = "";
	        clearCurrentDraft();
	        localStorage.removeItem(userStorageKey("chatDraft:new"));
	        localStorage.removeItem(quoteDraftStorageKey(draftConversationId));
	        localStorage.removeItem(userStorageKey("chatQuotes:new"));
	        state.pendingQuotes = [];
	        renderComposerQuotes();
	        autosizePrompt();
	      }
	      const sentAt = Math.floor(Date.now() / 1000);
	      const sentImages = readyAttachments.map((item) => ({
	        id: item.id,
	        filename: item.filename,
	        view_url: item.view_url,
	        mime_type: item.mime_type || item.file?.type || "",
	        file_size: item.file_size || item.file?.size || 0
	      }));
	      if (!hasOverride) clearAttachments();
	      const userContent = content || "请分析这些图片。";
	      state.messages.push({ role: "user", content: userContent, images: sentImages, created_at: sentAt });
	      const assistant = { role: "assistant", content: "", reasoning_content: "", sources: [], thinking: true, created_at: sentAt, _thinkingStartedAt: Date.now() };
	      state.messages.push(assistant);
	      state.followOutput = true;
	      state.hasNewWhilePaused = false;
	      appendMessageElements(state.messages.slice(-2), { forceScroll: true });
	      const searchStatusText = options.statusText || (
	        mode === "always" ? "正在联网搜索..." :
	        mode === "auto" ? (useWebSearch ? "正在联网搜索..." : "AI 思考中，必要时会自动联网...") :
	        (useWebSearch ? "正在联网搜索..." : "AI 思考中...")
	      );
	      setStatus("chatStatus", searchStatusText, "");

	      try {
	        const useProfile = !profileDisabledForConversation(state.currentConversation.id);
	        const res = await api(`/api/conversations/${state.currentConversation.id}/messages`, {
	          method: "POST",
	          body: JSON.stringify({ content: userContent, web_search: useWebSearch, use_profile: useProfile, image_ids: readyAttachments.map((item) => item.id) }),
	          signal: state.abortController.signal
	        });
        if (!res.ok) throw new Error(await readError(res, "发送失败，稍后再试一下。"));
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split(/\r?\n/);
          buffer = lines.pop() || "";
          for (const line of lines) {
            if (!line.startsWith("data:")) continue;
            const payload = line.slice(5).trim();
            if (!payload || payload === "[DONE]") continue;
            try {
              const event = JSON.parse(payload);
	              if (event.type === "search_status") {
	                assistant.sources = event.sources || [];
	                if (event.count) setStatus("chatStatus", "找到 " + event.count + " 个来源，正在生成...", "ok");
	                updateStreamingMessage(assistant, { sources: true });
	                continue;
	              }
	              if (event.usage) {
	                assistant.usage = event.usage;
	                updateStreamingMessage(assistant, { usage: true });
	              }
	              if (event.type === "message_saved" && event.message_id) {
	                assistant.id = event.message_id;
	                assistant.favorite_id = null;
	                assistant.usage = event.usage || assistant.usage || null;
	                updateStreamingMessage(assistant, { saved: true, usage: true });
	                continue;
	              }
	              const choice = event.choices?.[0] || {};
	              const piece = choice.delta?.content || choice.message?.content || "";
	              const responseReasoningValue = event.delta || event.text || event.content || "";
	              const responseEventReasoning = /reasoning|thinking/i.test(String(event.type || ""))
	                ? (typeof responseReasoningValue === "string" ? responseReasoningValue : (responseReasoningValue?.text || ""))
	                : "";
	              const reasoningPiece =
	                choice.delta?.reasoning_content ||
	                choice.message?.reasoning_content ||
	                choice.delta?.reasoning ||
	                choice.message?.reasoning ||
	                choice.delta?.thinking ||
	                choice.message?.thinking ||
	                event.reasoning_content ||
	                event.reasoning ||
	                event.thinking ||
	                responseEventReasoning ||
	                "";
	              if (reasoningPiece) {
	                if (!assistant._reasoningStartedAt) assistant._reasoningStartedAt = Date.now();
	                assistant.reasoning_content = (assistant.reasoning_content || "") + reasoningPiece;
	                updateStreamingMessage(assistant, { reasoning: true });
	              }
	              if (piece) {
	                enqueueAssistantText(assistant, piece);
	              }
	            } catch {}
	          }
	        }
	        completeReasoning(assistant);
	        assistant.thinking = false;
	        await drainAssistantQueue();
	        if (!assistant.content) {
	          assistant.content = "没有收到可显示的内容。";
	        }
	        updateStreamingMessage(assistant, { final: true, usage: true, sources: true });
	        await loadConversations();
	        await loadConversationStats(state.currentConversation?.id);
	        setStatus("chatStatus", "");
	      } catch (err) {
	        completeReasoning(assistant);
	        assistant.thinking = false;
	        if (state.userStopped || err?.name === "AbortError") {
	          if (assistant.content) {
	            enqueueAssistantText(assistant, "\n\n（已停止生成）");
	            await drainAssistantQueue();
	          } else {
	            assistant.content = "已停止生成。";
	          }
	          updateStreamingMessage(assistant, { final: true });
	          setStatus("chatStatus", "已停止生成", "");
	        } else {
	          const message = friendlyError(err, "发送失败，稍后再试一下。");
	          enqueueAssistantText(assistant, "\n" + message);
	          await drainAssistantQueue();
	          updateStreamingMessage(assistant, { final: true });
	          setStatus("chatStatus", message, "err");
	        }
	      } finally {
	        if (assistant.thinking) {
	          completeReasoning(assistant);
	          assistant.thinking = false;
	          updateStreamingMessage(assistant, { final: true });
	        }
	        state.abortController = null;
	        state.userStopped = false;
	        setSendingUI(false);
	        renderSearchToggle();
	        updateScrollLatestButton();
	        $("prompt").focus();
	      }
	    }

	    async function deleteCurrentConversation() {
	      if (!state.currentConversation) return;
	      await deleteConversationById(state.currentConversation.id);
	    }

	    async function deleteConversationById(id) {
	      const conv = state.conversations.find((item) => item.id === id);
	      if (!conv) return;
	      const ok = await confirmAction({
	        title: "删除对话",
	        message: `确定删除“${conv.title}”吗？删除后会从这里移除。`,
	        confirmText: "删除",
	        danger: true
	      });
	      if (!ok) return;
	      const res = await api(`/api/conversations/${id}`, { method: "DELETE" });
	      if (!res.ok) {
	        setStatus("chatStatus", await readError(res, "删除失败，稍后再试一下。"), "err");
	        return;
	      }
	      state.editingConversationId = null;
	      if (state.currentConversation?.id === id) {
	        state.currentConversation = null;
	        state.messages = [];
	      }
	      await loadConversations();
	      if (!state.currentConversation) renderEmpty();
	    }

	    const adminSections = {
	      overview: { title: "概览", desc: "查看平台状态、用量和关键配置。" },
	      accounts: { title: "账号管理", desc: "创建、编辑和禁用家庭账号。" },
	      models: { title: "模型管理", desc: "维护模型名称、供应商、Endpoint、System Prompt 和能力标签。" },
	      keys: { title: "密钥管理", desc: "集中维护管理密钥、模型 API Key 和搜索 API Key。" },
	      search: { title: "联网搜索", desc: "配置 Tavily/Brave、搜索策略、搜索深度和结果数量。" },
	      plugins: { title: "插件管理", desc: "查看图片、听悟、搜索、提示词等功能状态，后续可扩展独立开关。" },
	      tokens: { title: "Token统计", desc: "按账号查看累计 Token 用量和最近请求记录。" },
	      costs: { title: "成本统计", desc: "根据模型价格快照查看平台成本、模型排行和用户排行。" },
	      system: { title: "系统设置", desc: "修改登录密码并查看系统基础信息。" }
	    };

	    function switchAdminSection(section) {
	      const key = adminSections[section] ? section : "overview";
	      state.adminSection = key;
	      $("settingsDrawer").dataset.adminSection = key;
	      document.querySelectorAll(".admin-nav-item[data-admin-section]").forEach((button) => {
	        button.classList.toggle("active", button.dataset.adminSection === key);
	      });
	      document.querySelectorAll(".admin-page[data-admin-page]").forEach((page) => {
	        page.classList.toggle("active", page.dataset.adminPage === key);
	      });
	      $("adminModuleTitle").textContent = adminSections[key].title;
	      $("adminModuleDesc").textContent = adminSections[key].desc;
	      if (key === "overview") loadAdminOverview();
	      if (key === "accounts") loadAdminUsers();
	      if (key === "models") loadAdminModels();
	      if (key === "keys") loadAdminModels();
	      if (key === "search") loadAdminSearch();
	      if (key === "plugins") {
	        if (!state.adminOverview) loadAdminOverview();
	        renderPluginStatus();
	      }
	      if (key === "tokens") loadTokenStats();
	      if (key === "costs") loadCostStats();
	      queueLucideRefresh();
	    }

	    function openSettings() {
	      closeSidebarTools();
	      $("sidebar").classList.remove("show");
	      document.body.classList.remove("sidebar-open");
	      $("drawerMask").classList.add("show");
	      $("settingsDrawer").classList.add("show");
	      document.body.classList.add("admin-open");
	      closeDesktopPetMenu();
	      switchAdminSection(state.adminSection || "overview");
	      loadAdminOverview();
	      loadAdminModels();
	      loadAdminSearch();
	      loadAdminUsers();
	      loadTokenStats();
	      loadCostStats();
	    }

	    function closeSettings() {
	      $("drawerMask").classList.remove("show");
	      $("settingsDrawer").classList.remove("show");
	      document.body.classList.remove("admin-open");
	      schedulePetPositionCorrection();
	    }

	    async function loadAdminOverview() {
	      if (!hasAdminAccess()) {
	        state.adminOverview = null;
	        renderAdminOverview();
	        renderPluginStatus();
	        setStatus("adminOverviewStatus", "管理员账号或管理密钥可查看后台概览。", "");
	        return;
	      }
	      setStatus("adminOverviewStatus", "正在加载概览...", "");
	      const res = await adminApi("/api/admin/overview");
	      if (!res.ok) {
	        state.adminOverview = null;
	        renderAdminOverview();
	        renderPluginStatus();
	        setStatus("adminOverviewStatus", await readError(res, "概览加载失败，稍后再试一下。"), "err");
	        return;
	      }
	      const data = await res.json();
	      state.adminOverview = data.overview || {};
	      renderAdminOverview();
	      renderPluginStatus();
	      setStatus("adminOverviewStatus", "");
	    }

	    function renderAdminOverview() {
	      const overview = state.adminOverview || {};
	      const summary = state.tokenStats?.summary || {};
	      const models = overview.models || {};
	      const users = overview.users || {};
	      const conversations = overview.conversations || {};
	      const search = overview.search || {};
	      const oss = overview.oss || {};
	      const tingwu = overview.tingwu || {};
	      const metricCards = [
	        ["users", "用户数", users.total || summary.total_users || 0, "启用 " + tokenNumber(users.active || 0) + " 个账号"],
	        ["message-square", "总请求数", summary.total_requests || 0, "来自聊天请求日志"],
	        ["coins", "总 Token", summary.total_tokens || 0, "输入 " + tokenNumber(summary.prompt_tokens || 0) + " · 输出 " + tokenNumber(summary.completion_tokens || 0)],
	        ["bot", "可用模型", models.enabled || state.adminModels.filter((item) => item.enabled).length || 0, "共配置 " + tokenNumber(models.total || state.adminModels.length || 0) + " 个模型"],
	        ["messages-square", "会话数", conversations.total || 0, "未归档会话"],
	        ["search", "联网搜索", search.enabled ? "已开启" : "未开启", search.configured ? ((search.provider || "search") + " · " + (search.mode || "auto")) : "尚未配置 Key"],
	        ["hard-drive-upload", "OSS", oss.configured ? "已配置" : "未配置", ["猫相册", "聊天图片", "音视频"].filter((_, i) => [oss.cat, oss.chat_image, oss.media][i]).join(" · ") || "上传能力待配置"],
	        ["file-video", "听悟", tingwu.configured ? "已配置" : "未配置", "音视频分析状态"]
	      ];
	      const grid = $("adminOverviewGrid");
	      if (grid) {
	        grid.innerHTML = metricCards.map(([icon, title, value, desc]) => (
	          '<article class="admin-metric-card">' +
	            '<span class="admin-metric-title">' + iconMarkup(icon) + '<span>' + escapeHTML(title) + '</span></span>' +
	            '<strong>' + escapeHTML(String(typeof value === "number" ? tokenNumber(value) : value)) + '</strong>' +
	            '<p>' + escapeHTML(desc || "") + '</p>' +
	          '</article>'
	        )).join("");
	      }
	      const statusGrid = $("adminOverviewStatusGrid");
	      if (statusGrid) {
	        const statuses = [
	          ["search", "联网搜索", search.enabled && search.configured, search.enabled ? "自动/手动搜索策略可用" : "当前未启用"],
	          ["image", "图片理解上传", Boolean(oss.chat_image), oss.chat_image ? "OSS 已配置，可上传图片" : "聊天图片 OSS 待配置"],
	          ["file-video", "音视频分析", Boolean(oss.media && tingwu.configured), oss.media && tingwu.configured ? "听悟与媒体 OSS 已就绪" : "需要听悟 AppKey 与媒体 OSS"],
	          ["book-open", "提示词库", true, "默认模板与自定义模板可用"],
	          ["user-round-cog", "AI档案", true, "按账号隔离的长期档案可用"],
	          ["shield-check", "后台权限", hasAdminAccess(), hasAdminAccess() ? "当前账号可管理后台" : "需要管理员身份"]
	        ];
	        statusGrid.innerHTML = statuses.map(([icon, title, ok, desc]) => (
	          '<article class="admin-status-card">' +
	            '<span class="admin-status-title">' + iconMarkup(icon) + '<span>' + escapeHTML(title) + '</span></span>' +
	            '<span class="admin-status-badge ' + (ok ? "ok" : "warn") + '">' + escapeHTML(ok ? "正常" : "待配置") + '</span>' +
	            '<p>' + escapeHTML(desc) + '</p>' +
	          '</article>'
	        )).join("");
	      }
	      queueLucideRefresh();
	    }

	    function renderPluginStatus() {
	      const overview = state.adminOverview || {};
	      const search = overview.search || state.adminSearch || {};
	      const oss = overview.oss || {};
	      const tingwu = overview.tingwu || {};
	      const visionCount = state.adminModels.filter((item) => item.enabled && item.supports_vision).length;
	      const plugins = [
	        ["search", "联网搜索", Boolean(search.enabled && (search.configured || search.has_api_key)), search.enabled ? "已启用搜索策略" : "未启用"],
	        ["image", "图片理解", visionCount > 0, visionCount ? tokenNumber(visionCount) + " 个模型支持图片理解" : "没有开启图片理解的模型"],
	        ["upload-cloud", "图片上传", Boolean(oss.chat_image), oss.chat_image ? "聊天图片 OSS 已配置" : "待配置聊天图片 OSS"],
	        ["file-video", "音视频分析", Boolean(oss.media && tingwu.configured), oss.media && tingwu.configured ? "通义听悟可用" : "待配置听悟或媒体 OSS"],
	        ["book-open", "提示词库", true, "常用提示词模板已启用"],
	        ["star", "收藏回答", true, "按账号隔离保存收藏"],
	        ["user-round-cog", "AI档案", true, "长期档案已启用"],
	        ["map", "Conversation Minimap", true, "桌面端对话缩略导航"]
	      ];
	      const box = $("pluginStatusList");
	      if (!box) return;
	      box.innerHTML = plugins.map(([icon, title, ok, desc]) => (
	        '<article class="admin-plugin-card">' +
	          '<span class="admin-plugin-title">' + iconMarkup(icon) + '<span>' + escapeHTML(title) + '</span></span>' +
	          '<span class="admin-status-badge ' + (ok ? "ok" : "warn") + '">' + escapeHTML(ok ? "已启用" : "待配置") + '</span>' +
	          '<p>' + escapeHTML(desc) + '</p>' +
	        '</article>'
	      )).join("");
	      queueLucideRefresh();
	    }

	    async function loadAdminModels() {
	      if (!hasAdminAccess()) {
	        state.adminModels = [];
	        setStatus("adminStatus", "管理员账号或管理密钥可加载模型", "");
	        if ($("adminModelList")) $("adminModelList").innerHTML = "";
	        renderModelKeys([]);
	        renderAdminOverview();
	        renderPluginStatus();
	        return;
	      }
	      const res = await adminApi("/api/admin/models");
	      if (!res.ok) {
	        setStatus("adminStatus", "管理密钥无效", "err");
	        return;
	      }
	      setStatus("adminStatus", "管理密钥有效", "ok");
	      const data = await res.json();
	      state.adminModels = data.models || [];
	      renderAdminModels(state.adminModels);
	      renderModelKeys(state.adminModels);
	      renderAdminOverview();
	      renderPluginStatus();
	    }

	    async function loadAdminSearch() {
	      if (!hasAdminAccess()) {
	        state.adminSearch = null;
	        setStatus("searchStatus", "管理员账号或管理密钥可加载搜索配置", "");
	        renderAdminOverview();
	        renderPluginStatus();
	        return;
	      }
	      const res = await adminApi("/api/admin/search");
	      if (!res.ok) {
	        setStatus("searchStatus", "管理密钥无效", "err");
	        return;
	      }
	      const data = await res.json();
	      const search = data.search || {};
	      state.adminSearch = search;
	      $("searchProvider").value = search.provider || "tavily";
	      $("searchEnabled").value = search.enabled ? "1" : "0";
	      $("searchMode").value = search.mode || "auto";
	      $("searchDepth").value = search.depth || "advanced";
	      $("searchResultCount").value = search.result_count || 5;
	      $("searchApiKey").value = "";
	      $("searchApiKey").placeholder = search.has_api_key ? "已保存，留空保持原值" : "请输入搜索 API Key";
	      setStatus("searchStatus", search.has_api_key ? "搜索 Key 已保存；日期会自动按当天注入" : "尚未配置搜索 Key", search.has_api_key ? "ok" : "");
	      renderAdminOverview();
	      renderPluginStatus();
	    }

	    async function saveSearchConfig(clearKey = false) {
	      const body = {
	        provider: $("searchProvider").value,
	        enabled: $("searchEnabled").value === "1",
	        mode: $("searchMode").value,
	        depth: $("searchDepth").value,
	        result_count: Number($("searchResultCount").value || 5),
	        api_key: $("searchApiKey").value.trim(),
	        clear_api_key: clearKey
	      };
	      const res = await adminApi("/api/admin/search", {
	        method: "POST",
	        body: JSON.stringify(body)
	      });
	      if (!res.ok) {
	        setStatus("searchStatus", await readError(res, "搜索配置保存失败，稍后再试一下。"), "err");
	        return;
	      }
	      $("searchApiKey").value = "";
	      setStatus("searchStatus", clearKey ? "搜索 Key 已清空" : "搜索配置已保存", "ok");
	      await loadAdminSearch();
	      await loadSearchConfig();
	      await loadAdminOverview();
	    }

	    async function saveSearchKey() {
	      await saveSearchConfig(false);
	    }

	    function tokenNumber(value) {
	      return Number(value || 0).toLocaleString();
	    }

	    function moneyNumber(value) {
	      const num = Number(value || 0);
	      if (num >= 1000) return "￥" + num.toLocaleString(undefined, { maximumFractionDigits: 0 });
	      if (num >= 1) return "￥" + num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
	      return "￥" + num.toLocaleString(undefined, { minimumFractionDigits: 4, maximumFractionDigits: 4 });
	    }

	    function renderTokenSummary(summary = {}) {
	      const box = $("tokenSummaryGrid");
	      if (!box) return;
	      const cards = [
	        ["总用户数", summary.total_users || 0],
	        ["总请求数", summary.total_requests || 0],
	        ["累计输入 Token", summary.prompt_tokens || 0],
	        ["累计输出 Token", summary.completion_tokens || 0],
	        ["累计 Token", summary.total_tokens || 0]
	      ];
	      box.innerHTML = cards.map(([label, value]) => (
	        '<div class="token-summary-card"><span>' + escapeHTML(label) + '</span><strong>' + tokenNumber(value) + '</strong></div>'
	      )).join("");
	    }

	    function renderModelTokenSummary(summary = {}) {
	      const box = $("modelTokenSummaryGrid");
	      if (!box) return;
	      const topRequest = summary.top_request_model?.name || "暂无";
	      const topToken = summary.top_token_model?.name || "暂无";
	      const cards = [
	        ["总模型数", summary.total_models || 0],
	        ["总请求数", summary.total_requests || 0],
	        ["累计 Token", summary.total_tokens || 0],
	        ["使用最多模型", topRequest],
	        ["Token最高模型", topToken]
	      ];
	      box.innerHTML = cards.map(([label, value]) => (
	        '<div class="token-summary-card"><span>' + escapeHTML(label) + '</span><strong title="' + escapeHTML(String(value)) + '">' + escapeHTML(typeof value === "number" ? tokenNumber(value) : String(value)) + '</strong></div>'
	      )).join("");
	    }

	    function switchTokenStatsTab(tab) {
	      const key = tab === "models" ? "models" : "users";
	      state.tokenStatsTab = key;
	      document.querySelectorAll(".token-tab[data-token-tab]").forEach((button) => {
	        const active = button.dataset.tokenTab === key;
	        button.classList.toggle("active", active);
	        button.setAttribute("aria-selected", active ? "true" : "false");
	      });
	      document.querySelectorAll(".token-panel[data-token-panel]").forEach((panel) => {
	        panel.classList.toggle("active", panel.dataset.tokenPanel === key);
	      });
	      renderTokenStatsStatus();
	      queueLucideRefresh();
	    }

	    function renderTokenStatsStatus() {
	      const data = state.tokenStats;
	      if (!data) {
	        setStatus("tokenStatsStatus", "");
	        return;
	      }
	      if (state.tokenStatsTab === "models") {
	        setStatus("tokenStatsStatus", data.models?.length ? "" : "没有匹配的模型。", data.models?.length ? "" : "err");
	      } else {
	        setStatus("tokenStatsStatus", data.users?.length ? "" : "没有匹配的账号。", data.users?.length ? "" : "err");
	      }
	    }

	    function scheduleTokenStatsLoad() {
	      clearTimeout(state.tokenStatsTimer);
	      state.tokenStatsTimer = setTimeout(loadTokenStats, 180);
	    }

	    async function loadTokenStats() {
	      const list = $("tokenStatsList");
	      if (!hasAdminAccess()) {
	        state.tokenStats = null;
	        if (list) list.innerHTML = '<div class="status">管理员账号或管理密钥可查看 Token 统计。</div>';
	        renderTokenSummary({});
	        renderModelTokenSummary({});
	        if ($("modelTokenStatsList")) $("modelTokenStatsList").innerHTML = '<div class="status">管理员账号或管理密钥可查看模型 Token 统计。</div>';
	        renderAdminOverview();
	        setStatus("tokenStatsStatus", "");
	        return;
	      }
	      const query = encodeURIComponent(($("tokenStatsQuery")?.value || "").trim());
	      const sort = encodeURIComponent($("tokenStatsSort")?.value || "tokens");
	      const modelQuery = encodeURIComponent(($("modelTokenStatsQuery")?.value || "").trim());
	      const modelSort = encodeURIComponent($("modelTokenStatsSort")?.value || "tokens");
	      setStatus("tokenStatsStatus", "正在加载 Token 统计...", "");
	      const res = await adminApi(`/api/admin/token-stats?q=${query}&sort=${sort}&model_q=${modelQuery}&model_sort=${modelSort}`);
	      if (!res.ok) {
	        if (list) list.innerHTML = "";
	        state.tokenStats = null;
	        renderTokenSummary({});
	        renderModelTokenSummary({});
	        if ($("modelTokenStatsList")) $("modelTokenStatsList").innerHTML = "";
	        renderAdminOverview();
	        setStatus("tokenStatsStatus", await readError(res, "Token 统计加载失败，稍后再试一下。"), "err");
	        return;
	      }
	      const data = await res.json();
	      state.tokenStats = data;
	      renderTokenSummary(data.summary || {});
	      renderModelTokenSummary(data.model_summary || {});
	      renderTokenStatsList(data.users || []);
	      renderModelTokenStatsList(data.models || []);
	      renderAdminOverview();
	      renderTokenStatsStatus();
	    }

	    function renderTokenStatsList(users) {
	      const box = $("tokenStatsList");
	      if (!box) return;
	      box.innerHTML = "";
	      if (!users.length) {
	        box.appendChild(createEmptyState("bar-chart-3", "暂无 Token 记录", "有聊天请求后，这里会显示各账号用量。", { compact: true }));
	        queueLucideRefresh();
	        return;
	      }
	      for (const user of users) {
	        const row = document.createElement("div");
	        row.className = "model-row token-user-row";
	        const main = document.createElement("div");
	        main.className = "token-user-main";
	        const title = document.createElement("strong");
	        title.textContent = (user.display_name || user.username) + " · " + user.username + (user.is_active ? "" : "（已禁用）");
	        const meta = document.createElement("span");
	        meta.textContent = "注册 " + formatTime(user.created_at) + " · 最后使用 " + (user.last_used_at ? formatTime(user.last_used_at) : "暂无");
	        const stats = document.createElement("div");
	        stats.className = "token-user-stats";
	        stats.innerHTML =
	          '<span>对话 <b>' + tokenNumber(user.conversation_count) + '</b></span>' +
	          '<span>请求 <b>' + tokenNumber(user.request_count) + '</b></span>' +
	          '<span>输入 <b>' + tokenNumber(user.prompt_tokens) + '</b></span>' +
	          '<span>输出 <b>' + tokenNumber(user.completion_tokens) + '</b></span>' +
	          '<span>总计 <b>' + tokenNumber(user.total_tokens) + '</b></span>';
	        main.append(title, meta, stats);
	        const actions = document.createElement("div");
	        actions.className = "library-actions";
	        const expanded = state.tokenStatsExpandedUserId === user.id;
	        const detailBtn = createIconButton(expanded ? "chevron-up" : "chevron-down", expanded ? "收起" : "详情", { fallback: expanded ? "收" : "详" });
	        detailBtn.addEventListener("click", () => {
	          state.tokenStatsExpandedUserId = expanded ? "" : user.id;
	          renderTokenStatsList(state.tokenStats?.users || []);
	        });
	        actions.append(detailBtn);
	        row.append(main, actions);
	        if (expanded) row.appendChild(renderTokenUserDetail(user));
	        box.appendChild(row);
	      }
	      queueLucideRefresh();
	    }

	    function renderTokenUserDetail(user) {
	      const detail = document.createElement("div");
	      detail.className = "token-detail";
	      const rows = user.recent_requests || [];
	      if (!rows.length) {
	        detail.textContent = "最近还没有请求记录。";
	        return detail;
	      }
	      const tableRows = rows.map((item) => {
	        const model = [item.model_name, item.model_code].filter(Boolean).join(" · ") || "-";
	        const web = item.web_search ? "是" : "否";
	        const duration = item.duration_ms ? (Number(item.duration_ms) / 1000).toFixed(1) + "s" : "-";
	        return '<tr>' +
	          '<td>' + escapeHTML(formatTime(item.created_at)) + '</td>' +
	          '<td title="' + escapeHTML(model) + '">' + escapeHTML(model) + '</td>' +
	          '<td>' + tokenNumber(item.prompt_tokens) + '</td>' +
	          '<td>' + tokenNumber(item.completion_tokens) + '</td>' +
	          '<td>' + tokenNumber(item.total_tokens) + '</td>' +
	          '<td>' + escapeHTML(duration) + '</td>' +
	          '<td>' + web + '</td>' +
	        '</tr>';
	      }).join("");
	      detail.innerHTML =
	        '<table><thead><tr><th>时间</th><th>模型</th><th>输入Token</th><th>输出Token</th><th>总Token</th><th>耗时</th><th>联网</th></tr></thead><tbody>' +
	        tableRows +
	        '</tbody></table>';
	      return detail;
	    }

	    function renderModelTokenStatsList(models) {
	      const box = $("modelTokenStatsList");
	      if (!box) return;
	      box.innerHTML = "";
	      if (!models.length) {
	        box.appendChild(createEmptyState("bot", "暂无模型统计", "没有匹配的模型，或还没有模型调用记录。", { compact: true }));
	        queueLucideRefresh();
	        return;
	      }
	      for (const model of models) {
	        const row = document.createElement("div");
	        row.className = "model-row token-user-row";
	        const main = document.createElement("div");
	        main.className = "token-user-main";
	        const title = document.createElement("strong");
	        title.textContent = model.name + (model.enabled ? "" : "（停用）");
	        const meta = document.createElement("span");
	        meta.textContent = [model.provider || "未知供应商", model.model || "未知模型", "最后调用 " + (model.last_used_at ? formatTime(model.last_used_at) : "暂无")].join(" · ");
	        const stats = document.createElement("div");
	        stats.className = "token-user-stats";
	        stats.innerHTML =
	          '<span>请求 <b>' + tokenNumber(model.request_count) + '</b></span>' +
	          '<span>账号 <b>' + tokenNumber(model.user_count) + '</b></span>' +
	          '<span>输入 <b>' + tokenNumber(model.prompt_tokens) + '</b></span>' +
	          '<span>输出 <b>' + tokenNumber(model.completion_tokens) + '</b></span>' +
	          '<span>总计 <b>' + tokenNumber(model.total_tokens) + '</b></span>';
	        main.append(title, meta, stats);
	        const actions = document.createElement("div");
	        actions.className = "library-actions";
	        const expanded = state.tokenStatsExpandedModelId === model.id;
	        const detailBtn = createIconButton(expanded ? "chevron-up" : "chevron-down", expanded ? "收起" : "详情", { fallback: expanded ? "收" : "详" });
	        detailBtn.addEventListener("click", () => {
	          state.tokenStatsExpandedModelId = expanded ? "" : model.id;
	          renderModelTokenStatsList(state.tokenStats?.models || []);
	        });
	        actions.append(detailBtn);
	        row.append(main, actions);
	        if (expanded) row.appendChild(renderModelTokenDetail(model));
	        box.appendChild(row);
	      }
	      queueLucideRefresh();
	    }

	    function renderModelTokenDetail(model) {
	      const detail = document.createElement("div");
	      detail.className = "token-detail";
	      const rows = model.recent_requests || [];
	      if (!rows.length) {
	        detail.textContent = "这个模型最近还没有调用记录。";
	        return detail;
	      }
	      const tableRows = rows.map((item) => {
	        const account = [item.display_name, item.username].filter(Boolean).join(" · ") || "-";
	        const title = item.conversation_title || "未命名对话";
	        const web = item.web_search ? "是" : "否";
	        const duration = item.duration_ms ? (Number(item.duration_ms) / 1000).toFixed(1) + "s" : "-";
	        return '<tr>' +
	          '<td>' + escapeHTML(formatTime(item.created_at)) + '</td>' +
	          '<td title="' + escapeHTML(account) + '">' + escapeHTML(account) + '</td>' +
	          '<td title="' + escapeHTML(title) + '">' + escapeHTML(title) + '</td>' +
	          '<td>' + tokenNumber(item.prompt_tokens) + '</td>' +
	          '<td>' + tokenNumber(item.completion_tokens) + '</td>' +
	          '<td>' + tokenNumber(item.total_tokens) + '</td>' +
	          '<td>' + web + '</td>' +
	          '<td>' + escapeHTML(duration) + '</td>' +
	        '</tr>';
	      }).join("");
	      detail.innerHTML =
	        '<table><thead><tr><th>时间</th><th>账号</th><th>会话标题</th><th>输入Token</th><th>输出Token</th><th>总Token</th><th>联网</th><th>耗时</th></tr></thead><tbody>' +
	        tableRows +
	        '</tbody></table>';
	      return detail;
	    }

	    async function loadCostStats() {
	      if (!hasAdminAccess()) {
	        state.costStats = null;
	        renderCostStats();
	        setStatus("costStatsStatus", "管理员账号或管理密钥可查看成本统计。", "");
	        return;
	      }
	      setStatus("costStatsStatus", "正在加载成本统计...", "");
	      const range = encodeURIComponent($("costStatsRange")?.value || "30d");
	      const res = await adminApi(`/api/admin/cost-stats?range=${range}`);
	      if (!res.ok) {
	        state.costStats = null;
	        renderCostStats();
	        setStatus("costStatsStatus", await readError(res, "成本统计加载失败，稍后再试一下。"), "err");
	        return;
	      }
	      state.costStats = await res.json();
	      renderCostStats();
	      setStatus("costStatsStatus", "");
	    }

	    function renderCostStats() {
	      const data = state.costStats || {};
	      const summary = data.summary || {};
	      const costGrid = $("costSummaryGrid");
	      if (costGrid) {
	        const cards = [
	          ["今日成本", moneyNumber(summary.today_cost)],
	          ["本月成本", moneyNumber(summary.month_cost)],
	          ["累计成本", moneyNumber(summary.total_cost)],
	          ["平均每次", moneyNumber(summary.average_request_cost)],
	          ["范围内成本", moneyNumber(summary.range_cost)]
	        ];
	        costGrid.innerHTML = cards.map(([label, value]) => (
	          '<div class="token-summary-card"><span>' + escapeHTML(label) + '</span><strong>' + escapeHTML(value) + '</strong></div>'
	        )).join("");
	      }
	      renderCostRank("costModelList", data.models || [], "model");
	      renderCostRank("costUserList", data.users || [], "user");
	      queueLucideRefresh();
	    }

	    function renderCostRank(id, rows, type) {
	      const box = $(id);
	      if (!box) return;
	      box.innerHTML = "";
	      if (!rows.length) {
	        box.appendChild(createEmptyState(type === "model" ? "bot" : "users", "暂无成本记录", "配置模型价格并产生新请求后，这里会显示成本排行。", { compact: true }));
	        return;
	      }
	      for (const item of rows.slice(0, 20)) {
	        const row = document.createElement("div");
	        row.className = "model-row token-user-row";
	        const main = document.createElement("div");
	        main.className = "token-user-main";
	        const title = document.createElement("strong");
	        title.textContent = type === "model" ? (item.model_name || "未知模型") : (item.display_name || item.username || "未知账号");
	        const meta = document.createElement("span");
	        meta.textContent = type === "model"
	          ? [item.provider, item.model_code, "账号 " + tokenNumber(item.user_count || 0)].filter(Boolean).join(" · ")
	          : [item.username, "最后 " + (item.last_used_at ? formatTime(item.last_used_at) : "暂无")].filter(Boolean).join(" · ");
	        const stats = document.createElement("div");
	        stats.className = "token-user-stats";
	        stats.innerHTML =
	          '<span>成本 <b>' + escapeHTML(moneyNumber(item.estimated_cost)) + '</b></span>' +
	          '<span>请求 <b>' + tokenNumber(item.request_count) + '</b></span>' +
	          '<span>Token <b>' + tokenNumber(item.total_tokens) + '</b></span>';
	        main.append(title, meta, stats);
	        row.append(main);
	        box.appendChild(row);
	      }
	    }

	    async function recalculateCostStats() {
	      if (!hasAdminAccess()) {
	        setStatus("costStatsStatus", "需要管理员账号或管理密钥。", "err");
	        return;
	      }
	      const range = $("costStatsRange")?.value || "30d";
	      const label = range === "7d" ? "最近7天" : (range === "30d" ? "最近30天" : "全部时间");
	      const ok = await confirmAction({
	        title: "回算历史成本",
	        message: "将按当前模型价格回算“" + label + "”内成本仍为 0 的历史回答，并重建每日统计。已固化过成本的请求不会被覆盖。",
	        confirmText: "开始回算"
	      });
	      if (!ok) return;
	      setStatus("costStatsStatus", "正在按当前模型价格回算历史成本...", "");
	      const res = await adminApi("/api/admin/cost-recalculate", {
	        method: "POST",
	        body: JSON.stringify({ range })
	      });
	      if (!res.ok) {
	        setStatus("costStatsStatus", await readError(res, "历史成本回算失败，稍后再试一下。"), "err");
	        return;
	      }
	      const data = await res.json();
	      setStatus(
	        "costStatsStatus",
	        "已回算 " + tokenNumber(data.updated_messages) + " 条，新增估算成本 " + moneyNumber(data.estimated_cost_added) + "。",
	        "ok"
	      );
	      await loadCostStats();
	      await loadTokenStats();
	      if ($("tokenActivityDialog").classList.contains("show")) await loadTokenActivity();
	    }

	    function closeTokenActivity() {
	      $("tokenActivityDialog").classList.remove("show");
	      setDialogOpenState();
	    }

	    async function openTokenActivity() {
	      $("tokenActivityDialog").classList.add("show");
	      setDialogOpenState();
	      await loadTokenActivity();
	    }

	    async function loadTokenActivity() {
	      setStatus("tokenActivityStatus", "正在加载 Token Activity...", "");
	      const res = await api("/api/token-activity");
	      if (!res.ok) {
	        setStatus("tokenActivityStatus", await readError(res, "Token Activity 加载失败，稍后再试一下。"), "err");
	        return;
	      }
	      state.tokenActivity = await res.json();
	      renderTokenActivity();
	      setStatus("tokenActivityStatus", "");
	    }

	    function tokenActivityLevel(tokens) {
	      const value = Number(tokens || 0);
	      if (value >= 50000) return 4;
	      if (value >= 10000) return 3;
	      if (value >= 1000) return 2;
	      if (value >= 100) return 1;
	      return 0;
	    }

	    function renderTokenActivity() {
	      const data = state.tokenActivity || {};
	      const summary = data.summary || {};
	      const grid = $("activitySummaryGrid");
	      if (grid) {
	        const cards = [
	          ["累计 Token", tokenNumber(summary.total_tokens)],
	          ["累计请求", tokenNumber(summary.request_count)],
	          ["最长连续", tokenNumber(summary.longest_streak) + " 天"],
	          ["连续登录", tokenNumber(summary.current_streak) + " 天"],
	          ["平均每日", tokenNumber(summary.average_daily_tokens)],
	          ["累计花费", moneyNumber(summary.estimated_cost)]
	        ];
	        grid.innerHTML = cards.map(([label, value]) => (
	          '<div class="activity-summary-card"><span>' + escapeHTML(label) + '</span><strong>' + escapeHTML(value) + '</strong></div>'
	        )).join("");
	      }
	      const heatmap = $("activityHeatmap");
	      if (heatmap) {
	        heatmap.innerHTML = "";
	        for (const day of data.days || []) {
	          const button = document.createElement("button");
	          button.type = "button";
	          button.className = "activity-day level-" + tokenActivityLevel(day.total_tokens);
	          button.title = day.date + "\n请求：" + tokenNumber(day.request_count) + " 次\n输入：" + tokenNumber(day.input_tokens) + "\n输出：" + tokenNumber(day.output_tokens) + "\n总 Token：" + tokenNumber(day.total_tokens);
	          button.addEventListener("click", () => renderActivityDayDetail(day.date));
	          heatmap.appendChild(button);
	        }
	      }
	      renderActivityMonthLabels(data.days || []);
	      renderActivityDayDetail(todayTextFromClient(data.days || []));
	      renderActivityList("activityTopModels", data.top_models || [], "model");
	      renderActivityList("activityTopConversations", data.top_conversations || [], "conversation");
	      renderActivityMeta();
	      queueLucideRefresh();
	    }

	    function renderActivityMonthLabels(days) {
	      const box = $("activityMonthLabels");
	      if (!box) return;
	      const weekCount = Math.max(1, Math.ceil((days || []).length / 7));
	      box.style.setProperty("--activity-weeks", String(weekCount));
	      box.innerHTML = "";
	      if (!days.length) return;
	      const months = [];
	      let currentKey = "";
	      let startIndex = 0;
	      const flushMonth = (endIndex) => {
	        if (!currentKey) return;
	        const [year, month] = currentKey.split("-");
	        const startWeek = Math.floor(startIndex / 7) + 1;
	        const endWeek = Math.floor(Math.max(startIndex, endIndex) / 7) + 1;
	        months.push({
	          label: Number(month) + "月",
	          title: year + "年" + Number(month) + "月",
	          startWeek,
	          span: Math.max(1, endWeek - startWeek + 1)
	        });
	      };
	      days.forEach((day, index) => {
	        const key = String(day.date || "").slice(0, 7);
	        if (!key) return;
	        if (key !== currentKey) {
	          flushMonth(index - 1);
	          currentKey = key;
	          startIndex = index;
	        }
	      });
	      flushMonth(days.length - 1);
	      for (const item of months) {
	        const label = document.createElement("span");
	        label.className = "activity-month-label";
	        label.textContent = item.label;
	        label.title = item.title;
	        label.style.gridColumn = item.startWeek + " / span " + item.span;
	        box.appendChild(label);
	      }
	    }

	    function todayTextFromClient(days) {
	      return days.length ? days[days.length - 1].date : "";
	    }

	    function renderActivityDayDetail(date) {
	      const data = state.tokenActivity || {};
	      const day = (data.days || []).find((item) => item.date === date) || {};
	      const models = data.day_models?.[date] || [];
	      const modelText = models.length
	        ? models.slice(0, 5).map((item) => escapeHTML(item.model_name) + "：" + tokenNumber(item.total_tokens) + " Token").join("<br>")
	        : "当天暂无模型分布。";
	      $("activityDayDetail").innerHTML =
	        '<strong>' + escapeHTML(date || "暂无日期") + '</strong><br>' +
	        '请求：' + tokenNumber(day.request_count) + ' 次 · 输入：' + tokenNumber(day.input_tokens) +
	        ' · 输出：' + tokenNumber(day.output_tokens) + ' · 总 Token：' + tokenNumber(day.total_tokens) +
	        ' · 花费：' + escapeHTML(moneyNumber(day.estimated_cost)) +
	        '<br><br>' + modelText;
	    }

	    function renderActivityList(id, rows, type) {
	      const box = $(id);
	      if (!box) return;
	      if (!rows.length) {
	        box.innerHTML = '<div class="activity-row"><span>暂无记录</span></div>';
	        return;
	      }
	      box.innerHTML = '<div class="activity-list">' + rows.map((item) => {
	        const title = type === "model" ? (item.model_name || "未知模型") : (item.title || "未命名对话");
	        const meta = type === "model"
	          ? tokenNumber(item.request_count) + " 次 · " + tokenNumber(item.total_tokens) + " Token · " + moneyNumber(item.estimated_cost)
	          : tokenNumber(item.request_count) + " 次 · " + tokenNumber(item.total_tokens) + " Token";
	        return '<div class="activity-row"><strong>' + escapeHTML(title) + '</strong><span>' + escapeHTML(meta) + '</span></div>';
	      }).join("") + '</div>';
	    }

	    function renderActivityMeta() {
	      const box = $("activityTopMeta");
	      if (!box) return;
	      box.innerHTML =
	        '<div class="activity-list">' +
	          '<div class="activity-row"><strong>Top5 Agent</strong><span>当前版本还没有独立 Agent 记录。</span></div>' +
	          '<div class="activity-row"><strong>Top5 Prompt</strong><span>提示词点击暂未单独记录，后续可继续接入。</span></div>' +
	        '</div>';
	    }

	    function renderAdminModels(models) {
	      const box = $("adminModelList");
	      box.innerHTML = "";
	      if (!models.length) {
	        box.appendChild(createEmptyState("bot", "暂无模型", "添加一个模型后，家人就可以开始使用 AI槑槑。", { compact: true }));
	        queueLucideRefresh();
	        return;
	      }
      for (const model of models) {
        const row = document.createElement("div");
        row.className = "model-row";
        const info = document.createElement("div");
        info.innerHTML = `<strong></strong><span></span>`;
        info.querySelector("strong").textContent = model.name + (model.enabled ? "" : "（停用）");
        const costText = model.cost_enabled ? (" · 成本 " + model.input_price_per_million + "/" + model.output_price_per_million + " 元/百万") : " · 未计成本";
        info.querySelector("span").textContent = model.model
          + (model.supports_vision ? " · 支持图片理解" : "")
          + (model.supports_native_web_search ? " · 百炼原生联网" : "")
          + " · " + model.base_url
          + (model.has_api_key ? " · Key 已保存" : " · 未配置 Key")
          + costText;
	        const actions = document.createElement("div");
	        actions.className = "library-actions";
	        const edit = createIconButton("pencil", "编辑", { fallback: "✎" });
	        edit.addEventListener("click", () => fillModelForm(model));
	        const del = createIconButton("trash-2", "删除", { danger: true, fallback: "删" });
	        del.addEventListener("click", () => deleteModel(model.id));
        actions.append(edit, del);
        row.append(info, actions);
        box.appendChild(row);
      }
    }

	    function renderModelKeys(models) {
	      const box = $("modelKeyList");
	      if (!box) return;
	      box.innerHTML = "";
	      if (!hasAdminAccess()) {
	        box.appendChild(createEmptyState("key-round", "需要管理员权限", "管理员账号或管理密钥可维护模型 API Key。", { compact: true }));
	        queueLucideRefresh();
	        return;
	      }
	      if (!models.length) {
	        box.appendChild(createEmptyState("key-round", "暂无模型 Key", "先在模型管理里添加模型，再回到这里配置 Key。", { compact: true }));
	        queueLucideRefresh();
	        return;
	      }
	      const list = document.createElement("div");
	      list.className = "admin-key-list";
	      for (const model of models) {
	        const card = document.createElement("article");
	        card.className = "admin-key-card";
	        const title = document.createElement("div");
	        title.className = "admin-key-title";
	        title.innerHTML = iconMarkup("bot") + '<strong></strong>';
	        title.querySelector("strong").textContent = model.name + (model.has_api_key ? " · Key 已保存" : " · 未配置 Key");
	        const desc = document.createElement("p");
	        desc.textContent = [model.provider, model.model, model.base_url].filter(Boolean).join(" · ");
	        const row = document.createElement("div");
	        row.className = "admin-key-row";
	        const label = document.createElement("label");
	        label.textContent = "API Key";
	        const input = document.createElement("input");
	        input.type = "password";
	        input.autocomplete = "off";
	        input.placeholder = model.has_api_key ? "已保存，留空保持原值" : "请输入 API Key";
	        label.appendChild(input);
	        const save = createIconButton("save", "保存", { primary: true });
	        save.addEventListener("click", () => saveModelKey(model.id, input, false));
	        const clear = createIconButton("eraser", "清空");
	        clear.addEventListener("click", () => saveModelKey(model.id, input, true));
	        row.append(label, save, clear);
	        card.append(title, desc, row);
	        list.appendChild(card);
	      }
	      box.appendChild(list);
	      queueLucideRefresh();
	    }

	    async function saveModelKey(modelId, input, clearKey = false) {
	      const model = state.adminModels.find((item) => item.id === modelId);
	      if (!model) return;
	      if (!clearKey && !input.value.trim()) {
	        setStatus("adminStatus", "请输入要保存的模型 API Key。", "err");
	        return;
	      }
	      const body = {
	        name: model.name || "",
	        provider: model.provider || "",
	        base_url: model.base_url || "",
	        model: model.model || "",
	        api_key: clearKey ? "" : input.value.trim(),
	        clear_api_key: clearKey,
	        system_prompt: model.system_prompt || "",
	        enabled: Boolean(model.enabled),
	        supports_vision: Boolean(model.supports_vision),
	        supports_native_web_search: Boolean(model.supports_native_web_search)
	      };
	      const res = await adminApi(`/api/admin/models/${modelId}`, {
	        method: "PUT",
	        body: JSON.stringify(body)
	      });
	      if (!res.ok) {
	        setStatus("adminStatus", await readError(res, "模型 Key 保存失败，稍后再试一下。"), "err");
	        return;
	      }
	      input.value = "";
	      setStatus("adminStatus", clearKey ? "模型 Key 已清空" : "模型 Key 已保存", "ok");
	      await loadAdminModels();
	      await loadModels();
	    }

    function fillModelForm(model) {
      $("editingModelId").value = model.id;
      $("modelName").value = model.name || "";
      $("provider").value = model.provider || "";
      $("baseUrl").value = model.base_url || "";
      $("modelCode").value = model.model || "";
      $("apiKey").value = "";
      $("apiKey").placeholder = model.has_api_key ? "已保存，留空保持原值" : "请输入 API Key";
      $("systemPrompt").value = model.system_prompt || "";
      $("enabled").value = model.enabled ? "1" : "0";
      $("supportsVision").value = model.supports_vision ? "1" : "0";
      $("supportsNativeWebSearch").value = model.supports_native_web_search ? "1" : "0";
      $("inputPricePerMillion").value = model.input_price_per_million || "";
      $("outputPricePerMillion").value = model.output_price_per_million || "";
      $("costEnabled").value = model.cost_enabled ? "1" : "0";
      $("costNote").value = model.cost_note || "";
      syncCostEnabledFromPrices();
      setStatus("modelStatus", "正在编辑：" + model.name, "");
    }

    function syncCostEnabledFromPrices() {
      const inputPrice = Number($("inputPricePerMillion").value || 0);
      const outputPrice = Number($("outputPricePerMillion").value || 0);
      if (inputPrice > 0 || outputPrice > 0) $("costEnabled").value = "1";
    }

    function resetModelForm() {
      for (const id of ["editingModelId","modelName","provider","baseUrl","modelCode","apiKey","systemPrompt","inputPricePerMillion","outputPricePerMillion","costNote"]) $(id).value = "";
      $("enabled").value = "1";
      $("supportsVision").value = "0";
      $("supportsNativeWebSearch").value = "0";
      $("costEnabled").value = "0";
      $("apiKey").placeholder = "留空则保持原值";
      setStatus("modelStatus", "");
    }

    async function saveModel() {
      const id = $("editingModelId").value;
      const body = {
        name: $("modelName").value.trim(),
        provider: $("provider").value.trim(),
        base_url: $("baseUrl").value.trim(),
        model: $("modelCode").value.trim(),
        api_key: $("apiKey").value.trim(),
        system_prompt: $("systemPrompt").value.trim(),
        enabled: $("enabled").value === "1",
        supports_vision: $("supportsVision").value === "1",
        supports_native_web_search: $("supportsNativeWebSearch").value === "1",
        input_price_per_million: Number($("inputPricePerMillion").value || 0),
        output_price_per_million: Number($("outputPricePerMillion").value || 0),
        cost_enabled: $("costEnabled").value === "1" || Number($("inputPricePerMillion").value || 0) > 0 || Number($("outputPricePerMillion").value || 0) > 0,
        cost_note: $("costNote").value.trim()
      };
      const res = await adminApi(id ? `/api/admin/models/${id}` : "/api/admin/models", {
        method: id ? "PUT" : "POST",
        body: JSON.stringify(body)
      });
      if (!res.ok) {
        setStatus("modelStatus", await readError(res, "模型保存失败，请检查名称、地址和模型 ID。"), "err");
        return;
      }
      resetModelForm();
      setStatus("modelStatus", "模型已保存", "ok");
      await loadAdminModels();
      await loadModels();
    }

    async function deleteModel(id) {
      const ok = await confirmAction({
        title: "删除模型",
        message: "确定删除这个模型吗？已有对话会保留，关联中的模型会改为停用。",
        confirmText: "删除",
        danger: true
      });
      if (!ok) return;
      const res = await adminApi(`/api/admin/models/${id}`, { method: "DELETE" });
      if (!res.ok) {
        setStatus("modelStatus", await readError(res, "删除模型失败，稍后再试一下。"), "err");
        return;
      }
      await loadAdminModels();
      await loadModels();
    }

	    async function changePassword() {
	      const password = $("familyPassword").value;
	      const res = await adminApi("/api/admin/password", {
	        method: "POST",
	        body: JSON.stringify({ password })
      });
      if (!res.ok) {
        setStatus("adminStatus", await readError(res, "密码修改失败，请确认新密码至少 8 位。"), "err");
        return;
      }
	      $("familyPassword").value = "";
	      setStatus("adminStatus", "登录密码已修改，需要重新登录", "ok");
	    }

	    async function loadAdminUsers() {
	      const box = $("accountList");
	      if (!hasAdminAccess()) {
	        state.adminUsers = [];
	        box.innerHTML = '<div class="status">管理员账号或管理密钥可管理家庭账号。</div>';
	        setStatus("accountStatus", "");
	        renderAdminOverview();
	        return;
	      }
	      const res = await adminApi("/api/admin/users");
	      if (!res.ok) {
	        state.adminUsers = [];
	        box.innerHTML = "";
	        setStatus("accountStatus", await readError(res, "账号列表加载失败。"), "err");
	        renderAdminOverview();
	        return;
	      }
	      const data = await res.json();
	      state.adminUsers = data.users || [];
	      renderAdminUsers(state.adminUsers);
	      renderAdminOverview();
	      setStatus("accountStatus", "");
	    }

	    function renderAdminUsers(users) {
	      const box = $("accountList");
	      box.innerHTML = "";
	      if (!users.length) {
	        box.appendChild(createEmptyState("users", "暂无账号", "新增家庭账号后，每个人会看到自己的会话和收藏。", { compact: true }));
	        queueLucideRefresh();
	        return;
	      }
	      for (const user of users) {
	        const row = document.createElement("div");
	        row.className = "model-row";
	        const info = document.createElement("div");
	        info.innerHTML = `<strong></strong><span></span>`;
	        info.querySelector("strong").textContent = (user.display_name || user.username) + (user.is_active ? "" : "（已禁用）");
	        info.querySelector("span").textContent = user.username + " · " + (user.role === "admin" ? "管理员" : "家庭成员") + " · " + formatTime(user.created_at);
		        const actions = document.createElement("div");
		        actions.className = "library-actions";
		        const edit = createIconButton("pencil", "编辑", { fallback: "✎" });
		        edit.addEventListener("click", () => fillAccountForm(user));
	        actions.append(edit);
	        row.append(info, actions);
	        box.appendChild(row);
	      }
	      queueLucideRefresh();
	    }

	    function fillAccountForm(user) {
	      $("editingUserId").value = user.id || "";
	      $("accountUsername").value = user.username || "";
	      $("accountUsername").disabled = true;
	      $("accountDisplayName").value = user.display_name || "";
	      $("accountRole").value = user.role || "family";
	      $("accountActive").value = user.is_active ? "1" : "0";
	      $("accountPassword").value = "";
	      $("accountPassword").placeholder = "留空保持原密码";
	      setStatus("accountStatus", "正在编辑：" + (user.display_name || user.username), "");
	    }

	    function resetAccountForm() {
	      $("editingUserId").value = "";
	      $("accountUsername").value = "";
	      $("accountUsername").disabled = false;
	      $("accountDisplayName").value = "";
	      $("accountRole").value = "family";
	      $("accountActive").value = "1";
	      $("accountPassword").value = "";
	      $("accountPassword").placeholder = "新增账号必填，编辑时留空保持原密码";
	      setStatus("accountStatus", "");
	    }

	    async function saveAccount() {
	      if (!hasAdminAccess()) {
	        setStatus("accountStatus", "需要管理员账号或管理密钥。", "err");
	        return;
	      }
	      const id = $("editingUserId").value;
	      const body = {
	        username: $("accountUsername").value.trim(),
	        display_name: $("accountDisplayName").value.trim(),
	        role: $("accountRole").value,
	        is_active: $("accountActive").value === "1",
	        password: $("accountPassword").value
	      };
	      const res = await adminApi(id ? `/api/admin/users/${id}` : "/api/admin/users", {
	        method: id ? "PUT" : "POST",
	        body: JSON.stringify(body)
	      });
	      if (!res.ok) {
	        setStatus("accountStatus", await readError(res, "账号保存失败，请检查账号和密码。"), "err");
	        return;
	      }
	      resetAccountForm();
	      await loadAdminUsers();
	      setStatus("accountStatus", "账号已保存", "ok");
	    }

	function applySidebarToolsState(open, options = {}) {
	  const popover = $("sidebarToolsPopover");
	  const trigger = $("toggleSidebarTools");
	  state.sidebarToolsOpen = Boolean(open);
	  popover?.classList.toggle("show", state.sidebarToolsOpen);
	  trigger?.setAttribute("aria-expanded", state.sidebarToolsOpen ? "true" : "false");
	  if (options.save !== false && state.user) {
	    setUserStorage("sidebar_tools_open", state.sidebarToolsOpen ? "1" : "0");
	  }
	  if (state.sidebarToolsOpen) queueLucideRefresh();
	}

	function openSidebarTools() {
	  applySidebarToolsState(true);
	}

	function closeSidebarTools(options = {}) {
	  applySidebarToolsState(false, options);
	}

	function toggleSidebarTools(event) {
	  event?.stopPropagation();
	  applySidebarToolsState(!state.sidebarToolsOpen);
	}

	function handleSidebarToolsOutsidePointer(event) {
	  if (!state.sidebarToolsOpen) return;
	  if ($("sidebarToolsPopover")?.contains(event.target) || $("toggleSidebarTools")?.contains(event.target)) return;
	  closeSidebarTools();
	}

	    function openSidebar() {
      $("sidebar").classList.add("show");
      $("drawerMask").classList.add("show");
      document.body.classList.add("sidebar-open");
	  closeDesktopPetMenu();
    }
    function closeSidebar() {
      $("sidebar").classList.remove("show");
      document.body.classList.remove("sidebar-open");
      if (!$("settingsDrawer").classList.contains("show")) $("drawerMask").classList.remove("show");
	  schedulePetPositionCorrection();
    }
    function autosizePrompt() {
      const el = $("prompt");
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 180) + "px";
      syncComposerLayout();
    }
    function insertNewlineAtCursor() {
      const el = $("prompt");
      const start = typeof el.selectionStart === "number" ? el.selectionStart : el.value.length;
      const end = typeof el.selectionEnd === "number" ? el.selectionEnd : el.value.length;
      el.setRangeText("\n", start, end, "end");
      autosizePrompt();
      el.focus();
    }

    $("globalSearchShortcut").textContent = globalSearchShortcutText();
    $("loginForm").addEventListener("submit", login);
    $("logout").addEventListener("click", logout);
    $("newChat").addEventListener("click", () => {
      newConversation().catch((err) => setStatus("chatStatus", friendlyError(err, "新建对话失败，稍后再试一下。"), "err"));
    });
    $("openGlobalSearch").addEventListener("click", openGlobalSearch);
    $("globalSearchDialog").addEventListener("click", (event) => {
      if (event.target === $("globalSearchDialog")) closeGlobalSearch();
    });
    $("globalSearchInput").addEventListener("input", scheduleGlobalSearch);
    $("globalSearchInput").addEventListener("keydown", handleGlobalSearchKeydown);
    $("modelPickerButton").addEventListener("click", openModelPicker);
    $("modelPickerDialog").addEventListener("click", (event) => {
      if (event.target === $("modelPickerDialog")) closeModelPicker();
    });
    $("modelPickerSearch").addEventListener("input", handleModelPickerSearchInput);
    $("modelPickerSearch").addEventListener("keydown", handleModelPickerKeydown);
    $("openPrompts").addEventListener("click", openPromptLibrary);
    document.querySelectorAll(".prompt-chip[data-prompt-text]").forEach((button) => {
      button.addEventListener("click", () => insertPromptText(button.dataset.promptText || ""));
    });
    $("openPromptLibrary").addEventListener("click", openPromptLibrary);
    $("closePromptDialog").addEventListener("click", closePromptLibrary);
	    $("promptDialog").addEventListener("click", (event) => {
	      if (event.target === $("promptDialog")) closePromptLibrary();
	    });
	    $("openProfiles").addEventListener("click", openProfiles);
	    $("closeProfileDialog").addEventListener("click", closeProfiles);
	    $("profileDialog").addEventListener("click", (event) => {
	      if (event.target === $("profileDialog")) closeProfiles();
	    });
	    $("saveProfile").addEventListener("click", saveProfile);
	    $("resetProfile").addEventListener("click", resetProfileForm);
	    $("profileTitle").addEventListener("input", updateProfileEditorMeta);
	    $("profileContent").addEventListener("input", updateProfileEditorMeta);
	    $("profileStatus").addEventListener("click", toggleProfilePopover);
	    $("disableProfileForConversation").addEventListener("change", () => setProfileDisabledForCurrentConversation($("disableProfileForConversation").checked));
	    document.addEventListener("click", handleProfileOutsideClick);
	    document.querySelectorAll("[data-version-trigger]").forEach((button) => {
	      button.addEventListener("click", (event) => openChangelog(event, { full: false }));
	    });
	    $("closeChangelog").addEventListener("click", closeChangelog);
	    $("openFullChangelog").addEventListener("click", (event) => openChangelog(event, { full: true }));
	    document.addEventListener("click", handleChangelogOutsideClick);
	    $("savePromptTemplate").addEventListener("click", savePromptTemplate);
    $("resetPromptTemplate").addEventListener("click", resetPromptForm);
	    $("openFavorites").addEventListener("click", openFavorites);
	    $("closeFavoriteDialog").addEventListener("click", closeFavorites);
	    $("favoriteDialog").addEventListener("click", (event) => {
	      if (event.target === $("favoriteDialog")) closeFavorites();
	    });
	    $("openMediaAnalysis").addEventListener("click", openMediaAnalysis);
	    $("closeMediaDialog").addEventListener("click", closeMediaAnalysis);
	    $("mediaDialog").addEventListener("click", (event) => {
	      if (event.target === $("mediaDialog")) closeMediaAnalysis();
	    });
	    $("openTokenActivity").addEventListener("click", openTokenActivity);
	    $("toggleSidebarTools").addEventListener("click", toggleSidebarTools);
	    $("sidebarToolsPopover").addEventListener("click", (event) => {
	      if (event.target.closest("button")) closeSidebarTools();
	    });
	    document.addEventListener("pointerdown", handleSidebarToolsOutsidePointer);
	    $("closeTokenActivity").addEventListener("click", closeTokenActivity);
	    $("tokenActivityDialog").addEventListener("click", (event) => {
	      if (event.target === $("tokenActivityDialog")) closeTokenActivity();
	    });
	    $("uploadMediaTask").addEventListener("click", uploadMediaTask);
		    $("refreshConversations").addEventListener("click", loadConversations);
	    $("sidebarResizer").addEventListener("pointerdown", startSidebarResize);
	    $("sidebarResizer").addEventListener("mousedown", startSidebarResize);
	    $("sidebarResizer").addEventListener("dblclick", () => applySidebarWidth(sidebarWidthDefaults.value, true));
		    $("send").addEventListener("click", () => {
	      if (state.sending) stopGeneration();
	      else sendMessage();
	    });
	    $("attachImage").addEventListener("click", () => {
	      if (!selectedModelSupportsVision()) {
	        setStatus("chatStatus", "当前模型不支持图片理解，请切换支持图片的模型。", "err");
	        return;
	      }
	      $("imageInput").click();
	    });
	    $("imageInput").addEventListener("change", (event) => {
	      handleImageFiles(event.target.files).catch((err) => setStatus("chatStatus", friendlyError(err, "图片上传失败。"), "err"));
	    });
	    $("insertNewline").addEventListener("click", insertNewlineAtCursor);
	    $("deleteConversation").addEventListener("click", deleteCurrentConversation);
	    $("messages").addEventListener("pointerdown", beginChatTextSelection);
	    $("messages").addEventListener("scroll", handleMessagesScroll, { passive: true });
	    document.addEventListener("pointerup", endChatTextSelection);
	    document.addEventListener("pointercancel", endChatTextSelection);
	    document.addEventListener("selectionchange", handleSelectionChange);
	    $("selectionToolbar").addEventListener("pointerdown", (event) => event.preventDefault());
	    $("quoteSelection").addEventListener("click", addActiveSelectionQuote);
	    $("discussSelection").addEventListener("click", () => createSideDiscussionFromSelection().catch((err) => setStatus("chatStatus", friendlyError(err, "创建侧边讨论失败。"), "err")));
	    $("copySelection").addEventListener("click", copyActiveSelection);
	    $("reopenSideDiscussion").addEventListener("click", () => {
	      const discussion = state.sideDiscussions[0];
	      if (discussion) openSideDiscussion(discussion.id);
	    });
	    $("closeSideDiscussion").addEventListener("click", closeSideDiscussion);
	    $("quoteSideAnswer").addEventListener("click", quoteLastSideAnswer);
	    $("saveSideConversation").addEventListener("click", saveSideDiscussionAsConversation);
	    $("sideDiscussionSend").addEventListener("click", sendSideDiscussionMessage);
	    $("sideDiscussionPrompt").addEventListener("input", () => {
	      const field = $("sideDiscussionPrompt");
	      field.style.height = "auto";
	      field.style.height = Math.min(160, field.scrollHeight) + "px";
	    });
	    $("sideDiscussionPrompt").addEventListener("keydown", (event) => {
	      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
	        event.preventDefault();
	        sendSideDiscussionMessage();
	      }
	    });
	    $("sideDiscussionResizer").addEventListener("pointerdown", handleSideDiscussionResizePointerDown);
	    $("sideDiscussionResizer").addEventListener("pointermove", handleSideDiscussionResizePointerMove);
	    $("sideDiscussionResizer").addEventListener("pointerup", handleSideDiscussionResizePointerUp);
	    $("sideDiscussionResizer").addEventListener("pointercancel", handleSideDiscussionResizePointerUp);
	    $("sideDiscussionResizer").addEventListener("dblclick", () => applySideDiscussionWidth(440, { save: true }));
	    document.addEventListener("pointerdown", handleSelectionToolbarOutsidePointer);
	    document.addEventListener("pointerdown", handleMessageQuoteOutsidePointer);
	    document.querySelector(".composer")?.addEventListener("selectstart", handleComposerSelectStart);
	    $("scrollLatest").addEventListener("selectstart", (event) => event.preventDefault());
	    $("conversationMinimap").addEventListener("pointerenter", expandConversationMinimap);
	    $("conversationMinimap").addEventListener("pointerleave", scheduleCollapseConversationMinimap);
	    $("conversationMinimap").addEventListener("focusin", expandConversationMinimap);
	    $("conversationMinimap").addEventListener("focusout", scheduleCollapseConversationMinimap);
	    document.addEventListener("pointerdown", handleMinimapOutsidePointer);
    $("scrollLatest").addEventListener("click", () => scrollToLatest("smooth"));
	    $("prompt").addEventListener("input", handlePromptInput);
	    $("prompt").addEventListener("focus", handlePromptFocus);
	    $("refreshForUpdate").addEventListener("click", refreshForVersionUpdate);
	    $("snoozeVersionUpdate").addEventListener("click", snoozeVersionUpdate);
	    $("closeVersionUpdate").addEventListener("click", snoozeVersionUpdate);
	    $("openInterfaceSettings").addEventListener("click", toggleInterfaceSettings);
	    $("closeInterfaceSettings").addEventListener("click", closeInterfaceSettings);
	    $("interfacePopover").addEventListener("click", (event) => event.stopPropagation());
	    $("composerOpacityRange").addEventListener("input", () => {
	      applyInterfaceSettings({
	        opacity: $("composerOpacityRange").value,
	        blur: $("composerBlurRange").value
	      });
	    });
	    $("composerBlurRange").addEventListener("input", () => {
	      applyInterfaceSettings({
	        opacity: $("composerOpacityRange").value,
	        blur: $("composerBlurRange").value
	      });
	    });
	    $("resetInterfaceSettings").addEventListener("click", resetInterfaceSettings);
	    $("desktopPetHandle").addEventListener("pointerdown", startDesktopPetDrag);
	    $("desktopPetHandle").addEventListener("pointermove", moveDesktopPet);
	    $("desktopPetHandle").addEventListener("pointerup", finishDesktopPetDrag);
	    $("desktopPetHandle").addEventListener("pointercancel", finishDesktopPetDrag);
	    $("desktopPetHandle").addEventListener("click", handleDesktopPetClick);
	    $("desktopPetMenu").addEventListener("click", handleDesktopPetAction);
	    $("petEnabledToggle").addEventListener("change", () => {
	      applyDesktopPetSettings({ enabled: $("petEnabledToggle").checked });
	    });
	    $("petAnimationToggle").addEventListener("change", () => {
	      applyDesktopPetSettings({ animation: $("petAnimationToggle").checked });
	    });
	    $("resetPetPosition").addEventListener("click", resetDesktopPetPosition);
	    document.addEventListener("pointerdown", handleDesktopPetOutsidePointer);
	    document.addEventListener("click", handleInterfaceOutsideClick);
	    document.addEventListener("keydown", (event) => {
	      const key = String(event.key || "").toLowerCase();
	      if ((event.metaKey || event.ctrlKey) && key === "k") {
	        event.preventDefault();
	        openGlobalSearch();
	        return;
	      }
	      if (event.key === "Escape") {
	        hideSelectionToolbar({ clearSelection: true });
	        if (!$("sideDiscussionPanel").hidden) closeSideDiscussion();
	        closeMessageQuotePreviews();
	        if ($("versionUpdateToast")?.classList.contains("show")) snoozeVersionUpdate();
	        closeModelPicker();
	        closeGlobalSearch();
	        closeChangelog();
	        closeProfilePopover();
	        closeProfiles();
	        closeTokenActivity();
	        closeInterfaceSettings();
	        closeDesktopPetMenu();
	        closeSidebarTools();
	        closeImagePreview();
	        closeSettings();
	      }
	    });
	    $("prompt").addEventListener("compositionstart", () => {
	      state.isComposing = true;
	    });
    $("prompt").addEventListener("compositionend", () => {
      state.isComposing = false;
      state.lastCompositionEndAt = Date.now();
    });
    $("prompt").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        if (isImeEnter(event)) {
          if (!event.isComposing && !state.isComposing && event.keyCode !== 229) {
            event.preventDefault();
          }
          return;
        }
        event.preventDefault();
        if (!state.sending) sendMessage();
      }
    });
	    $("themeToggle").addEventListener("click", toggleTheme);
	    $("modelSelect").addEventListener("change", () => {
	      syncModelPickerButton();
	      renderModelPickerList();
	      updateVisionUI();
	      if (state.attachments.length && !selectedModelSupportsVision()) {
	        setStatus("chatStatus", "当前模型不支持图片理解，请切换支持图片的模型。", "err");
	      }
	    });
	    $("accentToggle").addEventListener("click", openAccentDialog);
    $("fontSizeToggle").addEventListener("click", toggleFontSize);
    $("closeAccentDialog").addEventListener("click", closeAccentDialog);
    $("accentDialog").addEventListener("click", (event) => {
      if (event.target === $("accentDialog")) closeAccentDialog();
    });
    $("applyCustomAccent").addEventListener("click", applyCustomAccent);
    $("resetAccent").addEventListener("click", resetAccent);
    $("openSettings").addEventListener("click", openSettings);
    $("closeSettings").addEventListener("click", closeSettings);
    $("drawerMask").addEventListener("click", () => { closeSettings(); closeSidebar(); });
	    document.querySelectorAll(".admin-nav-item[data-admin-section]").forEach((button) => {
	      button.addEventListener("click", () => switchAdminSection(button.dataset.adminSection));
	    });
	    $("saveModel").addEventListener("click", saveModel);
	    $("resetModelForm").addEventListener("click", resetModelForm);
	    $("inputPricePerMillion").addEventListener("input", syncCostEnabledFromPrices);
	    $("outputPricePerMillion").addEventListener("input", syncCostEnabledFromPrices);
		    $("changePassword").addEventListener("click", changePassword);
		    $("saveAccount").addEventListener("click", saveAccount);
		    $("resetAccountForm").addEventListener("click", resetAccountForm);
		    $("adminKey").addEventListener("change", () => {
		      loadAdminOverview();
		      loadAdminModels();
		      loadAdminSearch();
		      loadAdminUsers();
		      loadTokenStats();
		      loadCostStats();
		    });
	    $("tokenStatsQuery").addEventListener("input", scheduleTokenStatsLoad);
	    $("tokenStatsSort").addEventListener("change", loadTokenStats);
	    $("refreshTokenStats").addEventListener("click", loadTokenStats);
	    document.querySelectorAll(".token-tab[data-token-tab]").forEach((button) => {
	      button.addEventListener("click", () => switchTokenStatsTab(button.dataset.tokenTab));
	    });
	    $("modelTokenStatsQuery").addEventListener("input", scheduleTokenStatsLoad);
	    $("modelTokenStatsSort").addEventListener("change", loadTokenStats);
	    $("refreshModelTokenStats").addEventListener("click", loadTokenStats);
	    $("costStatsRange").addEventListener("change", loadCostStats);
	    $("refreshCostStats").addEventListener("click", loadCostStats);
	    $("recalculateCostStats").addEventListener("click", recalculateCostStats);
	    $("openSide").addEventListener("click", openSidebar);
	    $("closeSide").addEventListener("click", closeSidebar);
	    $("webSearchToggle").addEventListener("change", () => {
	      if ((state.searchConfig?.mode || "auto") === "manual") {
		        setUserStorage("aiPlatformWebSearch", $("webSearchToggle").checked ? "1" : "0");
	      }
	    });
	    $("saveSearch").addEventListener("click", () => saveSearchConfig(false));
	    $("saveSearchKey").addEventListener("click", saveSearchKey);
	    $("clearSearchKey").addEventListener("click", () => saveSearchConfig(true));
		    $("closeCopyDialog").addEventListener("click", closeManualCopy);
		    $("copyDialog").addEventListener("click", (event) => {
		      if (event.target === $("copyDialog")) closeManualCopy();
		    });
	    $("closeImagePreview").addEventListener("click", closeImagePreview);
	    $("imagePreviewDialog").addEventListener("click", (event) => {
	      if (event.target === $("imagePreviewDialog")) closeImagePreview();
	    });
	    $("selectManualCopy").addEventListener("click", () => {
	      $("manualCopyText").focus();
	      $("manualCopyText").select();
	    });
	    $("retryManualCopy").addEventListener("click", async () => {
	      const text = $("manualCopyText").value;
	      if (await writeClipboard(text) || fallbackCopy(text)) {
	        closeManualCopy();
	        setStatus("chatStatus", "已复制", "ok");
	      }
	    });
			    syncViewportHeight();
			    observeComposerLayout();
			    window.addEventListener("resize", syncViewportHeight, { passive: true });
			    window.addEventListener("resize", syncComposerLayout, { passive: true });
			    window.addEventListener("resize", () => applySidebarWidth(state.sidebarWidth, true), { passive: true });
			    window.addEventListener("resize", updateChatUsage, { passive: true });
			    window.addEventListener("resize", positionModelPickerPopover, { passive: true });
			    window.addEventListener("resize", positionChangelogPanel, { passive: true });
			    window.addEventListener("resize", () => queueMarkdownOverflowRefresh($("messages")), { passive: true });
			    window.addEventListener("resize", queueConversationMinimap, { passive: true });
			    window.addEventListener("resize", () => schedulePetPositionCorrection({ save: true }), { passive: true });
			    window.addEventListener("resize", hideSelectionToolbar, { passive: true });
			    window.addEventListener("resize", handleSideDiscussionViewportChange, { passive: true });
		    window.addEventListener("blur", endChatTextSelection);
		    window.addEventListener("pagehide", saveCurrentDraft);
		    window.visualViewport?.addEventListener("resize", syncViewportHeight, { passive: true });
	    window.visualViewport?.addEventListener("resize", () => schedulePetPositionCorrection({ save: true }), { passive: true });
	    window.visualViewport?.addEventListener("scroll", syncViewportHeight, { passive: true });
	    window.visualViewport?.addEventListener("scroll", schedulePetPositionCorrection, { passive: true });

	    initializeVersionMonitoring();
	    queueLucideRefresh();
	    bootstrap();
