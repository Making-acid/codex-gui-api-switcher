"""Flask 应用：一期全部 REST API + 前端静态服务。

安全：服务仅绑定 127.0.0.1；提供 auth_token 时，/api/* 请求必须携带
X-Auth-Token（或 ?token=）且 Origin 必须为本地；测试接口仅允许 http/https。
"""
from __future__ import annotations

import json
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, jsonify, request, send_from_directory

from core.backups import BackupError, BackupManager
from core.config_manager import ConfigManager, ConfigError
from core.connectivity import test_connection
from core.env_manager import EnvError, EnvManager
from core.providers import (
    CHATGPT_CLEAR_MARKER,
    TemplateError,
    build_apply_config,
    build_chatgpt_clear_config,
    load_templates,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULTS_FILE = "my-defaults.json"
VERSION = "1.1.0"

# 保留（read_api_config 返回 raw 中含 experimental_bearer_token 明文，
# 不再对外返回 raw 字段）
SENSITIVE_RAW_FIELD = "raw"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_app(config_manager: ConfigManager | None = None,
               env_manager: EnvManager | None = None,
               auth_token: str | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["JSON_AS_ASCII"] = False

    mgr = config_manager or ConfigManager()
    env = env_manager or EnvManager()
    backups = BackupManager(mgr)
    state_lock = threading.RLock()

    # 首次运行时自动生成初始状态快照（baseline），供"恢复 Codex 原始配置"使用
    backups.ensure_baseline()

    # ------------------------------------------------------------------
    # 鉴权：token 校验 + Origin 校验（仅 /api/*）
    # ------------------------------------------------------------------

    @app.before_request
    def guard():
        if not request.path.startswith("/api/"):
            return None
        origin = request.headers.get("Origin")
        if origin:
            host = urlparse(origin).hostname
            if host != "127.0.0.1":
                return jsonify({"ok": False, "message": "跨源请求被拒绝"}), 403
        if auth_token:
            header_token = request.headers.get("X-Auth-Token", "")
            query_token = request.args.get("token", "")
            if not secrets.compare_digest(header_token, auth_token) and \
               not secrets.compare_digest(query_token, auth_token):
                return jsonify({"ok": False, "message": "未授权"}), 403
        return None

    # ------------------------------------------------------------------
    # 通用
    # ------------------------------------------------------------------

    def _err(message: str, code: int = 400):
        return jsonify({"ok": False, "message": str(message)}), code

    def _auto_backup(note: str):
        try:
            backups.create_backup(note=note, source="auto")
        except Exception:
            pass

    def _read_defaults() -> list[dict]:
        p = mgr.data_dir / DEFAULTS_FILE
        if not p.is_file():
            return []
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def _save_defaults(entries: list[dict]) -> None:
        mgr.data_dir.mkdir(parents=True, exist_ok=True)
        (mgr.data_dir / DEFAULTS_FILE).write_text(
            json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # 状态 / 配置
    # ------------------------------------------------------------------

    @app.get("/api/status")
    def status():
        return jsonify({
            "ok": True,
            "version": VERSION,
            "template_count": len(load_templates()),
            "platform": "windows",
            "config": {
                "path": str(mgr.config_path),
                "exists": mgr.exists(),
                "mtime": mgr.mtime(),
            },
            "env_file": str(env.env_file),
            "backup_count": len(backups.list_backups()),
            "override_count": len(mgr.get_overrides()),
            "default_count": len(_read_defaults()),
        })

    @app.get("/api/config")
    def get_config():
        cfg = mgr.read_api_config()
        # raw 全文含 experimental_bearer_token 等明文，不外发
        cfg.pop(SENSITIVE_RAW_FIELD, None)
        overrides = mgr.get_overrides()
        return jsonify({"ok": True, "config": cfg, "overrides": overrides})

    @app.put("/api/config")
    def put_config():
        body = request.get_json(silent=True) or {}
        api_config = body.get("config") or body
        with state_lock:
            _auto_backup("写回 API 配置前")
            try:
                result = mgr.write(api_config)
            except ConfigError as exc:
                return _err(str(exc), 400)
            return jsonify({"ok": True, "changes": result["changes"]})

    # ------------------------------------------------------------------
    # 模板
    # ------------------------------------------------------------------

    @app.get("/api/templates")
    def templates():
        return jsonify({"ok": True, "templates": load_templates()})

    @app.post("/api/templates/apply")
    def apply_template():
        body = request.get_json(silent=True) or {}
        template_id = body.get("template_id")
        if not template_id:
            return _err("缺少 template_id")
        env_scope = body.get("env_scope") or "user"
        try:
            built = build_apply_config(
                template_id,
                model=body.get("model"),
                provider_id=body.get("provider_id"),
                base_url=body.get("base_url"),
                query_params=body.get("query_params"),
            )
        except (TemplateError, ConfigError) as exc:
            return _err(str(exc), 400)

        api_config = built["config"]
        env_key = built["env_key"]
        api_key = body.get("api_key")

        # ChatGPT 订阅模式：展开为清空全部 API 覆盖的指令
        if api_config.get(CHATGPT_CLEAR_MARKER):
            api_config = build_chatgpt_clear_config(mgr.read_api_config())
            env_key = None
            api_key = None
            chatgpt_mode = True
        else:
            chatgpt_mode = False

        with state_lock:
            _auto_backup(f"应用模板 {template_id}")
            try:
                result = mgr.write(api_config)
            except ConfigError as exc:
                return _err(str(exc), 400)
            # 顺序：config 成功后才写 env；env 失败则回滚 config，避免残留
            if api_key and env_key:
                try:
                    if env_scope == "file":
                        env.write_env_file([{"name": env_key, "value": api_key}])
                    else:
                        env.write_user_env([{"name": env_key, "value": api_key}])
                except Exception as exc:
                    try:
                        mgr.restore_overrides()
                    except ConfigError:
                        pass
                    return _err(f"写入环境变量失败，已回滚本次配置更改: {exc}", 500)

        return jsonify({
            "ok": True,
            "changes": result["changes"],
            "env_key": env_key,
            "env_scope": env_scope,
            "restart_required": (bool(api_key) and bool(env_key) and env_scope == "user"),
            "message": ("已切回 ChatGPT 订阅模式（Codex 原生登录态）。请重启 Codex Desktop，"
                        "用你的 ChatGPT 账号登录即可使用订阅配额。")
            if chatgpt_mode
            else ("应用成功。若写入的是用户环境变量，请重启 Codex Desktop 后生效。"
                  if (bool(api_key) and bool(env_key) and env_scope == "user")
                  else "应用成功。"),
        })

    # ------------------------------------------------------------------
    # 连通测试
    # ------------------------------------------------------------------

    @app.post("/api/test-connection")
    def test_conn():
        body = request.get_json(silent=True) or {}
        base_url = body.get("base_url")
        model = body.get("model")
        if not base_url or not model:
            return _err("需要 base_url 与 model")
        if urlparse(base_url).scheme not in ("http", "https"):
            return _err("仅支持 http/https 地址")
        result = test_connection(
            base_url,
            body.get("api_key"),
            model,
            headers=body.get("headers"),
            query_params=body.get("query_params"),
            timeout=body.get("timeout", 20),
        )
        return jsonify({"ok": True, **result})

    # ------------------------------------------------------------------
    # 环境变量
    # ------------------------------------------------------------------

    @app.get("/api/env")
    def get_env():
        scope = request.args.get("scope", "all")
        out = {}
        if scope in ("user", "all"):
            try:
                values = env.read_user_env()
            except OSError as exc:
                return _err(f"读取用户环境变量失败: {exc}", 500)
            out["user"] = [{"name": n, "masked": _mask(n, v)} for n, v in values.items()]
        if scope in ("file", "all"):
            out["file"] = env.read_env_file()
        return jsonify({"ok": True, "env": out, "env_file": str(env.env_file)})

    @app.put("/api/env")
    def put_env():
        scope = request.args.get("scope")
        body = request.get_json(silent=True) or {}
        entries = body.get("entries")
        if scope not in ("user", "file"):
            return _err("需要 scope=user|file")
        if not isinstance(entries, list):
            return _err("entries 必须是数组")
        try:
            if scope == "user":
                result = env.write_user_env(entries)
            else:
                result = env.write_env_file(entries)
        except EnvError as exc:
            return _err(str(exc), 400)
        return jsonify({"ok": True, "restart_required": scope == "user", **result})

    @app.post("/api/env/import")
    def import_env():
        body = request.get_json(silent=True) or {}
        direction = body.get("direction")
        try:
            if direction == "file_to_user":
                result = env.import_file_to_user()
            elif direction == "user_to_file":
                result = env.export_user_to_file()
            else:
                return _err("direction 必须是 file_to_user|user_to_file")
        except OSError as exc:
            return _err(str(exc), 500)
        return jsonify({"ok": True, **result})

    # ------------------------------------------------------------------
    # 备份 / 恢复
    # ------------------------------------------------------------------

    @app.get("/api/backups")
    def list_backups():
        return jsonify({"ok": True, "backups": backups.list_backups()})

    @app.post("/api/backups")
    def create_backup():
        body = request.get_json(silent=True) or {}
        try:
            entry = backups.create_backup(note=body.get("note"), source="manual")
        except Exception as exc:
            return _err(str(exc), 500)
        return jsonify({"ok": True, "backup": entry})

    @app.post("/api/backups/restore")
    def restore_backup():
        body = request.get_json(silent=True) or {}
        backup_id = body.get("id")
        if not backup_id:
            return _err("缺少备份 id")
        try:
            result = backups.restore_backup(backup_id)
        except Exception as exc:
            return _err(str(exc), 400)
        return jsonify({"ok": True, **result, "message": "已恢复。"})

    # ------------------------------------------------------------------
    # baseline（初始状态快照）
    # ------------------------------------------------------------------

    @app.get("/api/baseline")
    def get_baseline():
        info = backups.get_baseline()
        if info["exists"]:
            info["note"] = "首次运行本工具时自动快照的 Codex 原始配置"
        return jsonify({"ok": True, "baseline": info})

    @app.post("/api/baseline/restore")
    def restore_baseline():
        with state_lock:
            try:
                result = backups.restore_baseline()
            except BackupError as exc:
                return _err(str(exc), 400)
        return jsonify({
            **result,
            "message": "已恢复到初始状态（Codex 原始配置）。请重启 Codex Desktop 后生效。",
        })

    @app.post("/api/baseline/refresh")
    def refresh_baseline():
        with state_lock:
            try:
                result = backups.refresh_baseline()
            except BackupError as exc:
                return _err(str(exc), 400)
        return jsonify({"ok": True, **result})

    # ------------------------------------------------------------------
    # 覆盖追踪 / 恢复默认
    # ------------------------------------------------------------------

    @app.get("/api/overrides")
    def get_overrides():
        return jsonify({"ok": True, "overrides": mgr.get_overrides()})

    @app.post("/api/reset")
    def reset():
        body = request.get_json(silent=True) or {}
        keys = body.get("keys")
        with state_lock:
            _auto_backup("恢复默认前")
            try:
                result = mgr.restore_overrides(keys)
            except ConfigError as exc:
                return _err(str(exc), 400)
            return jsonify({"ok": True, "changes": result["changes"],
                            "message": "已移除所选覆盖。" if result["changes"]
                            else "没有需要移除的覆盖。"})

    # ------------------------------------------------------------------
    # 我的默认
    # ------------------------------------------------------------------

    @app.get("/api/defaults")
    def list_defaults():
        return jsonify({"ok": True, "defaults": _read_defaults()})

    @app.post("/api/defaults/save-as-mine")
    def save_as_mine():
        """保存"我的默认"：一律剥离密钥类字段（env_key/bearer/静态 headers），
        与"密钥不落盘"的设计一致。"""
        body = request.get_json(silent=True) or {}
        name = body.get("name") or "我的默认"
        cfg = mgr.read_api_config()
        for key in ("raw", "path", "exists"):
            cfg.pop(key, None)
        # 顶层无密钥字段；逐个 provider 剥离敏感字段
        for spec in cfg.get("model_providers", {}).values():
            for sensitive in ("env_key", "env_key_instructions",
                              "experimental_bearer_token", "http_headers"):
                spec.pop(sensitive, None)
        entry = {
            "id": datetime.now().strftime("%Y%m%d-%H%M%S"),
            "name": name,
            "saved_at": utcnow_iso(),
            "config": cfg,
        }
        entries = _read_defaults()
        entries.append(entry)
        _save_defaults(entries)
        return jsonify({"ok": True, "default": entry})

    @app.post("/api/defaults/apply")
    def apply_default():
        body = request.get_json(silent=True) or {}
        default_id = body.get("id")
        entries = _read_defaults()
        target = next((d for d in entries if d["id"] == default_id), None)
        if target is None:
            return _err("未找到该默认模板")
        with state_lock:
            _auto_backup(f"应用我的默认：{target['name']}")
            try:
                result = mgr.write(target["config"])
            except ConfigError as exc:
                return _err(str(exc), 400)
            return jsonify({"ok": True, "changes": result["changes"],
                            "message": "已应用我的默认。"})

    @app.post("/api/defaults/delete")
    def delete_default():
        body = request.get_json(silent=True) or {}
        default_id = body.get("id")
        entries = [d for d in _read_defaults() if d["id"] != default_id]
        _save_defaults(entries)
        return jsonify({"ok": True})

    # ------------------------------------------------------------------
    # 静态前端
    # ------------------------------------------------------------------

    @app.get("/")
    def index():
        resp = send_from_directory(STATIC_DIR, "index.html")
        resp.headers["Cache-Control"] = "no-store, max-age=0"
        return resp

    @app.get("/<path:filename>")
    def static_files(filename: str):
        resp = send_from_directory(STATIC_DIR, filename)
        resp.headers["Cache-Control"] = "no-store, max-age=0"
        return resp

    return app


def _mask(name: str, value: str) -> str:
    """用户环境变量脱敏：PATH 类变量全量返回，其余遮蔽。"""
    if name.upper() in ("PATH", "PATHEXT"):
        return value
    from core.env_manager import mask_secret
    return mask_secret(value)
