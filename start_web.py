"""独立启动 uvicorn Web 服务（脱离 bash 会话，避免被连带终止）。

用法: python start_web.py <版本目录> <端口> [host]

示例:
    python start_web.py D:/项目/aiagent/langgraph_version 8000
    python start_web.py D:/项目/aiagent/langchain_version 8001 127.0.0.1
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="独立启动 uvicorn Web 服务（脱离 bash 会话）",
    )
    parser.add_argument(
        "version_dir",
        type=str,
        help="版本目录（例如 D:/项目/aiagent/langgraph_version）",
    )
    parser.add_argument("port", type=int, help="服务端口（1-65535）")
    parser.add_argument("host", type=str, nargs="?", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    version_dir = os.path.abspath(args.version_dir)
    if not Path(version_dir).is_dir():
        print(f"❌ 版本目录不存在: {version_dir}", file=sys.stderr)
        return 2
    if not (Path(version_dir) / "web_app.py").exists():
        print(f"❌ 目录中未找到 web_app.py: {version_dir}", file=sys.stderr)
        return 2
    if not 0 < args.port < 65536:
        print(f"❌ 端口号非法: {args.port}", file=sys.stderr)
        return 2

    env = dict(os.environ)
    env.setdefault("MOCK_LLM", "1")

    out_log = os.path.join(version_dir, "web_out.log")
    err_log = os.path.join(version_dir, "web_err.log")
    # 以追加模式写入，避免覆盖历史日志；子进程继承句柄后父进程再关闭，避免句柄泄漏
    out_handle = open(out_log, "a", encoding="utf-8")
    err_handle = open(err_log, "a", encoding="utf-8")

    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "web_app:app",
             "--host", args.host, "--port", str(args.port)],
            cwd=version_dir,
            env=env,
            stdout=out_handle,
            stderr=err_handle,
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    except OSError as e:
        print(f"❌ 启动失败: {e}", file=sys.stderr)
        return 1
    finally:
        # 父进程句柄已由子进程继承，这里必须关闭，否则文件句柄泄漏
        out_handle.close()
        err_handle.close()

    print(f"STARTED pid={proc.pid} port={args.port} dir={version_dir}")
    print(f"日志: {out_log} / {err_log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
