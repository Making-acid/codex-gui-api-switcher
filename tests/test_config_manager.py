"""config_manager 单元测试。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.config_manager import ConfigManager, ConfigError, ReservedProviderError

SAMPLE = """\
model = "gpt-5.6-sol"

[plugins."browser@openai-bundled"]
enabled = true

[mcp_servers.node_repl]
command = 'node_repl.exe'

[desktop]
sansFontSize = 14
"""


class ConfigManagerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = self.root / "config.toml"
        self.cfg.write_text(SAMPLE, encoding="utf-8")
        self.mgr = ConfigManager(config_path=self.cfg, data_dir=self.root / "data")

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_keeps_other_sections(self):
        cfg = self.mgr.read_api_config()
        self.assertEqual(cfg["model"], "gpt-5.6-sol")
        self.assertIn("browser@openai-bundled", cfg["raw"])

    def test_write_preserves_unrelated_sections(self):
        self.mgr.write({
            "model": "gpt-5.6-luna",
            "model_provider": "myprov",
            "model_providers": {
                "myprov": {
                    "name": "My Provider",
                    "base_url": "https://api.example.com/v1",
                    "env_key": "MY_API_KEY",
                    "wire_api": "responses",
                    "requires_openai_auth": False,
                }
            },
        })
        raw = self.cfg.read_text(encoding="utf-8")
        self.assertIn('model = "gpt-5.6-luna"', raw)
        self.assertIn('model_provider = "myprov"', raw)
        self.assertIn("browser@openai-bundled", raw)
        self.assertIn("mcp_servers.node_repl", raw)
        self.assertIn("sansFontSize", raw)
        # 未涉及键被保留
        self.assertIn('model = "gpt-5.6-luna"', raw)

    def test_remove_provider(self):
        self.mgr.write({"model_providers": {"myprov": {"name": "X", "base_url": "u"}}})
        self.mgr.remove_provider("myprov")
        cfg = self.mgr.read_api_config()
        self.assertNotIn("myprov", cfg["model_providers"])

    def test_null_value_removes_key(self):
        self.mgr.write({"model": "gpt-5.6-luna"})
        self.mgr.write({"model": None})
        cfg = self.mgr.read_api_config()
        self.assertIsNone(cfg["model"])

    def test_reserved_provider_rejected(self):
        with self.assertRaises(ReservedProviderError):
            self.mgr.write({"model_providers": {"openai": {"name": "x"}}})

    def test_wire_api_chat_rejected(self):
        with self.assertRaises(ConfigError):
            self.mgr.write({"model_providers": {"myprov": {"name": "X", "wire_api": "chat"}}})

    def test_overrides_recorded_and_restored(self):
        self.mgr.write({"model_provider": "myprov"})
        self.mgr.write({"model_provider": "other"})
        overrides = self.mgr.get_overrides()
        self.assertEqual(len(overrides), 1)
        self.assertEqual(overrides[0]["key"], "model_provider")
        self.assertIsNone(overrides[0]["before"])

        self.mgr.restore_overrides()
        cfg = self.mgr.read_api_config()
        self.assertIsNone(cfg["model_provider"])
        self.assertEqual(self.mgr.get_overrides(), [])

    def test_restore_original_value(self):
        # 模拟工具介入前用户已有配置：model_provider = "a"
        self.cfg.write_text('model_provider = "a"\n' + SAMPLE, encoding="utf-8")
        self.mgr.write({"model_provider": "b"})
        self.mgr.restore_overrides()
        cfg = self.mgr.read_api_config()
        self.assertEqual(cfg["model_provider"], "a")

    def test_restore_subset(self):
        self.mgr.write({"model": "gpt-x", "model_provider": "p"})
        overrides = self.mgr.get_overrides()
        keys = [o["key"] for o in overrides]
        self.assertEqual(len(keys), 2)
        self.mgr.restore_overrides([keys[0]])
        remaining = self.mgr.get_overrides()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["key"], keys[1])

    def test_missing_config_raises(self):
        mgr = ConfigManager(config_path=self.root / "nope.toml", data_dir=self.root / "d2")
        with self.assertRaises(ConfigError):
            mgr.write({"model": "x"})

    def test_restore_nested_provider_key(self):
        # 嵌套路径键（model_providers.X）必须能被覆盖追踪/恢复删除
        self.mgr.write({"model_providers": {"p1": {"name": "P1", "base_url": "u"}}})
        self.mgr.write({"model_provider": "p1"})
        self.mgr.restore_overrides()
        cfg = self.mgr.read_api_config()
        self.assertEqual(cfg["model_providers"], {})
        self.assertIsNone(cfg["model_provider"])
        self.assertEqual(self.mgr.get_overrides(), [])

    def test_roundtrip_provider_fields(self):
        self.mgr.write({
            "model_providers": {
                "p1": {
                    "name": "P1",
                    "base_url": "https://u/v1",
                    "env_key": "P1_KEY",
                    "wire_api": "responses",
                    "requires_openai_auth": False,
                    "query_params": {"api-version": "2024-10-21"},
                    "http_headers": {"X-Test": "1"},
                }
            }
        })
        cfg = self.mgr.read_api_config()
        p = cfg["model_providers"]["p1"]
        self.assertEqual(p["query_params"], {"api-version": "2024-10-21"})
        self.assertEqual(p["http_headers"], {"X-Test": "1"})
        self.assertFalse(p["requires_openai_auth"])


if __name__ == "__main__":
    unittest.main()
