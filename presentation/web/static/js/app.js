// 全局应用状态
const appState = {
  currentSessionId: null,
  currentProjectId: null,
  sessions: [],
  currentTab: 1,
  streams: { content: null, ppt: null },
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// API helper
async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  if (!r.ok) {
    let detail;
    try { detail = (await r.json()).detail; } catch (_) { detail = r.statusText; }
    throw new Error(detail || `HTTP ${r.status}`);
  }
  if (r.status === 204) return null;
  return r.json();
}

function formatTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  const diff = (now - d) / 1000;
  if (diff < 60) return "刚刚";
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} 天前`;
  return d.toLocaleDateString();
}

// 加载会话列表
async function loadSessions() {
  try {
    appState.sessions = await api("GET", "/api/sessions");
  } catch (e) {
    console.error("loadSessions failed:", e);
    appState.sessions = [];
  }
  renderSessionList();
}

function renderSessionList() {
  const list = $("#sessionList");
  list.innerHTML = "";
  for (const s of appState.sessions) {
    const item = document.createElement("div");
    item.className = "session-item" + (s.id === appState.currentSessionId ? " session-item-active" : "");
    item.innerHTML = `
      <div class="session-title">${escapeHtml(s.title)}</div>
      <div class="session-meta">
        <span>${formatTime(s.updated_at)}</span>
        <button class="session-delete" data-id="${s.id}" title="删除">🗑</button>
      </div>
    `;
    item.addEventListener("click", (ev) => {
      if (ev.target.classList.contains("session-delete")) return;
      selectSession(s);
    });
    list.appendChild(item);
  }

  list.querySelectorAll(".session-delete").forEach((btn) => {
    btn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const id = btn.dataset.id;
      if (!(await showConfirm({ title: "删除会话", message: "确定删除此会话？" }))) return;
      try {
        await api("DELETE", `/api/sessions/${id}`);   // 后端判断运行中并删除，409/5xx 会 throw
        if (appState.currentSessionId === id) {
          appState.currentSessionId = null;
          appState.currentProjectId = null;
          clearAllState();
          showHome();
        }
        await loadSessions();
      } catch (e) {
        if (String(e.message).includes("执行中")) {
          showAlert({ title: "提示", message: "该会话正在执行中，请等待完成后再删除" });
        } else {
          showAlert({ title: "删除失败", message: e.message, type: "error" });
        }
      }
    });
  });
}

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

async function selectSession(s) {
  appState.currentSessionId = s.id;
  appState.currentProjectId = s.project_id;
  renderSessionList();
  showMain();
  // 切换会话：重置视频区域（进度/结果），并默认回到内容 tab
  // （内容/PPT 聊天区由 onSessionSelected 负责清空并加载新会话历史）
  switchTab(1);
  $("#videoProgressArea").hidden = true;
  $("#videoResult").hidden = true;
  $("#videoProgressStep").textContent = "";
  // 重置一键生成按钮状态
  const genBtn = $("#generateVideoBtn");
  if (genBtn) { genBtn.textContent = "🚀 一键生成视频"; genBtn.disabled = false; genBtn.classList.remove("video-btn-generating"); }
  const advBtn = $("#advancedGenerateBtn");
  if (advBtn) advBtn.disabled = false;
  // 通知 chat.js 切换会话
  if (window.onSessionSelected) window.onSessionSelected(s);
}

// 新建会话
function openNewSessionModal() {
  $("#newSessionTitle").value = "";
  $("#newSessionModal").hidden = false;
  $("#newSessionTitle").focus();
}
$("#newSessionBtn").addEventListener("click", openNewSessionModal);
$("#homeNewSessionBtn").addEventListener("click", openNewSessionModal);

// 点击左上角品牌名称（驭帧）返回首页
$("#brandLogo").addEventListener("click", showHome);

// 关闭新建会话弹窗
$("#newSessionCloseBtn").addEventListener("click", () => {
  $("#newSessionModal").hidden = true;
});

$("#newSessionCancelBtn").addEventListener("click", () => {
  $("#newSessionModal").hidden = true;
});

// 确认创建
$("#newSessionConfirmBtn").addEventListener("click", async () => {
  const title = $("#newSessionTitle").value.trim();
  if (!title) return;
  try {
    const s = await api("POST", "/api/sessions", { title });
    await loadSessions();
    selectSession(s);
    switchTab(1);
    $("#newSessionModal").hidden = true;
  } catch (e) {
    showAlert({ title: "创建失败", message: e.message, type: "error" });
  }
});

// Enter 键提交
$("#newSessionTitle").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    $("#newSessionConfirmBtn").click();
  }
});

function clearChat() {
  $("#chatContainer").innerHTML = '<div class="empty-hint">选择会话后即可开始对话</div>';
  $("#pptChatContainer").innerHTML = '<div class="empty-hint">在下方输入框中发送消息，生成的幻灯片会显示在此处</div>';
  $("#galleryBtn").hidden = true;
  $("#contentProgress").hidden = true;
  $("#pptProgress").hidden = true;
  $("#videoProgressArea").hidden = true;
  $("#videoResult").hidden = true;
  // 重置一键生成按钮状态
  const genBtn = $("#generateVideoBtn");
  if (genBtn) { genBtn.textContent = "🚀 一键生成视频"; genBtn.disabled = false; genBtn.classList.remove("video-btn-generating"); }
  const advBtn = $("#advancedGenerateBtn");
  if (advBtn) advBtn.disabled = false;
  if (appState.streams.content) { appState.streams.content.close(); appState.streams.content = null; }
  if (appState.streams.ppt) { appState.streams.ppt.close(); appState.streams.ppt = null; }
}

// 切换会话与删除会话共用的统一清除函数
// 先做执行态清理（SSE 流/轮询/busy/介入/缓存/视频轮询/进度条，由 chat.js 的 _cleanupAgentState 提供），
// 再清空界面态（两个对话区、画廊按钮、视频区域，复用 clearChat）
function clearAllState() {
  if (window._cleanupAgentState) window._cleanupAgentState();
  clearChat();
}

// 首页 / 主界面切换：未选中会话时显示首页（无选项卡），选中后显示正常三选项卡界面
function showHome() {
  $("#homePage").hidden = false;
  $("#tabBar").hidden = true;
  $(".tab-content").hidden = true;
}
function showMain() {
  $("#homePage").hidden = true;
  $("#tabBar").hidden = false;
  $(".tab-content").hidden = false;
}

function switchTab(n) {
  appState.currentTab = n;
  $$(".tab").forEach((t) => t.classList.toggle("tab-active", t.dataset.tab == n));
  $$(".tab-pane").forEach((p) => p.classList.toggle("tab-pane-active", p.id === `tab${n}`));
  if (window.onTabChanged) window.onTabChanged(n);
  if (window.onTabChange) window.onTabChange(n);
  // 切到聊天 tab 后自动滚到底部（display:none 容器滚动无效，必须在激活后再滚）
  const chatEl = n == 1 ? $("#chatContainer") : (n == 2 ? $("#pptChatContainer") : null);
  if (chatEl) chatEl.scrollTop = chatEl.scrollHeight;
}

// 选项卡切换
$$(".tab").forEach((t) => {
  t.addEventListener("click", () => switchTab(t.dataset.tab));
});

// 启动
showHome();  // 初始未选中任何会话，显示首页
loadSessions();
