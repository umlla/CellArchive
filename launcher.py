"""CellTracker 桌面启动器。

源码运行：python launcher.py
打包运行：PyInstaller 生成的 CellTracker.exe
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

APP_TITLE = "CellTracker · 细胞培养追踪"
logger = logging.getLogger("celltracker.launcher")


def _open_url(url: str) -> bool:
    from backend.serve import open_url

    try:
        if open_url(url, _CONFIG):
            return True
    except Exception:  # noqa: BLE001 - 浏览器打不开时至少还能手动复制地址
        logger.exception("调用系统浏览器失败")

    try:
        if os.name == "nt":
            os.startfile(url)
            return True
    except Exception:  # noqa: BLE001
        logger.exception("os.startfile 打开失败")

    try:
        return bool(webbrowser.open(url))
    except Exception:  # noqa: BLE001
        logger.exception("webbrowser 打开失败")
        return False


def _wait_for_server(port: int, timeout: float = 12.0) -> bool:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/api/healthz"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.6) as response:
                if response.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    return False


def _center_window(root, width: int, height: int) -> None:
    root.update_idletasks()
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = max(0, (screen_width - width) // 2)
    y = max(0, (screen_height - height) // 3)
    root.geometry(f"{width}x{height}+{x}+{y}")


def _show_error(message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_TITLE, message)
        root.destroy()
    except Exception:  # noqa: BLE001
        print(message, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    global _CONFIG

    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--port", type=int, default=None, help="监听端口（默认 18600）")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    args = parser.parse_args(argv)

    from backend.config import Config
    from backend.serve import existing_celltracker, port_available

    config = Config.load()
    if args.port:
        config.port = args.port
    _CONFIG = config

    config.ensure_dirs()
    log_path = config.db_path.parent / "celltracker.log"
    if getattr(sys, "frozen", False):
        # 无控制台窗口时，把 Flask/waitress 的输出写入日志，便于排查
        log_file = open(log_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = log_file
        sys.stderr = log_file
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )
    logger.info("CellTracker 启动，数据目录：%s", config.db_path.parent)

    url = f"http://127.0.0.1:{config.port}/"

    if not port_available(config.host, config.port):
        if existing_celltracker(config.port):
            if not args.no_browser:
                _open_url(url)
            return 0
        _show_error(
            f"端口 {config.port} 已被其他程序占用。\n\n"
            f"请关闭占用该端口的程序，或修改 config.json 里的 port 后重试。"
        )
        return 1

    try:
        from waitress import create_server

        from backend import create_app

        app = create_app(config)
        server = create_server(
            app,
            host=config.host,
            port=config.port,
            threads=8,
            channel_timeout=120,
        )
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        _show_error(f"启动失败：{exc}\n\n详细日志：{log_path}")
        return 1

    thread = threading.Thread(target=server.run, name="celltracker-server", daemon=True)
    thread.start()

    if not _wait_for_server(config.port):
        _show_error(f"服务启动超时。\n\n请查看日志：{log_path}")
        return 1

    if not args.no_browser:
        threading.Timer(0.6, lambda: _open_url(url)).start()

    try:
        import tkinter as tk
        from tkinter import messagebox, ttk

        root = tk.Tk()
        root.title(APP_TITLE)
        root.configure(bg="#f4f8f7")
        root.resizable(False, False)
        try:
            icon = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets" / "app.ico"
            if icon.is_file():
                root.iconbitmap(str(icon))
        except Exception:  # noqa: BLE001
            pass

        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("Title.TLabel", background="#ffffff", foreground="#123b34", font=("Microsoft YaHei UI", 16, "bold"))
        style.configure("Sub.TLabel", background="#ffffff", foreground="#60736e", font=("Microsoft YaHei UI", 9))
        style.configure("Status.TLabel", background="#ffffff", foreground="#12805c", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Url.TLabel", background="#ffffff", foreground="#0f766e", font=("Consolas", 11))
        style.configure("Hint.TLabel", background="#ffffff", foreground="#8a9995", font=("Microsoft YaHei UI", 9))
        style.configure("Primary.TButton", font=("Microsoft YaHei UI", 10), padding=(16, 8))
        style.configure("TButton", font=("Microsoft YaHei UI", 9), padding=(12, 7))

        card = ttk.Frame(root, style="Card.TFrame", padding=(28, 24, 28, 20))
        card.pack(fill="both", expand=True, padx=18, pady=18)

        ttk.Label(card, text="CellTracker", style="Title.TLabel").pack(anchor="w")
        ttk.Label(card, text="细胞培养追踪 · 本地服务已启动", style="Sub.TLabel").pack(anchor="w", pady=(4, 16))
        status_label = ttk.Label(card, text="● 运行中", style="Status.TLabel")
        status_label.pack(anchor="w")

        def open_and_report() -> None:
            if _open_url(url):
                status_label.config(text="● 运行中 · 已发送打开请求")
                return
            status_label.config(text="● 运行中 · 请手动打开下面的地址")
            messagebox.showwarning(
                APP_TITLE,
                f"浏览器没有自动打开。\n\n请手动访问：\n{url}\n\n"
                f"也可以点“复制地址”后粘贴到浏览器。",
            )

        def copy_url() -> None:
            try:
                root.clipboard_clear()
                root.clipboard_append(url)
                status_label.config(text="● 运行中 · 地址已复制")
            except tk.TclError:
                logger.exception("复制地址失败")

        url_label = ttk.Label(card, text=url, style="Url.TLabel", cursor="hand2")
        url_label.pack(anchor="w", pady=(6, 2))
        url_label.bind("<Button-1>", lambda _event: open_and_report())

        ttk.Label(
            card,
            text=f"数据保存在：{config.db_path.parent}",
            style="Hint.TLabel",
            wraplength=520,
            justify="left",
        ).pack(anchor="w", pady=(6, 16))

        buttons = ttk.Frame(card, style="Card.TFrame")
        buttons.pack(anchor="w")

        def close_app() -> None:
            try:
                server.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                root.destroy()
            finally:
                os._exit(0)

        ttk.Button(buttons, text="打开界面", style="Primary.TButton", command=open_and_report).pack(side="left")
        ttk.Button(buttons, text="复制地址", command=copy_url).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="数据文件夹", command=lambda: os.startfile(config.db_path.parent)).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="退出", command=close_app).pack(side="left", padx=(8, 0))

        ttk.Label(
            card,
            text="关闭此窗口会停止服务。如果“打开界面”没反应，点“复制地址”手动打开。",
            style="Hint.TLabel",
            wraplength=520,
            justify="left",
        ).pack(anchor="w", pady=(18, 0))

        _center_window(root, 620, 380)
        root.protocol("WM_DELETE_WINDOW", close_app)
        root.lift()
        root.focus_force()
        root.attributes("-topmost", True)
        root.after(1500, lambda: root.attributes("-topmost", False))
        root.mainloop()
        return 0
    except Exception:  # noqa: BLE001 - 没有图形环境时退化为控制台常驻
        traceback.print_exc()
        print(f"CellTracker 已启动：{url}")
        print("按 Ctrl+C 停止服务。")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0


_CONFIG = None


if __name__ == "__main__":
    raise SystemExit(main())
