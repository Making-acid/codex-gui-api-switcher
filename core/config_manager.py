"""Codex config.toml 增量读写与覆盖追踪。

只操作 API 相关键（白名单），其余段落（插件/MCP/市场/桌面设置等）原样保留。
"""
from __future__ import annotations

import json
import os
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

import tomlkit

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

RESERVED_PROVIDER_IDS = {
    "openai",
    "ollama",
    "lmstudio",
    "amazon-bedrock",
    "amazon-bedrock-runtime",
}

# 本工具可以管理的顶层键（白名单）
API_KEYS = (
    "model",
    "model_provider",
    "openai_base_url",
    "oss_provider",
    "model_providers",
)

# 允许透传编辑的额外顶层键（非 API 必需，但常见于切换场景）
EXTRA_KEYS = ("model_reasoning_effort", "service_tier")

DEFAULT_CONFIG_PATH = Path(os.environ.get("CODEX_HOME", "~")).expanduser() / ".codex" / "config.toml"
DEFAULT_DATA_DIR = Path(os.environ.get("CODEX_HOME", "~")).expanduser() / ".codex" / "codex-api-manager"
OVERRIDES_FILE = "overrides.json"

# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------


class ConfigError(Exception):
    """配置读写/校验错误。"""


class ReservedProviderError(ConfigError):
    """试图覆盖内置 provider。"""


# ---------------------------------------------------------------------------
# 数据
# ---------------------------------------------------------------------------


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# 主类
# ---------------------------------------------------------------------------


class ConfigManager:
    def __init__(self, config_path: str | Path | None = None, data_dir: str | Path | None = None):
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self.data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # 路径与状态
    # ------------------------------------------------------------------

    def exists(self) -> bool:
        return self.config_path.is_file()

    def mtime(self) -> float | None:
        if not self.exists():
            return None
        return self.config_path.stat().st_mtime

    def overrides_file(self) -> Path:
        return self.data_dir / OVERRIDES_FILE

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------

    def read_document(self) -> tomlkit.TOMLDocument:
        if not self.exists():
            return tomlkit.parse("")
        text = self.config_path.read_text(encoding="utf-8")
        try:
            return tomlkit.parse(text)
        except Exception as exc:  # tomlkit.TOMLKitError
            raise ConfigError(
                f"config.toml 解析失败（文件可能被其他程序修改）：{exc}"
            ) from exc

    def read_raw(self) -> str:
        if not self.exists():
            return ""
        return self.config_path.read_text(encoding="utf-8")

    def read_api_config(self) -> dict:
        """提取 API 相关结构化配置 + 原始 TOML。"""
        doc = self.read_document()
        providers = {}
        providers_table = doc.get("model_providers")
        if isinstance(providers_table, dict):
            for pid, p in providers_table.items():
                if isinstance(p, dict):
                    providers[str(pid)] = _provider_info(p)
        cfg = {
            "model": _str_or_none(doc.get("model")),
            "model_provider": _str_or_none(doc.get("model_provider")),
            "openai_base_url": _str_or_none(doc.get("openai_base_url")),
            "oss_provider": _str_or_none(doc.get("oss_provider")),
            "model_providers": providers,
            "raw": tomlkit.dumps(doc),
            "path": str(self.config_path),
            "exists": self.exists(),
        }
        return cfg

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def write(self, api_config: dict) -> dict:
        """增量写回 API 相关键。

        api_config 中出现的键：模型/model_providers 会被设置；
        值为 None 的键会被移除（如删除某个 provider）。
        返回变更摘要。
        """
        with self._lock:
            if not self.exists():
                raise ConfigError(f"配置文件不存在: {self.config_path}")
            doc = self.read_document()
            changes = []
            overrides_before = self.get_overrides()

            # 1) 顶层标量（model_providers 子表单独处理，跳过）
            for key in API_KEYS + EXTRA_KEYS:
                if key == "model_providers":
                    continue
                if key not in api_config:
                    continue
                value = api_config[key]
                before = _key_value(doc, key)
                if value is None or value == "" or value == {}:
                    if key in doc:
                        self._record_override(overrides_before, key, before, "write")
                        del doc[key]
                        changes.append({"key": key, "before": before, "after": None})
                else:
                    after = _json_compat(value)
                    if _json_compat(before) != after:
                        self._record_override(overrides_before, key, before, "write")
                        doc[key] = after
                        changes.append({"key": key, "before": before, "after": after})

            # 2) model_providers 子表
            if "model_providers" in api_config:
                providers = api_config["model_providers"] or {}
                self._apply_providers(doc, providers, overrides_before, changes)

            text = tomlkit.dumps(doc)
            self._atomic_write(text)
            self._save_overrides(overrides_before)
            return {"ok": True, "changes": changes, "raw": text}

    def remove_provider(self, provider_id: str) -> dict:
        """删除单个自定义 provider。"""
        return self.write({"model_providers": {provider_id: None}})

    # ------------------------------------------------------------------
    # 覆盖追踪 / 恢复默认
    # ------------------------------------------------------------------

    def get_overrides(self) -> list[dict]:
        if not self.overrides_file().is_file():
            return []
        try:
            return json.loads(self.overrides_file().read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def restore_overrides(self, keys: list[str] | None = None) -> dict:
        """移除本工具管理的覆盖：还原原值（原不存在则删除键）。

        keys=None 表示全部；keys 可指定子集。
        """
        with self._lock:
            overrides = self.get_overrides()
            if keys is not None:
                keyset = set(keys)
                selected = [o for o in overrides if o["key"] in keyset]
            else:
                selected = list(overrides)
            if not selected:
                return {"ok": True, "changes": []}

            doc = self.read_document()
            changes = []
            remaining = list(overrides)
            for entry in selected:
                key = entry["key"]
                resolved = _resolve_path(doc, key)
                before = _key_value(*resolved) if resolved else None
                if resolved is None:
                    # 键当前不存在（曾手动删除等情况）→ 只需从追踪清单摘除
                    changes.append({"key": key, "before": before, "after": entry["before"]})
                    remaining = [o for o in remaining if o["key"] != key]
                    continue
                parent, leaf = resolved
                if entry["before"] is None:
                    if leaf in parent:
                        del parent[leaf]
                else:
                    parent[leaf] = _to_toml(entry["before"])
                changes.append({"key": key, "before": before, "after": entry["before"]})
                remaining = [o for o in remaining if o["key"] != key]

            text = tomlkit.dumps(doc)
            self._atomic_write(text)
            self._save_overrides(remaining)
            return {"ok": True, "changes": changes, "raw": text}

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _apply_providers(self, doc, providers: dict, overrides_before, changes) -> None:
        existing = doc.get("model_providers")
        if not isinstance(existing, dict):
            if providers:
                doc["model_providers"] = tomlkit.table()
            else:
                return

        table = doc["model_providers"]
        for pid, spec in providers.items():
            self._validate_provider_id(pid)
            if spec is None:
                # 删除
                if pid in table:
                    before = _key_value(table, pid)
                    self._record_override(overrides_before, f"model_providers.{pid}", before, "write")
                    del table[pid]
                    changes.append({"key": f"model_providers.{pid}", "before": before, "after": None})
                continue
            # 新增/更新
            spec = _provider_info(spec)
            before = _key_value(table, pid)
            self._validate_provider_spec(pid, spec)
            sub = table.get(pid)
            if not isinstance(sub, dict):
                sub = tomlkit.table()
                table[pid] = sub
            for field in ("name", "base_url", "env_key", "wire_api", "requires_openai_auth",
                          "query_params", "http_headers", "env_http_headers",
                          "experimental_bearer_token", "env_key_instructions"):
                if field not in spec:
                    continue
                value = spec[field]
                if value is None:
                    if field in sub:
                        del sub[field]
                else:
                    sub[field] = _to_toml(value)
            if before is None or _json_compat(before) != _json_compat(spec):
                self._record_override(overrides_before, f"model_providers.{pid}", before, "write")
                changes.append({"key": f"model_providers.{pid}", "before": before, "after": spec})

    def _validate_provider_id(self, provider_id: str) -> None:
        if provider_id in RESERVED_PROVIDER_IDS:
            raise ReservedProviderError(
                f"`{provider_id}` 是内置 provider ID，不可覆盖。请改用其他名字（如 {provider_id}-custom）。"
            )

    def _validate_provider_spec(self, provider_id: str, spec: dict) -> None:
        name = spec.get("name")
        if not name or not str(name).strip():
            raise ConfigError(f"model_providers.{provider_id}: name 不能为空")
        wire = spec.get("wire_api", "responses")
        if wire != "responses":
            raise ConfigError(
                f"model_providers.{provider_id}: wire_api 仅支持 \"responses\"（chat 已被 Codex 移除）"
            )

    def _record_override(self, overrides_before, key: str, before, by: str) -> None:
        exists = [o for o in overrides_before if o["key"] == key]
        if exists:
            return  # 已记录过，保留最早的原值
        overrides_before.append({
            "key": key,
            "before": _json_compat(before),
            "applied_at": utcnow_iso(),
            "by": by,
        })

    def _save_overrides(self, overrides: list[dict]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.overrides_file().write_text(
            json.dumps(overrides, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _atomic_write(self, text: str) -> None:
        """原子写：先写临时文件再 os.replace，崩溃不损坏原文件。"""
        backup_path = self.config_path.with_suffix(".toml.bak")
        try:
            shutil.copy2(self.config_path, backup_path)
        except OSError:
            pass
        tmp = self.config_path.with_suffix(".toml.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, self.config_path)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _str_or_none(value):
    if value is None:
        return None
    return str(value)


def _key_value(table, key):
    if key not in table:
        return None
    return _json_compat(table[key])


def _resolve_path(doc, path: str):
    """解析带点路径（如 model_providers.openai-custom），返回 (父容器, 末段)。"""
    parts = path.split(".")
    if not parts:
        return None
    node = doc
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    if not isinstance(node, dict) or parts[-1] not in node:
        return None
    return (node, parts[-1])


def _to_toml(value):
    """把纯 Python 结构转成 tomlkit 结构（dict → table，list → array），
    避免嵌套写入时退化为 inline table 破坏格式。"""
    if isinstance(value, dict):
        table = tomlkit.table()
        for k, v in value.items():
            table[str(k)] = _to_toml(v)
        return table
    if isinstance(value, (list, tuple)):
        arr = tomlkit.array()
        for v in value:
            arr.append(_to_toml(v))
        return arr
    return value


def _json_compat(value):
    """把 tomlkit 类型转成纯 Python（JSON 可序列化）。"""
    if value is None:
        return None
    if hasattr(value, "value") and isinstance(value, (tomlkit.items.String, tomlkit.items.Integer,
                                                       tomlkit.items.Float, tomlkit.items.Bool,
                                                       tomlkit.items.Date, tomlkit.items.Time,
                                                       tomlkit.items.DateTime)):
        return value.value
    if isinstance(value, dict):
        return {str(k): _json_compat(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compat(v) for v in value]
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return str(value)
    return str(value)


def _provider_info(p) -> dict:
    out = {}
    for field in ("name", "base_url", "env_key", "wire_api", "requires_openai_auth",
                  "query_params", "http_headers", "env_http_headers",
                  "experimental_bearer_token", "env_key_instructions"):
        if field in p:
            out[field] = _json_compat(p[field])
    return out
