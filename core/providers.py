"""供应商模板库：加载 / 校验 / 生成一键应用配置。"""
from __future__ import annotations

import json
from pathlib import Path

from core.config_manager import ConfigError, RESERVED_PROVIDER_IDS

TEMPLATES_FILE = Path(__file__).resolve().parent.parent / "templates" / "providers.json"

# 本地 OSS 服务不写 model_provider（Codex 通过 oss_provider 选择）
KIND_OSS = "oss"
KIND_CUSTOM = "custom"


class TemplateError(Exception):
    pass


def load_templates() -> list[dict]:
    with TEMPLATES_FILE.open("r", encoding="utf-8") as fh:
        templates = json.load(fh)
    for t in templates:
        if "provider_id" in t and t["kind"] == KIND_CUSTOM:
            t["provider_id"] = _safe_provider_id(t["provider_id"])
    return templates


def get_template(template_id: str) -> dict:
    for t in load_templates():
        if t["id"] == template_id:
            return t
    raise TemplateError(f"未知模板: {template_id}")


def _safe_provider_id(pid: str) -> str:
    """避免与内置 ID 冲突。"""
    if pid in RESERVED_PROVIDER_IDS:
        return f"{pid}-custom"
    return pid


def build_apply_config(template_id: str, model: str | None = None,
                       provider_id: str | None = None,
                       base_url: str | None = None,
                       query_params: dict | None = None) -> dict:
    """把模板展开为可直接写入 config.toml 的结构化配置。

    返回 {config: {...}, env_key: str|None}
    """
    t = get_template(template_id)
    kind = t["kind"]
    model = model or t.get("default_model")
    env_key = t.get("default_env_key")

    if kind == KIND_OSS:
        oss_id = t.get("oss_id") or template_id
        config = {"oss_provider": oss_id}
        if model:
            config["model"] = model
        return {"config": config, "env_key": env_key}

    if kind == KIND_CUSTOM:
        pid = provider_id or t.get("provider_id") or template_id
        pid = _safe_provider_id(pid)
        if pid in RESERVED_PROVIDER_IDS:
            raise ConfigError(f"`{pid}` 是内置 provider ID，请使用其他名字")
        url = base_url or t.get("base_url")
        if not url:
            raise ConfigError("该模板需要填写 base_url")
        qp = query_params if query_params is not None else t.get("query_params")
        spec = {
            "name": t["name"],
            "base_url": url,
            "wire_api": "responses",
            "requires_openai_auth": False,
        }
        if env_key:
            spec["env_key"] = env_key
        if qp:
            spec["query_params"] = qp
        config = {
            "model_provider": pid,
            "model_providers": {pid: spec},
        }
        if model:
            config["model"] = model
        return {"config": config, "env_key": env_key}

    raise TemplateError(f"模板 kind 不支持: {kind}")
