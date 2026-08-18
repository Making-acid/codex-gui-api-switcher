"""env_manager 单元测试（file scope + 脱敏；user scope 涉及真实注册表，留待端到端验证）。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.env_manager import EnvManager, mask_secret


class EnvFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env_file = Path(self.tmp.name) / ".env"
        self.mgr = EnvManager(env_file=self.env_file)

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_and_read(self):
        self.mgr.write_env_file([
            {"name": "MY_KEY", "value": "sk-1234567890abcdef"},
            {"name": "BASE_URL", "value": "https://api.example.com/v1"},
        ])
        entries = self.mgr.read_env_file()
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["value"], "sk-1234567890abcdef")
        self.assertIn("****", entries[0]["masked"])
        self.assertEqual(entries[0]["masked"], "sk****cdef")

    def test_delete_entry(self):
        self.mgr.write_env_file([{"name": "A", "value": "1"}, {"name": "B", "value": "2"}])
        self.mgr.write_env_file([{"name": "A", "value": None}])
        entries = self.mgr.read_env_file()
        self.assertEqual([e["name"] for e in entries], ["B"])

    def test_update_preserves_others(self):
        self.mgr.write_env_file([{"name": "A", "value": "1"}, {"name": "B", "value": "2"}])
        self.mgr.write_env_file([{"name": "B", "value": "22"}])
        entries = {e["name"]: e["value"] for e in self.mgr.read_env_file()}
        self.assertEqual(entries, {"A": "1", "B": "22"})

    def test_missing_file_returns_empty(self):
        self.assertEqual(self.mgr.read_env_file(), [])

    def test_comment_lines_ignored(self):
        self.env_file.write_text("# comment\nA=1\n\nB=2\n", encoding="utf-8")
        entries = self.mgr.read_env_file()
        self.assertEqual([e["name"] for e in entries], ["A", "B"])


class MaskTest(unittest.TestCase):
    def test_mask(self):
        self.assertEqual(mask_secret("sk-abcdef1234"), "sk****1234")
        self.assertEqual(mask_secret("short"), "****")
        self.assertEqual(mask_secret(""), "")


if __name__ == "__main__":
    unittest.main()
