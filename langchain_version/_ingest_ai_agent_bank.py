"""将《AI Agent工程师1000题面经总结.docx》解析入库 interview_kb。

格式（规整版）：
    1. 什么是AI Agent？它和普通的大模型有什么区别？
    参考答案：
    AI Agent（人工智能智能体）是一种能够自主感知环境……
    （多行答案续行，直到下一个题号行）

用法: python _ingest_ai_agent_bank.py <docx_path>
"""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

from interview_knowledge_base import add_experiences, count_questions

logger = logging.getLogger(__name__)

_Q_RE = re.compile(r"^\s*(\d+)\s*[.、．]\s*(.+)$")
_A_RE = re.compile(r"^参考答案[:：]?\s*(.*)$")


def parse_bank(docx_path: str) -> list[dict]:
    """解析题库文档为结构化题目列表（role=AI Agent工程师）。"""
    from docx import Document

    doc = Document(docx_path)
    paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    items: list[dict] = []
    cur: dict | None = None
    in_answer = False

    for line in paras:
        m = _Q_RE.match(line)
        if m and int(m.group(1)) <= 1000 and not line.startswith("第"):
            if cur:
                items.append(cur)
            cur = {
                "_num": int(m.group(1)),
                "company": "",
                "role": "AI Agent工程师",
                "stage": "专业面",
                "question_type": "面试问答",
                "question": m.group(2).strip(),
                "key_points": [],
                "reference_answer": "",
                "quality": 4,
                "is_algorithm": False,
                "source": "AI Agent工程师1000题面经总结",
                "source_url": "",
                "collected_at": datetime.now().strftime("%Y-%m-%d"),
            }
            in_answer = False
            continue

        if line.startswith("参考答案"):
            in_answer = True
            tail = _A_RE.sub(r"\1", line).strip()
            if tail and cur is not None:
                cur["reference_answer"] = tail
            continue

        if in_answer and cur is not None and line:
            cur["reference_answer"] = (cur["reference_answer"] + " " + line).strip()

    if cur:
        items.append(cur)
    return items


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    if len(sys.argv) < 2:
        print("用法: python _ingest_ai_agent_bank.py <docx_path>")
        sys.exit(1)

    docx_path = sys.argv[1]
    if not Path(docx_path).exists():
        print(f"文件不存在: {docx_path}")
        sys.exit(1)

    items = parse_bank(docx_path)
    # 仅按题号去重：同一题号出现多次时保留首次（避免答案解析时续行被误判为新题），
    # 题干不去重——题库中重复题干也全部保留入库
    seen_nums: set[int] = set()
    final: list[dict] = []
    for item in items:
        num = item.get("_num", 0)
        if num in seen_nums:
            continue
        seen_nums.add(num)
        final.append(item)

    print(f"解析到 {len(items)} 题（按题号去重后 {len(final)} 题，题干不去重）")
    if not final:
        sys.exit(1)

    # 题干不去重 → 不能走 add_experiences（相同题干生成相同 ID 会触发 DuplicateIDError）。
    # 改用题号参与生成唯一 ID 直接 upsert，重复题干全部保留。
    import hashlib

    from interview_knowledge_base import (
        _get_interview_collection,
        _to_document,
        _to_metadata,
    )

    collection = _get_interview_collection()
    ids, documents, metadatas = [], [], []
    for item in final:
        qid = "exp_" + hashlib.md5(
            f"{item.get('_num', 0)}|{item.get('question', '')}".encode("utf-8")
        ).hexdigest()[:12]
        doc = _to_document(item)
        if not doc.strip():
            continue
        ids.append(qid)
        documents.append(doc)
        metadatas.append(_to_metadata(item))

    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    added = len(ids)
    total = count_questions()
    print(json.dumps({"解析": len(items), "新增": added, "题库总数": total}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
