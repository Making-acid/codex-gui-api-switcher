"""入口：桌面窗口（pywebview / Edge WebView2）与浏览器模式双启动。

用法：
  python app.py            # 桌面窗口
  python app.py --browser  # 用默认浏览器打开
  python app.py --no-window --port 18080   # 只启动服务（调试 API）
"""
from __future__ import annotations

import argparse
import secrets
import socket
import threading
import time
import webbrowser
from urllib.parse import urlparse

from waitress import serve

from server import create_app


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_ready(url: str, timeout: float = 15.0) -> bool:
    """等待本地服务就绪（避免 webview 打开白屏）。"""
    parsed = urlparse(url)
    host, port = parsed.hostname, parsed.port
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Codex API Manager")
    parser.add_argument("--browser", action="store_true", help="用浏览器打开而非桌面窗口")
    parser.add_argument("--port", type=int, default=0, help="指定端口（默认随机）")
    parser.add_argument("--no-window", action="store_true", help="只启动服务（配合浏览器使用）")
    parser.add_argument("--no-auth", action="store_true", help="关闭 API 鉴权（仅调试用）")
    args = parser.parse_args()

    token = None if args.no_auth else secrets.token_urlsafe(32)
    app = create_app(auth_token=token)
    # 先绑定 socket 再交给 waitress，避免端口竞态
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", args.port))
    port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    if token:
        url = f"{url}?token={token}"

    thread = threading.Thread(
        target=serve, args=(app,), kwargs={"sockets": [sock]},
        daemon=True,
    )
    thread.start()
    wait_ready(url)
    print(f"Codex API Manager 已启动: {url}")
    if token:
        print(f"API 鉴权 token: {token}")

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

if __name__ == "__main__":
    main()
