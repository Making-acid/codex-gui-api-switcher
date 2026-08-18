"""入口：桌面窗口（pywebview / Edge WebView2）与浏览器模式双启动。

用法：
  python app.py            # 桌面窗口
  python app.py --browser  # 用默认浏览器打开
"""
from __future__ import annotations

import argparse
import socket
import threading
import webbrowser
from pathlib import Path

from waitress import serve

from server import create_app


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Codex API Manager")
    parser.add_argument("--browser", action="store_true", help="用浏览器打开而非桌面窗口")
    parser.add_argument("--port", type=int, default=0, help="指定端口（默认随机）")
    parser.add_argument("--no-window", action="store_true", help="只启动服务（配合浏览器使用）")
    args = parser.parse_args()

    app = create_app()
    port = args.port or find_free_port()
    url = f"http://127.0.0.1:{port}"

    thread = threading.Thread(
        target=serve, args=(app,), kwargs={"host": "127.0.0.1", "port": port},
        daemon=True,
    )
    thread.start()
    print(f"Codex API Manager 已启动: {url}")

    if args.no_window or args.browser:
        webbrowser.open(url)
        try:
            thread.join()
        except KeyboardInterrupt:
            pass
        return

    # 桌面窗口模式
    import webview

    webview.create_window(
        "Codex API Manager",
        url,
        width=1100,
        height=760,
        min_size=(820, 600),
    )
    webview.start()


if __name__ == "__main__":
    main()
