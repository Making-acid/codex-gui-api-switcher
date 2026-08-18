"""入口：桌面窗口（pywebview / Edge WebView2）与浏览器模式双启动。

用法：
  python app.py            # 桌面窗口
  python app.py --browser  # 用默认浏览器打开
  python app.py --no-window --port 18080   # 只启动服务
"""
from __future__ import annotations

import argparse
import socket
import threading
import time
import webbrowser

from waitress import serve

from server import create_app


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_ready(url: str, timeout: float = 15.0) -> bool:
    """等待本地服务就绪（避免 webview 打开白屏）。"""
    port = int(url.rsplit(":", 1)[1].rstrip("/"))
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.1)
    return False


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
    wait_ready(url)
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
        width=1120,
        height=780,
        min_size=(860, 620),
        background_color="#0f1115",
    )
    webview.start()


if __name__ == "__main__":
    main()
