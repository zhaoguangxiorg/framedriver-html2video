# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""API layer (technical layer) for the PPT video generation system.

只包含 HTTP 技术逻辑：路由注册、请求模型、参数透传。
所有业务逻辑在 appservice/ 应用服务层；api 层对 appservice 一一调用，
不包含任何业务编排，也不反向引用 appservice 之外的业务模块。
"""