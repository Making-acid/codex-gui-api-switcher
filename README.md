# Codex API Manager

图形化修改 Codex API 配置的工具（Windows）。项目概述与完整设计见 [DESIGN.md](DESIGN.md)，最终用户操作说明见 [用户手册.md](用户手册.md)。

## 环境要求

- Python 3.9+（Windows）
- 运行桌面窗口需 Edge WebView2 Runtime（Win10/11 自带）

## 运行

```bash
pip install -r requirements.txt
python app.py            # 桌面窗口
python app.py --browser  # 浏览器模式
python app.py --no-window --port 18080   # 只起服务（调试 API）
```

## 打包 exe

```bash
pip install pyinstaller
python -m PyInstaller --clean --noconfirm CodexAPIManager.spec
# 产物：dist\CodexAPIManager.exe（单文件，双击即用）
```

## 测试

```bash
python -m unittest discover -s tests
```

## 目录结构

```
app.py                  # 入口（桌面窗口 / --browser / --no-window）
server.py               # Flask REST API（127.0.0.1 随机端口）
core/
  config_manager.py     # config.toml 增量读写（tomlkit）+ 覆盖追踪 + 校验
  backups.py            # 备份 / 恢复 / 覆盖清单式"恢复默认"
  providers.py          # 供应商模板加载与一键应用逻辑
  env_manager.py        # Windows 用户环境变量 + .env 双 scope（脱敏）
  connectivity.py       # 连通测试（/responses smoke 硬条件 + /models 软探测）
static/                 # 前端（原生 JS 单页，离线可用）
templates/providers.json# 供应商模板数据（含 default_model / models）
tests/                  # 单元测试（24 个）
CodexAPIManager.spec    # PyInstaller 打包配置
```

## 设计要点

- **零破坏写入**：只操作 API 相关键（`model` / `model_provider` / `model_providers` / `openai_base_url` / `oss_provider`），插件 / MCP / 市场等段落原样保留
- **覆盖追踪**：工具写过的每个键记录原值于 `~/.codex/codex-api-manager/overrides.json`，"恢复默认"= 按清单还原/删除，不整份覆盖
- **密钥**：默认写入用户环境变量（Codex Desktop 主通道，写后需重启）；`.env` 仅供脚本；接口返回一律脱敏
- **安全**：服务仅绑定 127.0.0.1，随机端口

## 路线图

- **1.1**：命令中心（codex doctor / exec / login 图形化执行）
- **二期**：内置 Responses→Chat Completions 转换代理，解锁 DeepSeek / 通义 / 豆包 / Kimi / 智谱 / OpenRouter 等

## REST API 一览

| 方法 | 路径 | 功能 |
|---|---|---|
| GET | `/api/status` | 服务与配置状态 |
| GET/PUT | `/api/config` | 读/写 API 结构化配置（写前自动备份） |
| GET | `/api/templates` | 供应商模板列表 |
| POST | `/api/templates/apply` | 模板一键应用（含写 key） |
| POST | `/api/test-connection` | 连通测试 |
| GET/PUT | `/api/env?scope=user\|file` | 环境变量读写 |
| POST | `/api/env/import` | .env ↔ 用户变量互导 |
| GET/POST | `/api/backups` | 备份列表 / 手动创建 |
| POST | `/api/backups/restore` | 恢复备份点 |
| GET | `/api/overrides` | 覆盖追踪清单 |
| POST | `/api/reset` | 移除所选/全部覆盖 |
| GET/POST | `/api/defaults` | "我的默认"模板管理 |
