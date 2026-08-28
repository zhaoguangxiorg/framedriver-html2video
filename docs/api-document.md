# 流式接口（SSE）说明

> 版本：v1.0 · 更新日期：2026-08-11
> 基准：以当前代码（presentation/api + appservice）为准。
> Author: AI Agent (guided by zhaoguangxi)

智能体对话采用 **SSE（Server-Sent Events）流式接口**：`POST` 提交消息后，服务端以 `text/event-stream` 持续推送事件，前端通过 `fetch + ReadableStream` 消费，逐条渲染执行步骤、文本与幻灯片卡片。

---

## 一、流式接口清单

| 接口 | 用途 |
|------|------|
| `POST /api/content/{project_id}` | 内容智能体对话流（Tab ①） |
| `POST /api/ppt/{project_id}` | PPT 智能体对话流（Tab ②） |
| `POST /api/ppt/{project_id}/intervention` | 人工介入答案提交 + 恢复执行流 |

辅助接口（非流式）：

| 接口 | 用途 |
|------|------|
| `POST /api/content/{project_id}/stop` | 停止内容智能体（返回 204） |
| `POST /api/ppt/{project_id}/stop` | 停止 PPT 智能体（返回 204） |
| `GET /api/ppt/{project_id}/agent-status` | 执行状态轮询（返回 JSON） |

## 二、请求方式（以 PPT 为例）

```
POST /api/ppt/{project_id}
Content-Type: application/json

{ "message": "帮我生成一个 AI 入门 PPT", "model_code": "deepseek-chat" }
```

- `message`：必填，用户消息
- `model_code`：可选，指定模型（不传用默认模型）

响应头 `Content-Type: text/event-stream`。

## 三、SSE 传输帧格式

每帧由 `event:` 行 + `data:` 行组成，`data` 为 JSON，帧间以空行分隔：

```
event: step
data: {"type":"step","name":"正在初始化项目","code":"init_project","tc_id":"call_1"}

event: text
data: {"type":"text","content":"正在为你生成..."}
```

## 四、消息类型与 JSON 示例

### 1. progress — 进度

```json
{
  "type": "progress",
  "percent": 100,
  "current_step": "已完成 3 张幻灯片"
}
```

### 2. step — 步骤开始

```json
{
  "type": "step",
  "name": "正在初始化项目",
  "code": "init_project",
  "tc_id": "call_abc123"
}
```

### 3. step_done — 步骤完成

```json
{
  "type": "step_done",
  "name": "初始化项目成功",
  "code": "init_project",
  "tc_id": "call_abc123"
}
```

### 4. text — 流式文本

```json
{ "type": "text", "content": "PPT 已全部生成完成..." }
```

### 5. slide — 幻灯片卡片

```json
{
  "type": "slide",
  "slide_index": 1,
  "title": "人工智能入门",
  "html_path": "/api/slides/{project_id}/1/html",
  "narration": "大家好，欢迎来到今天的内容...",
  "slide_text": "幻灯片正文内容",
  "slides_meta": [
    { "slide_index": 1, "title": "人工智能入门" },
    { "slide_index": 2, "title": "什么是人工智能" }
  ],
  "video_config": { "aspect_ratio": "16:9", "resolution": "1920x1080" }
}
```

### 6. human_intervention — 人工介入问题卡片

```json
{
  "type": "human_intervention",
  "intervention_id": "uuid-xxx",
  "questions": [
    {
      "question_id": "q1",
      "type": "single_choice",
      "text": "选择主色调风格：",
      "options": [
        { "key": "A", "label": "商务蓝" },
        { "key": "B", "label": "科技紫" }
      ],
      "required": true,
      "placeholder": "",
      "confirm_text": "确认",
      "cancel_text": "取消"
    }
  ]
}
```

> 收到该事件后，流随即以 `done`（`interrupted: true`）结束，等待用户通过 `/intervention` 接口提交答案后恢复。

### 7. done — 结束

正常完成：

```json
{ "type": "done", "summary": "已生成 3 张幻灯片" }
```

人工介入中断时：

```json
{ "type": "done", "summary": "等待用户作答", "interrupted": true }
```

### 8. stopped — 用户停止

```json
{ "type": "stopped", "summary": "已停止" }
```

### 9. error — 错误

```json
{
  "type": "error",
  "error_code": "AGENT_ERROR",
  "message": "智能体执行失败: ..."
}
```

---

**文档结束**
