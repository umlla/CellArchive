"""启动入口：python -m backend.serve"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser

logger = logging.getLogger(__name__)

from . import create_app
from .config import APP_VERSION, Config


EDGE_PATHS = (
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
)
CHROME_PATHS = (
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
)
BROWSER_PROCESS_NAMES = (
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "360se.exe",
    "360chrome.exe",
    "brave.exe",
)


def _find_executable(paths: tuple[str, ...]) -> str | None:
    for raw in paths:
        candidate = os.path.expandvars(raw)
        if "%" in candidate:
            continue
        if os.path.isfile(candidate):
            return candidate
    return None


def _default_browser_kind() -> str:
    """读取系统默认浏览器：edge / chrome / 其他。"""
    if os.name != "nt":
        return "default"
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
        ) as key:
            prog_id = str(winreg.QueryValueEx(key, "ProgId")[0]).lower()
    except (OSError, ImportError):
        return "default"
    if "edge" in prog_id:
        return "edge"
    if "chrome" in prog_id:
        return "chrome"
    return "default"


def _browser_process_ids() -> set[int] | None:
    """列出当前运行中的浏览器进程；无法获取时返回 None（避免误判为「没打开」）。"""
    if os.name != "nt":
        return None
    try:
        completed = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = completed.stdout.decode("utf-8", errors="ignore")
    if "chrome" not in output.lower() and "msedge" not in output.lower():
        output = completed.stdout.decode("mbcs", errors="ignore")
    pids: set[int] = set()
    for line in output.splitlines():
        parts = [part.strip('"') for part in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() in BROWSER_PROCESS_NAMES:
            try:
                pids.add(int(parts[1]))
            except ValueError:
                continue
    return pids


def _wait_for_new_browser_window(before: set[int], timeout: float = 5.0) -> bool:
    """等待出现新的浏览器进程（浏览器已在运行时，打开新窗口也会新建渲染进程）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = _browser_process_ids()
        if current is not None and current - before:
            return True
        time.sleep(0.4)
    return False


def _open_with_launch(command: list[str]) -> bool:
    """用指定浏览器打开网址，并确认它没有立刻退出。

    浏览器已有实例时，新进程会在约 1 秒内退出并把网址交给现有实例，
    所以额外观察是否有新的浏览器进程出现。
    """
    before = _browser_process_ids()
    try:
        process = subprocess.Popen(
            command,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        logger.exception("直接启动浏览器失败：%s", command[0])
        return False
    time.sleep(1.0)
    code = process.poll()
    if code is None:
        return True
    if before is not None and _wait_for_new_browser_window(before, timeout=3.0):
        return True
    logger.info("浏览器进程立即退出（退出码 %s），尝试其他打开方式", code)
    return False


def _open_with_shell(url: str) -> bool:
    """用系统默认关联打开（等同手动双击链接）。"""
    if os.name == "nt":
        try:
            os.startfile(url)
            return True
        except OSError:
            logger.exception("系统默认浏览器打开失败：%s", url)
            return False
    try:
        return bool(webbrowser.open(url))
    except Exception:  # noqa: BLE001 - 浏览器关联损坏时不要影响主程序
        logger.exception("webbrowser 打开失败：%s", url)
        return False


def _open_with_edge_profile(url: str, config: Config) -> bool:
    """用独立配置目录启动 Edge 窗口。

    系统里有以管理员权限运行的 Edge 时，普通权限去调系统默认的 Edge 会弹
    「Microsoft Edge 未响应，因为现有实例正在以提升的权限运行」，
    独立配置目录会作为新实例启动，不会触发这个提示。
    """
    edge = _find_executable(EDGE_PATHS)
    if not edge:
        return False
    profile = config.db_path.parent / "browser-profile" / "edge"
    try:
        profile.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.exception("创建 Edge 配置目录失败")
        return False
    return _open_with_launch(
        [
            edge,
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "--new-window",
            url,
        ]
    )


def open_url(url: str, config: Config) -> bool:
    """打开浏览器。

    默认浏览器是 Edge 时直接开独立配置的 Edge 窗口，避免管理员权限实例的提示；
    其他情况先交给系统关联处理，再依次尝试 Chrome、独立配置的 Edge。
    """
    if os.name != "nt":
        return _open_with_shell(url)

    if _default_browser_kind() == "edge":
        if _open_with_edge_profile(url, config):
            return True
        if _open_with_shell(url):
            return True
        chrome = _find_executable(CHROME_PATHS)
        return bool(chrome) and _open_with_launch(
            [chrome, "--new-window", "--no-first-run", "--no-default-browser-check", url]
        )

    if _open_with_shell(url):
        return True

    chrome = _find_executable(CHROME_PATHS)
    if chrome and _open_with_launch(
        [chrome, "--new-window", "--no-first-run", "--no-default-browser-check", url]
    ):
        return True

    return _open_with_edge_profile(url, config)


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
    """端口上是否已经跑着一个 CellTracker（用于重复双击时直接开浏览器）。"""
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/healthz", timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and bool(payload.get("ok"))
    except Exception:  # noqa: BLE001 - 任何错误都视为不是本应用
        return False


def open_browser_when_ready(url: str, port: int, config: Config, timeout: float = 15.0) -> None:
    """等服务真正能响应后再打开浏览器。

    双击 start.bat 时，服务启动后浏览器可能立即打开一个「无法访问此网站」的页面，
    或者浏览器还没就绪就退出，看起来就像「双击后没有自动出现页面」。
    这里先轮询 /api/healthz，确认可用后再打开，并记录结果。
    """
    import json
    import urllib.request

    deadline = time.time() + timeout
    health = f"http://127.0.0.1:{port}/api/healthz"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(health, timeout=0.8) as response:
                if response.status == 200 and json.loads(response.read().decode("utf-8")).get("ok"):
                    break
        except Exception:  # noqa: BLE001 - 服务尚未就绪
            pass
        time.sleep(0.3)

    opened = open_url(url, config)
    if opened:
        logger.info("已在浏览器中打开：%s", url)
        print(f" 已打开浏览器：{url}", flush=True)
    else:
        logger.warning("自动打开浏览器失败，请手动访问：%s", url)
        print(f" 未能自动打开浏览器，请手动访问：{url}", flush=True)


def main(argv: list[str] | None = None) -> int:
    configure_console()
    parser = argparse.ArgumentParser(description="启动 CellTracker v4")
    parser.add_argument("--host", default=None, help="监听地址（默认读取 config.json，127.0.0.1）")
    parser.add_argument("--port", type=int, default=None, help="监听端口（默认 18600）")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
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
            print(f"CellTracker 已经运行在 {local_url}")
            if config.open_browser and not args.no_browser:
                if open_url(local_url, config):
                    print(f" 已打开浏览器：{local_url}", flush=True)
                else:
                    print(f" 自动打开浏览器失败，请手动访问：{local_url}", flush=True)
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
    print(f" 本机访问：{local_url}")
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

    if config.open_browser and not args.no_browser:
        threading.Thread(
            target=open_browser_when_ready,
            args=(local_url, config.port, config),
            name="open-browser",
            daemon=True,
        ).start()

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
