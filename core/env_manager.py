"""环境变量管理：user（Windows 用户级）与 file（.env）双 scope。

- user：HKCU\\Environment 注册表持久化，Codex Desktop 主通道（写后广播并提示重启）
- file：.env 文件，供自定义启动脚本使用；Codex 不读取
"""
from __future__ import annotations

import ctypes
import os
import threading
from pathlib import Path

import winreg

DEFAULT_ENV_FILE = Path(os.environ.get("CODEX_HOME", "~")).expanduser() / ".codex" / ".env"

SCOPE_USER = "user"
SCOPE_FILE = "file"

_HWND_BROADCAST = 0xFFFF
_WM_SETTINGCHANGE = 0x001A
_SMTO_ABORTIFHUNG = 0x0002
_MAX_VALUE_LEN = 2048


class EnvError(Exception):
    pass


def mask_secret(value: str, keep_tail: int = 4) -> str:
    """脱敏：sk-****abcd。空值/短值直接遮蔽。"""
    value = value or ""
    if not value:
        return ""
    if len(value) <= keep_tail + 4:
        return "****"
    return value[:2] + "****" + value[-keep_tail:]


class EnvManager:
    def __init__(self, env_file: str | Path | None = None):
        self.env_file = Path(env_file) if env_file else DEFAULT_ENV_FILE
        self._lock = threading.RLock()
        self._reg_key = None

    # ------------------------------------------------------------------
    # user scope
    # ------------------------------------------------------------------

    def read_user_env(self) -> dict[str, str]:
        with self._lock:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                values = {}
                i = 0
                while True:
                    try:
                        name, value, kind = winreg.EnumValue(key, i)
                    except OSError:
                        break
                    if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                        values[str(name)] = str(value)
                    i += 1
                return values

    def write_user_env(self, entries: list[dict]) -> dict:
        """entries: [{name, value|None}]；value=None 表示删除。"""
        with self._lock:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                                winreg.KEY_SET_VALUE) as key:
                for entry in entries:
                    name = str(entry["name"]).strip()
                    if not name:
                        continue
                    value = entry.get("value")
                    if value is None or str(value) == "":
                        try:
                            winreg.DeleteValue(key, name)
                        except FileNotFoundError:
                            pass
                    else:
                        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))
            self._broadcast()
            return {"ok": True, "restart_required": True}

    # ------------------------------------------------------------------
    # file scope
    # ------------------------------------------------------------------

    def read_env_file(self) -> list[dict]:
        """返回 [{name, value, masked}]（保留文件顺序）。"""
        if not self.env_file.is_file():
            return []
        out = []
        for line in self.env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            name, _, value = line.partition("=")
            name = name.strip()
            if not name:
                continue
            out.append({
                "name": name,
                "value": value.strip().strip('"').strip("'"),
                "masked": mask_secret(value.strip().strip('"').strip("'")),
            })
        return out

    def write_env_file(self, entries: list[dict]) -> dict:
        """entries: [{name, value|None}]；value=None 删除该行。"""
        with self._lock:
            current = {e["name"]: e["value"] for e in self.read_env_file()}
            for entry in entries:
                name = str(entry["name"]).strip()
                value = entry.get("value")
                if value is None:
                    current.pop(name, None)
                else:
                    current[name] = str(value)
            lines = []
            for name, value in current.items():
                lines.append(f"{name}={value}")
            self.env_file.parent.mkdir(parents=True, exist_ok=True)
            self.env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return {"ok": True, "path": str(self.env_file)}

    # ------------------------------------------------------------------
    # 互导
    # ------------------------------------------------------------------

    def import_file_to_user(self) -> dict:
        entries = [{"name": e["name"], "value": e["value"]} for e in self.read_env_file()]
        return self.write_user_env(entries)

    def export_user_to_file(self) -> dict:
        entries = [{"name": n, "value": v} for n, v in self.read_user_env().items()]
        return self.write_env_file(entries)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _broadcast(self) -> None:
        """通知系统环境变量已变更（新进程生效；已运行进程需重启）。"""
        try:
            ctypes.windll.user32.SendMessageTimeoutW(
                _HWND_BROADCAST, _WM_SETTINGCHANGE, 0, "Environment",
                _SMTO_ABORTIFHUNG, 5000, None)
        except Exception:
            pass
