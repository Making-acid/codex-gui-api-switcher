# Codex API Manager

一个图形化轻松修改 Codex API 配置的工具。

- 一键切换供应商模板（OpenAI / Azure / Ollama / LM Studio / 通用 Responses 中转站）
- 填 API key 即用：自动写 `~/.codex/config.toml` + 管理 Windows 用户环境变量
- 内置 `Responses API` 连通性测试
- 每次写操作自动备份，可一键回退
- 恢复默认 = 仅移除本工具管理的覆盖配置（零破坏插件 / MCP 配置）

技术栈：Python 3.9 + Flask + tomlkit + pywebview（本地桌面窗口，离线可用）

详见 [DESIGN.md](DESIGN.md)。
