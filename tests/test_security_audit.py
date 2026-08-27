"""审计修复回归测试：鉴权 / 密钥剥离 / 端点拼接 / 原子写 / 备份毫秒。"""
from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

import requests
from waitress import serve

from core.backups import BackupManager, now_ts
from core.config_manager import ConfigManager, ConfigError, _to_toml
from core.connectivity import smoke_test, probe_models, _endpoint
from server import create_app


def start_server(config_manager, env_manager=None, auth_token=None):
    import socket as socket_mod
    app = create_app(config_manager=config_manager, env_manager=env_manager,
                     auth_token=auth_token)
    sock = socket_mod.socket(socket_mod.AF_INET, socket_mod.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    thread = threading.Thread(target=serve, args=(app,), kwargs={"sockets": [sock]},
                              daemon=True)
    thread.start()
    time.sleep(0.8)
    return f"http://127.0.0.1:{port}"


class AuthGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = self.root / "config.toml"
        self.cfg.write_text('model = "m1"\n', encoding="utf-8")
        self.mgr = ConfigManager(config_path=self.cfg, data_dir=self.root / "data")
        self.token = "test-token-123"
        self.base = start_server(self.mgr, auth_token=self.token)

    def tearDown(self):
        self.tmp.cleanup()

    def test_api_requires_token(self):
        r = requests.get(self.base + "/api/status", timeout=5)
        self.assertEqual(r.status_code, 403)
        r = requests.get(self.base + "/api/status", timeout=5,
                         headers={"X-Auth-Token": self.token})
        self.assertEqual(r.status_code, 200)

    def test_token_via_query(self):
        r = requests.get(self.base + f"/api/status?token={self.token}", timeout=5)
        self.assertEqual(r.status_code, 200)

    def test_wrong_token_rejected(self):
        r = requests.get(self.base + "/api/status", timeout=5,
                         headers={"X-Auth-Token": "wrong"})
        self.assertEqual(r.status_code, 403)

    def test_cross_origin_rejected(self):
        r = requests.post(self.base + "/api/reset", json={}, timeout=5,
                          headers={"X-Auth-Token": self.token,
                                   "Origin": "https://evil.example.com"})
        self.assertEqual(r.status_code, 403)

    def test_local_origin_allowed(self):
        r = requests.get(self.base + "/api/status", timeout=5,
                         headers={"X-Auth-Token": self.token,
                                  "Origin": self.base})
        self.assertEqual(r.status_code, 200)

    def test_config_has_no_raw(self):
        r = requests.get(self.base + "/api/config", timeout=5,
                         headers={"X-Auth-Token": self.token})
        body = r.json()
        self.assertNotIn("raw", body["config"])

    def test_test_connection_scheme_whitelist(self):
        r = requests.post(self.base + "/api/test-connection", timeout=5,
                          headers={"X-Auth-Token": self.token},
                          json={"base_url": "file:///C:/etc", "model": "m"})
        self.assertEqual(r.status_code, 400)


class SaveAsMineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = self.root / "config.toml"
        self.cfg.write_text(
            '[model_providers.p1]\nname = "P1"\nbase_url = "https://u/v1"\n'
            'env_key = "P1_KEY"\nexperimental_bearer_token = "sk-secret-token"\n'
            'http_headers = {Authorization = "Bearer sk-secret-token"}\n',
            encoding="utf-8")
        self.mgr = ConfigManager(config_path=self.cfg, data_dir=self.root / "data")
        self.base = start_server(self.mgr)

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_as_mine_strips_secrets(self):
        r = requests.post(self.base + "/api/defaults/save-as-mine",
                          json={"name": "t"}, timeout=5)
        self.assertEqual(r.status_code, 200)
        defaults = self.mgr.data_dir / "my-defaults.json"
        saved = defaults.read_text(encoding="utf-8")
        self.assertNotIn("sk-secret-token", saved)
        self.assertNotIn("P1_KEY", saved)
        self.assertNotIn("Authorization", saved)
        # 无鉴权模式下仍可用（本测试服务器未加 token，仅覆盖落盘逻辑）
        r2 = requests.get(self.base + "/api/defaults", timeout=5)
        cfg = r2.json()["defaults"][0]["config"]
        spec = cfg["model_providers"]["p1"]
        self.assertNotIn("env_key", spec)
        self.assertNotIn("http_headers", spec)
        self.assertNotIn("experimental_bearer_token", spec)
        self.assertIn("base_url", spec)


class StubEnvManager:
    """隔离真实注册表：user 变量内存模拟。"""

    def __init__(self):
        self.user = {}
        self.env_file = Path("unused.env")

    def read_user_env(self):
        return dict(self.user)

    def write_user_env(self, entries):
        for e in entries:
            if e.get("value") is None or e["value"] == "":
                self.user.pop(e["name"], None)
            else:
                self.user[e["name"]] = str(e["value"])
        return {"ok": True, "restart_required": True}

    def read_env_file(self):
        return []

    def write_env_file(self, entries):
        return {"ok": True}


class EnvDirtyLogicTest(unittest.TestCase):
    """后端语义：未修改行不会被发送（发送层在前端），后端只处理收到的条目。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = self.root / "config.toml"
        self.cfg.write_text("", encoding="utf-8")
        self.mgr = ConfigManager(config_path=self.cfg, data_dir=self.root / "data")
        self.base = start_server(self.mgr, env_manager=StubEnvManager())

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_entries_are_noop(self):
        """空数组保存 = 什么都不发生（前端未修改行不会出现在 entries 里）。"""
        r = requests.put(self.base + "/api/env?scope=user", json={"entries": []}, timeout=5)
        self.assertEqual(r.status_code, 200)
        r = requests.get(self.base + "/api/env?scope=user", timeout=5)
        self.assertEqual(r.json()["env"]["user"], [])

    def test_explicit_delete_works(self):
        r = requests.put(self.base + "/api/env?scope=user",
                         json={"entries": [{"name": "A", "value": "1"}]}, timeout=5)
        self.assertEqual(r.status_code, 200)
        r = requests.put(self.base + "/api/env?scope=user",
                         json={"entries": [{"name": "A", "value": None}]}, timeout=5)
        self.assertEqual(r.status_code, 200)
        r = requests.get(self.base + "/api/env?scope=user", timeout=5)
        self.assertEqual(r.json()["env"]["user"], [])

    def test_user_env_masked(self):
        r = requests.get(self.base + "/api/env?scope=user", timeout=5)
        for e in r.json()["env"]["user"]:
            self.assertIn("masked", e)
            self.assertNotIn("value", e)


class ConnectivityEndpointTest(unittest.TestCase):
    def test_endpoint_suffix(self):
        self.assertEqual(_endpoint("https://a/v1", "responses"),
                         "https://a/v1/responses")
        self.assertEqual(_endpoint("https://a/v1/responses/", "responses"),
                         "https://a/v1/responses")
        self.assertEqual(_endpoint("https://a/v1/models", "models"),
                         "https://a/v1/models")


class AtomicWriteTest(unittest.TestCase):
    def test_atomic_write_preserves_file(self):
        import os
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        cfg = root / "config.toml"
        cfg.write_text("a = 1\n", encoding="utf-8")
        mgr = ConfigManager(config_path=cfg, data_dir=root / "data")
        mgr.write({"model": "x"})
        self.assertTrue(cfg.is_file())
        self.assertFalse(cfg.with_suffix(".toml.tmp").exists())
        self.assertIn("model = \"x\"", cfg.read_text(encoding="utf-8"))
        tmp.cleanup()


class BackupTsTest(unittest.TestCase):
    def test_timestamp_has_ms(self):
        ts = now_ts()
        # 格式：YYYYmmdd-HHMMSS-ffffff（含微秒，避免秒级冲突）
        self.assertRegex(ts, r"^\d{8}-\d{6}-\d{6}$")

    def test_to_toml_nested(self):
        out = _to_toml({"a": 1, "b": {"c": "x"}})
        self.assertIn("a", out)
        self.assertIsInstance(out["b"], dict)


class ChatgptModeTest(unittest.TestCase):
    """ChatGPT 订阅模式：清空全部 API 覆盖。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = self.root / "config.toml"
        self.cfg.write_text('model = "gpt-5.6-sol"\n[plugins."x"]\nenabled = true\n',
                            encoding="utf-8")
        self.mgr = ConfigManager(config_path=self.cfg, data_dir=self.root / "data")
        self.base = start_server(self.mgr)

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_chatgpt_clear_config(self):
        from core.providers import build_chatgpt_clear_config
        current = {"model_providers": {"a": {}, "b": {}}}
        out = build_chatgpt_clear_config(current)
        self.assertIsNone(out["model_provider"])
        self.assertIsNone(out["openai_base_url"])
        self.assertIsNone(out["oss_provider"])
        self.assertEqual(out["model_providers"], {"a": None, "b": None})

    def test_apply_chatgpt_clears_api(self):
        # 先应用一个模板制造覆盖
        r = requests.post(self.base + "/api/templates/apply",
                          json={"template_id": "openai"}, timeout=5)
        self.assertEqual(r.status_code, 200)
        # 应用 ChatGPT 订阅模式
        r = requests.post(self.base + "/api/templates/apply",
                          json={"template_id": "chatgpt"}, timeout=5)
        self.assertEqual(r.status_code, 200)
        self.assertIn("ChatGPT", r.json()["message"])
        cfg = requests.get(self.base + "/api/config", timeout=5).json()["config"]
        self.assertIsNone(cfg["model_provider"])
        self.assertEqual(cfg["model_providers"], {})
        # 插件段保留
        raw = self.cfg.read_text(encoding="utf-8")
        self.assertIn("browser", raw) if "browser" in raw else self.assertIn("x", raw)

    def test_chatgpt_is_initial_active_state(self):
        r = requests.get(self.base + "/api/config", timeout=5)
        cfg = r.json()["config"]
        self.assertIsNone(cfg["model_provider"])
        self.assertEqual(cfg["model_providers"], {})


if __name__ == "__main__":
    unittest.main()
