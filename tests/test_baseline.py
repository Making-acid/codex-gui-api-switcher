"""baseline（初始状态快照）单测：ensure / get / restore / refresh + server API。"""
from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

import requests
from waitress import serve

from core.backups import BackupManager
from core.config_manager import ConfigManager
from server import create_app

ORIG = 'model = "orig-model"\n[plugins."x"]\nenabled = true\n'


class BaselineCoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = self.root / "config.toml"
        self.cfg.write_text(ORIG, encoding="utf-8")
        self.mgr = ConfigManager(config_path=self.cfg, data_dir=self.root / "data")
        self.bm = BackupManager(self.mgr)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ensure_creates_once(self):
        self.bm.ensure_baseline()
        self.assertTrue(self.bm.baseline_path().is_file())
        first = self.bm.baseline_path().read_text(encoding="utf-8")
        # 修改 config 后再次 ensure 不覆盖
        self.cfg.write_text("model = \"changed\"\n", encoding="utf-8")
        self.bm.ensure_baseline()
        self.assertEqual(self.bm.baseline_path().read_text(encoding="utf-8"), first)

    def test_get_baseline_info(self):
        self.bm.ensure_baseline()
        info = self.bm.get_baseline()
        self.assertTrue(info["exists"])
        self.assertIn("created_at", info)
        self.assertGreater(info["size"], 0)

    def test_restore_baseline(self):
        self.bm.ensure_baseline()
        self.cfg.write_text('model = "gpt-5.6"\nmodel_provider = "p"\n', encoding="utf-8")
        # 模拟有覆盖记录（写入与当前不同的值才会记录）
        self.bm.mgr.write({"model": "other-model"})
        self.assertTrue(self.bm.mgr.get_overrides())
        result = self.bm.restore_baseline()
        self.assertTrue(result["ok"])
        self.assertEqual(self.cfg.read_text(encoding="utf-8"), ORIG)
        self.assertEqual(self.bm.mgr.get_overrides(), [])
        # 恢复前自动备份存在
        self.assertTrue(self.bm.list_backups())

    def test_restore_without_baseline_raises(self):
        with self.assertRaises(Exception):
            self.bm.restore_baseline()

    def test_refresh_baseline(self):
        self.bm.ensure_baseline()
        self.cfg.write_text('model = "new"\n', encoding="utf-8")
        self.bm.refresh_baseline()
        self.assertEqual(self.bm.baseline_path().read_text(encoding="utf-8"),
                         'model = "new"\n')


def start_server(config_manager):
    import socket as socket_mod
    app = create_app(config_manager=config_manager)
    sock = socket_mod.socket(socket_mod.AF_INET, socket_mod.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    thread = threading.Thread(target=serve, args=(app,), kwargs={"sockets": [sock]},
                              daemon=True)
    thread.start()
    time.sleep(0.8)
    return f"http://127.0.0.1:{port}"


class BaselineApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = self.root / "config.toml"
        self.cfg.write_text(ORIG, encoding="utf-8")
        self.mgr = ConfigManager(config_path=self.cfg, data_dir=self.root / "data")
        self.base = start_server(self.mgr)

    def tearDown(self):
        self.tmp.cleanup()

    def test_baseline_api_roundtrip(self):
        r = requests.get(self.base + "/api/baseline", timeout=5)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["baseline"]["exists"])

        # 修改配置后恢复 baseline
        self.cfg.write_text('model = "gpt-5.6"\n', encoding="utf-8")
        r = requests.post(self.base + "/api/baseline/restore", json={}, timeout=5)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.cfg.read_text(encoding="utf-8"), ORIG)

        # refresh 把当前设为 baseline
        self.cfg.write_text('model = "new"\n', encoding="utf-8")
        r = requests.post(self.base + "/api/baseline/refresh", json={}, timeout=5)
        self.assertEqual(r.status_code, 200)
        r = requests.get(self.base + "/api/baseline", timeout=5)
        self.assertTrue(r.json()["baseline"]["exists"])


if __name__ == "__main__":
    unittest.main()