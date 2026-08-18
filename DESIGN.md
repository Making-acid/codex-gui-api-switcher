# Codex API Manager — 设计文档

> 版本：v2（2026-08-18）｜状态：设计已确认，待开发

## 1. 项目概述与目标

Codex（CLI / 桌面应用）通过 `~/.codex/config.toml` 配置模型供应商。当前需要手工编辑 TOML 才能切换 API，且新版 Codex 只支持 **Responses API 协议**（`wire_api = "chat"` 已被官方移除）。

本工具提供桌面图形界面，实现核心闭环：

```
选供应商模板 → 选模型 → 填 API key → 一键应用
    → 写 config.toml（tomlkit 增量，零破坏）
    → key 写入 Windows 用户环境变量
    → 自动备份 + 覆盖追踪
    → 可选连通性测试（Responses smoke）
```

硬性约束：

- **绝不整文件重写** `config.toml`（含插件 / MCP / 市场 / 桌面设置等无关段落，必须原样保留）
- 只操作 API 相关键：`model`、`model_provider`、`model_providers.*`、`openai_base_url`、`oss_provider` 等
- 每次写操作前自动备份，可回退任意时间点
- 密钥全程脱敏，不落日志、不入库

## 2. 技术选型

| 项 | 选择 | 理由 |
|---|---|---|
| 后端 | Flask + waitress | 依赖少，Python 3.9 兼容（本机 3.9.13） |
| TOML 读写 | tomlkit（增量修改） | 保留注释、键顺序与无关段落 |
| 桌面壳 | pywebview（Edge WebView2） | 系统自带渲染引擎，免 Electron 依赖 |
| 前端 | 原生 HTML/CSS/JS 单页，深色主题，无 CDN | 完全离线可用 |
| 网络 | 仅绑定 127.0.0.1 + 随机端口 | 本地安全，防局域网暴露 |
| 测试 | unittest + requests | 模块级自测 + 接口冒烟 |

## 3. 目录结构

```
codex改api/
├── DESIGN.md                # 本文件
├── README.md
├── app.py                   # 入口：pywebview 窗口 / --browser 双模式
├── server.py                # Flask 应用 + 全部 REST API
├── core/
│   ├── __init__.py
│   ├── config_manager.py    # tomlkit 增量读写 + 保留 ID 校验 + 覆盖追踪
│   ├── backups.py           # 自动备份 / 恢复 / 默认模板
│   ├── providers.py         # 供应商模板库（一期清单）
│   ├── env_manager.py       # user（Windows 用户级）与 .env 双 scope
│   ├── connectivity.py      # 连通测试（responses smoke 为核心）
│   ├── codex_runner.py      # 【1.1】codex.exe 动态发现 + 命令执行/终止
│   └── proxy.py             # 【二期】Responses→Chat 转换代理
├── static/
│   ├── index.html
│   ├── app.js
│   └── style.css
├── templates/
│   ├── providers.json       # 供应商模板数据（含 default_model / models）
│   └── factory.toml         # Codex 出厂最小配置参考（仅用于展示，不整份覆盖）
├── requirements.txt         # flask / tomlkit / requests / pywebview / waitress
└── .gitignore               # .env / 密钥 / 构建产物 一律忽略
```

## 4. 功能范围

### 4.1 一期（本次开发）

- **内置供应商模板**（原生 Responses 协议）：

  | 模板 | base_url | 说明 |
  |---|---|---|
  | openai | `https://api.openai.com/v1` | 官方；key 走 `OPENAI_API_KEY` |
  | azure-openai | 用户填 endpoint | 需填 `api-version` 等参数（query_params） |
  | ollama | `http://localhost:11434/v1` | 本地，Codex 内置支持 |
  | lmstudio | `http://localhost:1234/v1` | 本地，Codex 内置支持 |
  | generic-responses | 用户填 | 任意兼容 Responses 协议的中转站 |

- **一键切换流程**（见 §5）
- 备份 / 回退 / 恢复默认（覆盖清单式，见 §7）
- 连通测试（见 §8）
- 环境变量双 scope 管理（见 §6）

### 4.2 1.1（延后，不列入一期验收）

- 命令中心：codex.exe 动态发现（`AppData\Local\OpenAI\Codex\bin\` 最新版本目录 → config 内 `CODEX_CLI_PATH` → 手动指定）、`doctor` / `exec` / `login` 流式执行与终止、Codex Desktop 运行检测

### 4.3 二期（预留，接口已留位）

- 内置 **Responses→Chat Completions 本地转换代理**（127.0.0.1 随机端口），解锁全部 OpenAI 兼容服务商：DeepSeek、通义千问、豆包(火山方舟)、Kimi、智谱 GLM、腾讯混元、百度文心、MiniMax、OpenRouter、Groq / Mistral / xAI / Gemini、自定义中转站
- 协议映射要点（设计预留）：`POST /v1/responses` → `POST /v1/chat/completions`；字段映射 `instructions/input/tools` ↔ `messages/tools`；流式事件映射 `response.created` / `response.output_text.delta` / `response.completed`；`GET /v1/models` 软探测
- 切换时 `base_url` 指向本地代理，UI 不变（仍是"选供应商→填 key"）

## 5. 一键切换流程（核心用例）

```
用户操作：快速切换页 → 点供应商卡片 → 选模型 → 粘贴 API key → 点「应用」
后端执行：
  1. 读取当前 config.toml（tomlkit）
  2. 备份当前文件 → ~/.codex/backups/config-YYYYMMDD-HHMMSS.toml
  3. 记录覆盖追踪条目（每个将修改的键：原值 / 原不存在）
  4. 写 provider：
     - 自定义 provider → [model_providers.<id>]（name/base_url/env_key/wire_api="responses"/requires_openai_auth=false）
     - 内置 openai → openai_base_url
     - ollama/lmstudio → oss_provider
  5. model = 模板 default_model（或用户选择）
  6. key 写入用户级 Windows 环境变量（env_key 指向的名字），WM_SETTINGCHANGE 广播
  7. 返回变更摘要；界面提示「需重启 Codex Desktop 后生效」
可选：应用后自动触发连通测试
```

## 6. Key 传递机制（明确区分双 scope）

| Scope | 存储 | Codex Desktop 能否读到 | 用途 |
|---|---|---|---|
| `user`（默认，切换主通道） | Windows 用户环境变量（`HKCU\Environment`，注册表持久化） | ✅ 桌面应用与所有新开进程继承 | 一键切换时默认写入 |
| `file` | `.env` 文件（默认 `~/.codex/.env`，可自选路径） | ❌ 不读取 | 供自定义启动脚本 `set -a; source .env` 使用 |

关键机制：

- Codex Desktop 是 GUI 进程（从开始菜单/桌面启动），**只继承用户级环境变量**，不继承终端临时变量、不读 `.env`
- 写入 `user` 后：执行 `WM_SETTINGCHANGE` 广播（P/Invoke `SendMessageTimeout`），并**明确提示重启 Codex Desktop**
- 提供「从 .env 导入到 user」/「从 user 导出到 .env」互导按钮
- UI 双面板：左侧 user 变量，右侧 .env 文件内容；key 值一律遮蔽（`sk-****abc`），可切换明文
- 删除语义：value=null 即删除该变量

## 7. 覆盖追踪与恢复默认

### 7.1 覆盖追踪

- 工具在自身数据目录持久化 `overrides.json`（建议 `~/.codex/codex-api-manager/`，与 Codex 自身文件分离）：

```json
{
  "overrides": [
    {
      "key": "model_provider",
      "before": null,            // 原值；null = 原不存在
      "applied_at": "2026-08-18T12:00:00Z",
      "by": "template:openai"
    }
  ]
}
```

- 每次写操作前**记录**，写回成功后**追加**；备份文件与覆盖条目通过时间戳关联

### 7.2 恢复默认（语义 = 删除本工具的覆盖）

- 绝不整份覆盖 factory TOML
- 流程：确认页展示待移除键清单（键名 + 原值/原不存在）→ 用户勾选子集或全选 → 执行（自动备份 → tomlkit 移除/还原 → 从追踪清单摘除）→ 插件/MCP 零影响
- `GET /api/overrides` 随时可查

### 7.3 "我的默认"

- 把当前完整 API 配置（model + model_provider + model_providers + openai_base_url + oss_provider）另存为命名模板，可一键应用；默认不包含密钥（仅占位 env_key 名）

## 8. 连通测试策略

- **硬条件（判定依据）**：最小 `POST {base_url}/responses` smoke test

  ```
  POST {base_url}/responses
  Authorization: Bearer <key>
  { "model": "<model>", "input": "ping", "max_output_tokens": 1, "stream": false }
  ```

- **软探测（非硬条件）**：`GET {base_url}/models` —— 404 / 不支持 / 超时不判失败，仅展示可用模型供选择
- 报告内容：状态码、耗时、错误类型（网络/认证/协议/限流）、探测到的模型列表
- 测试请求经后端代理发出（避免 CORS 与密钥在前端直连暴露）

## 9. REST API 规格

> 全部绑定 127.0.0.1，JSON；写操作统一先备份、统一返回 `{ok, message, diff?}`

| 方法 | 路径 | 功能 |
|---|---|---|
| GET | `/api/status` | codex 路径/版本发现结果、config 路径与 mtime、备份数、Codex Desktop 运行检测【1.1】 |
| GET | `/api/config` | API 相关结构化配置 + 原始 TOML 文本 + 覆盖追踪摘要 |
| PUT | `/api/config` | 增量写回（body 传结构化 API 配置），自动备份 + 覆盖追踪，返回 diff |
| GET | `/api/templates` | 供应商模板列表（含 default_model、models、说明） |
| POST | `/api/templates/apply` | 模板一键应用：`{template_id, provider_name?, model?, api_key?, env_scope?}` |
| POST | `/api/test-connection` | `{base_url, api_key, model, headers?, query_params?, timeout?}` → responses smoke 结果 + models 软探测 |
| GET | `/api/env?scope=user\|file\|all` | 读环境变量（脱敏） |
| PUT | `/api/env?scope=user\|file` | `{entries: [{name, value\|null, masked?}]}`；写 user 后广播 + 返回「需重启」提示 |
| POST | `/api/env/import` | `.env` ↔ user 互导：`{direction: "file_to_user"\|"user_to_file"}` |
| GET | `/api/backups` | 备份列表（时间、来源：手动/自动/恢复前、备注） |
| POST | `/api/backups` | 手动创建备份：`{note?}` |
| POST | `/api/backups/restore` | `{id}` 恢复（恢复前自动备份当前） |
| GET | `/api/overrides` | 覆盖追踪清单（§7.1） |
| POST | `/api/reset` | `{keys?: [...]}` 移除指定/全部覆盖（确认页数据来自 /api/overrides） |
| GET | `/api/defaults` | "我的默认"命名模板列表 |
| POST | `/api/defaults/save-as-mine` | `{name?, include_keys?: bool}` 保存当前配置为默认模板 |
| POST | `/api/defaults/apply` | `{id}` 应用"我的默认" |
| GET | `/api/commands` | 【1.1】可用命令列表 |
| POST | `/api/run` | 【1.1】`{command, args, cwd}` 启动子进程返回 job_id |
| GET | `/api/run/{id}/output` | 【1.1】增量拉取输出 |
| POST | `/api/run/{id}/kill` | 【1.1】终止进程 |

## 10. 数据模型

```python
# ModelProviderInfo（对应 config.toml [model_providers.X]）
class ModelProviderInfo:
    name: str
    base_url: str | None
    env_key: str | None            # 读哪个环境变量拿 key
    wire_api: str = "responses"    # 仅允许 responses
    requires_openai_auth: bool = False
    query_params: dict | None
    http_headers: dict | None
    env_http_headers: dict | None
    experimental_bearer_token: str | None  # 不推荐，界面折叠

# ProviderTemplate（templates/providers.json 中的条目）
class ProviderTemplate:
    id: str
    name: str                       # 显示名
    kind: "custom" | "openai" | "oss"   # custom=写 model_providers；openai=写 openai_base_url；oss=写 oss_provider
    base_url: str | None            # None = 用户填写
    default_model: str              # 应用时写入 model= 的值
    models: list[str]               # 可选模型列表（UI 下拉）
    default_env_key: str            # 建议的 env_key 名，如 DEEPSEEK_API_KEY
    notes: str                      # 说明（是否需网关等）
    default_query_params: dict | None

# BackupEntry
class BackupEntry:
    id: str                         # config-20260818-120000
    path: str
    created_at: str
    source: "manual" | "auto" | "pre_restore"
    note: str | None

# OverrideEntry（§7.1）
class OverrideEntry:
    key: str
    before: any | None              # null = 原不存在
    applied_at: str
    by: str
```

保留 ID 校验（不可覆盖）：`openai`、`ollama`、`lmstudio`、`amazon-bedrock`、`amazon-bedrock-runtime`。

## 11. 前端 UI（6 标签页，深色主题）

1. **快速切换**：供应商卡片网格（含"当前生效"徽标）→ 选模型下拉 → key 输入 → 应用按钮；结果横幅（成功 + "需重启 Codex Desktop 生效"提示）
2. **Provider 管理**：provider 列表 + 编辑表单（基础字段可见，headers/query_params/bearer_token 折叠为"高级"）
3. **连接测试**：目标选择（当前 provider / 自定义）→ 运行 → 结果面板（smoke 状态大字 + models 软信息）
4. **环境变量**：user / .env 双面板，遮蔽开关，互导按钮，新增/删除行
5. **备份与恢复**：备份时间线（来源着色）、恢复按钮（二次确认）、"恢复默认"入口（覆盖清单确认页）、"我的默认"管理
6. **命令中心**：【1.1】占位页

交互约定：所有写操作按钮带加载态；破坏性操作（恢复/删除）一律二次确认；错误 toast 展示后端 message。

## 12. 安全设计

- 服务仅绑定 `127.0.0.1`，随机端口，启动时输出访问地址
- 密钥：接口返回一律脱敏（保留尾 4 字符）；日志禁止打印；`.gitignore` 忽略 `.env`/`auth.json`/密钥类文件
- 无外部网络依赖：前端资源全部本地；测试请求仅由用户主动触发
- 写前校验 config 文件 mtime（检测桌面 App 是否可能并发覆盖），差异时提示

## 13. 开发步骤与一期验收

### 开发顺序
1. 项目骨架 + `requirements.txt` + 依赖安装
2. `core/config_manager.py`（tomlkit 读写 + 校验 + 覆盖追踪）+ 单测
3. `core/backups.py` + `core/providers.py`（含 templates/providers.json）
4. `core/env_manager.py`（双 scope + 广播）+ 单测
5. `core/connectivity.py`（smoke + 软探测）+ 单测
6. `server.py`（全部一期 API）
7. 前端三件套（index.html / app.js / style.css）
8. `app.py` 双模式入口
9. 真实 config.toml 端到端试运行（全程自动备份）
10. README 使用说明补充

### 一期验收清单
- [ ] 界面可打开（桌面窗口 / `--browser` 双模式）
- [ ] 一键切换 OpenAI / 通用中转站模板：选模型 → 填 key → 应用；key 写入用户级环境变量，提示重启 Codex Desktop
- [ ] 原 config.toml 插件/MCP 段零破坏（diff 验证）
- [ ] 写前自动备份，可回退任意时间点
- [ ] 恢复默认 = 仅移除工具写过的键（确认页列出清单）
- [ ] 连通测试以 /responses smoke 判定，/models 失败不影响结论
- [ ] "我的默认"保存与应用可用
- [ ] 密钥全程脱敏
- 命令中心 → 1.1，不列入一期验收

## 14. 二期转换代理（预留设计）

- 独立线程内 HTTP 服务（Flask 同款栈或 werkzeug 内嵌），监听 `127.0.0.1:<随机端口>`
- 路由：`POST /v1/responses`、`POST /v1/chat/completions`（直通）、`GET /v1/models`（映射）
- 映射表：`instructions` → `system`；`input`(字符串/数组) → `messages`；`tools`/`function` → `tools`；`reasoning.effort` → 供应商对应参数（如 `reasoning_effort` / `thinking.type`）；流式 SSE 事件逐条转换
- 模板新增 `kind="proxy"`，base_url 由工具动态生成
- 二期验收以 DeepSeek / OpenRouter 实跑为准
