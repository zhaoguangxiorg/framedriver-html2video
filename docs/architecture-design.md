# 驭帧(FrameDriver)·驭帧让每一帧知识，都尽在掌控 — 完整架构设计文档

> 文档版本：v3.0（依据当前代码重新校准，以代码为准）
> 更新日期：2026-08-11
> Author: AI Agent (guided by zhaoguangxi)
---

## 目录

1. [系统概述](#1-系统概述)
2. [技术选型](#2-技术选型)
3. [整体架构](#3-整体架构)
4. [完整流程与技术栈深度解析](#4-完整流程与技术栈深度解析)
5. [智能体 1：ContentAgent（内容创作）](#5-智能体-1contentagent内容创作)
6. [智能体 2：HTMLAgent（HTML 设计，主从架构）](#6-智能体-2htmlagenthtml-设计主从架构)
7. [视频生成大工具](#7-视频生成大工具)
8. [数据流转机制](#8-数据流转机制)
9. [视频生成流水线](#9-视频生成流水线)
10. [数据存储层（SQLite）](#10-数据存储层sqlite)
11. [项目目录结构](#11-项目目录结构)
12. [核心设计决策](#12-核心设计决策)

---

## 1. 系统概述

### 1.1 系统目标

用户输入一个主题/题目，系统通过**三个智能体（含一个主从组合）协作 + 一个视频生成大工具**，自动生成带语音讲解的 PPT 视频。整个流程在前端一体化串联：内容 → PPT → 视频，无需用户手动复制粘贴。

### 1.2 核心设计理念

- **多智能体分工协作**：内容创作、HTML 设计（主从调度）、幻灯片结构管理各司其职
- **智能体思考 + 工具执行**：生成内容由智能体（LLM）完成，工具只负责执行动作
- **文件系统解耦**：智能体和视频生成通过项目目录交换数据，不直接调用
- **人工介入机制**：智能体在执行中遇到需要用户决策/补充信息的节点，可通过 ask_user 卡片提问，阻塞等待用户作答后继续
- **大工具封装**：视频生成是一个确定性流水线，封装为一个大工具，内部由多个小步骤组成
- **分层架构**：表现层（api）→ 应用服务层（appservice）→ 领域层（domain）+ 智能体层（agent）+ 流水线（video_pipeline）→ 共享层（shared），单向依赖

### 1.3 四阶段流程

```
阶段一：内容创作  →  阶段二：PPT设计  →  阶段三：视频生成  →  阶段四：交付
 (ContentAgent)      (HTMLPPTAgent主从)     (大工具generate_video)
```

---

## 2. 技术选型

### 2.1 Web 与接口层

| 技术 | 选型 | 说明 |
|------|------|------|
| Web 框架 | FastAPI | 提供 REST API 与 SSE 流式接口 |
| 静态前端 | 原生 HTML/CSS/JS | 零第三方资源，挂载于 `/` |
| 启动方式 | `uvicorn main:app --port 8000` | 入口见 `main.py` |
| CORS | FastAPI CORSMiddleware | 全放开（本机部署场景） |

### 2.2 智能体层

| 技术 | 选型 | 说明 |
|------|------|------|
| 智能体框架 | deepagents（基于 LangGraph） | 核心 API `create_deep_agent`，支持子智能体（subagents）与流式 `stream()` |
| 模型网关 | 自研 `agent/llm/llm.py` | 从 `model_configs` 表加载模型配置，支持多提供商（OpenAI 兼容协议） |
| 模型切换 | `ConfigurableModelMiddleware` | 请求级切换模型（context 传入 model_code） |
| 记忆 | LangGraph SQLite Checkpointer | 短期对话记忆 + interrupt 恢复 |

### 2.3 内容生成层

| 技术     | 选型 | 说明 |
|--------|------|------|
| 文本生成   | LLM（可配置多模型） | 生成幻灯片内容和逐字稿 |
| PPT 生成 | LLM（智能体自身能力） | 直接生成完整 HTML + 内联 CSS |

### 2.4 视频处理层

| 技术 | 选型 | 说明                                    |
|------|------|---------------------------------------|
| HTML 转图 | Playwright (Chromium) | 无头浏览器截图，支持高清、高 DPI                    |
| 语音合成 (TTS) | edge-tts | 微软在线 TTS，免费、高质量、多音色                   |
| 视频处理 | FFmpeg + imageio-ffmpeg + subprocess | H.264 + AAC 编码                        |
| 视频效果 | FFmpeg 滤镜 | zoompan（Ken Burns）、xfade（转场）、afade（淡入淡出） |
| 字幕渲染 | 自研 `subtitle_render.py` + `font_resolver.py` | 使用 drawtext 滤镜渲染字幕                    |

### 2.5 数据存储层

| 技术 | 选型 | 说明 |
|------|------|------|
| 业务数据库 | SQLite | 3 张表：sessions / messages / model_configs |
| 智能体状态 | SQLite（langgraph checkpoints/writes） | 对话历史 + interrupt 断点 |
| 配置存储 | JSON 文件 | `config/video_settings.json`、`voice_settings.json` 等全局配置 |
| 项目数据 | 文件系统 | `output/html_slides/{project_id}/` 按项目组织 |
| API Key 加密 | Fernet | `shared/crypto.py` 加解密 model_configs.api_key |

### 2.6 开发与运行

| 技术 | 选型 |
|------|------|
| 编程语言 | Python 3.10+ |
| 数据模型 | Pydantic v2 |
| 环境变量 | python-dotenv（`.env`） |
| 运行环境 | Windows（跨平台兼容） |
| 依赖管理 | pip + requirements.txt |

---

## 3. 整体架构

### 3.1 分层架构（单向依赖）

```
┌──────────────────────────────────────────────────────────────┐
│  presentation/   表现层                                        │
│    api/          薄路由（仅参数透传，无业务逻辑）                 │
│    web/static/   原生前端（HTML/CSS/JS）                        │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  appservice/    应用服务层（全部业务逻辑，统一管控入口）          │
│  agent_manager / content / ppt / video / session / slide      │
│  / package / model                                            │
└───────┬──────────────────────────────────────┬───────────────┘
        ▼                                      ▼
┌─────────────────────────┐    ┌────────────────────────────────┐
│  domain/  领域层          │    │  agent/  智能体层               │
│  entities/ 数据结构       │    │  content_agent  内容创作         │
│  dal/      数据存取        │    │  html_agent     HTML 主从架构    │
│  service/  业务规则        │    │  llm/          模型网关          │
│  (session/message/model) │    │  checkpointer  SQLite 记忆       │
│  project_store  项目文件   │    │                                 │
└─────────────────────────┘    └──────────────┬─────────────────┘
        ▼                                      ▼
┌──────────────────────────────────────────────────────────────┐
│  video_pipeline/  视频流水线（确定性，无 LLM）                   │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  shared/  共享层（config / crypto / file_utils）               │
└──────────────────────────────────────────────────────────────┘
```

依赖方向严格单向：`api → appservice → (domain / agent / video_pipeline) → shared`，无反向依赖。

### 3.2 多智能体架构

```
用户题目
   │
   ▼
┌──────────────────────────────────────────────────────────┐
│  ContentAgent（内容创作智能体）                            │
│  · 2 个工具：read_content / save_content                  │
│  · 生成 Markdown 内容 → save_content 写入 content.md       │
│  · 支持多轮修改                                           │
└──────────────────────┬───────────────────────────────────┘
                       │ content.md（前端自动串联，非手动复制）
                       ▼
┌──────────────────────────────────────────────────────────┐
│  HTMLAgent（HTML 设计，Orchestrator-Worker 主从架构）       │
│  · OrchestratorAgent（主智能体，6 工具）                    │
│      init_project / read_content_md / read_style_spec      │
│      / update_style_spec / update_video_config / ask_user  │
│  · WorkerAgent「slide-designer」（5 工具，每次一张）         │
│      read_full_content / read_style_spec / read_slide_html  │
│      / save_slide_content / save_slide_html                │
│  · SlideManagerAgent「slide-manager」（4 工具）             │
│      read_slides_meta / insert_slide / delete_slide         │
│      / move_slide                                          │
└──────────────────────┬───────────────────────────────────┘
                       │ project_id
                       ▼
┌──────────────────────────────────────────────────────────┐
│  视频生成大工具（generate_video）                           │
│  · 确定性流水线，无 LLM                                    │
│  · 内部步骤：HTML→图片 / 逐字稿→音频 / 图+音→单段 / 拼接      │
│  · 可选字幕渲染                                            │
│  输出：最终视频 MP4                                        │
└──────────────────────────────────────────────────────────┘
```

### 3.3 智能体与工具分工原则

| 角色 | 职责 | 能力来源 |
|------|------|----------|
| **智能体** | 思考、创作、决策 | LLM 本身的能力 |
| **工具** | 执行、存储、计算 | 确定性的代码逻辑 |

> **核心原则**：生成内容是智能体的工作，工具只负责执行动作。

---

## 4. 完整流程与技术栈深度解析

### 4.1 前端一体化流程（三选项卡）

前端为单页应用（原生 JS），包含三个选项卡：

| 选项卡 | 功能 | 关键接口 |
|--------|------|----------|
| ① 内容 | ContentAgent 对话，生成 Markdown 内容 | `POST /api/content/{project_id}`（SSE 流） |
| ② PPT | HTMLAgent 对话，生成幻灯片卡片 | `POST /api/ppt/{project_id}`（SSE 流） |
| ③ 视频 | 视频配置 + 一键/高级生成 | `POST /api/video/{project_id}` 等 |

页面结构：左侧会话列表（sessions）、右侧主区（三选项卡）、设置弹窗（模型管理）、播放器、画廊等。

### 4.2 各阶段详解

#### 阶段 1：内容创作

| 项目 | 说明 |
|------|------|
| **做什么** | ContentAgent 根据用户主题生成 Markdown 格式的幻灯片内容和逐字讲解稿，通过 `save_content` 写入 `content.md` |
| **原理** | deepagents 驱动 LLM 思考循环；`read_content` 读取已保存内容，`save_content` 覆盖保存 |
| **输出** | `output/html_slides/{project_id}/content.md`（Markdown） |

#### 阶段 2：PPT 设计

| 项目 | 说明 |
|------|------|
| **做什么** | OrchestratorAgent 读取 content.md → 初始化项目 → 逐张派单给 WorkerAgent 生成/修改 HTML；SlideManagerAgent 处理结构操作 |
| **原理** | 主从架构：Orchestrator 只做调度与沟通，Worker 每次只处理一张（防上下文爆炸）；`init_project` 只写元数据，内容/逐字稿由 Worker 的 `save_slide_content` 写入 |
| **输出** | `slides_data.json` + 每张 `slide_XX/slide.html`、`content.md`、`narration.md` |

#### 阶段 3：HTML 转图

Playwright 无头浏览器渲染 HTML → PNG（1920×1080 或自定义分辨率，device_scale_factor 控制清晰度）。

#### 阶段 4：语音合成

edge-tts 将逐字稿合成为 MP3。

#### 阶段 5：视频合成

FFmpeg 将图片 + 音频合成单段视频，多段 xfade 拼接为最终视频；可选字幕渲染（drawtext 滤镜）。

### 4.3 SSE 流式事件

前端通过 `fetch + ReadableStream` 消费 SSE 流，事件类型：

| 事件 | 说明 |
|------|------|
| `progress` | 进度条（百分比 + 当前步骤） |
| `step` / `step_done` | 执行步骤（气泡内步骤区） |
| `text` | 流式文本 |
| `slide` | 幻灯片卡片（含 slides_meta 骨架、video_config） |
| `human_intervention` | 人工介入（问题卡片） |
| `done` / `stopped` / `error` | 结束 / 停止 / 错误 |

### 4.4 人工介入机制

- **触发**：OrchestratorAgent 在需要用户决策/补充信息/敏感操作确认时调用 `ask_user` 工具
- **机制**：工具内部调用 LangGraph `interrupt()` 阻塞；前端渲染问题卡片（单选/多选/问答/确认 4 种形态，逐题作答）
- **恢复**：前端提交答案 → `POST /api/ppt/{project_id}/intervention` → `Command(resume=answers)` 恢复执行
- **持久化**：中断 + 恢复 = 1 条 `role=agent` 消息，问题卡片存入 `messages.cards` 字段；刷新页面可继续作答（详情见 10 章）

---

## 5. 智能体 1：ContentAgent（内容创作）

### 5.1 基本信息

| 项目 | 说明 |
|------|------|
| 名称 | ContentAgent |
| 类型 | 工具型智能体 |
| 工具数量 | 2 个（read_content / save_content） |
| 职责 | 根据用户题目，创作幻灯片内容 + 逐字讲解稿，保存为 content.md |

### 5.2 工具清单

| 工具 | 功能 |
|------|------|
| `read_content` | 读取项目目录中已保存的 content.md（支持多轮修改时先读后改） |
| `save_content(content)` | 保存完整 Markdown 内容到 content.md（完全覆盖） |

### 5.3 输入输出

**输入**：用户的主题/题目描述（自然语言）

**输出**：Markdown 格式的幻灯片内容（人类友好，便于审核）

```markdown
# 选题标题

## 第 1 张

**标题**：幻灯片标题

**幻灯片内容**：
- 要点一
- 要点二

**逐字讲解稿**：
大家好，欢迎来到今天的内容...
```

### 5.4 工作流程

1. 用户给出主题，智能体生成初始内容并调用 `save_content` 保存
2. 用户提出修改意见（整体或单张），智能体 `read_content` 读取后调整
3. 重复 2，直到用户满意

---

## 6. 智能体 2：HTMLAgent（PPT 设计，主从架构）

### 6.1 基本信息

| 项目 | 说明 |
|------|------|
| 名称 | HTMLAgent |
| 类型 | 主从架构智能体（Orchestrator + Worker + SlideManager） |
| 职责 | 解析 content.md、生成/修改幻灯片 HTML、管理幻灯片结构、维护设计规范与视频配置 |

### 6.2 主从架构（Orchestrator-Worker）

```
OrchestratorAgent（主智能体：流程调度 + 用户沟通）
   │  task(subagent_type="slide-designer", description=...)
   ├──▶ WorkerAgent「slide-designer」（每次只处理一张幻灯片）
   │  task(subagent_type="slide-manager", description=...)
   └──▶ SlideManagerAgent「slide-manager」（只处理结构增删移）
```

**设计要点**：
- Orchestrator 不直接写 HTML、不使用文件系统工具，只负责读取内容/规范、更新配置、派单、汇报
- Worker 轻量、一次只处理一张，处理完即销毁，防止上下文爆炸
- 数据经项目目录传递，HTML 内容不回流到 Orchestrator 上下文
- Orchestrator 维护统一的 style_spec，由子智能体读取，保证风格一致

### 6.3 工具清单

#### OrchestratorAgent（6 个工具）

| 工具 | 功能 |
|------|------|
| `init_project(topic, slides_meta)` | 初始化项目，写入幻灯片元数据（仅 slide_index/title，不含正文） |
| `read_content_md()` | 读取 content.md（上一步内容生成结果） |
| `read_style_spec()` | 读取现有设计规范 style_spec.md |
| `update_style_spec(content)` | 保存完整设计规范 Markdown |
| `update_video_config(...)` | 增量更新项目视频配置（aspect_ratio/resolution/fps/voice 等字段） |
| `ask_user(questions)` | 人工介入：向用户提问并阻塞等待作答 |

#### WorkerAgent「slide-designer」（5 个工具）

| 工具 | 功能 |
|------|------|
| `read_full_content()` | 读取所有幻灯片最新内容拼成的完整 PPT Markdown（了解全局） |
| `read_style_spec()` | 读取设计规范 |
| `read_slide_html(slide_index)` | 读取指定幻灯片现有 HTML（修改任务必用） |
| `save_slide_content(slide_index, content, narration)` | 保存该张内容与逐字稿 |
| `save_slide_html(slide_index, html_content)` | 保存 HTML 文件 |

#### SlideManagerAgent「slide-manager」（4 个工具）

| 工具 | 功能 |
|------|------|
| `read_slides_meta()` | 读取当前幻灯片列表（slide_index + title） |
| `insert_slide(position, title)` | 插入新幻灯片（仅元数据，返回 new_slide_index） |
| `delete_slide(slide_index)` | 删除幻灯片并自动重排索引 |
| `move_slide(from_index, to_index)` | 移动幻灯片位置并重排索引 |


#### 数据与配置文件职责

| 文件 | 谁读写 |
|------|--------|
| `content.md` | ContentAgent 写，Orchestrator 用 read_content_md 读（只读） |
| `slides_data.json` | init_project 与 slide-manager 维护（元数据） |
| `style_spec.md` | Orchestrator 用 update_style_spec 写，Worker 自动读取 |
| `video_config.json`（项目级） | Orchestrator 用 update_video_config 写，覆盖全局默认 |

---

## 7. 视频生成大工具

### 7.1 设计思路：大工具 + 小步骤

视频生成是**确定性流水线**，不需要智能体决策，封装为大工具 `generate_video`，内部由多个小步骤组成，对调用者透明。

### 7.2 对外接口：generate_video

```python
generate_video(
    project_id: str,
    voice_persona: str = None,   # 可选，覆盖全局配置
    aspect_ratio: str = None,    # 可选，视频比例
    resolution: str = None,      # 可选，自定义分辨率（最高优先级）
    enable_subtitles: bool = None,
) -> dict  # final_video_path / total_duration / total_slides / warnings
```

### 7.3 配置优先级

```
参数传入（最高） > 项目配置（video_config.json） > 系统默认配置（config/*.json）
```

系统默认配置来源（`video_pipeline/video_settings.py`）：
- `config/video_settings.json`：视频参数（比例、分辨率、帧率、效果、转场等）
- `config/voice_settings.json`：语音参数（音色、语速、音量、音调、语音人设）
- `config/video_aspect_ratios.json`：比例 → 分辨率映射表
- `config/voice_personas.json`：语音人设定义

> `aspect_ratio` 变化时会根据映射表自动更新 `resolution`；用户自定义分辨率不受比例覆盖。


### 7.4 项目级配置 vs 全局配置

| 类型 | 存储位置 | 变更频率 | 作用范围 |
|------|----------|----------|----------|
| 内容数据 | 项目目录 `slides_data.json` | 每个项目不同 | 单个项目 |
| 项目视频配置 | 项目目录 `video_config.json` | 生成时按需更新 | 单个项目（覆盖全局） |
| 全局配置 | `config/*.json` | 一次设置长期使用 | 所有项目（默认值） |


### 7.5 字幕字体说明

- 字幕按配置的字体**文件**渲染（drawtext 文件加载，无回退，理论上不会静默替换成其他字体）。
- 配置位置：`config/video_settings.json` 的 `subtitle_font`（字体名）与 `enable_subtitles`；也可以配置 `subtitle_font_file` 直接指定字体文件路径（**优先于** `subtitle_font`，且**仅支持单 face 文件** `.ttf`/`.otf`，配置 `.ttc`/`.otc` 会生成失败）。
- `subtitle_font` 与 `subtitle_font_file` 都留空 → 无字幕（前端"启用字幕"复选框置灰）。
- 配置了字体名但系统找不到，或配置的字体文件不存在/为多 face 集合 → 视频生成失败，提示具体原因；可关闭字幕或修正配置后重试。
- **ttc 多 face 风险**：`.ttc` 集合文件仅使用第一个 face 渲染，若字体含多个字面（如日文/简体/繁体），实际字形可能与预期不同——这是字形差异，不影响字体授权。
- **授权边界**：字幕实际使用哪个字体、其授权如何，由用户配置的字体文件决定；平台只按配置渲染，不参与字体选择与授权判断。商用前请自行确认所用字体的授权条款。
- **建议**：如需精确控制字形，使用单 face 字体文件（.ttf/.otf，如思源黑体官方单语言版）。
- 查看中文字体名的方法：Linux 用 `fc-list :lang=zh`；Windows 系统字体一般为 Microsoft YaHei / SimHei / SimSun 等。

---

## 8. 运行时数据

### 8.1 项目目录文件清单（运行时）

```
output/html_slides/{project_id}/
├── content.md                # ContentAgent 产物（完整 Markdown 大纲）
├── slides_data.json          # 幻灯片元数据（slide_index/title/html_path）
├── style_spec.md             # 设计规范（Orchestrator 写入）
├── video_config.json         # 项目视频配置（Orchestrator 写入，覆盖全局）
├── slide_01/
│   ├── content.md            # 该张幻灯片内容
│   ├── narration.md          # 该张逐字稿
│   ├── slide.html            # HTML
│   ├── slide.png             # 图片（视频流水线产物）
│   ├── narration.mp3         # 音频（视频流水线产物）
│   └── segment.mp4           # 单段视频（视频流水线产物）
├── slide_02/
│   └── ...
└── final_video.mp4           # 最终视频
```

### 8.3 阶段衔接方式

| 阶段衔接 | 触发方式 | 衔接物 |
|----------|----------|--------|
| 内容创作 → HTML设计 | 前端切换选项卡，智能体内部 read_content_md | content.md |
| HTML设计 → 视频生成 | 前端点击「生成视频」按钮 | project_id |

---

## 9. 视频生成流水线

### 9.1 整体流程

```
generate_video(project_id)
    │
    ├─ 加载配置：参数 > 项目 video_config.json > 全局 config/*.json
    ├─ 加载数据：slides_data.json（含 html_path / narration）
    │
    ├─ 遍历每张幻灯片：
    │   ├─ 步骤1：HTML → 图片（html_to_image）
    │   ├─ 步骤2：逐字稿 → 音频（text_to_speech）
    │   └─ 步骤3：图片 + 音频 → 单段视频（image_audio_to_video，可选字幕）
    │
    └─ 步骤4：多段视频拼接 → 最终视频（concat_videos）
```

### 9.2 步骤 1：html_to_image（HTML → 图片）

| 项目 | 说明 |
|------|------|
| 技术 | Playwright + Chromium 无头浏览器 |
| 输出 | PNG（1920×1080 或自定义分辨率） |
| 关键参数 | viewport 宽高、device_scale_factor、等待加载完成 |

### 9.3 步骤 2：text_to_speech（逐字稿 → 音频）

| 项目 | 说明 |
|------|------|
| 技术 | edge-tts（微软在线 TTS） |
| 输出 | MP3 + 时长 |
| 重试机制 | 最多 3 次，指数退避（1s, 2s, 4s） |
| 时长获取 | 优先 ffprobe，fallback 为中文语速估算 |

### 9.4 步骤 3：image_audio_to_video（图片 + 音频 → 单段视频）

| 项目 | 说明 |
|------|------|
| 技术 | FFmpeg + imageio-ffmpeg + subprocess |
| 图片效果 | none（静态）/ ken_burns / zoom_in（zoompan 滤镜） |
| 字幕 | 可选：drawtext 滤镜渲染字幕（`subtitle_render.py` + `font_resolver.py`） |
| 编码 | H.264（libx264, crf=23, yuv420p）+ AAC（192kbps），`-shortest` 音频为准 |
| 淡入淡出 | 视频 fade + 音频 afade |

### 9.5 步骤 4：concat_videos（多段 → 最终视频）

| 项目 | 说明 |
|------|------|
| 技术 | FFmpeg xfade 滤镜 |
| 转场 | none（concat + `-c copy`）/ fade / dissolve（xfade） |
| 音频 | acrossfade 交叉淡入淡出 |



---

## 10. 数据存储层（SQLite）

### 10.1 业务表（domain/entities/db_models.py，SQLAlchemy ORM）

#### sessions 表（会话表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | String(36) | UUID 主键 |
| title | String | 会话标题 |
| project_id | String(64) | 关联项目目录 ID |
| created_at / updated_at | DateTime | 时间戳 |

#### messages 表（聊天记录主信息表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | String(36) | UUID 主键 |
| project_id | String(64) | 项目 ID |
| role | String(16) | user / agent |
| content | Text | 消息文本（气泡内） |
| tab | String(16) | content / ppt |
| steps | Text | 执行步骤 JSON（气泡内） |
| cards | Text | 卡片数组 JSON（气泡外）：intervention / slides 卡片 |
| status | String(16) | pending / completed / interrupted / error |
| created_at | DateTime | 创建时间 |

#### model_configs 表（模型网关大模型配置表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| name / model_name / model_provider | String | 展示名/模型名/提供商 |
| base_url / api_key | String | 接口地址 / 加密后的密钥 |
| temperature / max_tokens | Float/Int | 采样参数 |
| is_default / enabled | Integer | 默认 / 启用标志 |
| code | String | 唯一标识（服务层生成） |

### 10.2 智能体状态表（langgraph 自动维护）

`checkpoints` / `writes` 表存储对话历史与中断断点，供恢复执行使用（`agent/checkpointer.py`，SqliteSaver，`output/checkpoints.db`）。


---

## 11. 项目目录结构

### 11.1 代码结构（以当前代码为准）

```
ai_coding_trae_view/
│
├── main.py                    # FastAPI 入口（uvicorn main:app --port 8000）
│
├── presentation/              # 表现层
│   ├── __init__.py
│   ├── api/                   # REST API 与路由（薄壳，无业务逻辑）
│   │   ├── __init__.py
│   │   ├── sessions_api.py    # 会话 + 消息路由（含 messages_router）
│   │   ├── content_api.py     # 内容智能体路由
│   │   ├── ppt_api.py         # PPT 智能体路由（含中断恢复 /intervention）
│   │   ├── slides_api.py      # 幻灯片数据路由
│   │   ├── video_api.py       # 视频生成/进度/下载路由
│   │   ├── package_api.py     # PPT 打包/预览路由
│   │   └── models_api.py      # 模型配置路由
│   └── web/                   # Web 前端（原生，零第三方资源）
│       └── static/            # index.html / declaration.html / css/ / js/
│
├── appservice/                # 应用服务层（全部业务逻辑）
│   ├── __init__.py
│   ├── agent_manager.py       # 智能体单例管理
│   ├── content_appservice.py  # 内容智能体业务（stream/stop）
│   ├── ppt_appservice.py      # PPT 智能体业务（stream/中断恢复/状态轮询/停止）
│   ├── video_appservice.py    # 视频生成业务（任务表/进度/轮询）
│   ├── session_appservice.py  # 会话业务（忙碌判定/删除协调）
│   ├── slide_appservice.py    # 幻灯片数据业务
│   ├── package_appservice.py  # PPT 打包业务
│   └── model_appservice.py    # 模型配置业务
│
├── agent/                     # 智能体 + 智能体基础设施
│   ├── __init__.py
│   ├── checkpointer.py        # SQLite checkpointer（langgraph 记忆）
│   ├── content_agent/         # 智能体1：内容创作
│   │   ├── __init__.py
│   │   ├── agent.py           # create_content_agent()
│   │   ├── prompts.py         # CONTENT_SYSTEM_PROMPT
│   │   └── tools/
│   │       ├── read_content.py    # 读取 content.md
│   │       └── save_content.py    # 保存 content.md
│   ├── html_agent/            # 智能体2：HTML 设计（主从架构）
│   │   ├── __init__.py
│   │   ├── orchestrator_agent.py  # create_html_agent()（Orchestrator）
│   │   ├── orchestrator_prompts.py# Orchestrator 提示词
│   │   ├── worker_spec.py         # Worker（slide-designer）规格
│   │   ├── worker_prompts.py      # Worker 提示词
│   │   ├── slide_manager_spec.py  # SlideManager（slide-manager）规格
│   │   ├── slide_manager_prompts.py
│   │   └── tools/                 # 14 个工具文件
│   │       ├── init_project.py / save_slide_html.py
│   │       ├── save_slide_content.py / read_slide_html.py
│   │       ├── read_full_content.py / read_slides_meta.py
│   │       ├── read_content_md.py / read_style_spec.py
│   │       ├── update_style_spec.py / update_video_config.py
│   │       ├── ask_user_tool.py
│   │       └── insert_slide.py / delete_slide.py / move_slide.py
│   └── llm/                   # 模型网关
│       ├── llm.py             # 模型工厂与缓存（从 model_configs 加载）
│       └── configurable_model.py  # 请求级模型切换中间件
│
├── video_pipeline/            # 视频流水线（确定性，无 LLM）
│   ├── __init__.py            # （空：无顶层 re-export，子模块直接 import）
│   ├── video_settings.py      # 全局配置加载 + aspect_ratio 应用
│   ├── video_config_cache.py  # 项目配置缓存
│   ├── voice_personas.py      # 语音人设
│   ├── font_resolver.py       # 字幕字体解析
│   ├── subtitle_render.py     # 字幕渲染
│   ├── html_to_image.py       # 步骤1：HTML → 图片
│   ├── text_to_speech.py      # 步骤2：TTS
│   ├── image_audio_to_video.py# 步骤3：单段视频（含字幕）
│   ├── concat_videos.py       # 步骤4：视频拼接
│   ├── pipeline.py            # 流水线总控（run_pipeline）
│   ├── generate_video.py      # 对外入口 generate_video()
│   └── advanced_generate.py   # 高级生成（单张/合成）
│
├── domain/                    # 领域层：Entities / DAL / Service
│   ├── __init__.py
│   ├── entities/              # 数据结构
│   │   ├── db_models.py       # ORM：Session / Message / ModelConfig
│   │   └── schemas.py         # Pydantic：SlideData / VideoConfig
│   ├── dal/                   # 数据存取
│   │   ├── db.py / session_dal.py / message_dal.py
│   │   ├── model_config_dal.py / project_store.py
│   └── service/               # 业务规则
│       ├── model_config_service.py  # code 生成/默认唯一/加密脱敏
│       ├── session_service.py       # 会话编排（建目录+入库）
│       └── slide_service.py         # 幻灯片目录重排/平移
│
├── shared/                    # 共享层（仅通用组件）
│   ├── config.py              # 全局配置 + .env 加载
│   ├── crypto.py              # Fernet 加解密
│   └── file_utils.py          # 文件工具
│
├── cli/                       # 命令行工具
│   └── main.py                # ppt-cli：content / html / video 子命令
│
├── config/                    # 全局配置（运行时）
│   ├── video_settings.json    # 视频参数默认配置
│   ├── voice_settings.json    # 语音参数默认配置
│   ├── video_aspect_ratios.json  # 比例 → 分辨率映射
│   └── voice_personas.json    # 语音人设定义
│
├── docs/                      # 设计文档
│   └── architecture-design.md
│
├── output/                    # 输出目录（运行时生成）
│   ├── checkpoints.db         # SQLite数据库（会话记录+langgraph 智能体状态）
│   └── html_slides/{project_id}/   # 项目数据
│
├── scripts/                   # 脚本
├── .env.example
└── requirements.txt
```


### 11.2 前端文件清单

| 文件 | 职责 |
|------|------|
| `index.html` | 主页面（三选项卡 + 各弹窗） |
| `declaration.html` | 免责声明页 |
| `css/style.css` 等 7 个 | 全局/侧栏/聊天/选项卡/设置/视频设置/进度样式 |
| `js/app.js` | 全局状态、会话列表、API helper |
| `js/chat.js` | 聊天核心（SSE 消费、消息气泡、步骤、幻灯片卡片、播放器、人工介入卡片） |
| `js/tabs.js` | 会话切换与历史加载 |
| `js/settings.js` | 设置弹窗（模型管理） |
| `js/video-settings.js` | 视频选项卡（配置加载、一键/高级生成、轮询） |
| `js/dialog.js` | 通用弹窗（替代系统 alert/confirm） |

---

## 12. 核心设计决策

### 12.1 分层架构 vs 平铺

| 方案 | 说明 |
|------|------|
| **分层架构（选择）** | api（薄路由）→ appservice（业务）→ domain/agent/video_pipeline → shared；单向依赖，职责清晰 |
| 平铺 | 路由内含业务逻辑，耦合度高、难维护 |

### 12.2 HTML 设计：主从架构 vs 单智能体

| 方案 | 说明 |
|------|------|
| **主从架构（选择）** | Orchestrator 调度 + Worker 单张处理，防上下文爆炸，风格统一 |
| 单智能体 | 上下文随幻灯片数量膨胀，长项目易失真 |

### 12.3 结构管理：独立 SlideManager vs 并入 Worker

| 方案 | 说明 |
|------|------|
| **独立 SlideManager（选择）** | 增删移是纯结构操作，与内容创作职责分离 |
| 并入 Worker | 职责混杂，工具集膨胀 |

### 12.4 项目初始化：单独工具 vs save 时创建

| 方案 | 说明 |
|------|------|
| **init_project 单独工具（选择）** | 只写元数据（slide_index/title），内容由 Worker 的 save_slide_content 写入 |
| save 时创建 | 需要传递内容数据，参数膨胀 |

### 12.5 视频配置：三层覆盖 vs 全局单一

| 方案 | 说明 |
|------|------|
| **三层覆盖（选择）** | 参数 > 项目 video_config.json > 全局 config/*.json；灵活且默认一致 |
| 全局单一 | 无法按项目定制比例/字幕等参数 |

### 12.6 视频生成：大工具 vs 独立步骤

| 方案 | 说明 |
|------|------|
| **大工具（选择）** | 对外一个接口 generate_video(project_id, ...)，内部多步骤，对调用者透明 |
| 暴露多个小工具 | 增加调用方复杂度 |

### 12.7 人工介入：ask_user + interrupt vs 审批中间件

| 方案 | 说明 |
|------|------|
| **ask_user + interrupt（选择）** | LLM 主动发起提问，问题结构自定义（4 种形态），阻塞等待 |
| HumanInTheLoopMiddleware | 决策模型固定（approve/reject/edit），不适应"主动提问" |



---

## 附录：使用流程

```
前置：设置模型（可选，设置弹窗 → 模型管理）
  新增模型（提供商/模型名/base_url/api_key）→ 设为默认

第一步：内容创作（选项卡 ①）
  新建会话 → 输入主题 → 多轮修改 → 满意

第二步：HTML 设计（选项卡 ②）
  发送消息让智能体生成 PPT（自动读取 content.md）→ 生成幻灯片卡片
  → 预览/逐张修改/新增删除移动 → 满意
  （需要决策时出现问题卡片，作答后继续）

第三步：生成视频（选项卡 ③）
  配置比例/语音人设/字幕等 → 一键生成 或 高级生成（逐张/合成）→ 下载视频
```

---

> **声明**：本文档目前基本与代码保持一致，但项目仍在持续迭代，部分细节可能与最新代码存在出入。请在实际使用/开发时，请以代码为准，自行分析辨别差异。

**文档结束**
