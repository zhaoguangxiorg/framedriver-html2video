// 视频设置（选项卡3）
(function () {
  var _videoTimers = [];  // 视频相关轮询 timer 集合，切会话时统一清理
  var _oneKeyTimer = null;   // 一键生成轮询（单例）
  var _advancedTimer = null; // 高级生成全局轮询（单例，一个轮询覆盖所有单张+合成按钮）
  function _addVideoTimer(t) { _videoTimers.push(t); }

  // 选段合成状态：勾选集合（打开弹窗时重置）；上次片段合成状态（轮询变化检测用）
  var _selectedIndexes = new Set();
  var _lastClipStatus = null;

  // 生成任务状态标志：一键生成进行中 / 高级弹框内单张或合成正在生成。
  // 任一为 true 时禁用"一键生成"按钮，防止并发生成任务抢资源、写文件冲突。
  var _oneKeyRunning = false;
  var _advancedBusy = false;

  // 统一刷新按钮状态：
  // - 一键生成按钮：任一生成任务进行中则置灰（弹框关闭后由高级轮询持续刷新）；
  // - 高级生成按钮：仅一键生成进行中禁用（弹框内状态由弹框自身管理）。
  function _syncGenButtons() {
    const btn = $("#generateVideoBtn");
    if (btn) {
      btn.disabled = _oneKeyRunning || _advancedBusy;
      btn.textContent = _oneKeyRunning ? "⏳ 正在生成..." : "🚀 一键生成视频";
      btn.classList.toggle("video-btn-generating", _oneKeyRunning);
    }
    const advBtn = $("#advancedGenerateBtn");
    if (advBtn) advBtn.disabled = _oneKeyRunning;
  }

  function _setGenBtnRunning(running) {
    _oneKeyRunning = running;
    _syncGenButtons();
  }

  function _setAdvancedBusy(busy) {
    _advancedBusy = busy;
    _syncGenButtons();
  }

  async function loadVoicePersonas() {
    try {
      const personas = await api("GET", "/api/video/voice-personas");
      const container = document.querySelector('.voice-options');
      if (!container) return;
      container.innerHTML = "";
      personas.forEach(p => {
        const label = document.createElement("label");
        label.innerHTML = `<input type="radio" name="voice_persona" value="${p.id}" /> ${p.name}`;
        container.appendChild(label);
      });
      // 默认选中 "default" 人设（后续 loadAndFillConfig 会用项目配置覆盖）
      const defaultRadio = container.querySelector('input[value="default"]');
      if (defaultRadio) defaultRadio.checked = true;
    } catch (_) { /* ignore */ }
  }

  // 颜色值互转：#RRGGBB <-> 0xRRGGBB；其他（命名色等）统一回退白色
  function _colorToHex(color) {
    if (!color) return "#ffffff";
    const c = String(color).toLowerCase();
    if (c.startsWith("#")) return c;
    if (c.startsWith("0x")) return "#" + c.slice(2);
    return "#ffffff";
  }
  // drawtext 认的颜色格式（fontcolor 支持 0xRRGGBB）
  function _colorToDrawtext(color) {
    return _colorToHex(color).replace("#", "0x");
  }
  // 字幕颜色预览文字实时跟随取色器
  function _applySubtitleColorUI() {
    const preview = document.getElementById("subtitleColorPreview");
    const input = document.getElementById("subtitleColorInput");
    if (!preview || !input) return;
    preview.style.color = input.value;
  }
  // 取色器 input 事件实时更新预览文字颜色
  (function () {
    const input = document.getElementById("subtitleColorInput");
    if (input) input.addEventListener("input", _applySubtitleColorUI);
  })();

  async function loadAndFillConfig() {
    if (!appState.currentProjectId) return;
    try {
      const cfg = await api("GET", `/api/video/${appState.currentProjectId}/config`);
      if (!cfg) return;
      // Fill aspect ratio
      if (cfg.aspect_ratio) {
        const radios = document.querySelectorAll('input[name="aspect_ratio"]');
        radios.forEach(r => { r.checked = (r.value === cfg.aspect_ratio); });
      }
      // Fill resolution
      if (cfg.resolution) {
        const resInput = document.querySelector('input[name="resolution"]');
        if (resInput) resInput.value = cfg.resolution;
      }
      // Fill voice persona radio
      if (cfg.voice_persona) {
        const radios = document.querySelectorAll('input[name="voice_persona"]');
        radios.forEach(r => { r.checked = (r.value === cfg.voice_persona); });
      }
      // 字幕：已配置字体（字体名或字体文件路径）才可操作；未配置则置灰（复选框 + 颜色选择器 + 预览）
      const subCheckbox = document.querySelector('input[name="enable_subtitles"]');
      const colorField = document.getElementById("subtitleColorField");
      const colorInput = document.getElementById("subtitleColorInput");
      if (subCheckbox) {
        if (cfg.subtitle_font || cfg.subtitle_font_file) {
          subCheckbox.disabled = false;
          subCheckbox.checked = !!cfg.enable_subtitles;
          if (colorField) colorField.classList.remove("subtitle-color-disabled");
          if (colorInput) {
            colorInput.disabled = false;
            colorInput.value = _colorToHex(cfg.subtitle_color);
          }
        } else {
          subCheckbox.disabled = true;
          subCheckbox.checked = false;
          if (colorField) colorField.classList.add("subtitle-color-disabled");
          if (colorInput) {
            colorInput.disabled = true;
            colorInput.value = "#ffffff";
          }
        }
      }
      _applySubtitleColorUI();
      // Lock aspect_ratio and resolution (determined by slide generation)
      document.querySelectorAll('input[name="aspect_ratio"]').forEach(r => { r.disabled = true; });
      const resInput = document.querySelector('input[name="resolution"]');
      if (resInput) resInput.disabled = true;
    } catch (_) { /* ignore */ }
  }

  // 渲染字幕警告（多 face 等提示），无警告时隐藏
  function _renderWarnings(containerId, warnings) {
    const el = document.getElementById(containerId);
    if (!el) return;
    const list = Array.isArray(warnings) ? warnings.filter(Boolean) : [];
    if (!list.length) { el.hidden = true; el.innerHTML = ""; return; }
    el.hidden = false;
    el.innerHTML = list.map(w => `<div class="video-warning-item">⚠️ ${w}</div>`).join("");
  }

  // 刷新后进入视频选项卡：检测一次，恢复按钮/状态（running 则启动轮询等待完成）
  async function checkVideoStatus() {
    if (!appState.currentProjectId) return;
    const pid = appState.currentProjectId;
    try {
      const p = await api("GET", `/api/video/${pid}/progress`);
      if (p.status === "running") {
        _setGenBtnRunning(true);
        $("#videoProgressArea").hidden = false;
        $("#videoResult").hidden = true;
        $("#videoProgressStep").textContent = "⏳ 正在生成中...";
        _renderWarnings("videoWarnings", []);
        _ensureOneKeyPolling(pid);
      } else if (p.status === "completed" || p.has_video) {
        $("#videoProgressArea").hidden = false;
        $("#videoProgressStep").textContent = "✅ 视频生成成功";
        $("#videoResult").hidden = false;
        $("#downloadBtn").href = `/api/video/${pid}/download`;
        _renderWarnings("videoWarnings", p.warnings);
      } else if (p.status === "failed") {
        $("#videoProgressArea").hidden = false;
        $("#videoProgressStep").textContent = "❌ " + (p.error || "生成失败");
        _renderWarnings("videoWarnings", p.warnings);
      }
    } catch (_) { /* ignore */ }
  }

  // Load config when tab 3 becomes active
  window.onTabChange = async function(tab) {
    if (tab == 3) {
      await loadVoicePersonas();
      await loadAndFillConfig();
      await checkVideoStatus();
    }
  };

  // 观看视频
  $("#watchVideoBtn").addEventListener("click", () => {
    if (!appState.currentProjectId) return;
    const video = $("#videoPlayer");
    video.src = `/api/video/${appState.currentProjectId}/download`;
    $("#videoPlayerModal").hidden = false;
    video.play();
  });

  // 关闭视频播放
  $("#videoPlayerCloseBtn").addEventListener("click", () => {
    const video = $("#videoPlayer");
    video.pause();
    video.src = "";
    $("#videoPlayerModal").hidden = true;
  });

  // ---- 分享视频 ----

  // 打开分享弹窗：查询项目已绑定数字并预填；clipFile 传入时分享对应片段
  async function openShareModal(clipFile) {
    if (!appState.currentProjectId) { showAlert({ title: "提示", message: "请先选择会话" }); return; }
    $("#shareCodeInput").value = "";
    $("#shareResult").hidden = true;
    try {
      const r = await api("GET", `/api/share/current?project_id=${encodeURIComponent(appState.currentProjectId)}`);
      if (r && r.code) $("#shareCodeInput").value = r.code;
    } catch (_) { /* 未绑定过则留空 */ }
    $("#shareModal").dataset.clipFile = clipFile || "";
    $("#shareModal").hidden = false;
    $("#shareCodeInput").focus();
  }

  $("#shareVideoBtn").addEventListener("click", () => openShareModal());
  $("#shareCloseBtn").addEventListener("click", () => { $("#shareModal").hidden = true; });
  $("#shareCancelBtn").addEventListener("click", () => { $("#shareModal").hidden = true; });

  // 确认：绑定/修改数字映射，成功后显示分享链接
  $("#shareConfirmBtn").addEventListener("click", async () => {
    if (!appState.currentProjectId) return;
    const code = $("#shareCodeInput").value.trim();
    if (!code) { showAlert({ title: "提示", message: "请输入分享数字" }); return; }
    const btn = $("#shareConfirmBtn");
    btn.disabled = true;
    try {
      const r = await api("POST", "/api/share", {
        project_id: appState.currentProjectId,
        code: code,
        clip_file: $("#shareModal").dataset.clipFile || undefined,
      });
      $("#shareUrlInput").value = window.location.origin + r.share_url;
      $("#shareResult").hidden = false;
    } catch (err) {
      showAlert({ title: "分享失败", message: err.message, type: "error" });
    } finally {
      btn.disabled = false;
    }
  });

  // 复制分享链接
  $("#shareCopyBtn").addEventListener("click", async () => {
    const url = $("#shareUrlInput").value;
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
    } catch (_) {
      $("#shareUrlInput").select();
      document.execCommand("copy");
    }
    showAlert({ title: "提示", message: "链接已复制，发送给他人即可观看" });
  });

  // 通用免责声明入口：跳转独立声明页面
  $("#videoDeclareLink").addEventListener("click", () => {
    window.open("/declaration.html", "_blank");
  });

  $("#videoForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!appState.currentProjectId) { showAlert({ title: "提示", message: "请先选择会话" }); return; }
    const fd = new FormData(e.target);
    const body = {};
    for (const [k, v] of fd.entries()) {
      if (!v) continue;
      body[k] = v;
    }
    // 字幕复选框：未勾选/置灰时不在 FormData 中，显式提交布尔值（false 即无字幕）
    const subCheckbox = document.querySelector('input[name="enable_subtitles"]');
    if (subCheckbox) body["enable_subtitles"] = subCheckbox.checked;
    // 字幕颜色：取色器值 #RRGGBB → drawtext 认的 0xRRGGBB
    const subColorInput = document.getElementById("subtitleColorInput");
    if (subColorInput) body["subtitle_color"] = _colorToDrawtext(subColorInput.value);
    // 按钮进入"正在生成"状态（不显示进度条，只做状态翻转）
    _setGenBtnRunning(true);
    _renderWarnings("videoWarnings", []);
    $("#videoProgressArea").hidden = false;
    $("#videoResult").hidden = true;
    $("#videoProgressStep").textContent = "⏳ 正在生成中...";
    try {
      await api("POST", `/api/video/${appState.currentProjectId}`, body);
    } catch (err) {
      _setGenBtnRunning(false);
      $("#videoProgressStep").textContent = "❌ " + err.message;
      return;
    }
    // 轮询只做状态翻转检测（不渲染进度）
    const submitPid = appState.currentProjectId;
    _ensureOneKeyPolling(submitPid);
    _checkOneKeyStatus(submitPid);
  });

  // 一键生成状态轮询（单例）：running 期间按钮保持"正在生成"，完成/失败时翻转并停止
  function _ensureOneKeyPolling(pid) {
    if (_oneKeyTimer) return;
    _oneKeyTimer = setInterval(function () { _checkOneKeyStatus(pid); }, 3000);
    _addVideoTimer(_oneKeyTimer);
  }

  async function _checkOneKeyStatus(pid) {
    try {
      const p = await api("GET", `/api/video/${pid}/progress`);
      if (p.status === "running") {
        _setGenBtnRunning(true);
        $("#videoProgressArea").hidden = false;
        $("#videoProgressStep").textContent = "⏳ 正在生成中...";
        _renderWarnings("videoWarnings", []);
        return;
      }
      // 非运行中：停止轮询
      if (_oneKeyTimer) { clearInterval(_oneKeyTimer); _oneKeyTimer = null; }
      _setGenBtnRunning(false);
      if (p.status === "completed") {
        $("#videoProgressArea").hidden = false;
        $("#videoProgressStep").textContent = "✅ 视频生成成功";
        $("#videoResult").hidden = false;
        $("#downloadBtn").href = `/api/video/${pid}/download`;
        _renderWarnings("videoWarnings", p.warnings);
      } else if (p.status === "failed") {
        $("#videoProgressArea").hidden = false;
        $("#videoResult").hidden = true;
        $("#videoProgressStep").textContent = "❌ " + (p.error || "生成失败");
        _renderWarnings("videoWarnings", p.warnings);
      }
    } catch (_) { /* ignore */ }
  }

  // ---- 高级视频生成 ----

  // 5a: "高级生成" 按钮
  $("#advancedGenerateBtn").addEventListener("click", openAdvancedModal);

  // 5d': "查看历史合成" 按钮（常驻元素，一次性绑定）→ 打开历史合成弹窗
  $("#advancedHistoryBtn").addEventListener("click", () => {
    if (!appState.currentProjectId) { showAlert({ title: "提示", message: "请先选择会话" }); return; }
    renderClips(appState.currentProjectId);
    $("#clipHistoryModal").hidden = false;
  });
  $("#clipHistoryCloseBtn").addEventListener("click", () => { $("#clipHistoryModal").hidden = true; });

  // 5g: 关闭按钮
  $("#advancedCloseBtn").addEventListener("click", () => {
    $("#advancedModal").hidden = true;
  });

  // 5b: 打开高级生成弹窗
  async function openAdvancedModal() {
    if (!appState.currentProjectId) { showAlert({ title: "提示", message: "请先选择会话" }); return; }
    const pid = appState.currentProjectId;

    let slides, status;
    try {
      [slides, status] = await Promise.all([
        api("GET", `/api/slides/${pid}`),
        api("GET", `/api/video/${pid}/slides/status`),
      ]);
    } catch (e) {
      _renderWarnings("advancedWarnings", []);
      showAlert({ title: "加载失败", message: e.message, type: "error" });
      return;
    }

    const grid = $("#advancedGrid");
    grid.innerHTML = "";

    // 重置勾选集合与片段状态检测
    _selectedIndexes.clear();
    _lastClipStatus = null;

    const statusMap = {};
    if (status && status.slides) {
      status.slides.forEach(s => { statusMap[s.slide_index] = s; });
    }

    slides.forEach(sl => {
      const card = window.createSlideCard(sl, slides, {
        defaultTab: "narration",
        // 勾选框渲染在标题前；change 由卡片级事件委托处理（render() 重建后仍有效）
        titlePrefix: (s) =>
          `<label class="clip-checkbox" title="勾选以合成所选片段">` +
          `<input type="checkbox" class="clip-check" data-index="${s.slide_index}" />选</label>`,
      });
      card.dataset.slideIndex = sl.slide_index;  // 供全局轮询反查该卡片
      const slideStatus = statusMap[sl.slide_index] || {};
      const hasSegment = slideStatus.has_segment;

      // 卡片级事件委托：勾选框勾选/取消（标题前缀在 render 重建后无需重复绑定）
      card.addEventListener("change", (e) => {
        const cb = e.target;
        if (!cb || !cb.classList || !cb.classList.contains("clip-check")) return;
        const si = parseInt(cb.dataset.index, 10);
        if (cb.checked) _selectedIndexes.add(si);
        else _selectedIndexes.delete(si);
        _updateSelectAllUI(slides.length);
      });

      const actions = document.createElement("div");
      actions.className = "video-actions-right";

      // 5c: 生成按钮
      const genBtn = document.createElement("button");
      genBtn.className = "video-btn video-btn-gen";
      genBtn.textContent = hasSegment ? "🎬 重新生成视频" : "🎬 生成视频";
      genBtn.addEventListener("click", () => genSlideVideo(pid, sl.slide_index, genBtn));

      // 5e: 预览按钮
      const previewBtn = document.createElement("button");
      previewBtn.className = "video-btn video-btn-preview";
      previewBtn.textContent = "👁 观看视频";
      if (!hasSegment) previewBtn.disabled = true;
      previewBtn.addEventListener("click", () => previewSlideVideo(pid, sl.slide_index));

      // 5f: 下载按钮
      const downloadBtn = document.createElement("a");
      downloadBtn.className = "video-btn video-btn-download";
      downloadBtn.textContent = "⬇ 下载视频";
      downloadBtn.href = `/api/video/${pid}/slide/${sl.slide_index}/download`;
      downloadBtn.setAttribute("download", "");
      if (!hasSegment) downloadBtn.style.pointerEvents = "none";

      actions.appendChild(genBtn);
      actions.appendChild(previewBtn);
      actions.appendChild(downloadBtn);
      card.querySelector(".slide-card-actions").appendChild(actions);
      grid.appendChild(card);
    });

    _updateSelectAllUI(slides.length);

    // 应用当前状态到所有按钮 + 有任务运行则启动全局轮询（刷新后打开弹窗恢复状态）
    _renderWarnings("advancedWarnings", status.warnings);
    _applyAdvancedStatus(pid, status);
    _ensureAdvancedPolling(pid);
    _pollAdvanced(pid);

    // 5d: 更新合成按钮文字
    updateConcatBtn(pid, status);

    // 全选：勾选/取消全部卡片勾选框（一次性绑定，弹窗元素常驻）
    const selectAllBox = $("#advancedSelectAll");
    if (selectAllBox) {
      selectAllBox.checked = false;
      selectAllBox.onchange = () => {
        grid.querySelectorAll(".clip-check").forEach(cb => {
          cb.checked = selectAllBox.checked;
          const si = parseInt(cb.dataset.index, 10);
          if (selectAllBox.checked) _selectedIndexes.add(si);
          else _selectedIndexes.delete(si);
        });
        _updateSelectAllUI(slides.length);
      };
    }

    // 片段合成完成/失败提示由全局轮询负责，历史列表在「查看历史合成」弹窗中查看
    $("#advancedModal").hidden = false;
  }

  // 全选勾选框与已选计数的 UI 同步
  function _updateSelectAllUI(totalSlides) {
    const countEl = $("#advancedSelectCount");
    const allBox = $("#advancedSelectAll");
    if (countEl) countEl.textContent = `已选 ${_selectedIndexes.size} 张`;
    if (allBox) allBox.checked = totalSlides > 0 && _selectedIndexes.size === totalSlides;
  }

  // 5d: 更新合成按钮
  async function updateConcatBtn(pid, status) {
    const btn = $("#advancedConcatBtn");
    if (!btn) return;
    const hasFinal = status && status.has_final;
    const concatStatus = status && status.concat_status;
    // 任一单张正在生成或片段合成进行中时禁止完整合成（避免并发占用资源）
    const anyGenerating = (status && status.slides || []).some(function (s) { return s.generating; })
      || (status && status.clip_status === "running");

    if (concatStatus === "running") {
      btn.disabled = true;
      btn.textContent = "⏳ 合成中...";
      btn.classList.add("video-btn-generating");
      btn.title = "";
    } else if (anyGenerating) {
      btn.disabled = true;
      // 片段合成进行中 → 显示"合成中"并闪烁；单张生成中 → 保持"合成视频"（等单张完成）
      if (status && status.clip_status === "running") {
        btn.textContent = "⏳ 合成中...";
        btn.classList.add("video-btn-generating");
        btn.title = "";
      } else {
        btn.textContent = "🎬 合成视频";
        btn.classList.remove("video-btn-generating");
        btn.title = "有幻灯片正在生成，请等待完成后再合成";
      }
    } else if (concatStatus === "failed") {
      btn.disabled = false;
      btn.textContent = "❌ 合成失败，点击重试";
      btn.classList.remove("video-btn-generating");
      btn.title = "";
    } else if (hasFinal) {
      btn.disabled = false;
      btn.textContent = "🎬 合成视频";
      btn.classList.remove("video-btn-generating");
      btn.title = "";
    } else {
      btn.disabled = false;
      btn.textContent = "🎬 合成视频";
      btn.classList.remove("video-btn-generating");
      btn.title = "";
    }

    const newBtn = btn.cloneNode(true);
    btn.parentNode.replaceChild(newBtn, btn);
    newBtn.addEventListener("click", () => concatVideo(pid));
  }

  // 5c: 生成单张幻灯片视频（状态由全局轮询统一管理）
  async function genSlideVideo(pid, slideIndex, genBtn) {
    genBtn.disabled = true;
    genBtn.textContent = "⏳ 生成中...";
    genBtn.classList.add("video-btn-generating");

    // 携带当前表单的视频设置（随请求保存到项目配置）
    const body = {};
    const personaRadio = document.querySelector('input[name="voice_persona"]:checked');
    if (personaRadio) body["voice_persona"] = personaRadio.value;
    const subCheckbox = document.querySelector('input[name="enable_subtitles"]');
    if (subCheckbox) body["enable_subtitles"] = subCheckbox.checked;
    const subColorInput = document.getElementById("subtitleColorInput");
    if (subColorInput) body["subtitle_color"] = _colorToDrawtext(subColorInput.value);

    try {
      await api("POST", `/api/video/${pid}/slide/${slideIndex}`, body);
    } catch (e) {
      genBtn.disabled = false;
      genBtn.textContent = "🎬 生成视频";
      genBtn.classList.remove("video-btn-generating");
      showAlert({ title: "生成失败", message: e.message, type: "error" });
      return;
    }

    // 启动全局轮询（单例），一次刷新整个列表所有按钮状态
    _ensureAdvancedPolling(pid);
    _pollAdvanced(pid);
  }

  // 5d: 合成视频：按勾选状态分流 —— 未勾选提示；勾选部分合成片段；
  //      勾选全部合成 final_video.mp4（原逻辑，位置不变）。状态由全局轮询统一管理。
  async function concatVideo(pid) {
    const btn = $("#advancedConcatBtn");
    if (!btn) return;
    if (!_selectedIndexes.size) {
      showAlert({ title: "提示", message: "请先勾选要合成的幻灯片：在幻灯片标题前勾选，或点击上方「全选」" });
      return;
    }
    // 校验：所选幻灯片必须都已生成单张视频，缺一不可
    let status;
    try {
      status = await api("GET", `/api/video/${pid}/slides/status`);
    } catch (_) { status = null; }
    if (status && status.slides) {
      const missing = Array.from(_selectedIndexes)
        .map(function (si) { return parseInt(si, 10); })
        .filter(function (si) {
          const s = status.slides.find(function (x) { return x.slide_index === si; });
          return !s || !s.has_segment;
        })
        .sort(function (a, b) { return a - b; });
      if (missing.length) {
        showAlert({ title: "提示", message: `以下幻灯片尚未生成视频，请先生成后再合成：${missing.join("、")}` });
        return;
      }
    }
    const total = document.querySelectorAll("#advancedGrid .clip-check").length;
    const isAll = total > 0 && _selectedIndexes.size >= total;

    btn.disabled = true;
    btn.textContent = "⏳ 合成中...";
    btn.classList.add("video-btn-generating");

    try {
      if (isAll) {
        await api("POST", `/api/video/${pid}/concat`);
      } else {
        const indexes = Array.from(_selectedIndexes).sort((a, b) => a - b);
        await api("POST", `/api/video/${pid}/clips`, { slide_indexes: indexes });
      }
    } catch (e) {
      btn.disabled = false;
      btn.textContent = "🎬 合成视频";
      btn.classList.remove("video-btn-generating");
      showAlert({ title: "合成失败", message: e.message, type: "error" });
      return;
    }

    // 启动全局轮询（单例）
    _ensureAdvancedPolling(pid);
    _pollAdvanced(pid);
  }

  // 渲染片段历史列表（合成来源 | 观看/下载/分享/删除）
  async function renderClips(pid) {
    const tbody = $("#videoClipsList");
    const empty = $("#videoClipsEmpty");
    if (!tbody) return;
    let data;
    try {
      data = await api("GET", `/api/video/${pid}/clips`);
    } catch (_) { return; }
    const clips = (data && data.clips) || [];
    tbody.innerHTML = "";
    if (empty) empty.hidden = clips.length > 0;
    if (!clips.length) return;

    // 分离 final（完整视频）和普通片段：final 始终在最上方，普通片段按最新在前
    const finalClip = clips.find(function (c) { return c.type === "final"; });
    const normalClips = clips.filter(function (c) { return c.type !== "final"; }).reverse();
    const ordered = finalClip ? [finalClip].concat(normalClips) : normalClips;

    ordered.forEach(function (clip) {
      const isFinal = clip.type === "final";
      const tr = document.createElement("tr");
      const tdSrc = document.createElement("td");
      tdSrc.className = "clip-src-cell";
      // final 类型：合成来源名称直接显示"所有幻灯片"（不带"幻灯片"前缀）
      const srcName = isFinal
        ? escapeHtml(clip.video_name)
        : ("幻灯片 " + escapeHtml(clip.video_name));
      tdSrc.innerHTML =
        `<div class="clip-src-name">${srcName}</div>` +
        `<div class="clip-src-time">${escapeHtml(clip.created_at)}</div>`;

      const tdOps = document.createElement("td");
      tdOps.className = "clip-ops-cell";
      const base = `/api/video/${pid}/clips/${encodeURIComponent(clip.file_name)}`;

      const watchBtn = document.createElement("button");
      watchBtn.className = "video-btn video-btn-preview";
      watchBtn.textContent = "👁 观看";
      watchBtn.addEventListener("click", function () {
        const video = $("#videoPlayer");
        video.src = base + "/download?t=" + Date.now();
        $("#videoPlayerModal").hidden = false;
        video.play();
      });

      const dl = document.createElement("a");
      dl.className = "video-btn video-btn-download";
      dl.textContent = "⬇ 下载";
      dl.href = base + "/download";
      dl.setAttribute("download", "");

      const shareBtn = document.createElement("button");
      shareBtn.className = "video-btn video-btn-share";
      shareBtn.textContent = "🔗 分享";
      // final 类型分享完整视频（不传 clip_file）；片段传 clip.file_name
      shareBtn.addEventListener("click", function () {
        openShareModal(isFinal ? "" : clip.file_name);
      });

      tdOps.appendChild(watchBtn);
      tdOps.appendChild(dl);
      tdOps.appendChild(shareBtn);

      // final 类型（完整视频）不显示删除按钮
      if (!isFinal) {
        const delBtn = document.createElement("button");
        delBtn.className = "video-btn video-btn-delete";
        delBtn.textContent = "🗑 删除";
        delBtn.addEventListener("click", function () { deleteClip(pid, clip.file_name); });
        tdOps.appendChild(delBtn);
      }

      tr.appendChild(tdSrc);
      tr.appendChild(tdOps);
      tbody.appendChild(tr);
    });
  }

  // 删除片段（自定义确认弹窗，避免系统 confirm）
  async function deleteClip(pid, file_name) {
    const ok = await showConfirm({
      title: "删除片段",
      message: `确定删除片段 ${file_name} 吗？删除后不可恢复。`,
      confirmText: "删除",
    });
    if (!ok) return;
    try {
      await api("DELETE", `/api/video/${pid}/clips/${encodeURIComponent(file_name)}`);
    } catch (e) {
      showAlert({ title: "删除失败", message: e.message, type: "error" });
      return;
    }
    renderClips(pid);
  }
  function _ensureAdvancedPolling(pid) {
    if (_advancedTimer) return;
    _advancedTimer = setInterval(function () { _pollAdvanced(pid); }, 3000);
    _addVideoTimer(_advancedTimer);
  }

  async function _pollAdvanced(pid) {
    try {
      const status = await api("GET", `/api/video/${pid}/slides/status`);
      _renderWarnings("advancedWarnings", status.warnings);
      _applyAdvancedStatus(pid, status);
      updateConcatBtn(pid, status);
      // 片段合成状态变化：完成/失败后刷新历史列表并提示
      if (status.clip_status !== _lastClipStatus) {
        _lastClipStatus = status.clip_status;
        if (status.clip_status === "completed") {
          renderClips(pid);
        } else if (status.clip_status === "failed") {
          renderClips(pid);
          showAlert({ title: "片段合成失败", message: status.clip_error || "未知错误", type: "error" });
        }
      }
      // 同步"高级生成忙碌"标志：弹框关闭后仍由该轮询刷新一键生成按钮置灰状态
      const anyRunning = (status.slides || []).some(function (s) { return s.generating; })
        || status.concat_status === "running"
        || status.clip_status === "running";
      _setAdvancedBusy(anyRunning);
      // 自动停止：所有单张均不在生成且合成与片段合成均未在运行
      if (!anyRunning && _advancedTimer) {
        clearInterval(_advancedTimer);
        _advancedTimer = null;
      }
    } catch (_) { /* ignore */ }
  }

  // 根据整个列表状态统一更新每张卡片的按钮
  function _applyAdvancedStatus(pid, status) {
    const grid = $("#advancedGrid");
    if (!grid) return;
    const statusMap = {};
    if (status && status.slides) {
      status.slides.forEach(function (s) { statusMap[s.slide_index] = s; });
    }
    grid.querySelectorAll(".slide-card").forEach(function (card) {
      const si = parseInt(card.dataset.slideIndex, 10);
      if (isNaN(si)) return;
      const st = statusMap[si] || {};
      const genBtn = card.querySelector(".video-btn-gen");
      const previewBtn = card.querySelector(".video-btn-preview");
      const downloadBtn = card.querySelector(".video-btn-download");
      if (!genBtn) return;
      if (st.generating) {
        genBtn.disabled = true;
        genBtn.textContent = "⏳ 生成中...";
        genBtn.classList.add("video-btn-generating");
        genBtn.title = "";
        if (previewBtn) previewBtn.disabled = true;
        if (downloadBtn) downloadBtn.style.pointerEvents = "none";
      } else if (st.has_segment) {
        genBtn.disabled = false;
        genBtn.textContent = "🎬 重新生成视频";
        genBtn.classList.remove("video-btn-generating");
        genBtn.title = "";
        if (previewBtn) previewBtn.disabled = false;
        if (downloadBtn) downloadBtn.style.pointerEvents = "";
      } else if (st.error) {
        genBtn.disabled = false;
        genBtn.textContent = "🎬 重试生成";
        genBtn.classList.remove("video-btn-generating");
        genBtn.title = st.error;
        if (previewBtn) previewBtn.disabled = true;
        if (downloadBtn) downloadBtn.style.pointerEvents = "none";
      } else {
        genBtn.disabled = false;
        genBtn.textContent = "🎬 生成视频";
        genBtn.classList.remove("video-btn-generating");
        genBtn.title = "";
        if (previewBtn) previewBtn.disabled = true;
        if (downloadBtn) downloadBtn.style.pointerEvents = "none";
      }
    });
  }

  // 5e: 预览幻灯片视频
  function previewSlideVideo(pid, slideIndex) {
    const video = $("#videoPlayer");
    video.src = `/api/video/${pid}/slide/${slideIndex}/download?t=${Date.now()}`;
    $("#videoPlayerModal").hidden = false;
    video.play();
  }

  // 切会话时清理所有视频轮询 timer（整片进度/单张生成/合成），避免旧轮询写入新会话 UI
  window._cleanupVideoState = function () {
    _videoTimers.forEach(function (t) { clearInterval(t); });
    _videoTimers = [];
    _oneKeyTimer = null;
    _advancedTimer = null;
    // 重置生成状态标志并恢复按钮，避免切会话后按钮残留禁用
    _oneKeyRunning = false;
    _advancedBusy = false;
    // 重置选段合成状态
    _selectedIndexes.clear();
    _lastClipStatus = null;
    _syncGenButtons();
  };
})();
