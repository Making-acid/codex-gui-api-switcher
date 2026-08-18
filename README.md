# Codex API Manager

一个图形化轻松修改 Codex API 配置的工具（Windows）。

## 功能

- **一键切换供应商**：选模板 → 选模型 → 填 API key → 应用。内置 OpenAI 官方 / Azure OpenAI / Ollama / LM Studio / 通用 Responses 中转站模板
- **零破坏写入**：用 tomlkit 增量修改 `~/.codex/config.toml`，插件 / MCP / 市场 / 桌面设置等段落原样保留
- **密钥管理**：写入 Windows 用户环境变量（Codex Desktop 主通道）或 `.env` 文件，全程脱敏
- **连通性测试**：以 `/responses` smoke 请求为判定核心，`/models` 探测为参考
- **备份与恢复**：每次写操作前自动备份到 `~/.codex/codex-api-manager/backups/`，可一键回退任意时间点
- **恢复默认**：仅移除本工具修改过的键（覆盖追踪清单可勾选），不整份覆盖配置文件
- **我的默认**：把当前 API 配置另存为命名模板，随时一键应用

## 快速开始

```bash
pip install -r requirements.txt
python app.py            # 桌面窗口（Edge WebView2）
python app.py --browser  # 用浏览器打开
```

## 打包为桌面软件（exe）

```bash
pip install pyinstaller
python -m PyInstaller --clean --noconfirm CodexAPIManager.spec
# 产物：dist\CodexAPIManager.exe（单文件，双击即用，无需 Python 环境）
```

## 使用提示

- 写入用户环境变量后需**重启 Codex Desktop** 才会生效（GUI 进程只继承启动时的环境变量）
- 新版 Codex 仅支持 Responses API 协议（`wire_api = "chat"` 已被官方移除）。若你的服务商只提供 Chat Completions 接口，需要经兼容 Responses 的中转网关（二期将内置本地转换代理）
- 内置 provider ID（`openai` / `ollama` / `lmstudio` / `amazon-bedrock`）不可覆盖，自定义 provider 使用其他名字

## 目录结构

```
app.py                  # 入口（桌面窗口 / --browser 双模式）
server.py               # Flask REST API
core/
  config_manager.py     # tomlkit 增量读写 + 覆盖追踪
  backups.py            # 备份 / 恢复 / 恢复默认
  providers.py          # 供应商模板逻辑
  env_manager.py        # 用户环境变量 + .env 双 scope
  connectivity.py       # 连通测试（/responses smoke）
static/                 # 前端（原生 JS，离线可用）
templates/providers.json# 供应商模板数据
tests/                  # 单元测试
```

## 测试

```bash
python -m unittest discover -s tests
```

## 路线图

- **1.1**：命令中心（codex doctor / exec / login 图形化执行）
- **二期**：内置 Responses→Chat Completions 转换代理，解锁 DeepSeek / 通义 / 豆包 / Kimi / 智谱 / OpenRouter 等全部 OpenAI 兼容服务商

详细设计见 [DESIGN.md](DESIGN.md)。
