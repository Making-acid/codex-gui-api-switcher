"""供应商模板库单元测试：字段完整性 + 直连模板展开 + 附加配置写入。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.config_manager import ConfigManager
from core.providers import build_apply_config, get_template, load_templates

SAMPLE = """\
model = "gpt-5.6-sol"

[plugins."browser@openai-bundled"]
enabled = true
"""


class TemplateLibraryTest(unittest.TestCase):
    def test_all_templates_have_required_fields(self):
        templates = load_templates()
        self.assertGreaterEqual(len(templates), 27)
        seen = set()
        for t in templates:
            self.assertTrue(t.get("id"), f"模板缺 id: {t}")
            self.assertTrue(t.get("name"), f"模板缺 name: {t}")
            self.assertIn(t.get("kind"), ("custom", "oss", "builtin", "chatgpt"))
            self.assertNotIn(t["id"], seen, f"模板 id 重复: {t['id']}")
            seen.add(t["id"])
        for expected in ("chatgpt", "openai", "opencode-go", "deepseek", "kimi",
                         "minimax", "dashscope", "volcengine-ark", "zai", "xai"):
            self.assertIn(expected, seen, f"缺少模板: {expected}")

    def test_deepseek_direct_config(self):
        built = build_apply_config("deepseek")
        self.assertEqual(built["env_key"], "DEEPSEEK_API_KEY")
        cfg = built["config"]
        self.assertEqual(cfg["model_provider"], "deepseek")
        spec = cfg["model_providers"]["deepseek"]
        self.assertEqual(spec["base_url"], "https://api.deepseek.com")
        self.assertEqual(spec["wire_api"], "responses")
        self.assertEqual(cfg["model"], "deepseek-flash")

    def test_kimi_direct_config_with_context_window(self):
        built = build_apply_config("kimi")
        self.assertEqual(built["env_key"], "KIMI_API_KEY")
        cfg = built["config"]
        spec = cfg["model_providers"]["kimi"]
        self.assertEqual(spec["base_url"], "https://api.moonshot.cn/v1")
        self.assertEqual(spec["wire_api"], "responses")
        self.assertEqual(cfg["model"], "kimi-k3")
        self.assertEqual(cfg["model_context_window"], 1048576)

    def test_minimax_direct_config(self):
        built = build_apply_config("minimax")
        self.assertEqual(built["env_key"], "MINIMAX_API_KEY")
        cfg = built["config"]
        self.assertEqual(cfg["model_providers"]["minimax"]["base_url"], "https://api.minimax.cn/v1")
        self.assertEqual(cfg["model"], "MiniMax-M3")

    def test_extra_config_written_and_restorable(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cfg_path = root / "config.toml"
            cfg_path.write_text(SAMPLE, encoding="utf-8")
            mgr = ConfigManager(config_path=cfg_path, data_dir=root / "data")

            mgr.write(build_apply_config("kimi")["config"])
            raw = cfg_path.read_text(encoding="utf-8")
            self.assertIn("model_context_window", raw)
            self.assertIn("kimi-k3", raw)
            # 插件段保留
            self.assertIn("browser@openai-bundled", raw)

            mgr.restore_overrides()
            raw2 = cfg_path.read_text(encoding="utf-8")
            self.assertNotIn("model_context_window", raw2)
            self.assertIn('model = "gpt-5.6-sol"', raw2)


if __name__ == "__main__":
    unittest.main()
