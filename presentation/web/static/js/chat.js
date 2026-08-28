// 对话界面逻辑（选项卡1 + 选项卡2）
(function () {
  // 当前项目全部幻灯片缓存（最新全量），供卡片左右导航补全
  var _projectSlidesCache = null;
  var _streamingSlides = [];  // 流式渲染全局骨架（来自 SSE slides_meta）

  var _agentState = {
    busy: false,              // 发送按钮禁用标志
    runningTab: null,         // 当前运行智能体所在 tab（"content"/"ppt"），决定哪个按钮显示停止
    stopping: false,          // 已请求停止：按钮显示"正在停止"且禁用，防止重复点击
    pollTimer: null,          // 轮询定时器
    runningProjectId: null,   // 当前正在执行的 project_id，用于会话切换时防止泄漏
    sseReader: null,          // 当前活动的 SSE 流 reader，切会话时 cancel 停止旧流
  };
  var _interventionWrap = null;  // 人工介入时保存当前 agent 气泡，恢复接口复用（避免新气泡）

  function _setInputDisabled(disabled) {
    $("#chatInput").disabled = disabled;
    $("#pptInput").disabled = disabled;
    // 仅当前运行 tab 的发送按钮切换为可点击的"停止"，非运行 tab 按禁用状态保持"发送"
    var runningTab = _agentState.runningTab;
    [["#chatSendBtn", "content"], ["#pptSendBtn", "ppt"]].forEach(function (pair) {
      var btn = $(pair[0]);
      if (!btn) return;
      if (runningTab === pair[1]) {
        if (_agentState.stopping) {
          // 已请求停止：按钮变为"正在停止"且禁用，防止重复点击
          btn.disabled = true;
          btn.textContent = "⏹ 正在停止...";
        } else {
          btn.disabled = false;
          btn.textContent = "⏹ 停止";
        }
        btn.classList.add("stop-btn");
      } else {
        btn.disabled = disabled;
        btn.textContent = "发送";
        btn.classList.remove("stop-btn");
      }
    });
    var area1 = $("#chatInput").closest(".chat-input-area");
    var area2 = $("#pptInput").closest(".chat-input-area");
    // 运行 tab 的输入区不加 .disabled（其 pointer-events:none 会挡住停止按钮），仅禁用 textarea
    if (area1) area1.classList.toggle("disabled", disabled && runningTab !== "content");
    if (area2) area2.classList.toggle("disabled", disabled && runningTab !== "ppt");
  }

  async function _checkAgentStatusAndAct(projectId, container) {
    try {
      var status = await api("GET", "/api/ppt/" + projectId + "/agent-status");
      if (status.db_status === "pending" && status.backend_running) {
        // 正在执行中
        _agentState.busy = true;
        _agentState.runningTab = "ppt";
        _agentState.runningProjectId = projectId;
        _setInputDisabled(true);

        // 渲染"执行中"提示
        var pendingWrap = document.createElement("div");
        pendingWrap.className = "message message-agent pending-agent-msg";
        pendingWrap.innerHTML = '<div class="message-avatar message-avatar-agent">🤖</div>' +
          '<div class="message-bubble message-bubble-agent">' +
            '<div class="pending-status">⏳ 智能体正在执行中...</div>' +
          '</div>';
        container.appendChild(pendingWrap);
        container.scrollTop = container.scrollHeight;

        // 有内存快照数据，立即渲染
        if (status.memory) {
          _updatePendingBubble(status.memory, pendingWrap);
        }

        // 开始轮询
        startPolling(projectId, container);
      } else if (status.db_status === "pending") {
        // DB pending 但后端不在跑 → 执行异常
        _agentState.busy = false;
        _agentState.runningTab = null;
        _agentState.stopping = false;
        _agentState.runningProjectId = null;
        _setInputDisabled(false);
        var errorDiv = document.createElement("div");
        errorDiv.className = "message agent-error-msg";
        errorDiv.innerHTML = "<span class='agent-error-text'>❌ 智能体执行异常，请重新发送</span>";
        container.appendChild(errorDiv);
      }
    } catch (e) {
      console.warn("check agent status failed:", e);
      _agentState.busy = false;
      _agentState.runningTab = null;
      _agentState.stopping = false;
      _agentState.runningProjectId = null;
      _setInputDisabled(false);
    }
  }

  function startPolling(projectId, container) {
    _agentState.pollTimer = setInterval(async function () {
      try {
        // 守卫：当前会话已切换，停止轮询并清理
        if (appState.currentProjectId !== projectId) {
          clearInterval(_agentState.pollTimer);
          _agentState.pollTimer = null;
          _agentState.runningProjectId = null;
          _agentState.runningTab = null;
          _agentState.stopping = false;
          return;
        }

        var status = await api("GET", "/api/ppt/" + projectId + "/agent-status");

        if (status.db_status === "pending" && status.backend_running) {
          // 还在执行：用内存全量快照覆盖渲染
          var pendingEl = container.querySelector(".pending-agent-msg");
          if (pendingEl && status.memory) {
            _updatePendingBubble(status.memory, pendingEl);
          }
          return;
        }

        if (status.db_status === "completed") {
          // 停止轮询
          clearInterval(_agentState.pollTimer);
          _agentState.pollTimer = null;
          _agentState.busy = false;
          _agentState.runningTab = null;
          _agentState.stopping = false;
          _agentState.runningProjectId = null;
          _setInputDisabled(false);

          // 最后一次用完整内存数据渲染（捕获轮询间隔内产生的文本/卡片）
          var pendingEl = container.querySelector(".pending-agent-msg");
          if (pendingEl && status.memory) {
            _updatePendingBubble(status.memory, pendingEl);
          }

          // 就地切换 pending 气泡为完成态
          if (pendingEl) {
            pendingEl.classList.remove("pending-agent-msg");
            var bubble = pendingEl.querySelector(".message-bubble");
            if (bubble) {
              var statusEl = bubble.querySelector(".pending-status");
              if (statusEl) statusEl.remove();
              var placeholder = bubble.querySelector(".step-placeholder");
              if (placeholder) placeholder.remove();
              var stepsContainer = bubble.querySelector(".steps-container");
              if (stepsContainer) {
                // 步骤标题同步切换为完成态
                var titleEl = stepsContainer.querySelector(".steps-title");
                if (titleEl) titleEl.textContent = "⚙️ 执行步骤：已执行完成";
                var stepsList = stepsContainer.querySelector(".steps-list");
                if (stepsList) stepsList.hidden = true;
                var toggleBtn = stepsContainer.querySelector(".steps-toggle");
                if (toggleBtn) toggleBtn.textContent = "展开";
              }
              if (!bubble.querySelector(".message-text")) {
                var doneEl = document.createElement("div");
                doneEl.className = "message-text";
                doneEl.textContent = "✅ 完成";
                bubble.appendChild(doneEl);
              }
            }
          }
          // 完成态切换后滚动到底
          container.scrollTop = container.scrollHeight;
        } else if (status.db_status === "stopped") {
          // 用户主动停止：停轮询、恢复输入、pending 气泡切换为"已停止"
          clearInterval(_agentState.pollTimer);
          _agentState.pollTimer = null;
          _agentState.busy = false;
          _agentState.runningTab = null;
          _agentState.stopping = false;
          _agentState.runningProjectId = null;
          _setInputDisabled(false);
          var pendingEl = container.querySelector(".pending-agent-msg");
          if (pendingEl) {
            pendingEl.classList.remove("pending-agent-msg");
            var bubble = pendingEl.querySelector(".message-bubble");
            if (bubble) {
              var statusEl = bubble.querySelector(".pending-status");
              if (statusEl) statusEl.remove();
              var placeholder = bubble.querySelector(".step-placeholder");
              if (placeholder) placeholder.remove();
              var stepsContainer = bubble.querySelector(".steps-container");
              if (stepsContainer) {
                var titleEl = stepsContainer.querySelector(".steps-title");
                if (titleEl) titleEl.textContent = "⚙️ 执行步骤：已停止";
                var stepsList = stepsContainer.querySelector(".steps-list");
                if (stepsList) stepsList.hidden = true;
                var toggleBtn = stepsContainer.querySelector(".steps-toggle");
                if (toggleBtn) toggleBtn.textContent = "展开";
              }
              if (!bubble.querySelector(".message-text")) {
                var doneEl = document.createElement("div");
                doneEl.className = "message-text";
                doneEl.textContent = "⏹ 已停止";
                bubble.appendChild(doneEl);
              }
            }
          }
          container.scrollTop = container.scrollHeight;
        } else if (status.db_status === "pending" && !status.backend_running) {
          clearInterval(_agentState.pollTimer);
          _agentState.pollTimer = null;
          _agentState.busy = false;
          _agentState.runningTab = null;
          _agentState.stopping = false;
          _agentState.runningProjectId = null;
          _setInputDisabled(false);
          var el = document.querySelector(".pending-agent-msg");
          if (el) {
            var statusEl = el.querySelector(".pending-status");
            if (statusEl) {
              statusEl.innerHTML = "❌ 智能体执行异常，请重新发送";
              statusEl.className = "agent-error-text";
            }
          }
        } else if (status.db_status === "error") {
          clearInterval(_agentState.pollTimer);
          _agentState.pollTimer = null;
          _agentState.busy = false;
          _agentState.runningTab = null;
          _agentState.stopping = false;
          _agentState.runningProjectId = null;
          _setInputDisabled(false);
          var el = document.querySelector(".pending-agent-msg");
          if (el) {
            var statusEl = el.querySelector(".pending-status");
            if (statusEl) {
              statusEl.innerHTML = "❌ 智能体执行失败";
              statusEl.className = "agent-error-text";
            }
          }
        }
      } catch (e) {
        console.warn("poll agent status failed:", e);
      }
    }, 3000);
  }

  function _updatePendingBubble(memory, pendingWrap) {
    var bubble = pendingWrap.querySelector(".message-bubble");
    if (!bubble || !memory) return;

    // 首次渲染：建立基本 DOM 结构
    if (!bubble.querySelector(".pending-status")) {
      bubble.innerHTML = '<div class="pending-status">⏳ 智能体正在执行中...</div>';
    }

    // 增量更新步骤（格式与 SSE 一致：编号 + 正在XXX + done 子行）
    var steps = memory.steps || [];
    if (steps.length > 0) {
      var stepsContainer = bubble.querySelector(".steps-container");
      if (!stepsContainer) {
        stepsContainer = document.createElement("div");
        stepsContainer.className = "steps-container";
        stepsContainer.innerHTML = '<div class="steps-header"><span class="steps-title">⚙️ 执行步骤：正在执行中</span>' +
          '<button class="btn steps-toggle">折叠</button></div>' +
          '<div class="steps-list" style="margin-top:8px;"><div class="step-item step-placeholder">正在处理中...</div></div>';
        bubble.appendChild(stepsContainer);
        // 绑定折叠按钮
        var _toggleBtn = stepsContainer.querySelector(".steps-toggle");
        var _list = stepsContainer.querySelector(".steps-list");
        _toggleBtn.addEventListener("click", function () {
          var isHidden = _list.hidden;
          _list.hidden = !isHidden;
          _toggleBtn.textContent = isHidden ? "折叠" : "展开";
        });
      }
      var stepsList = stepsContainer.querySelector(".steps-list");
      var existingItems = stepsList.querySelectorAll(".step-item:not(.step-placeholder)");
      var existingCount = existingItems.length;

      // 首步时移除占位符（与 SSE 一致：第一个 step 事件清 placeholder）
      if (existingCount === 0) {
        var placeholder = stepsList.querySelector(".step-placeholder");
        if (placeholder) placeholder.remove();
      }

      // 只添加新增的步骤
      for (var i = existingCount; i < steps.length; i++) {
        var s = steps[i];
        var item = document.createElement("div");
        item.className = "step-item";
        // 与 SSE 格式一致：编号 + 正在 + 步骤名
        item.textContent = (i + 1) + ". 正在" + escapeHtml(s.name || "");
        stepsList.appendChild(item);
        // 如果已有 done，立即渲染子行
        if (s.done) {
          var sub = document.createElement("div");
          sub.className = "step-done";
          sub.textContent = s.done;
          item.appendChild(sub);
        }
      }

      // 更新已有步骤的 done（后续轮询可能新增 done 标记）
      for (var j = 0; j < Math.min(existingItems.length, steps.length); j++) {
        var memStep = steps[j];
        var existingItem = existingItems[j];
        if (memStep && memStep.done && !existingItem.querySelector(".step-done")) {
          var sub = document.createElement("div");
          sub.className = "step-done";
          sub.textContent = memStep.done;
          existingItem.appendChild(sub);
        }
      }
    }

    // 增量更新文本
    if (memory.text) {
      var textEl = bubble.querySelector(".message-text");
      if (!textEl) {
        textEl = document.createElement("div");
        textEl.className = "message-text";
        textEl.style.marginTop = "8px";
        bubble.appendChild(textEl);
      }
      textEl.textContent = memory.text;
    }

    // 渲染卡片（按生成顺序追加到末尾；用 pendingWrap 上的集合去重，防重复创建）
    if (memory.cards && memory.cards.length > 0) {
      var cardParent = pendingWrap.parentNode;
      if (!pendingWrap._renderedSlides) pendingWrap._renderedSlides = {};
      memory.cards.forEach(function (card) {
        var si = card.slide_index;
        if (si == null) return;
        if (pendingWrap._renderedSlides[si]) return;
        pendingWrap._renderedSlides[si] = true;
        cardParent.appendChild(createSlideCard(card, memory.cards));
      });
    }

    // 轮询更新内容后滚动到底（与 SSE 实时滚动保持一致）
    var container = pendingWrap.parentNode;
    if (container) container.scrollTop = container.scrollHeight;
  }

  function _checkPendingAfterLoad() {
    // tabs.js 发现最后一条是 pending 后才调此函数
    _checkAgentStatusAndAct(appState.currentProjectId, $("#pptChatContainer"));
  }

  // 模型选择器状态
  var _contentModelCode = null;
  var _pptModelCode = null;

  // 加载启用的模型列表到下拉框
  async function loadModelSelectors() {
    try {
      var models = await api("GET", "/api/models?enabled=1");
      if (!models || !models.length) return;

      // 默认选中 is_default=1 的模型，若无默认选第一个
      var defaultCode = null;
      for (var i = 0; i < models.length; i++) {
        if (models[i].is_default === 1) {
          defaultCode = models[i].code;
          break;
        }
      }
      if (!defaultCode) defaultCode = models[0].code;

      _fillSelector($("#contentModelSelector"), models, defaultCode);
      _fillSelector($("#pptModelSelector"), models, defaultCode);
      _contentModelCode = defaultCode;
      _pptModelCode = defaultCode;
    } catch (e) {
      console.warn("load models failed:", e);
    }
  }

  function _fillSelector(select, models, defaultCode) {
    select.innerHTML = "";
    models.forEach(function (m) {
      var opt = document.createElement("option");
      opt.value = m.code;
      opt.textContent = m.name;
      if (m.code === defaultCode) opt.selected = true;
      select.appendChild(opt);
    });
  }

  // 模型选择变化时更新 code
  $("#contentModelSelector").addEventListener("change", function () {
    _contentModelCode = this.value;
  });
  $("#pptModelSelector").addEventListener("change", function () {
    _pptModelCode = this.value;
  });

  // 更新/读取幻灯片缓存；异步从 API 拉取最新全量
  async function _ensureProjectSlidesCache() {
    if (_projectSlidesCache && _projectSlidesCache.length) return _projectSlidesCache;
    if (!appState.currentProjectId) return null;
    try {
      _projectSlidesCache = await api("GET", `/api/slides/${appState.currentProjectId}`);
    } catch (_) { _projectSlidesCache = null; }
    return _projectSlidesCache;
  }

  function escapeHtml(s) {
    return String(s || "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function appendMessage(container, role, text, opts = {}) {
    // 移除容器内占位提示（如"选择会话后即可开始对话"），避免残留显示在历史消息顶部
    const emptyHint = container.querySelector(".empty-hint");
    if (emptyHint) emptyHint.remove();
    const wrap = document.createElement("div");
    wrap.className = `message message-${role}`;
    if (opts.status) wrap.dataset.msgStatus = opts.status;
    const avatar = role === "user" ? "👤" : "🤖";
    const bubble = document.createElement("div");
    bubble.className = `message-bubble message-bubble-${role === "user" ? "user" : "agent"}`;
    if (opts.error) bubble.classList.add("message-bubble-error");
    wrap.innerHTML = `<div class="message-avatar message-avatar-${role}">${avatar}</div>`;
    wrap.appendChild(bubble);

    // 渲染执行步骤（仅 agent 消息且存在 steps 时）
    const steps = opts.steps;
    if (role === "agent" && Array.isArray(steps) && steps.length > 0) {
      // 历史步骤标题：最后一条 agent 消息按状态展示（interrupted → 等待用户作答）
      const stepsTitle = (opts.isLastAgent && opts.status === "interrupted")
        ? "⚙️ 执行步骤：等待用户作答"
        : "⚙️ 执行步骤";
      const stepsContainer = document.createElement("div");
      stepsContainer.className = "steps-container";
      stepsContainer.innerHTML = `
        <div class="steps-header">
          <span class="steps-title">${stepsTitle}</span>
          <button class="btn steps-toggle">展开</button>
        </div>
        <div class="steps-list" hidden></div>
      `;
      const stepsList = stepsContainer.querySelector(".steps-list");
      steps.forEach((s, i) => {
        const item = document.createElement("div");
        item.className = "step-item";
        const name = (s && s.name) ? s.name : "未知步骤";
        item.textContent = `${i + 1}. ${name}`;
        stepsList.appendChild(item);
        // 如果有 done 字段，追加成功子行
        if (s && s.done) {
          const sub = document.createElement("div");
          sub.className = "step-done";
          sub.textContent = s.done;
          item.appendChild(sub);
        }
      });
      const toggleBtn = stepsContainer.querySelector(".steps-toggle");
      const _list = stepsList;
      toggleBtn.addEventListener("click", () => {
        const isHidden = _list.hidden;
        _list.hidden = !isHidden;
        toggleBtn.textContent = isHidden ? "折叠" : "展开";
      });
      bubble.appendChild(stepsContainer);
    }

    // 渲染文本
    if (text) {
      const textEl = document.createElement("div");
      textEl.className = "message-text";
      textEl.textContent = text;
      bubble.appendChild(textEl);
    }

    container.appendChild(wrap);

    // 渲染历史卡片（仅 agent 消息，放在气泡外部）
    // 优先遍历 cards 数组（新结构），回退到 slides 字段（老数据兼容）
    const cards = opts.cards;
    const slides = opts.slides;
    if (role === "agent") {
      if (Array.isArray(cards) && cards.length > 0) {
        const allSlides = opts.allSlides || _projectSlidesCache || [];
        cards.forEach((c) => {
          if (!c || !c.card_type) return;
          if (c.card_type === "intervention") {
            renderInterventionCard(c.card_data, "history", container, wrap);
          } else if (c.card_type === "slides") {
            const sl = c.card_data || {};
            // 用最新 slides 缓存补全字段（与 tabs.js 逻辑一致）
            const latest = allSlides.find((s) => s.slide_index === sl.slide_index);
            if (latest) {
              if (!sl.slide_text) sl.slide_text = latest.slide_text;
              if (!sl.narration) sl.narration = latest.narration;
              sl.html_path = latest.html_path;
            }
            const allForCard = allSlides.length ? allSlides : [sl];
            container.appendChild(createSlideCard(sl, allForCard));
          }
        });
      } else if (Array.isArray(slides) && slides.length > 0) {
        const allForCard = opts.allSlides || _projectSlidesCache || slides;
        slides.forEach((sl) => {
          container.appendChild(createSlideCard(sl, allForCard));
        });
      }
    }

    container.scrollTop = container.scrollHeight;
    return bubble;
  }

  function createSlideCard(slide, allSlides, opts) {
    opts = opts || {};
    const card = document.createElement("div");
    card.className = "slide-card";

    // 归一化 allSlides：优先用传入参数；若参数不完整（长度<=1 / undefined）且缓存有更长列表，用缓存
    if (!Array.isArray(allSlides) || allSlides.length <= 1) {
      if (_projectSlidesCache && _projectSlidesCache.length > (Array.isArray(allSlides) ? allSlides.length : 0)) {
        allSlides = _projectSlidesCache;
      } else if (!Array.isArray(allSlides)) {
        allSlides = [slide];
      }
    }

    let currentIdx = allSlides.findIndex(s => s.slide_index === slide.slide_index);
    if (currentIdx < 0) { currentIdx = 0; }
    let currentSlide = allSlides[currentIdx] || slide;

    // ===== 置灰模式判定：数据库快照 slide 在最新 allSlides 中不存在 =====
    var isDisabled = !allSlides.some(function (s) { return s.slide_index === slide.slide_index; });

    // 若不为置灰模式，且 allSlides 有匹配项，使用 allSlides 中的最新数据（含 html_path 最新化）
    if (!isDisabled) {
      var _matchIdx = allSlides.findIndex(function (s) { return s.slide_index === slide.slide_index; });
      if (_matchIdx >= 0) {
        currentIdx = _matchIdx;
        currentSlide = allSlides[_matchIdx];
      }
    }

    // 如果 allSlides 里仍然只有 1 张，尝试异步拉取最新全量并重新渲染（只拉一次）
    if (allSlides.length <= 1 && !card._asyncFetched) {
      card._asyncFetched = true;
      _ensureProjectSlidesCache().then(function (list) {
        if (list && list.length > allSlides.length) {
          allSlides = list;
          currentIdx = Math.max(0, allSlides.findIndex(s => s.slide_index === slide.slide_index));
          if (currentIdx < 0) currentIdx = 0;
          currentSlide = allSlides[currentIdx] || slide;
          render();
        }
      });
    }
    // 默认 tab 优先级：置灰模式→content；否则用 opts.defaultTab；再否则 preview
    let activeTab = isDisabled ? "content" : (opts.defaultTab || "preview");
    let previewLoaded = false;

    function render() {
      const s = currentSlide;
      card.className = "slide-card" + (isDisabled ? " disabled" : "");
      card.innerHTML = `
        <div class="slide-card-title">${opts.titlePrefix ? opts.titlePrefix(s) : ""}📄 幻灯片 ${s.slide_index}：${escapeHtml(s.title)}</div>
        <div class="slide-card-actions">
          <button class="btn preview-btn" ${isDisabled ? "disabled" : ""}>预览</button>
          <button class="btn popout-btn" ${isDisabled ? "disabled" : ""}>弹出预览</button>
          <a class="btn download-btn" href="${s.html_path}" download="slide_${s.slide_index}.html" ${isDisabled ? 'style="pointer-events:none;opacity:0.6"' : ''}>下载</a>
          <button class="btn play-btn" data-index="${s.slide_index}" ${isDisabled ? "disabled" : ""}>▶ 播放</button>
        </div>
        <div class="slide-card-nav-tabs">
          <button class="slide-nav-btn prev" ${(currentIdx === 0 || isDisabled) ? "disabled" : ""}>◀</button>
          <div class="slide-card-tabs">
            <button class="slide-card-tab ${activeTab === "preview" ? "active" : ""}" data-tab="preview" ${isDisabled ? "disabled" : ""}>预览</button>
            <button class="slide-card-tab ${activeTab === "content" ? "active" : ""}" data-tab="content" ${isDisabled ? "disabled" : ""}>幻灯片内容</button>
            <button class="slide-card-tab ${activeTab === "narration" ? "active" : ""}" data-tab="narration" ${isDisabled ? "disabled" : ""}>逐字稿</button>
          </div>
          <button class="slide-nav-btn next" ${(currentIdx === allSlides.length - 1 || isDisabled) ? "disabled" : ""}>▶</button>
        </div>
        <div class="slide-card-tab-content ${activeTab === "preview" ? "active" : ""}" data-tab="preview">
          <div class="slide-preview-wrap"><iframe class="slide-preview-iframe" src=""></iframe></div>
        </div>
        <div class="slide-card-tab-content ${activeTab === "content" ? "active" : ""}" data-tab="content">
          <pre class="slide-content-pre">${escapeHtml(s.slide_text || "(无内容)")}</pre>
          <div class="slide-card-edit-actions">
            <button class="btn content-edit-btn" ${isDisabled ? "disabled" : ""}>编辑内容</button>
          </div>
        </div>
        <div class="slide-card-tab-content ${activeTab === "narration" ? "active" : ""}" data-tab="narration">
          <pre class="slide-narration-pre">${escapeHtml(s.narration || "(无逐字稿)")}</pre>
          <div class="slide-card-edit-actions">
            <button class="btn narration-edit-btn" ${isDisabled ? "disabled" : ""}>编辑</button>
          </div>
        </div>
      `;
      previewLoaded = false;
      bindEvents();
      if (activeTab === "preview") loadPreview();
    }

    async function loadPreview() {
      if (previewLoaded) return;
      const iframe = card.querySelector(".slide-preview-iframe");
      if (iframe && currentSlide.html_path) {
        await _loadSlideSize();
        previewLoaded = true;
        // 先设 onload 再设 src，避免缓存导致 onload 不触发
        iframe.onload = function () {
          _fitCardPreviewScheduled(iframe);
        };
        iframe.src = currentSlide.html_path;
      }
    }

    // 兜底：onload 后 100/1000/3000/8000ms 各算一次，覆盖容器布局稳定、字体加载、动画等延迟场景
    function _fitCardPreviewScheduled(iframe) {
      [100, 1000, 3000, 8000].forEach(function (ms) {
        setTimeout(function () { fitCardPreview(iframe); }, ms);
      });
    }

    // 卡片内预览 iframe 等比缩放居中（复用全局 _slideW/_slideH）
    function fitCardPreview(iframe) {
      const wrap = card.querySelector(".slide-preview-wrap");
      if (!wrap || !iframe) return;
      const rect = wrap.getBoundingClientRect();
      const cw = rect.width;
      const ch = rect.height;
      if (!cw || !ch || !_slideW || !_slideH) return;
      const ratio = Math.min(cw / _slideW, ch / _slideH);
      const scaledW = _slideW * ratio;
      const scaledH = _slideH * ratio;
      const offsetX = (cw - scaledW) / 2;
      const offsetY = (ch - scaledH) / 2;
      iframe.style.position = "absolute";
      iframe.style.top = "0";
      iframe.style.left = "0";
      iframe.style.width = _slideW + "px";
      iframe.style.height = _slideH + "px";
      iframe.style.transformOrigin = "top left";
      iframe.style.transform = "translate(" + offsetX + "px," + offsetY + "px) scale(" + ratio + ")";
    }

    function bindEvents() {
      // tab 切换
      card.querySelectorAll(".slide-card-tab").forEach(t => {
        t.addEventListener("click", () => {
          if (isDisabled) return;
          activeTab = t.dataset.tab;
          card.querySelectorAll(".slide-card-tab").forEach(x => x.classList.toggle("active", x === t));
          card.querySelectorAll(".slide-card-tab-content").forEach(c =>
            c.classList.toggle("active", c.dataset.tab === activeTab));
          if (activeTab === "preview") {
            if (previewLoaded) {
              // 已加载过，切回预览 tab 时容器从 display:none 恢复，需重算缩放
              const iframe = card.querySelector(".slide-preview-iframe");
              if (iframe) _fitCardPreviewScheduled(iframe);
            } else {
              loadPreview();
            }
          }
        });
      });

      // 左右导航
      const prevBtn = card.querySelector(".slide-nav-btn.prev");
      const nextBtn = card.querySelector(".slide-nav-btn.next");
      prevBtn.addEventListener("click", () => {
        if (currentIdx > 0) { currentIdx--; currentSlide = allSlides[currentIdx]; render(); }
      });
      nextBtn.addEventListener("click", () => {
        if (currentIdx < allSlides.length - 1) { currentIdx++; currentSlide = allSlides[currentIdx]; render(); }
      });

      // 主操作栏：预览（弹窗，支持左右切换所有幻灯片）
      card.querySelector(".preview-btn").addEventListener("click", function () {
        openPreviewModal(currentSlide, allSlides);
      });

      // 弹出预览
      card.querySelector(".popout-btn").addEventListener("click", () => {
        if (!appState.currentProjectId) { showAlert({ title: "提示", message: "请先选择会话" }); return; }
        window.open(`/api/package/${appState.currentProjectId}/view?slide=${currentSlide.slide_index}`, "_blank");
      });

      // 播放
      card.querySelector(".play-btn").addEventListener("click", () => {
        startPlayback(currentSlide.slide_index);
      });

      // 逐字稿编辑 → 保存
      bindNarrationEdit();
      // 幻灯片内容编辑 → 发送
      bindContentEdit();
    }

    function bindNarrationEdit() {
      const wrap = card.querySelector('.slide-card-tab-content[data-tab="narration"]');
      const editBtn = wrap.querySelector(".narration-edit-btn");
      editBtn.addEventListener("click", () => {
        const pre = wrap.querySelector(".slide-narration-pre");
        const original = currentSlide.narration || "";
        pre.outerHTML = `<textarea class="slide-narration-textarea" rows="8">${escapeHtml(original)}</textarea>`;
        wrap.querySelector(".slide-card-edit-actions").innerHTML = `
          <button class="btn btn-primary narration-save-btn">保存</button>
          <button class="btn narration-cancel-btn">取消</button>
        `;
        wrap.querySelector(".slide-narration-textarea").focus();

        wrap.querySelector(".narration-save-btn").addEventListener("click", async () => {
          const newText = wrap.querySelector(".slide-narration-textarea").value;
          try {
            await api("PUT",
              `/api/slides/${appState.currentProjectId}/${currentSlide.slide_index}/narration`,
              { narration: newText });
            currentSlide.narration = newText;
            render();
          } catch (e) {
            showAlert({ title: "保存失败", message: e.message, type: "error" });
          }
        });

        wrap.querySelector(".narration-cancel-btn").addEventListener("click", () => {
          render();
        });
      });
    }

    function bindContentEdit() {
      const wrap = card.querySelector('.slide-card-tab-content[data-tab="content"]');
      const editBtn = wrap.querySelector(".content-edit-btn");
      editBtn.addEventListener("click", () => {
        const pre = wrap.querySelector(".slide-content-pre");
        const original = currentSlide.slide_text || "";
        pre.outerHTML = `<textarea class="slide-content-textarea" rows="12">${escapeHtml(original)}</textarea>`;
        wrap.querySelector(".slide-card-edit-actions").innerHTML = `
          <button class="btn btn-primary content-send-btn">发送</button>
          <button class="btn content-cancel-btn">取消</button>
        `;
        wrap.querySelector(".slide-content-textarea").focus();

        wrap.querySelector(".content-send-btn").addEventListener("click", async () => {
          const editedText = wrap.querySelector(".slide-content-textarea").value;
          const msg = `第${currentSlide.slide_index}张幻灯片，内容进行了修改调整，最新内容如下：\n**幻灯片内容**：\n${editedText}`;
          await sendPptMessage(msg);
          render();
        });

        wrap.querySelector(".content-cancel-btn").addEventListener("click", () => {
          render();
        });
      });
    }

    card._fitCardPreview = fitCardPreview;
    render();
    return card;
  }

  function appendSlideCard(container, slide, allSlides) {
    // 参数兼容：后两个参数可选；优先用传入的 allSlides，否则走缓存刷新
    var resolvedAll = allSlides;
    function doAppend(list) {
      var card = createSlideCard(slide, list || [slide]);
      container.appendChild(card);
      container.scrollTop = container.scrollHeight;
    }
    if (Array.isArray(resolvedAll) && resolvedAll.length > 0) {
      // allSlides 已提供（流式SSE场景），直接使用
      // 但仍异步刷新缓存供后续使用
      _ensureProjectSlidesCache().catch(function () {});
      doAppend(resolvedAll);
    } else {
      // 历史场景：刷新缓存后用最新缓存
      _ensureProjectSlidesCache().then(function (list) {
        doAppend(list || [slide]);
      }).catch(function () {
        doAppend([slide]);
      });
    }

    // 有幻灯片后显示画廊按钮
    if (slide.html_path) {
      const btn = $("#galleryBtn");
      if (btn) btn.hidden = false;
    }
  }

  // 画廊：打开/关闭
  async function openGallery() {
    if (!appState.currentProjectId) return;
    try {
      const slides = await api("GET", `/api/slides/${appState.currentProjectId}`);
      if (!slides || !slides.length) return;
      _projectSlidesCache = slides; // 更新缓存
      const grid = $("#galleryGrid");
      grid.innerHTML = "";
      slides.forEach((sl) => {
        grid.appendChild(createSlideCard(sl, slides));
      });
      $("#galleryModal").hidden = false;
    } catch (e) {
      console.warn("load gallery slides failed", e);
    }
  }

  $("#galleryBtn").addEventListener("click", openGallery);
  $("#galleryCloseBtn").addEventListener("click", () => { $("#galleryModal").hidden = true; });
  $("#packageDownloadBtn").addEventListener("click", () => {
    if (!appState.currentProjectId) return;
    window.location.href = `/api/package/${appState.currentProjectId}/download`;
  });

  // 播放模式
  let _playerSlides = [];
  let _playerCurrent = 0;

  // 荧光笔状态
  let _penActive = false;
  let _penColor = "yellow";
  let _penWidth = 12;
  const _PEN_COLORS = {
    yellow: "rgba(241,196,15,0.35)",
    red: "rgba(231,76,60,0.35)",
    blue: "rgba(52,152,219,0.35)",
    green: "rgba(46,204,113,0.35)",
    black: "rgba(0,0,0,0.4)",
    white: "rgba(255,255,255,0.45)",
  };
  let _strokesMap = {};  // { slideIndex: [[{x,y},...], ...] }
  // Expose to iframe via window
  window._penColor = _penColor;
  window._penWidth = _penWidth;
  window._PEN_COLORS = _PEN_COLORS;
  window._strokesMap = _strokesMap;
  window._currentSlideIndex = _currentSlideIndex;
  window._playerPrev = playerPrev;
  window._playerNext = playerNext;

  function _currentSlideIndex() {
    const sl = _playerSlides[_playerCurrent];
    return sl ? sl.slide_index : -1;
  }

  function _savePenStrokes() {
    const idx = _currentSlideIndex();
    if (idx < 0) return;
    try {
      const w = $("#playerFrame").contentWindow;
      if (w && w.__penGetStrokes) {
        _strokesMap[idx] = w.__penGetStrokes();
      }
    } catch (_) {}
  }

  function _callPen(method) {
    try {
      const w = $("#playerFrame").contentWindow;
      if (w && w.__pen) { w.__pen(method); }
    } catch (_) {}
  }

  function _injectPenCanvas() {
    try {
      const win = $("#playerFrame").contentWindow;
      const doc = $("#playerFrame").contentDocument;
      if (!doc || !doc.body) return;

      // Hide scrollbar
      let style = doc.querySelector("#pen-scrollbar-style");
      if (!style) {
        style = doc.createElement("style");
        style.id = "pen-scrollbar-style";
        style.textContent = "html{scrollbar-width:none;-ms-overflow-style:none}html::-webkit-scrollbar{display:none}";
        doc.head.appendChild(style);
      }

      // Remove old canvas if any
      const old = doc.querySelector("#pen-canvas");
      if (old) old.remove();

      const canvas = doc.createElement("canvas");
      canvas.id = "pen-canvas";
      canvas.style.cssText = "position:absolute;top:0;left:0;z-index:9999;pointer-events:none;";
      doc.body.appendChild(canvas);

      const ctx = canvas.getContext("2d");
      let PEN_COLOR = parent._penColor ? (parent._PEN_COLORS[parent._penColor] || "rgba(241,196,15,0.35)") : "rgba(241,196,15,0.35)";
      let PEN_WIDTH = parent._penWidth || 12;
      let isDrawing = false;
      let strokes = [];
      let curStroke = null;
      const epsilon = 2;

      function resize() {
        canvas.width = doc.documentElement.scrollWidth || win.innerWidth;
        canvas.height = doc.documentElement.scrollHeight || win.innerHeight;
        canvas.style.width = canvas.width + "px";
        canvas.style.height = canvas.height + "px";
      }
      resize();
      win.addEventListener("resize", resize);

      function redraw() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        for (const s of strokes) {
          const pts = s.points || s;
          if (pts.length < 2) continue;
          ctx.beginPath();
          ctx.strokeStyle = s.color || PEN_COLOR;
          ctx.lineWidth = s.width || PEN_WIDTH;
          ctx.moveTo(pts[0].x, pts[0].y);
          for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
          ctx.stroke();
        }
      }

      // Expose API on iframe window
      win.__penGetStrokes = () => strokes;
      win.__pen = function (cmd) {
        if (cmd === "enable") { canvas.style.pointerEvents = "auto"; }
        else if (cmd === "disable") { canvas.style.pointerEvents = "none"; }
        else if (cmd === "clear_page") { strokes = []; ctx.clearRect(0, 0, canvas.width, canvas.height); }
        else if (cmd === "undo") { strokes.pop(); redraw(); }
        else if (cmd && cmd.startsWith("set_color:")) {
          const c = cmd.slice(10);
          PEN_COLOR = parent._PEN_COLORS ? (parent._PEN_COLORS[c] || PEN_COLOR) : PEN_COLOR;
        }
        else if (cmd && cmd.startsWith("set_width:")) {
          PEN_WIDTH = parseInt(cmd.slice(10)) || PEN_WIDTH;
        }
        else if (cmd === "restore") {
          const idx = parent._currentSlideIndex ? parent._currentSlideIndex() : -1;
          if (idx >= 0 && parent._strokesMap) {
            strokes = parent._strokesMap[idx] || [];
            redraw();
          }
        }
      };

      // Forward keyboard events to parent for slide navigation
      win.addEventListener("keydown", (e) => {
        if (e.key === "ArrowLeft") { e.preventDefault(); if (parent._playerPrev) parent._playerPrev(); }
        else if (e.key === "ArrowRight") { e.preventDefault(); if (parent._playerNext) parent._playerNext(); }
      });

      canvas.addEventListener("mousedown", (e) => {
        if (!isDrawing) {
          isDrawing = true;
          const s = { points: [{ x: e.pageX, y: e.pageY }], color: PEN_COLOR, width: PEN_WIDTH };
          strokes.push(s);
          curStroke = s;
        }
      });
      canvas.addEventListener("mousemove", (e) => {
        if (!isDrawing) return;
        const pts = curStroke.points;
        const p = { x: e.pageX, y: e.pageY };
        const last = pts[pts.length - 1];
        const dx = p.x - last.x, dy = p.y - last.y;
        if (dx * dx + dy * dy < epsilon * epsilon) return;
        pts.push(p);
        redraw();
      });
      canvas.addEventListener("mouseup", () => { isDrawing = false; _savePenStrokes(); });
      canvas.addEventListener("mouseleave", () => { if (isDrawing) { isDrawing = false; _savePenStrokes(); } });

      // Restore strokes for this slide
      const idx = _currentSlideIndex();
      if (idx >= 0 && _strokesMap[idx]) {
        strokes = _strokesMap[idx];
        redraw();
      }
      if (_penActive) { canvas.style.pointerEvents = "auto"; }
    } catch (_) { /* cross-origin, ignore */ }
  }

  function updatePlayer() {
    const sl = _playerSlides[_playerCurrent];
    if (!sl) return;
    $("#playerFrame").src = sl.html_path;
  }

  function playerPrev() {
    if (_playerCurrent > 0) { _savePenStrokes(); _playerCurrent--; updatePlayer(); }
  }
  function playerNext() {
    if (_playerCurrent < _playerSlides.length - 1) { _savePenStrokes(); _playerCurrent++; updatePlayer(); }
  }

  function exitPlayer() {
    _savePenStrokes();
    if (document.fullscreenElement) {
      document.exitFullscreen();
    }
    $("#playerFrame").src = "about:blank";
    $("#playerModal").hidden = true;
  }

  async function startPlayback(startIndex) {
    if (!appState.currentProjectId) return;
    try {
      _playerSlides = await api("GET", `/api/slides/${appState.currentProjectId}`);
    } catch (e) {
      console.warn("load slides for playback failed", e);
      return;
    }
    if (!_playerSlides || !_playerSlides.length) return;

    _playerCurrent = _playerSlides.findIndex((s) => s.slide_index === startIndex);
    if (_playerCurrent < 0) _playerCurrent = 0;

    // Reset pen state
    _penActive = false;
    _strokesMap = {};
    _updatePenToggleUI();

    $("#playerModal").hidden = false;
    updatePlayer();
    $("#playerModal").requestFullscreen().catch(() => {});
  }

  // iframe load: inject pen canvas
  $("#playerFrame").addEventListener("load", _injectPenCanvas);

  $("#playerExitBtn").addEventListener("click", exitPlayer);

  // Keyboard controls
  window.addEventListener("keydown", (e) => {
    if ($("#playerModal").hidden) return;
    if (e.key === "ArrowLeft") { e.preventDefault(); playerPrev(); }
    else if (e.key === "ArrowRight") { e.preventDefault(); playerNext(); }
  });

  // Fullscreen exit
  document.addEventListener("fullscreenchange", () => {
    if (!document.fullscreenElement && !$("#playerModal").hidden) {
      _savePenStrokes();
      $("#playerFrame").src = "about:blank";
      $("#playerModal").hidden = true;
    }
  });

  // ---- 荧光笔工具栏 ----
  function _updatePenToggleUI() {
    const btn = $("#penToggle");
    if (_penActive) {
      btn.classList.add("active");
    } else {
      btn.classList.remove("active");
    }
  }

  $("#penToggle").addEventListener("click", () => {
    _penActive = !_penActive;
    _updatePenToggleUI();
    _callPen(_penActive ? "enable" : "disable");
  });

  // Color picker
  document.querySelectorAll("#penColors .pen-color").forEach(el => {
    el.addEventListener("click", () => {
      document.querySelectorAll("#penColors .pen-color").forEach(c => c.classList.remove("active"));
      el.classList.add("active");
      _penColor = el.dataset.color;
      window._penColor = _penColor;
      _callPen("set_color:" + _penColor);
    });
  });

  // Width picker
  document.querySelectorAll("#penWidths .pen-width").forEach(el => {
    el.addEventListener("click", () => {
      document.querySelectorAll("#penWidths .pen-width").forEach(w => w.classList.remove("active"));
      el.classList.add("active");
      _penWidth = parseInt(el.dataset.width);
      window._penWidth = _penWidth;
      _callPen("set_width:" + _penWidth);
    });
  });

  $("#penClearPage").addEventListener("click", () => {
    const idx = _currentSlideIndex();
    if (idx >= 0) { _strokesMap[idx] = []; }
    _callPen("clear_page");
  });

  $("#penClearAll").addEventListener("click", () => {
    _strokesMap = {};
    _callPen("clear_page");
  });

  $("#penUndo").addEventListener("click", () => {
    const idx = _currentSlideIndex();
    if (idx >= 0 && _strokesMap[idx] && _strokesMap[idx].length > 0) {
      _strokesMap[idx].pop();
      _callPen("undo");
    }
  });

  async function appendContentCard(container) {
    if (!appState.currentProjectId) return;
    try {
      const data = await api("GET", `/api/content/${appState.currentProjectId}/content-md`);
      if (!data.exists || !data.content) return;

      let content = data.content;

      // 从 Markdown 第一行 # 标题提取卡片标题
      const titleMatch = content.match(/^#\s+(.+)$/m);
      const cardTitle = titleMatch ? titleMatch[1].trim() : "PPT Markdown 格式内容";
      const summary = content.slice(0, 200) + (content.length > 200 ? "..." : "");

      const card = document.createElement("div");
      card.className = "content-card";
      card.innerHTML = `
        <div class="content-card-header">
          <span class="content-card-title">📄 ${escapeHtml(cardTitle)}</span>
          <button class="btn content-card-toggle">展开</button>
        </div>
        <div class="content-card-summary">${escapeHtml(summary)}</div>
        <div class="content-card-body" hidden></div>
      `;

      const toggleBtn = card.querySelector(".content-card-toggle");
      const bodyEl = card.querySelector(".content-card-body");
      const summaryEl = card.querySelector(".content-card-summary");

      // 渲染展示态
      function renderDisplay(currentContent) {
        bodyEl.innerHTML = `
          <pre class="content-card-pre">${escapeHtml(currentContent)}</pre>
          <div class="content-card-actions">
            <button class="btn content-card-edit-btn">编辑</button>
          </div>
        `;
        bodyEl.querySelector(".content-card-edit-btn").addEventListener("click", () => {
          renderEdit(currentContent);
        });
      }

      // 渲染编辑态
      function renderEdit(originalContent) {
        bodyEl.innerHTML = `
          <textarea class="content-card-textarea" rows="12">${escapeHtml(originalContent)}</textarea>
          <div class="content-card-actions">
            <button class="btn btn-primary content-card-save-btn">保存</button>
            <button class="btn content-card-cancel-btn">取消</button>
          </div>
        `;
        bodyEl.querySelector(".content-card-textarea").focus();

        bodyEl.querySelector(".content-card-save-btn").addEventListener("click", async () => {
          const newContent = bodyEl.querySelector(".content-card-textarea").value;
          try {
            await api("PUT", `/api/content/${appState.currentProjectId}/content-md`, { content: newContent });
            content = newContent;
            renderDisplay(newContent);
          } catch (e) {
            showAlert({ title: "保存失败", message: e.message, type: "error" });
          }
        });

        bodyEl.querySelector(".content-card-cancel-btn").addEventListener("click", () => {
          renderDisplay(originalContent);
        });
      }

      // 初始化为展示态
      renderDisplay(content);

      // 展开/折叠：展开时把卡片固定定位到聊天区可视区域（内容多时卡片内部滚动），
      // 折叠时恢复普通文档流。用 fixed 而不是 absolute——absolute 会定位到滚动
      // 内容的顶部而非可视区，消息流很长时卡片会跳到视口外"消失"。
      let _contentExpanded = false;
      function _pinCardToViewport() {
        const rect = container.getBoundingClientRect();
        card.style.position = "fixed";
        card.style.top = rect.top + "px";
        card.style.left = rect.left + "px";
        card.style.width = rect.width + "px";
        card.style.height = rect.height + "px";
      }
      function _unpinCard() {
        card.style.position = "";
        card.style.top = "";
        card.style.left = "";
        card.style.width = "";
        card.style.height = "";
      }
      function _onViewportResize() { if (_contentExpanded) _pinCardToViewport(); }

      toggleBtn.addEventListener("click", () => {
        const isHidden = bodyEl.hidden;
        bodyEl.hidden = !isHidden;
        toggleBtn.textContent = isHidden ? "折叠" : "展开";
        summaryEl.hidden = isHidden;
        card.classList.toggle("expanded", isHidden);
        _contentExpanded = isHidden;
        if (isHidden) {
          _pinCardToViewport();
          window.addEventListener("resize", _onViewportResize);
        } else {
          _unpinCard();
          window.removeEventListener("resize", _onViewportResize);
        }
      });

      container.appendChild(card);
      container.scrollTop = container.scrollHeight;
    } catch (e) {
      console.warn("load content.md failed", e);
    }
  }
  // Expose to other scripts (e.g. tabs.js loads historical slides)
  window.createSlideCard = createSlideCard;
  window.appendSlideCard = appendSlideCard;
  window.appendMessage = appendMessage;
  window.appendContentCard = appendContentCard;
  window.renderInterventionCard = renderInterventionCard;
  window._checkPendingAfterLoad = _checkPendingAfterLoad;

  // 暴露清理函数给 tabs.js 在会话切换时调用
  window._cleanupAgentState = function () {
    // 取消当前 SSE 流（切会话后旧流不再继续读取，避免渲染/状态污染新会话）
    if (_agentState.sseReader) {
      _agentState.sseReader.cancel().catch(function () {});
      _agentState.sseReader = null;
    }
    if (_agentState.pollTimer) {
      clearInterval(_agentState.pollTimer);
      _agentState.pollTimer = null;
    }
    _agentState.busy = false;
    _agentState.runningTab = null;
    _agentState.stopping = false;
    _agentState.runningProjectId = null;
    _interventionWrap = null;
    _setInputDisabled(false);
    // 清除上一会话的会话级状态：幻灯片缓存与流式骨架，避免被新会话误用
    _projectSlidesCache = null;
    _streamingSlides = [];
    _slideSizeLoaded = false;
    // 停止视频 tab 的轮询（整片进度/单张生成/合成）
    if (window._cleanupVideoState) window._cleanupVideoState();
    // 隐藏全局进度条
    var pptProg = $("#pptProgress");
    var contentProg = $("#contentProgress");
    if (pptProg) pptProg.hidden = true;
    if (contentProg) contentProg.hidden = true;
  };

  // 预览弹窗全局状态
  var _previewAllSlides = [];
  var _previewCurrentIdx = 0;

  // 打开预览弹窗（指定幻灯片 + 全部幻灯片，用于左右切换）
  function openPreviewModal(slide, allSlides) {
    if (!allSlides || !allSlides.length) return;
    _previewAllSlides = allSlides;
    _previewCurrentIdx = Math.max(0, Math.min(
      allSlides.findIndex(function (s) { return s.slide_index === slide.slide_index; }),
      allSlides.length - 1
    ));
    if (_previewCurrentIdx < 0) _previewCurrentIdx = 0;
    _renderPreviewCurrent();
    $("#previewModal").hidden = false;
  }

  // 渲染当前预览幻灯片（标题 + iframe + 按钮禁用状态）
  function _renderPreviewCurrent() {
    var s = _previewAllSlides[_previewCurrentIdx];
    if (!s) return;
    $("#previewTitle").textContent = "幻灯片 " + s.slide_index + "：" + s.title;
    $("#preview-prev-btn").disabled = _previewCurrentIdx === 0;
    $("#preview-next-btn").disabled = _previewCurrentIdx === _previewAllSlides.length - 1;
    var frame = $("#previewFrame");
    (async function () {
      await _loadSlideSize();
      frame.onload = function () {
        requestAnimationFrame(function () { _fitPreviewFrame(frame); });
      };
      frame.src = s.html_path;
    })();
  }

  $("#previewCloseBtn").addEventListener("click", function () {
    $("#previewModal").hidden = true;
    $("#previewFrame").src = "about:blank";
  });
  $("#preview-prev-btn").addEventListener("click", function () {
    if (_previewCurrentIdx > 0) { _previewCurrentIdx--; _renderPreviewCurrent(); }
  });
  $("#preview-next-btn").addEventListener("click", function () {
    if (_previewCurrentIdx < _previewAllSlides.length - 1) { _previewCurrentIdx++; _renderPreviewCurrent(); }
  });

  // 预览弹窗缩放适配：等比缩小幻灯片到弹窗容器内，无滚动条
  var _slideW = 1920, _slideH = 1080;
  var _slideSizeLoaded = false;
  async function _loadSlideSize() {
    if (_slideSizeLoaded || !appState.currentProjectId) return;
    try {
      var cfg = await api("GET", `/api/video/${appState.currentProjectId}/config`);
      if (_slideSizeLoaded) return; // await 期间已被 SSE 流式配置设置，以流为准
      if (cfg && cfg.resolution) {
        var parts = cfg.resolution.split("x");
        if (parts.length === 2 && parts[0] && parts[1]) {
          _slideW = parseInt(parts[0], 10);
          _slideH = parseInt(parts[1], 10);
        }
      }
    } catch (_) {}
    _slideSizeLoaded = true;
  }
  function _fitPreviewFrame(frame) {
    var modal = $("#previewModal");
    if (!modal || modal.hidden) return;
    var body = modal.querySelector(".preview-body");
    if (!body) return;
    var cs = getComputedStyle(body);
    var cw = body.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    var ch = body.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
    if (!cw || !ch) return;
    var ratio = Math.min(cw / _slideW, ch / _slideH);
    var scaledW = _slideW * ratio;
    var scaledH = _slideH * ratio;
    var offsetX = (cw - scaledW) / 2;
    var offsetY = (ch - scaledH) / 2;
    frame.style.flex = "none";
    frame.style.width = _slideW + "px";
    frame.style.height = _slideH + "px";
    frame.style.transformOrigin = "top left";
    frame.style.transform = "translate(" + offsetX + "px," + offsetY + "px) scale(" + ratio + ")";
  }
  // 弹窗resize时重新计算
  window.addEventListener("resize", function () {
    if (!$("#previewModal").hidden) {
      _fitPreviewFrame($("#previewFrame"));
    }
    // 卡片内预览 iframe 也重新计算缩放
    document.querySelectorAll(".slide-card-tab-content.active .slide-preview-iframe").forEach(function (frame) {
      var card = frame.closest(".slide-card");
      if (card && card._fitCardPreview) card._fitCardPreview(frame);
    });
  });

  // ===== 人工介入问题卡片 =====

  // 格式化答案为可读文本（折叠态摘要 + 展开态详情复用）
  function _formatAnswerText(q, ans) {
    if (ans === null || ans === undefined) return "(未作答)";
    var type = q.type;
    if (type === "single_choice") {
      if (typeof ans === "string" && ans.indexOf("OTHER:") === 0) {
        return "其他: " + ans.slice(6);
      }
      var opt = (q.options || []).find(function (o) { return o.key === ans; });
      return opt ? opt.label : String(ans);
    } else if (type === "multi_choice") {
      if (!Array.isArray(ans)) return String(ans);
      return ans.map(function (item) {
        if (typeof item === "string" && item.indexOf("OTHER:") === 0) {
          return "其他: " + item.slice(6);
        }
        var opt = (q.options || []).find(function (o) { return o.key === item; });
        return opt ? opt.label : String(item);
      }).join(", ");
    } else if (type === "text") {
      return String(ans);
    } else if (type === "confirm") {
      return ans ? "已确认" : "已取消";
    }
    return String(ans);
  }

  function _formatAnswerSummary(q, ans) {
    var text = _formatAnswerText(q, ans);
    return text.length > 30 ? text.slice(0, 30) + "..." : text;
  }

  // 渲染人工介入问题卡片
  // data: {intervention_id, questions, answers?}（有 answers 表示已作答）
  // mode: 'live'（实时中断）或 'history'（历史恢复）
  // originWrap: history 模式下传入该中断对应的 agent 气泡，作答恢复时复用（避免新建气泡）
  function renderInterventionCard(data, mode, container, originWrap) {
    var card = document.createElement("div");
    card.className = "intervention-card";
    container.appendChild(card);
    container.scrollTop = container.scrollHeight;

    var interventionId = data.intervention_id;
    var questions = data.questions || [];
    var total = questions.length;
    var existingAnswers = data.answers;

    var state = {
      current_index: 0,
      submitted: !!existingAnswers,
      mode: mode,
    };

    // 草稿答案: question_id → answer
    // single_choice: string | null；multi_choice: array；text: string；confirm: bool | null
    var draft = {};
    if (existingAnswers) {
      existingAnswers.forEach(function (a) { draft[a.question_id] = a.answer; });
    } else {
      questions.forEach(function (q) {
        draft[q.question_id] = (q.type === "multi_choice") ? [] : null;
      });
    }

    function render() {
      if (state.submitted) {
        renderCollapsed(false);
      } else {
        renderQuestion();
      }
    }

    // ===== 折叠态（已作答） =====
    function renderCollapsed(expanded) {
      var isConfirm = total === 1 && questions[0].type === "confirm";
      var titleText = isConfirm
        ? (draft[questions[0].question_id] ? "✓ 已确认" : "✓ 已取消")
        : "✓ 已作答（" + total + "/" + total + "）";

      var summaryHtml = questions.map(function (q, i) {
        return "<div>" + escapeHtml((i + 1) + ". " + _formatAnswerSummary(q, draft[q.question_id])) + "</div>";
      }).join("");

      var detailHtml = questions.map(function (q, i) {
        return '<div class="intervention-detail-item">' +
          '<div class="intervention-detail-q">问题 ' + (i + 1) + "/" + total + "：" + escapeHtml(q.text) + "</div>" +
          '<div class="intervention-detail-a">答案：' + escapeHtml(_formatAnswerText(q, draft[q.question_id])) + "</div>" +
          "</div>";
      }).join("");

      card.className = "intervention-card intervention-card-collapsed";
      card.innerHTML =
        '<div class="intervention-header">' +
          '<span class="intervention-title">' + titleText + "</span>" +
          '<button class="btn intervention-toggle-btn">' + (expanded ? "折叠" : "展开") + "</button>" +
        "</div>" +
        '<div class="intervention-summary"' + (expanded ? " hidden" : "") + ">" + summaryHtml + "</div>" +
        '<div class="intervention-detail"' + (expanded ? "" : " hidden") + ">" + detailHtml + "</div>";

      card.querySelector(".intervention-toggle-btn").addEventListener("click", function () {
        var isExp = !card.querySelector(".intervention-detail").hidden;
        renderCollapsed(!isExp);
      });
    }

    // ===== 作答态 =====
    function renderQuestion() {
      var idx = state.current_index;
      var q = questions[idx];
      if (!q) return;
      var isLast = idx === total - 1;
      var isConfirm = q.type === "confirm";

      card.className = "intervention-card intervention-card-active";
      card.innerHTML =
        '<div class="intervention-header">' +
          '<span class="intervention-title">❓ 问题确认</span>' +
          '<span class="intervention-progress">问题 ' + (idx + 1) + "/" + total + "</span>" +
        "</div>" +
        '<div class="intervention-question-body"></div>' +
        '<div class="intervention-nav"></div>';

      var body = card.querySelector(".intervention-question-body");
      body.innerHTML = _renderQuestionInner(q);
      _bindQuestionEvents(q, body);

      var nav = card.querySelector(".intervention-nav");
      _renderNav(q, idx, isLast, isConfirm, nav);
      _updateNavState(q, nav);
    }

    function _renderQuestionInner(q) {
      var qid = q.question_id;
      var type = q.type;
      var html = '<div class="intervention-q-text">' + escapeHtml(q.text) + "</div>";

      if (type === "single_choice" || type === "multi_choice") {
        var current = draft[qid];
        var options = q.options || [];
        var inputType = type === "single_choice" ? "radio" : "checkbox";
        var otherSelected = false;
        var otherText = "";

        // 解析当前"其他"状态
        if (type === "single_choice") {
          otherSelected = typeof current === "string" && current.indexOf("OTHER:") === 0;
          if (otherSelected) otherText = current.slice(6);
        } else {
          var arr = Array.isArray(current) ? current : [];
          for (var i = 0; i < arr.length; i++) {
            if (typeof arr[i] === "string" && arr[i].indexOf("OTHER:") === 0) {
              otherSelected = true;
              otherText = arr[i].slice(6);
              break;
            }
          }
        }

        // 当前选中的非"其他"选项 key 列表
        var selectedKeys = [];
        if (type === "single_choice") {
          if (!otherSelected && current) selectedKeys = [current];
        } else {
          var arr2 = Array.isArray(current) ? current : [];
          selectedKeys = arr2.filter(function (c) {
            return !(typeof c === "string" && c.indexOf("OTHER:") === 0);
          });
        }

        html += '<div class="intervention-options">';
        options.forEach(function (opt) {
          var checked = selectedKeys.indexOf(opt.key) >= 0 ? " checked" : "";
          html +=
            '<label class="intervention-option">' +
              '<input type="' + inputType + '" name="iv_' + qid + '" value="' + escapeHtml(opt.key) + '"' + checked + ">" +
              '<span class="intervention-option-label">' + escapeHtml(opt.label) + "</span>" +
            "</label>";
        });
        var oChecked = otherSelected ? " checked" : "";
        html +=
          '<label class="intervention-option intervention-option-other">' +
            '<input type="' + inputType + '" name="iv_' + qid + '" value="__OTHER__"' + oChecked + ">" +
            '<span class="intervention-option-label">其他</span>' +
            '<input type="text" class="intervention-other-input" value="' + escapeHtml(otherText) + '" placeholder="请输入">' +
          "</label>";
        html += "</div>";
      } else if (type === "text") {
        var currentText = draft[qid] || "";
        var placeholder = q.placeholder || "";
        html += '<textarea class="intervention-text-input" placeholder="' + escapeHtml(placeholder) + '" rows="4">' + escapeHtml(currentText) + "</textarea>";
      }
      // confirm 类型：无输入区域，按钮在 nav 中

      return html;
    }

    function _bindQuestionEvents(q, body) {
      var qid = q.question_id;
      var type = q.type;
      var nav = card.querySelector(".intervention-nav");

      if (type === "single_choice" || type === "multi_choice") {
        var inputs = body.querySelectorAll('input[name="iv_' + qid + '"]');
        inputs.forEach(function (inp) {
          inp.addEventListener("change", function () {
            _collectChoiceDraft(q, body);
            _updateNavState(q, nav);
          });
        });
        var otherInput = body.querySelector(".intervention-other-input");
        if (otherInput) {
          otherInput.addEventListener("input", function () {
            // 输入"其他"文本时自动勾选"其他"选项
            if (otherInput.value.trim()) {
              var otherOpt = body.querySelector('input[name="iv_' + qid + '"][value="__OTHER__"]');
              if (otherOpt && !otherOpt.checked) otherOpt.checked = true;
            }
            _collectChoiceDraft(q, body);
            _updateNavState(q, nav);
          });
        }
      } else if (type === "text") {
        var ta = body.querySelector(".intervention-text-input");
        if (ta) {
          ta.addEventListener("input", function () {
            draft[qid] = ta.value;
            _updateNavState(q, nav);
          });
        }
      }
    }

    function _collectChoiceDraft(q, body) {
      var qid = q.question_id;
      var type = q.type;
      if (type === "single_choice") {
        var checked = body.querySelector('input[name="iv_' + qid + '"]:checked');
        if (!checked) { draft[qid] = null; return; }
        if (checked.value === "__OTHER__") {
          var otherInput = body.querySelector(".intervention-other-input");
          var txt = otherInput ? otherInput.value.trim() : "";
          draft[qid] = txt ? "OTHER:" + txt : null;
        } else {
          draft[qid] = checked.value;
        }
      } else if (type === "multi_choice") {
        var checkedInputs = body.querySelectorAll('input[name="iv_' + qid + '"]:checked');
        var result = [];
        var otherText = "";
        checkedInputs.forEach(function (inp) {
          if (inp.value === "__OTHER__") {
            var otherInput = body.querySelector(".intervention-other-input");
            otherText = otherInput ? otherInput.value.trim() : "";
          } else {
            result.push(inp.value);
          }
        });
        if (otherText) result.push("OTHER:" + otherText);
        draft[qid] = result;
      }
    }

    function _renderNav(q, idx, isLast, isConfirm, nav) {
      if (isConfirm) {
        // confirm 类型：直接显示同意/取消按钮，即时提交
        nav.innerHTML =
          '<button class="btn intervention-cancel-btn">' + escapeHtml(q.cancel_text || "取消") + "</button>" +
          '<button class="btn btn-primary intervention-confirm-btn">' + escapeHtml(q.confirm_text || "确认") + "</button>";
        nav.querySelector(".intervention-confirm-btn").addEventListener("click", function () {
          draft[q.question_id] = true;
          _submitAnswers();
        });
        nav.querySelector(".intervention-cancel-btn").addEventListener("click", function () {
          draft[q.question_id] = false;
          _submitAnswers();
        });
      } else {
        var prevHtml = idx > 0 ? '<button class="btn intervention-prev-btn">上一题</button>' : "";
        var nextLabel = isLast ? "提交" : "下一题";
        var nextCls = isLast ? "intervention-submit-btn" : "intervention-next-btn";
        nav.innerHTML = prevHtml + '<button class="btn btn-primary ' + nextCls + '" disabled>' + nextLabel + "</button>";
        if (idx > 0) {
          nav.querySelector(".intervention-prev-btn").addEventListener("click", function () {
            state.current_index--;
            render();
          });
        }
        var nextBtn = nav.querySelector("." + nextCls);
        nextBtn.addEventListener("click", function () {
          if (!_validateCurrent(q)) return;
          if (isLast) {
            _submitAnswers();
          } else {
            state.current_index++;
            render();
          }
        });
      }
    }

    function _validateCurrent(q) {
      var qid = q.question_id;
      var type = q.type;
      var required = q.required !== false; // 默认 true
      if (!required) return true;
      if (type === "single_choice") {
        var v = draft[qid];
        return v !== null && v !== "";
      } else if (type === "multi_choice") {
        var arr = draft[qid];
        return Array.isArray(arr) && arr.length > 0;
      } else if (type === "text") {
        var t = draft[qid];
        return t !== null && String(t).trim() !== "";
      }
      return true;
    }

    function _updateNavState(q, nav) {
      if (!nav) return;
      if (q.type === "confirm") return; // 始终启用
      var btn = nav.querySelector(".intervention-next-btn, .intervention-submit-btn");
      if (btn) btn.disabled = !_validateCurrent(q);
    }

    function _restoreNavButtons() {
      var nav = card.querySelector(".intervention-nav");
      if (!nav) return;
      var q = questions[state.current_index];
      if (!q) return;
      if (q.type === "confirm") {
        nav.querySelectorAll("button").forEach(function (b) { b.disabled = false; });
      } else {
        var nb = nav.querySelector(".intervention-next-btn, .intervention-submit-btn");
        if (nb) nb.disabled = !_validateCurrent(q);
        var pb = nav.querySelector(".intervention-prev-btn");
        if (pb) pb.disabled = false;
      }
    }

    // 提交答案：调用恢复接口，消费 SSE 流，完成后折叠
    function _submitAnswers() {
      var answers = questions.map(function (q) {
        return { question_id: q.question_id, answer: draft[q.question_id] };
      });

      card.classList.add("intervention-card-submitting");
      var nav = card.querySelector(".intervention-nav");
      if (nav) {
        nav.querySelectorAll("button").forEach(function (b) { b.disabled = true; });
      }

      // 恢复执行视为运行中：按钮切换为"停止"，并防止期间误发新消息
      _agentState.busy = true;
      _agentState.runningTab = "ppt";
      _setInputDisabled(true);

      sendWithSSE(
        "/api/ppt/" + appState.currentProjectId + "/intervention",
        {
          intervention_id: interventionId,
          answers: answers,
          model_code: _pptModelCode,
        },
        container,
        {
          reuseWrap: originWrap || _interventionWrap,
          progressWrap: $("#pptProgress"),
          progressFill: $("#pptProgressFill"),
          progressStep: $("#pptProgressStep"),
          onHttpError: async function (response) {
            _agentState.busy = false;
            _agentState.runningTab = null;
            _agentState.stopping = false;
            _setInputDisabled(false);
            card.classList.remove("intervention-card-submitting");
            _restoreNavButtons();
            var errBody;
            try { errBody = await response.json(); } catch (_) { errBody = {}; }
            if (errBody.error_code === "CHECKPOINT_MISSING") {
              showAlert({ title: "提示", message: "智能体状态已失效，请重新发起对话" });
            } else if (errBody.error_code === "ALREADY_SUBMITTED") {
              showAlert({ title: "提示", message: "该介入问题已作答" });
            } else {
              showAlert({ title: "提交失败", message: (errBody.message || ("HTTP " + response.status)), type: "error" });
            }
            return true; // 已处理，sendWithSSE 清理空气泡后返回
          },
          onError: function () {
            _agentState.busy = false;
            _agentState.runningTab = null;
            _agentState.stopping = false;
            _setInputDisabled(false);
            card.classList.remove("intervention-card-submitting");
            _restoreNavButtons();
          },
          onDone: function () {
            state.submitted = true;
            renderCollapsed(false);
            _interventionWrap = null;
          },
        }
      );
    }

    render();
    return card;
  }

  // Single POST + SSE via fetch + ReadableStream
  async function sendWithSSE(url, body, container, opts = {}) {
    let currentBubble = null;
    let currentWrap = null;
    let stepsContainer = null;
    let stepsList = null;
    let stepCount = 0;
    let stepItemsMap = {};
    let hasRealStep = false;

    // 流所属项目：身份校验用（切会话后旧流不再处理任何消息/状态）
    var _urlMatch = url.match(/\/api\/(?:ppt|content)\/([^/]+)/);
    var streamProjectId = (body && body.project_id) || (_urlMatch ? _urlMatch[1] : null);

    // 立即创建消息块 + 展开态步骤区域（含"正在处理中..."）
    function createAgentWrap() {
      if (currentWrap) return;

      // 复用已有气泡（人工介入恢复场景）：续接在同一个 agent 消息内，不新建
      if (opts.reuseWrap && opts.reuseWrap.isConnected) {
        currentWrap = opts.reuseWrap;
        currentBubble = currentWrap.querySelector(".message-bubble");
        if (!currentBubble) return;

        // 移除上一次的完成标记（"等待用户作答"）
        var doneEl = currentWrap.querySelector(".message-done");
        if (doneEl) doneEl.remove();

        // 恢复步骤区域：续接编号，保持折叠（标题随后续 step 事件更新）
        stepsContainer = currentWrap.querySelector(".steps-container");
        if (!stepsContainer) {
          // 历史气泡可能没有步骤容器（中断发生在最早阶段、无任何步骤时），补建一个
          stepsContainer = document.createElement("div");
          stepsContainer.className = "steps-container";
          stepsContainer.innerHTML = `
            <div class="steps-header">
              <span class="steps-title">⚙️ 执行步骤：正在执行...</span>
              <button class="btn steps-toggle">展开</button>
            </div>
            <div class="steps-list" hidden></div>
          `;
          // 保持与历史渲染一致的顺序：步骤区在文本之前
          var textEl = currentBubble.querySelector(".message-text");
          if (textEl) currentBubble.insertBefore(stepsContainer, textEl);
          else currentBubble.appendChild(stepsContainer);
        }
        stepsList = stepsContainer.querySelector(".steps-list");
        if (stepsList) {
          stepCount = stepsList.querySelectorAll(".step-item:not(.step-placeholder)").length;
          // 已有旧步骤 → 视为真实步骤，避免 removeStepsIfNoReal 误删
          if (stepCount > 0) hasRealStep = true;
          // 全程折叠：恢复执行也保持折叠，标题随后续 step 事件更新
          var reuseToggle = stepsContainer.querySelector(".steps-toggle");
          if (reuseToggle) reuseToggle.textContent = "展开";
        }
        return;
      }

      currentWrap = document.createElement("div");
      currentWrap.className = "message message-agent";
      currentWrap.innerHTML = `<div class="message-avatar message-avatar-agent">🤖</div>`;
      currentBubble = document.createElement("div");
      currentBubble.className = "message-bubble message-bubble-agent";
      currentWrap.appendChild(currentBubble);
      container.appendChild(currentWrap);

      stepsContainer = document.createElement("div");
      stepsContainer.className = "steps-container";
      stepsContainer.innerHTML = `
        <div class="steps-header">
          <span class="steps-title">⚙️ 执行步骤：正在执行...</span>
          <button class="btn steps-toggle">展开</button>
        </div>
        <div class="steps-list" hidden></div>
      `;
      currentBubble.appendChild(stepsContainer);
      stepsList = stepsContainer.querySelector(".steps-list");

      // 占位文字
      const placeholder = document.createElement("div");
      placeholder.className = "step-item step-placeholder";
      placeholder.textContent = "正在处理中...";
      stepsList.appendChild(placeholder);

      const toggleBtn = stepsContainer.querySelector(".steps-toggle");
      const _list2 = stepsList;
      toggleBtn.addEventListener("click", () => {
        const isHidden = _list2.hidden;
        _list2.hidden = !isHidden;
        toggleBtn.textContent = isHidden ? "折叠" : "展开";
      });
    }

    // 清除"正在处理中..."占位
    function clearPlaceholder() {
      if (!stepsList) return;
      const ph = stepsList.querySelector(".step-placeholder");
      if (ph) ph.remove();
    }

    // 如果没有真实步骤，移除整个步骤区域
    function removeStepsIfNoReal() {
      if (!hasRealStep && stepsContainer) {
        stepsContainer.remove();
        stepsContainer = null;
        stepsList = null;
      }
    }

    // 立即显示
    createAgentWrap();

    const handleMessage = (msg) => {
      const t = msg.type;
      if (t === "progress") {
        if (opts.progressFill) opts.progressFill.style.width = (msg.percent || 0) + "%";
        if (opts.progressStep) opts.progressStep.textContent = msg.current_step || "";
        if (opts.progressWrap) opts.progressWrap.hidden = false;
        container.scrollTop = container.scrollHeight;
      } else if (t === "step") {
        if (!hasRealStep) {
          clearPlaceholder();
          hasRealStep = true;
        }
        stepCount++;
        const stepItem = document.createElement("div");
        stepItem.className = "step-item";
        stepItem.textContent = `${stepCount}. ${msg.name || "未知步骤"}`;
        // 防御：stepsList 缺失时只更新标题，不中断整个流
        if (stepsList) {
          stepsList.appendChild(stepItem);
          // 有 tc_id 用 tc_id 做 key（并行 task 场景），否则用 code
          if (msg.code) stepItemsMap[msg.tc_id || msg.code] = stepItem;
        }
        // 标题实时展示当前步骤状态
        if (stepsContainer) {
          const titleEl = stepsContainer.querySelector(".steps-title");
          if (titleEl) titleEl.textContent = "⚙️ 执行步骤：" + (msg.name || "未知步骤");
        }
        container.scrollTop = container.scrollHeight;
      } else if (t === "step_done") {
        const stepItem = (msg.tc_id || msg.code) ? stepItemsMap[msg.tc_id || msg.code] : null;
        if (stepItem && msg.name) {
          const sub = document.createElement("div");
          sub.className = "step-done";
          sub.textContent = msg.name;
          stepItem.appendChild(sub);
        }
        // 标题实时展示最近完成步骤
        if (stepsContainer && msg.name) {
          const titleEl = stepsContainer.querySelector(".steps-title");
          if (titleEl) titleEl.textContent = "⚙️ 执行步骤：" + msg.name;
        }
        container.scrollTop = container.scrollHeight;
      } else if (t === "text") {
        removeStepsIfNoReal();
        let textEl = currentBubble.querySelector(".message-text");
        if (!textEl) {
          textEl = document.createElement("div");
          textEl.className = "message-text";
          currentBubble.appendChild(textEl);
        }
        textEl.textContent += msg.content || "";
        container.scrollTop = container.scrollHeight;
      } else if (t === "slide") {
        // 1. 更新全局骨架（幂等覆盖）
        if (msg.slides_meta && Array.isArray(msg.slides_meta)) {
          _streamingSlides = msg.slides_meta.map(function (s) {
            return {
              slide_index: s.slide_index,
              title: s.title || "",
              html_path: null,
              slide_text: null,
              narration: null,
            };
          });
        }
        // 2. 更新全局视频配置（若未加载过尺寸则顺便更新 _slideW/_slideH）
        if (msg.video_config) {
          if (!_slideSizeLoaded && msg.video_config.resolution) {
            var parts = msg.video_config.resolution.split("x");
            if (parts.length === 2 && parts[0] && parts[1]) {
              _slideW = parseInt(parts[0], 10);
              _slideH = parseInt(parts[1], 10);
              _slideSizeLoaded = true;
            }
          }
        }
        // 3. 用当前 slide 完整数据填充骨架中的对应项
        if (_streamingSlides.length > 0 && typeof msg.slide_index === "number") {
          var _sIdx = _streamingSlides.findIndex(function (s) { return s.slide_index === msg.slide_index; });
          if (_sIdx >= 0) {
            _streamingSlides[_sIdx] = {
              slide_index: msg.slide_index,
              title: msg.title || (_streamingSlides[_sIdx] && _streamingSlides[_sIdx].title) || "",
              html_path: msg.html_path || null,
              slide_text: msg.slide_text || null,
              narration: msg.narration || null,
            };
          }
        }
        // 4. 创建卡片，传入完整上下文
        var _allForCard = _streamingSlides && _streamingSlides.length > 0 ? _streamingSlides : null;
        appendSlideCard(container, msg, _allForCard);
      } else if (t === "human_intervention") {
        // 人工介入：渲染问题卡片（放在气泡外部），mode='live' 可交互
        removeStepsIfNoReal();
        // 保存当前气泡，供恢复接口复用（保证同一条 agent 消息内续接，不新建气泡）
        _interventionWrap = currentWrap;
        renderInterventionCard(msg, "live", container);
      } else if (t === "done") {
        removeStepsIfNoReal();
        if (stepsContainer) {
          // 中断（ask_user）显示"正在ask_user"，正常完成显示"已执行完成"；均触发折叠
          const titleEl = stepsContainer.querySelector(".steps-title");
          if (titleEl) titleEl.textContent = msg.interrupted ? "⚙️ 执行步骤：正在ask_user" : "⚙️ 执行步骤：已执行完成";
          if (stepsList) {
            stepsList.hidden = true;
            const toggleBtn = stepsContainer.querySelector(".steps-toggle");
            if (toggleBtn) toggleBtn.textContent = "展开";
          }
        }
        const doneEl = document.createElement("div");
        doneEl.className = "message-done";
        doneEl.textContent = "✅ " + (msg.summary || "完成");
        currentBubble.appendChild(doneEl);

        _agentState.busy = false;
        _agentState.runningTab = null;
        _agentState.stopping = false;
        _setInputDisabled(false);
        if (opts.progressWrap) opts.progressWrap.hidden = true;
        currentBubble = null;
        currentWrap = null;
        stepsContainer = null;
        stepsList = null;
        stepCount = 0;
        stepItemsMap = {};
        hasRealStep = false;
        if (opts.onDone) opts.onDone();
      } else if (t === "stopped") {
        // 用户主动停止：标题"已停止" + 折叠，收尾与 done 一致
        removeStepsIfNoReal();
        if (stepsContainer) {
          const titleEl = stepsContainer.querySelector(".steps-title");
          if (titleEl) titleEl.textContent = "⚙️ 执行步骤：已停止";
          if (stepsList) {
            stepsList.hidden = true;
            const toggleBtn = stepsContainer.querySelector(".steps-toggle");
            if (toggleBtn) toggleBtn.textContent = "展开";
          }
        }
        const stopEl = document.createElement("div");
        stopEl.className = "message-done";
        stopEl.textContent = "⏹ " + (msg.summary || "已停止");
        currentBubble.appendChild(stopEl);

        _agentState.busy = false;
        _agentState.runningTab = null;
        _agentState.stopping = false;
        _setInputDisabled(false);
        if (opts.progressWrap) opts.progressWrap.hidden = true;
        currentBubble = null;
        currentWrap = null;
        stepsContainer = null;
        stepsList = null;
        stepCount = 0;
        stepItemsMap = {};
        hasRealStep = false;
        if (opts.onDone) opts.onDone();
      } else if (t === "error") {
        // 用当前气泡展示错误
        currentBubble.className = "message-bubble message-bubble-error";
        currentBubble.textContent = `❌ ${msg.message || msg.error_code || "错误"}`;
        if (opts.progressWrap) opts.progressWrap.hidden = true;
        currentBubble = null;
        currentWrap = null;
        stepsContainer = null;
        stepsList = null;
        stepCount = 0;
        stepItemsMap = {};
        hasRealStep = false;
        _agentState.runningTab = null;
        _agentState.stopping = false;
        if (opts.onError) opts.onError(msg);
        throw new Error(msg.message || msg.error_code || "Agent error");
      }
    };

    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        if (opts.onHttpError) {
          const handled = await opts.onHttpError(response);
          if (handled) {
            // 调用方已处理错误（如恢复接口的 CHECKPOINT_MISSING），清理空气泡后返回
            if (currentWrap && !hasRealStep) currentWrap.remove();
            if (opts.progressWrap) opts.progressWrap.hidden = true;
            return;
          }
        }
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      // 记录当前活动流，供切会话时 cancel 停止旧流
      _agentState.sseReader = reader;
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop();

        for (const part of parts) {
          // 身份校验：流已不属于当前项目（已切会话），停止读取并丢弃所有后续消息
          if (appState.currentProjectId !== streamProjectId) {
            _agentState.sseReader = null;
            try { await reader.cancel(); } catch (_) { /* ignore */ }
            return;
          }

          const lines = part.split("\n");
          let eventType = "message";
          let dataLines = [];

          for (const line of lines) {
            if (line.startsWith("event:")) {
              eventType = line.slice(6).trim();
            } else if (line.startsWith("data:")) {
              dataLines.push(line.slice(5).trim());
            }
          }

          if (dataLines.length === 0) continue;
          const dataStr = dataLines.join("\n");
          if (dataStr === "{}" || !dataStr) continue;

          try {
            const msg = JSON.parse(dataStr);
            if (msg.type) {
              handleMessage(msg);
            } else {
              handleMessage({ type: eventType, ...msg });
            }
          } catch (e) {
            console.warn("Failed to parse SSE message:", dataStr, e);
          }
        }
      }
      _agentState.sseReader = null;
    } catch (err) {
      // 因切会话被 cancel 终止：不修改任何状态（busy/输入框/气泡），静默返回
      if (appState.currentProjectId !== streamProjectId) {
        _agentState.sseReader = null;
        return;
      }
      if (err.message && err.message.includes("Agent error")) {
        // 智能体推送 error 事件：恢复输入态（无 onError 的内容/PPT 场景也能正确收尾）
        _agentState.busy = false;
        _agentState.runningTab = null;
        _agentState.stopping = false;
        _setInputDisabled(false);
        if (opts.onError) opts.onError({ message: err.message });
        return;
      }
      // 用当前气泡展示错误
      if (currentBubble) {
        currentBubble.className = "message-bubble message-bubble-error";
        currentBubble.textContent = "❌ " + err.message;
      }
      _agentState.busy = false;
      _agentState.runningTab = null;
      _agentState.stopping = false;
      _setInputDisabled(false);
      if (opts.progressWrap) opts.progressWrap.hidden = true;
      if (opts.onError) opts.onError({ message: err.message });
    }
  }

  // 选项卡1：发送
  $("#chatSendBtn").addEventListener("click", sendContent);
  $("#chatInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendContent();
    }
  });
  // 停止正在运行的内容智能体（温和停止：当前工具调用完成后停止）
  async function _stopContentAgent() {
    if (!appState.currentProjectId) return;
    // 立即切换按钮为"正在停止"且禁用，防止重复点击；收尾时（stopped 事件/轮询）恢复
    _agentState.stopping = true;
    _setInputDisabled(true);
    try {
      await api("POST", `/api/content/${appState.currentProjectId}/stop`);
    } catch (_) {
      // 停止请求失败不阻塞：智能体可能刚好执行完成
    }
    // 不 cancel SSE 流：等后端自然收尾（收到 stopped 事件）
  }

  async function sendContent() {
    if (!appState.currentProjectId) { showAlert({ title: "提示", message: "请先选择或创建会话" }); return; }
    if (_agentState.busy) {
      // busy 时按钮为"停止"：调用停止接口
      await _stopContentAgent();
      return;
    }
    const text = $("#chatInput").value.trim();
    if (!text) return;
    appendMessage($("#chatContainer"), "user", text);
    $("#chatInput").value = "";
    _agentState.busy = true;
    _agentState.runningTab = "content";
    _setInputDisabled(true);

    await sendWithSSE(
      `/api/content/${appState.currentProjectId}`,
      {
        project_id: appState.currentProjectId,
        message: text,
        model_code: _contentModelCode,
      },
      $("#chatContainer"),
      {
        progressWrap: $("#contentProgress"),
        progressFill: $("#contentProgressFill"),
        progressStep: $("#contentProgressStep"),
        onDone: async () => {
          await appendContentCard($("#chatContainer"));
        },
      }
    );
  }

  // 选项卡2：发送
  $("#pptSendBtn").addEventListener("click", sendPpt);
  $("#pptInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendPpt(); }
  });
  async function sendPptMessage(text) {
    if (!appState.currentProjectId) { showAlert({ title: "提示", message: "请先选择或创建会话" }); return; }
    _streamingSlides = [];
    appendMessage($("#pptChatContainer"), "user", text);
    _agentState.busy = true;
    _agentState.runningTab = "ppt";
    _setInputDisabled(true);
    await sendWithSSE(
      `/api/ppt/${appState.currentProjectId}`,
      { project_id: appState.currentProjectId, message: text, model_code: _pptModelCode },
      $("#pptChatContainer"),
      {
        progressWrap: $("#pptProgress"),
        progressFill: $("#pptProgressFill"),
        progressStep: $("#pptProgressStep"),
      }
    );
  }
  // 停止正在运行的 PPT 智能体（温和停止：当前工具调用完成后停止）
  async function _stopPptAgent() {
    if (!appState.currentProjectId) return;
    // 立即切换按钮为"正在停止"且禁用，防止重复点击；收尾时（stopped 事件/轮询）恢复
    _agentState.stopping = true;
    _setInputDisabled(true);
    try {
      await api("POST", `/api/ppt/${appState.currentProjectId}/stop`);
    } catch (_) {
      // 停止请求失败不阻塞：智能体可能刚好执行完成
    }
    // 不 cancel SSE 流：等后端自然收尾（实时场景收到 stopped 事件 / 刷新后轮询读到 stopped）
    // 按钮保持"停止"态，直到收尾时 busy 置 false 恢复
  }

  async function sendPpt() {
    if (_agentState.busy) {
      // busy 时按钮为"停止"：调用停止接口
      await _stopPptAgent();
      return;
    }
    const text = $("#pptInput").value.trim();
    if (!text) return;
    $("#pptInput").value = "";
    await sendPptMessage(text);
  }

  // 加载模型下拉
  loadModelSelectors();
})();
