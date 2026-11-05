"""启动入口：python -m backend.serve"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys

from . import create_app
from .config import APP_VERSION, Config


def lan_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            address = info[4][0]
            if not address.startswith("127.") and not address.startswith("169.254."):
                addresses.add(address)
    except OSError:
        pass
    return sorted(addresses)


def configure_console() -> None:
    """避免 Windows 控制台无法编码 emoji/中文时直接崩溃。"""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def port_available(host: str, port: int) -> bool:
    """检查端口是否可用。

    不用 bind + SO_REUSEADDR：Windows 上该选项会允许重复绑定同一个端口，
    导致检测失效（甚至起两个服务）。改用 connect 探测是否已有监听。
    """
    if host in ("0.0.0.0", ""):
        probe = "127.0.0.1"
    elif host == "::":
        probe = "::1"
    else:
        probe = host
    family = socket.AF_INET6 if ":" in probe else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.8)
        return sock.connect_ex((probe, port)) != 0


def existing_celltracker(port: int) -> bool:
    """端口上是否已经跑着一个 CellTracker（重复双击时直接提示地址）。"""
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/healthz", timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and bool(payload.get("ok"))
    except Exception:  # noqa: BLE001 - 任何错误都视为不是本应用
        return False


def main(argv: list[str] | None = None) -> int:
    configure_console()
    parser = argparse.ArgumentParser(description="启动 CellTracker v4")
    parser.add_argument("--host", default=None, help="监听地址（默认读取 config.json，127.0.0.1）")
    parser.add_argument("--port", type=int, default=None, help="监听端口（默认 18600）")
    parser.add_argument("--no-browser", action="store_true", help="兼容旧参数（现在不会自动打开浏览器）")
    parser.add_argument("--debug", action="store_true", help="Flask 调试模式")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = Config.load()
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    if args.debug:
        config.debug = True

    local_url = f"http://127.0.0.1:{config.port}/"

    # 端口被占用时给出明确提示，而不是抛出一大段 traceback
    if not port_available(config.host, config.port):
        if existing_celltracker(config.port):
            # 重复双击时不要自己退出：退出会连带关闭正在运行的那个控制台窗口，
            # 看起来就像「服务已停止」。这里停住，等用户按键再结束。
            print("=" * 62)
            print(f" CellTracker 已经在运行：{local_url}")
            print(" 请直接用浏览器打开上面的地址。")
            print(" 如果浏览器里打不开，请关闭所有 CellTracker 控制台窗口后重新双击 start.bat。")
            print("=" * 62, flush=True)
            try:
                input(" 按回车键关闭本窗口（不影响正在运行的服务）...")
            except EOFError:
                pass
            return 0
        print("=" * 62)
        print(f" 端口 {config.port} 已被其他程序占用，CellTracker 无法启动。")
        print(' 请编辑 config.json，把 "port" 改成其他数字（例如 18601），再双击启动。')
        print(" 也可以先关闭占用该端口的程序（例如 maibot 等后台服务）。")
        print("=" * 62, flush=True)
        return 1

    app = create_app(config)

    print("=" * 62)
    print(f" 🧬 CellTracker v{APP_VERSION}")
    print(f" 数据库：{config.db_path}")
    print(f" 本机访问：{local_url}  ← 复制到浏览器打开")
    if config.host in ("0.0.0.0", "::"):
        for address in lan_addresses():
            print(f" 局域网访问：http://{address}:{config.port}/")
    else:
        print(f" 监听地址：{config.host}（如需局域网访问，把 config.json 的 host 改为 0.0.0.0）")
    if config.auth_enabled:
        print(" 登录认证：已启用")
    else:
        print(" 登录认证：未启用（单用户本地模式）")
    print(" 按 Ctrl+C 停止服务")
    print("=" * 62, flush=True)

    try:
        from waitress import serve
    except ImportError:
        app.run(host=config.host, port=config.port, threaded=True, debug=config.debug, use_reloader=False)
    else:
        try:
            serve(app, host=config.host, port=config.port, threads=8, channel_timeout=120)
        except OSError as exc:
            print(f"\n启动失败：{exc}")
            print(f"端口 {config.port} 可能已被其他程序占用，请修改 config.json 的 port 后重试。")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
