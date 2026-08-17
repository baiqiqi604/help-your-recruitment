"""桌面版启动器：启动 Web 服务并打开浏览器（PyInstaller 打包入口）。

职责：
1. 首启时将模板 / 静态资源 / 题库数据 / 嵌入模型 / .env 从打包内置目录
   复制到 exe 同目录（后续启动直接复用，不重复复制）；
2. 设置离线环境变量（BGE 模型本地加载，避免联网检查卡死）；
3. 以 127.0.0.1 启动 uvicorn（端口占用自动顺延）；
4. 自动打开默认浏览器，并显示一个"关闭即退出服务"的小窗口。
"""
from __future__ import annotations

import os
import shutil
import sys
import threading
from pathlib import Path

# 自动化测试用：NO_BROWSER=1 时不自动打开浏览器
NO_BROWSER = os.getenv("NO_BROWSER", "").strip().lower() in {"1", "true", "yes"}

# 需要从打包目录复制到 exe 目录的运行时数据
BUNDLE_DIRS = ("templates", "static", "data/chroma_db", "input")
BUNDLE_FILES = (".env",)


def app_root() -> Path:
    """exe 所在目录（可写，作为运行时数据根目录）。"""
    return Path(sys.executable).resolve().parent


def bundle_root() -> Path:
    """打包内置资源目录（PyInstaller _MEIPASS；开发模式为项目根）。"""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
    return Path(__file__).resolve().parent.parent


def ensure_copied(src: Path, dst: Path) -> None:
    """缺失时才复制（目录递归复制，文件直接复制）。"""
    if dst.exists() or not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def bootstrap(root: Path, bundle: Path) -> None:
    """首启数据补齐 + 离线环境变量。"""
    for rel in BUNDLE_DIRS:
        ensure_copied(bundle / rel, root / rel)
    for name in BUNDLE_FILES:
        ensure_copied(bundle / name, root / name)

    # BGE 嵌入模型离线缓存（HF hub 目录结构）
    hf_home = root / "hf_model"
    ensure_copied(bundle / "hf_model", hf_home)
    os.environ["HF_HOME"] = str(hf_home)
    os.environ["SENTENCE_TRANSFORMERS_HOME"] = str(hf_home)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    os.environ["MOCK_LLM"] = "0"


def find_free_port(start: int = 8000, end: int = 8010) -> int:
    import socket

    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def _show_exit_window(server, url: str) -> None:
    """主线程显示退出窗口；关闭窗口即停止服务。"""
    import tkinter as tk

    win = tk.Tk()
    win.title("AI 简历优化 Agent")
    win.resizable(False, False)
    win.configure(padx=28, pady=18)

    tk.Label(win, text="✅ 服务运行中", font=("Microsoft YaHei UI", 14, "bold"),
             fg="#0f766e").pack(pady=(0, 6))
    tk.Label(win, text=f"访问地址：{url}", font=("Microsoft YaHei UI", 10),
             fg="#334155").pack()
    tk.Label(win, text="（已自动打开浏览器，如未打开请手动访问上面的地址）",
             font=("Microsoft YaHei UI", 9), fg="#64748b").pack(pady=(2, 10))
    tk.Button(win, text="关闭并退出服务", font=("Microsoft YaHei UI", 10),
              bg="#0f766e", fg="#ffffff", activebackground="#115e59",
              activeforeground="#ffffff", relief="flat", padx=16, pady=6,
              command=win.destroy).pack(pady=(0, 4))
    win.protocol("WM_DELETE_WINDOW", win.destroy)
    win.mainloop()


def main() -> None:
    # PyInstaller windowed 模式下 stdout/stderr 为 None，日志写入会崩溃，先兜底
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    root = app_root()
    bundle = bundle_root()
    bootstrap(root, bundle)
    os.chdir(root)

    # 必须在 bootstrap 之后导入（config 依赖 exe 目录与 .env / 环境变量）
    import uvicorn
    import web_app

    port = find_free_port()
    server = uvicorn.Server(uvicorn.Config(
        web_app.app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()

    url = f"http://127.0.0.1:{port}"

    # 等服务就绪后打开浏览器
    def _open_browser() -> None:
        import time
        import urllib.request

        for _ in range(60):
            try:
                urllib.request.urlopen(url + "/api/health", timeout=2)
                break
            except OSError:  # 服务未就绪（连接失败/超时），重试等待
                time.sleep(0.5)
        if not NO_BROWSER:
            import webbrowser
            webbrowser.open(url)

    threading.Thread(target=_open_browser, daemon=True).start()

    _show_exit_window(server, url)
    server.should_exit = True


if __name__ == "__main__":
    main()
