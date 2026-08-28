// 设置页（左导航 + 右内容面板）
// 依赖：app.js 中全局的 api() / $() / $$() / escapeHtml()

let _models = [];
let _dialogOnOk = null;
let _modelsLoaded = false;   // 只在进入"模型管理"面板时加载一次

// ---- 设置弹窗 ----
function openSettings() {
  $("#settingsModal").hidden = false;
  // 默认显示"通用"面板；模型管理面板在点击时再懒加载
  switchSettingsPane("general");
}

function closeSettings() {
  $("#settingsModal").hidden = true;
}

// ---- 导航切换（隐藏层方式：class 控制显隐，非 hidden 属性） ----
function switchSettingsPane(paneKey) {
  // 导航高亮
  $$("#settingsNav .settings-nav-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.pane === paneKey);
  });
  // 面板显隐：只显示当前选中的，其余隐藏
  $$(".settings-pane").forEach((pane) => {
    pane.classList.toggle("active", pane.dataset.pane === paneKey);
  });
  // 懒加载：进入"模型管理"面板时拉列表
  if (paneKey === "models" && !_modelsLoaded) {
    loadModels();
  }
}

$("#settingsNav").addEventListener("click", (e) => {
  const item = e.target.closest(".settings-nav-item");
  if (!item) return;
  if (item.dataset.pane === "declaration") {
    // 免责声明为独立页面，新标签打开
    closeSettings();
    window.open("/declaration.html", "_blank");
    return;
  }
  switchSettingsPane(item.dataset.pane);
});

// ---- 模型列表 ----
async function loadModels() {
  const tbody = $("#modelTableBody");
  tbody.innerHTML = `<tr><td colspan="7" class="settings-empty">加载中...</td></tr>`;
  try {
    _models = await api("GET", "/api/models");
    _modelsLoaded = true;
    renderModelTable();
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" class="settings-empty">加载失败：${escapeHtml(e.message)}</td></tr>`;
  }
}

function renderModelTable() {
  const tbody = $("#modelTableBody");
  if (!_models.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="settings-empty">暂无模型，点击「+ 新增模型」添加</td></tr>`;
    return;
  }
  tbody.innerHTML = _models.map(renderModelRow).join("");
}

function renderModelRow(m) {
  const def = m.is_default == 1
    ? `<span class="settings-badge settings-badge-default">默认</span>`
    : `<span class="settings-badge settings-badge-muted">—</span>`;
  const en = m.enabled == 1
    ? `<span class="settings-badge settings-badge-enabled">启用</span>`
    : `<span class="settings-badge settings-badge-disabled">禁用</span>`;
  const baseUrl = m.base_url ? escapeHtml(m.base_url) : `<span class="settings-badge-muted">—</span>`;
  return `
    <tr>
      <td>${escapeHtml(m.name)}</td>
      <td>${escapeHtml(m.model_provider)}</td>
      <td>${escapeHtml(m.model_name)}</td>
      <td>${baseUrl}</td>
      <td>${def}</td>
      <td>${en}</td>
      <td class="col-actions">
        <button class="btn row-btn" data-action="edit" data-id="${m.id}">编辑</button>
        <button class="btn row-btn" data-action="delete" data-id="${m.id}">删除</button>
      </td>
    </tr>
  `;
}

$("#modelTableBody").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-action]");
  if (!btn) return;
  const { action, id } = btn.dataset;
  if (action === "edit") openModelForm(id);
  else if (action === "delete") deleteModel(id);
});

// ---- 模型表单 ----
// name 自动同步：用户未手动改过 name 时，跟随 model_name 填充
let _nameTouched = false;

function openModelForm(id) {
  const form = $("#modelForm");
  form.reset();
  $("#modelFormId").value = "";
  _nameTouched = false;  // 重置同步标志
  if (id) {
    const m = _models.find((x) => x.id == id);
    if (m) {
      setModelFormValues(m);
      $("#modelFormTitle").textContent = "编辑模型";
      // 编辑时若 name != model_name，视为用户已自定义
      _nameTouched = !!(m.name && m.model_name && m.name !== m.model_name);
    }
  } else {
    $("#modelFormTitle").textContent = "新增模型";
    $("#mf_enabled").checked = true;
  }
  $("#modelFormModal").hidden = false;
}

function setModelFormValues(m) {
  $("#modelFormId").value = m.id;
  $("#mf_name").value = m.name || "";
  $("#mf_model_name").value = m.model_name || "";
  $("#mf_model_provider").value = m.model_provider || "";
  $("#mf_base_url").value = m.base_url || "";
  $("#mf_api_key").value = "";     // 编辑时 api_key 留空表示不修改
  $("#mf_temperature").value = m.temperature != null ? m.temperature : "";
  $("#mf_max_tokens").value = m.max_tokens != null ? m.max_tokens : "";
  $("#mf_is_default").checked = m.is_default == 1;
  $("#mf_enabled").checked = m.enabled == 1;
}

function closeModelForm() {
  $("#modelFormModal").hidden = true;
}

async function saveModel() {
  const id = $("#modelFormId").value;
  const name = $("#mf_name").value.trim();
  const model_name = $("#mf_model_name").value.trim();
  const model_provider = $("#mf_model_provider").value.trim();
  const base_url = $("#mf_base_url").value.trim();
  const api_key = $("#mf_api_key").value;
  const temperature = $("#mf_temperature").value;
  const max_tokens = $("#mf_max_tokens").value;
  const is_default = $("#mf_is_default").checked ? 1 : 0;
  const enabled = $("#mf_enabled").checked ? 1 : 0;

  if (!model_name || !model_provider) {
    showDialog({ title: "提示", text: "请填写必填项：提供商、模型名称", okText: "确定" });
    return;
  }
  // name 未填则默认等于 model_name
  const finalName = name || model_name;

  const body = {
    name: finalName,
    model_name,
    model_provider,
    base_url: base_url || null,
    temperature: temperature ? parseFloat(temperature) : null,
    max_tokens: max_tokens ? parseInt(max_tokens, 10) : null,
    is_default,
    enabled,
  };

  const saveBtn = $("#modelFormSaveBtn");
  saveBtn.disabled = true;
  try {
    if (id) {
      if (api_key) body.api_key = api_key;
      await api("PUT", `/api/models/${id}`, body);
    } else {
      if (!api_key) {
        showDialog({ title: "提示", text: "新增模型时 api_key 必填", okText: "确定" });
        return;
      }
      body.api_key = api_key;
      await api("POST", "/api/models", body);
    }
    closeModelForm();
    await loadModels();
  } catch (e) {
    showDialog({ title: "保存失败", text: e.message, okText: "确定" });
  } finally {
    saveBtn.disabled = false;
  }
}

// model_name 输入时，若用户未手动改过 name，则同步填充 name
$("#mf_model_name").addEventListener("input", () => {
  if (!_nameTouched) {
    $("#mf_name").value = $("#mf_model_name").value;
  }
});
// 用户手动改 name 后，标记为已自定义，不再自动同步
$("#mf_name").addEventListener("input", () => {
  _nameTouched = true;
});

// ---- 删除（自定义确认弹窗） ----
function deleteModel(id) {
  const m = _models.find((x) => x.id == id);
  const name = m ? m.name : "";
  showDialog({
    title: "确认删除",
    text: `确定删除模型「${name || id}」？此操作不可恢复。`,
    okText: "确认删除",
    showCancel: true,
    onOk: () => doDeleteModel(id),
  });
}

async function doDeleteModel(id) {
  try {
    await api("DELETE", `/api/models/${id}`);
    await loadModels();
  } catch (e) {
    showDialog({ title: "删除失败", text: e.message, okText: "确定" });
  }
}

// ---- 通用对话弹窗（复用删除确认弹窗，避免系统 alert/confirm） ----
function showDialog({ title = "提示", text = "", okText = "确定", showCancel = false, onOk = null }) {
  const modal = $("#deleteConfirmModal");
  modal.querySelector(".modal-header span").textContent = title;
  $("#deleteConfirmText").textContent = text;
  $("#deleteConfirmOkBtn").textContent = okText;
  $("#deleteConfirmCancelBtn").hidden = !showCancel;
  _dialogOnOk = onOk;
  modal.hidden = false;
}

function closeDialog() {
  $("#deleteConfirmModal").hidden = true;
  _dialogOnOk = null;
}

// ---- 事件绑定 ----
$("#settingsBtn").addEventListener("click", openSettings);
$("#settingsCloseBtn").addEventListener("click", closeSettings);
// ---- 关于弹窗 ----
$("#aboutBtn").addEventListener("click", () => { $("#aboutModal").hidden = false; });
$("#aboutCloseBtn").addEventListener("click", () => { $("#aboutModal").hidden = true; });
$("#addModelBtn").addEventListener("click", () => openModelForm());
$("#modelFormCloseBtn").addEventListener("click", closeModelForm);
$("#modelFormCancelBtn").addEventListener("click", closeModelForm);
$("#modelFormSaveBtn").addEventListener("click", saveModel);
$("#deleteConfirmOkBtn").addEventListener("click", () => {
  const cb = _dialogOnOk;
  closeDialog();
  if (cb) cb();
});
$("#deleteConfirmCloseBtn").addEventListener("click", closeDialog);
$("#deleteConfirmCancelBtn").addEventListener("click", closeDialog);
