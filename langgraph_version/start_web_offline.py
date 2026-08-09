"""离线启动 Web 服务（设置 HF 离线环境变量后启动 uvicorn）。

用途：避免模型加载时联网检查 HuggingFace（网络受限环境会长时间卡死）。
用法：python start_web_offline.py [port]
"""
from __future__ import annotations

import os
import sys

# 必须在 import sentence_transformers / transformers 之前设置
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

import uvicorn  # noqa: E402

from config import WEB_CONFIG  # noqa: E402


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else WEB_CONFIG["port"]
    host = WEB_CONFIG["host"]
    print(f"启动 Web 服务（HF 离线模式）: http://{host}:{port}")
    uvicorn.run(
        "web_app:app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
