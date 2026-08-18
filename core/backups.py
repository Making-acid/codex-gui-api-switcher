"""config.toml 备份 / 恢复 / 恢复默认（覆盖清单式）。"""
from __future__ import annotations

import json
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

from core.config_manager import ConfigManager

BACKUP_DIR = "backups"
MANIFEST = "backups.json"


class BackupError(Exception):
    pass


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


class BackupManager:
    def __init__(self, config_manager: ConfigManager):
        self.mgr = config_manager
        self._lock = threading.RLock()
        self.backup_dir = config_manager.data_dir / BACKUP_DIR

    # ------------------------------------------------------------------
    # 列表
    # ------------------------------------------------------------------

    def list_backups(self) -> list[dict]:
        manifest = self._manifest_path()
        if manifest.is_file():
            try:
                entries = json.loads(manifest.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                entries = []
        else:
            entries = []
        # 过滤掉文件已不存在的条目，按时间倒序
        alive = [e for e in entries if (self.backup_dir / e["file"]).is_file()]
        alive.sort(key=lambda e: e.get("created_at", ""), reverse=True)
        return alive

    # ------------------------------------------------------------------
    # 创建备份
    # ------------------------------------------------------------------

    def create_backup(self, note: str | None = None, source: str = "manual") -> dict:
        with self._lock:
            if not self.mgr.exists():
                raise BackupError(f"配置文件不存在，无法备份: {self.mgr.config_path}")
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            ts = now_ts()
            fname = f"config-{ts}-{source}.toml"
            dst = self.backup_dir / fname
            shutil.copy2(self.mgr.config_path, dst)
            entry = {
                "id": ts,
                "file": fname,
                "created_at": utcnow_iso(),
                "source": source,
                "note": note or "",
            }
            entries = self._read_manifest()
            entries.append(entry)
            self._write_manifest(entries)
            return entry

    # ------------------------------------------------------------------
    # 恢复
    # ------------------------------------------------------------------

    def restore_backup(self, backup_id: str) -> dict:
        """恢复到指定备份点；恢复前自动备份当前状态，并清空覆盖追踪。"""
        with self._lock:
            entries = self.list_backups()
            target = next((e for e in entries if e["id"] == backup_id), None)
            if target is None:
                raise BackupError(f"未找到备份: {backup_id}")
            src = self.backup_dir / target["file"]
            # 恢复前自动备份当前
            try:
                self.create_backup(note=f"恢复前（目标备份 {backup_id}）", source="pre_restore")
            except BackupError:
                pass
            shutil.copy2(src, self.mgr.config_path)
            # 文件状态已回退，旧的覆盖记录不再适用
            self._clear_overrides()
            return {"ok": True, "restored": target["file"]}

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _manifest_path(self) -> Path:
        return self.mgr.data_dir / MANIFEST

    def _read_manifest(self) -> list[dict]:
        p = self._manifest_path()
        if not p.is_file():
            return []
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def _write_manifest(self, entries: list[dict]) -> None:
        self.mgr.data_dir.mkdir(parents=True, exist_ok=True)
        self._manifest_path().write_text(
            json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _clear_overrides(self) -> None:
        self.mgr.data_dir.mkdir(parents=True, exist_ok=True)
        self.mgr.overrides_file().write_text("[]", encoding="utf-8")
