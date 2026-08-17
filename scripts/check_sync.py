#!/usr/bin/env python3
"""双版本共享文件同步一致性检查（CI 用）。

langchain_version / langgraph_version 共享同一批核心文件（检索层、LLM 客户端、
结构化输出、简历读写等）。项目约定「改动先在 langgraph 落地，随后同步到
langchain」，但手工同步容易漂移。本脚本逐字节对比共享文件，发现不一致时
退出码非 0，由 CI 阻止合并，把漂移挡在提交之前。

用法：
    python scripts/check_sync.py          # 检查并输出报告（默认）
    python scripts/check_sync.py --quiet  # 仅输出不一致项

说明：
    - 共享文件清单维护于 SHARED_FILES；新增共享文件请同步加入。
    - 版本特有文件（允许不一致）不在此列：main.py / web_app.py / agent.py /
      config.py / requirements.txt / chain.py / graph.py / jd_crawler.py /
      scheduler.py / .env.example 等。
    - 逐字节比较（含行尾符）：任一侧引入 CRLF 或 BOM 都会被检出。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 两个版本目录名（相对仓库根）
VERSION_DIRS = ("langchain_version", "langgraph_version")

# 必须逐字节一致的共享文件（相对各版本目录）
SHARED_FILES = [
    "company_researcher.py",
    "content_optimizer.py",
    "experience_crawler.py",
    "experience_processor.py",
    "interview_advisor.py",
    "interview_knowledge_base.py",
    "jd_analyzer.py",
    "jd_knowledge_base.py",
    "llm_client.py",
    "reranker.py",
    "resume_reader.py",
    "resume_writer.py",
    "resume_formatter.py",
    "retrievers.py",
    "schemas.py",
    "start_web_offline.py",
    "validate_runtime.py",
    "pytest.ini",
    "requirements-dev.txt",
]


def check_sync(root: Path) -> list[str]:
    """逐字节对比共享文件，返回不一致项描述列表（空 = 全部一致）。"""
    problems: list[str] = []
    for rel in SHARED_FILES:
        paths = [root / vd / rel for vd in VERSION_DIRS]
        missing = [str(p) for p in paths if not p.exists()]
        if missing:
            problems.append(f"[缺失] {rel} → {', '.join(missing)}")
            continue

        b_lc = paths[0].read_bytes()
        b_lg = paths[1].read_bytes()
        if b_lc != b_lg:
            problems.append(f"[不一致] {rel}（langchain 版与 langgraph 版内容不同）")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="双版本共享文件同步一致性检查")
    parser.add_argument("--quiet", action="store_true", help="仅输出不一致项")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    problems = check_sync(root)

    if not problems:
        if not args.quiet:
            print(f"✅ 同步检查通过：{len(SHARED_FILES)} 个共享文件两版完全一致")
        return 0

    print(f"❌ 同步检查失败：发现 {len(problems)} 处不一致/缺失")
    for item in problems:
        print(f"   {item}")
    print("\n修复方法：将 langgraph_version 中的对应文件同步到 langchain_version（或反之），")
    print("确保共享文件逐字节一致后再提交。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
