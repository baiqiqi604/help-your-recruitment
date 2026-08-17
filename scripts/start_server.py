"""
项目 Web 服务启动器：可靠的后台启动 / 停止 / 状态查询（跨平台）。

背景：在自动化会话（agent）环境下，直接 `python main.py web` 或
nohup / PowerShell Start-Process 后台启动的 uvicorn 会随调用方进程树
被一并清理。本脚本在 Windows 上使用 CREATE_BREAKAWAY_FROM_JOB 让
uvicorn 脱离调用方 Job 对象（POSIX 用 start_new_session），保证启动
命令返回后服务依然存活；并内置「已在运行则跳过」的幂等逻辑。

用法：
    python scripts/start_server.py [start]            # 启动（默认命令，幂等）
    python scripts/start_server.py status             # 查询运行状态
    python scripts/start_server.py stop               # 停止服务
    python scripts/start_server.py restart            # 重启
    python scripts/start_server.py --version langchain --port 8001

说明：
- 默认启动主力版 langgraph_version；--version 可指定 langchain_version。
- PID 记录在 <版本目录>/.server.pid；日志追加到 <版本目录>/web_out.log、web_err.log。
- 已设置 HF 离线环境变量（避免加载 Embedding 模型时联网卡死），
  与 start_web_offline.py 保持一致。
"""

from __future__ import annotations

import argparse
import ctypes
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSIONS = {"langgraph": "langgraph_version", "langchain": "langchain_version"}

# 与 start_web_offline.py 一致的 HF 离线变量，必须在导入
# sentence_transformers / transformers 之前设置（uvicorn 子进程继承）
HF_OFFLINE_ENV = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "HF_HUB_DISABLE_PROGRESS_BARS": "1",
    "MOCK_LLM": "0",
}


def _find_python(version_dir: Path) -> str:
    """优先使用项目 .venv 的解释器，其次版本目录内的 .venv，最后回退当前解释器。"""
    candidates = []
    if sys.platform.startswith("win"):
        candidates.append(ROOT / ".venv" / "Scripts" / "python.exe")
        candidates.append(version_dir / ".venv" / "Scripts" / "python.exe")
    else:
        candidates.append(ROOT / ".venv" / "bin" / "python")
        candidates.append(version_dir / ".venv" / "bin" / "python")
    for cand in candidates:
        if cand.exists():
            return str(cand)
    return sys.executable


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """探测端口是否已被监听（用于幂等判断）。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _port_pid(host: str, port: int) -> int | None:
    """解析监听端口的真实进程 PID。

    背景：.venv 的 python.exe 可能是启动器进程，`python -m uvicorn ...`
    实际运行在它的子进程中（Popen 返回的 PID ≠ uvicorn PID）。若把 Popen
    PID 写入 .server.pid，stop/restart 会杀不到服务进程（PID 文件失效、
    端口被占无法停止）。因此按端口反查真实监听 PID。

    Windows 用 netstat -ano 解析；POSIX 用 lsof -i。解析失败返回 None。
    """
    try:
        if sys.platform.startswith("win"):
            out = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=10,
            ).stdout
            marker = f":{port}"
            for line in out.splitlines():
                if "LISTENING" not in line:
                    continue
                # 行格式：协议  本地地址  外部地址  状态  PID
                parts = line.split()
                if len(parts) >= 5 and marker in parts[1]:
                    return int(parts[-1])
            return None
        # POSIX：优先 lsof，缺失时回退 fuser
        for cmd in (["lsof", "-i", f"tcp:{port}", "-sTCP:LISTEN", "-t"],
                    ["fuser", f"{port}/tcp"]):
            try:
                out = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=10,
                ).stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                continue
            if out:
                return int(out.splitlines()[0])
        return None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _health_ok(host: str, port: int, timeout: float = 2.0) -> bool:
    """请求 /api/health，返回是否 200。"""
    try:
        with urllib.request.urlopen(
            f"http://{host}:{port}/api/health", timeout=timeout
        ) as resp:
            return resp.status == 200
    except OSError:
        return False


def _pid_file(version_dir: Path) -> Path:
    return version_dir / ".server.pid"


def _read_pid(version_dir: Path) -> int | None:
    pid_file = _pid_file(version_dir)
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def _win_process_alive(pid: int) -> bool:
    """Windows 下用 OpenProcess 判断进程存活（避免解析 GBK 编码的 tasklist 输出）。"""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    if pid <= 0:
        return False
    handle = ctypes.windll.kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
    )
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return exit_code.value == STILL_ACTIVE
        return False
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _process_alive(pid: int) -> bool:
    """跨平台判断进程是否存活。"""
    if sys.platform.startswith("win"):
        return _win_process_alive(pid)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def cmd_status(args: argparse.Namespace) -> int:
    version_dir = ROOT / VERSIONS[args.version]
    pid = _read_pid(version_dir)
    listening = _port_open(args.host, args.port)

    if listening:
        if pid and _process_alive(pid):
            detail = f"PID {pid}（记录于 {_pid_file(version_dir).name}）"
        else:
            detail = "端口已监听（PID 文件缺失或失效）"
        print(f"[status] {args.version} 服务运行中：http://{args.host}:{args.port}（{detail}）")
        return 0

    if pid and _process_alive(pid):
        print(f"[status] PID {pid} 存活但端口未监听（服务可能启动中或异常）")
        return 1
    print(f"[status] {args.version} 服务未运行（http://{args.host}:{args.port} 无监听）")
    return 1


def cmd_start(args: argparse.Namespace) -> int:
    version_dir = ROOT / VERSIONS[args.version]
    if not version_dir.exists():
        print(f"[error] 版本目录不存在: {version_dir}", file=sys.stderr)
        return 1

    # 幂等：端口已在监听则直接报告，不重复启动
    if _port_open(args.host, args.port):
        print(f"[start] 服务已在运行：http://{args.host}:{args.port}（无需重复启动）")
        return 0

    python = _find_python(version_dir)
    if not Path(python).exists():
        print(f"[error] 未找到 Python 解释器: {python}", file=sys.stderr)
        return 1

    env = os.environ.copy()
    env.update(HF_OFFLINE_ENV)

    out_log = open(version_dir / "web_out.log", "ab")
    err_log = open(version_dir / "web_err.log", "ab")

    cmd = [
        python, "-m", "uvicorn", "web_app:app",
        "--host", str(args.host), "--port", str(args.port),
    ]
    print(f"[start] 启动 {args.version}（{python}）→ http://{args.host}:{args.port}")
    try:
        if sys.platform.startswith("win"):
            # 脱离调用方 Job 对象：避免随启动命令的进程树被清理
            flags = (
                subprocess.CREATE_BREAKAWAY_FROM_JOB
                | subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
            )
            proc = subprocess.Popen(
                cmd, cwd=str(version_dir), env=env,
                stdout=out_log, stderr=err_log, stdin=subprocess.DEVNULL,
                creationflags=flags,
            )
        else:
            proc = subprocess.Popen(
                cmd, cwd=str(version_dir), env=env,
                stdout=out_log, stderr=err_log, stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
    except OSError as e:
        print(f"[error] 启动失败: {e}", file=sys.stderr)
        return 1

    _pid_file(version_dir).write_text(str(proc.pid), encoding="utf-8")
    print(f"[start] 已启动，PID {proc.pid}（记录于 {_pid_file(version_dir).name}）")

    # 等待健康检查通过（warmup 在后台线程，通常几秒内即可响应）
    deadline = time.time() + args.wait
    while time.time() < deadline:
        if _health_ok(args.host, args.port):
            # 记录真实监听进程 PID：启动器进程与实际 uvicorn 可能不同，
            # 用 Popen PID 会导致 stop/restart 杀不到服务进程
            real_pid = _port_pid(args.host, args.port) or proc.pid
            _pid_file(version_dir).write_text(str(real_pid), encoding="utf-8")
            print(f"[start] 健康检查通过：http://{args.host}:{args.port} ✅（服务 PID {real_pid}）")
            return 0
        time.sleep(1)
    print(
        f"[warn] 健康检查 {args.wait}s 内未通过，请查看 {version_dir / 'web_err.log'}",
        file=sys.stderr,
    )
    return 1


def cmd_stop(args: argparse.Namespace) -> int:
    version_dir = ROOT / VERSIONS[args.version]
    pid = _read_pid(version_dir)
    listening = _port_open(args.host, args.port)

    if not listening and (pid is None or not _process_alive(pid)):
        print(f"[stop] 服务未运行（http://{args.host}:{args.port} 无监听）")
        _pid_file(version_dir).unlink(missing_ok=True)
        return 0

    stopped = False
    if pid and _process_alive(pid):
        try:
            if sys.platform.startswith("win"):
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True, check=False,
                )
            else:
                os.kill(pid, 15)  # SIGTERM
                time.sleep(1)
                if _process_alive(pid):
                    os.kill(pid, 9)
            stopped = True
        except OSError as e:
            print(f"[warn] 停止 PID {pid} 失败: {e}", file=sys.stderr)

    if not stopped and listening:
        print(
            f"[warn] 端口 {args.port} 被其他进程占用，未自动停止；"
            f"请手动处理: netstat -ano | findstr :{args.port}",
            file=sys.stderr,
        )
        return 1

    _pid_file(version_dir).unlink(missing_ok=True)
    print(f"[stop] 服务已停止（http://{args.host}:{args.port}）")
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    print("[restart] 停止旧服务...")
    cmd_stop(args)
    time.sleep(1)
    return cmd_start(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="start_server",
        description="AI 简历优化 Agent Web 服务启动器（后台守护、幂等、跨平台）",
    )
    parser.add_argument("--version", choices=sorted(VERSIONS), default="langgraph",
                        help="启动哪个版本（默认 langgraph 主力版）")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8000, help="监听端口（默认 8000）")
    parser.add_argument("--wait", type=int, default=60,
                        help="启动后等待健康检查通过的秒数（默认 60）")
    sub = parser.add_subparsers(dest="command", metavar="命令")
    sub.add_parser("start", help="启动服务（默认，幂等）")
    sub.add_parser("status", help="查询服务运行状态")
    sub.add_parser("stop", help="停止服务")
    sub.add_parser("restart", help="重启服务")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    handlers = {
        "start": cmd_start,
        "status": cmd_status,
        "stop": cmd_stop,
        "restart": cmd_restart,
    }
    handler = handlers.get(args.command or "start")
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
