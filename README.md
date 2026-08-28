# 驭帧(FrameDriver)·驭帧让每一帧知识，都尽在掌控。

PPT 内容生成 → 幻灯片 HTML → 视频生成的一体化平台（内容智能体 + PPT 智能体 + 视频流水线）。

## 项目介绍

### 项目简介
- 简介：驭帧一个「内容 → PPT → 视频」的全流程自动化平台：由 AI 智能体生成 PPT 内容与逐页幻灯片（HTML），再自动完成语音合成、字幕渲染与视频合成，输出成片。
- 版本：v1.0.0
- 开源地址：
    - **gitee地址**：https://gitee.com/zhaoguangxi/framedriver-html2video.git
    - **github地址**：https://github.com/zhaoguangxiorg/framedriver-html2video.git
- 项目名称:framedriver-html2video
- 开源协议：本项目基于 [Apache License 2.0](LICENSE) 开源协议。

### 核心功能

- **内容生成智能体**：根据主题生成结构化 PPT 内容（Markdown），支持中途人工介入确认；
- **PPT 生成智能体**：将内容生成逐页幻灯片 HTML，统一风格、可单独编辑每页；
- **视频流水线**：幻灯片截图 → 语音合成（edge-tts）→ 字幕渲染（确定性字体）→ 视频合成与拼接；
- **视频设置**：比例 / 分辨率 / 语音人设 / 字幕（字体、颜色、字号按分辨率自适应）等可配置。

### 技术架构

- **后端**：FastAPI + DeepAgnets(LangChain / LangGraph（Agent 编排）)+ SQLite（会话持久化）；
- **前端**：原生 HTML / CSS / JS（无框架）；
- **渲染**：Playwright 将 HTML 幻灯片截图为图片，ffmpeg 完成音视频合成。

## 快速启动

### 环境要求

- Python >= 3.11

### 安装依赖

```bash
pip install -r requirements.txt
```

### 浏览器运行时

视频流水线使用 Playwright 渲染幻灯片，需下载 Chromium（建议先设置 `PLAYWRIGHT_BROWSERS_PATH` 为项目内 `.playwright-browsers`，与 `video_pipeline/html_to_image.py` 的代码路径保持一致）：

```bash
set PLAYWRIGHT_BROWSERS_PATH=%CD%\.playwright-browsers   # Windows
export PLAYWRIGHT_BROWSERS_PATH="$(pwd)/.playwright-browsers"  # Linux
playwright install chromium
```

也可以直接运行一键部署脚本：Windows 执行 `scripts\setup.bat`，Linux 执行 `bash scripts/setup.sh`（自动创建虚拟环境、安装依赖并下载 Chromium）。

### 配置

复制 `.env.example` 为 `.env`（可选的运行参数：输出目录、加密密钥等；未配置时使用默认值或自动生成）：

```bash
cp .env.example .env
```

模型（API Key、Base URL 等）在应用的「设置 → 模型配置」界面中管理，无需写入 `.env`。

### 启动

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

浏览器访问 http://localhost:8000。

## 产品运行效果展示
- [产品效果展示](docs/product-demo.md)

## 产品文档

- [项目介绍](docs/project-intro.md)
- [设计文档](docs/architecture-design.md)
- [API 文档](docs/api-document.md)
- [视频设置](docs/video-settings.md)


## 第三方依赖及许可

本项目为纯源码开源（不含第三方库源码，依赖通过 `pip` 按 `requirements.txt` 引入）。主要第三方依赖及其许可如下：

| 依赖 | 用途 | 协议 |
|---|---|---|
| deepagents | Agent 框架 | MIT |
| langchain / langchain-openai / langchain-deepseek | LLM 编排与模型接入 | MIT |
| langgraph / langgraph-checkpoint-sqlite | Agent 状态图与持久化 | MIT |
| openai | OpenAI / DeepSeek API 客户端 | Apache-2.0 |
| playwright | 幻灯片渲染 | Apache-2.0 |
| edge-tts | 语音合成 | LGPL-3.0 |
| imageio-ffmpeg | ffmpeg 封装（内含 ffmpeg 可执行文件，LGPL） | BSD-2-Clause |
| python-dotenv | 环境变量加载 | BSD-3-Clause |
| pydantic | 数据模型 | MIT |
| fastapi | Web 框架 | MIT |
| uvicorn | ASGI 服务器 | BSD-3-Clause |
| sqlalchemy | 数据库 ORM | MIT |
| cryptography | 加密库 | Apache-2.0 OR BSD-3-Clause |

浏览器运行时：执行 `playwright install` 会下载 Chromium（BSD-3-Clause 许可）等浏览器组件，由使用者本地获取，本项目不随源码分发。

> 协议信息由 AI 辅助整理，依据各依赖发布时的官方许可声明，可能存在版本差异或整理疏漏，请以你实际安装版本及其官方许可为准，最终核准请自行确认。语音合成、AI 生成内容等相关事项见下方免责声明。

## 免责声明

语音合成（edge-tts）、AI 生成内容等相关事项声明，请查看独立声明页（`项目根目录下presentation/web/static/declaration.html`）。


## 作者

- 姓名：赵广西
- 邮箱：xige_aiagent_dev@163.com
- 简介： 
     - 赵广西架构师，十多年一线研发与架构设计经验；
     - 国内较早一批AI Agent开发转型实践与布道者；
     - AI Agent企业级平台从0到1实战落地经验；
     - 多个微服务架构师设计与研发落地经验； 
     - 多个saas系统架构设计与开发落地经验；
     - 多个产品研发与团队建设从0到1落地经验；
     - 提供AI Agent咨询/培训/开发服务。
