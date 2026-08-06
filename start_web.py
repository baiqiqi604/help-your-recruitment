"""独立启动 uvicorn Web 服务（脱离 bash 会话，避免被连带终止）。

用法: python start_web.py <版本目录> <端口> [host]
"""
import os
import subprocess
import sys

version_dir = sys.argv[1]  # 例如 D:/项目/aiagent/langchain_version
port = sys.argv[2]
host = sys.argv[3] if len(sys.argv) > 3 else "127.0.0.1"

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

env = dict(os.environ)
env.setdefault("MOCK_LLM", "1")

out_log = os.path.join(version_dir, "web_out.log")
err_log = os.path.join(version_dir, "web_err.log")

proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "web_app:app",
     "--host", host, "--port", port],
    cwd=version_dir,
    env=env,
    stdout=open(out_log, "w", encoding="utf-8"),
    stderr=open(err_log, "w", encoding="utf-8"),
    creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
    close_fds=True,
)
print(f"STARTED pid={proc.pid} port={port} dir={version_dir}")
