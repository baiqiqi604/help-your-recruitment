"""清空 interview_kb 后，一次性合并导入：AI PM 扩展版（973 题）+ AI Agent（1000 题，题干不去重）。

背景：在已有集合上增量 upsert 会导致 ChromaDB 1.5.x Rust 核心的 compactor 无法正确落盘
（跨进程加载报 Error loading hnsw index）；而"清空后一次性 upsert"（重建式写入）可正常落盘。
因此采用：clear → 一次性 upsert 全部 1973 条。

ID 规则：md5(role|num|question)[:12]，确保 AI PM 与 AI Agent 的题号互不冲突、且题干重复也保留。
"""
from __future__ import annotations

import hashlib
import json
import logging
import sys
from datetime import datetime

from interview_knowledge_base import (
    _TITLE_ID_SUFFIX,
    _get_interview_collection,
    _get_interview_title_collection,
    _to_document,
    _to_metadata,
    _to_title_document,
    clear_interview_kb,
    count_questions,
)

logger = logging.getLogger(__name__)


def _load_ai_pm(docx_path: str) -> list[dict]:
    """解析 AI PM 扩展版 docx（模块映射 stage，题干去重）。"""
    from _replace_ai_pm_bank import parse_bank

    items = parse_bank(docx_path)
    seen: set[str] = set()
    result: list[dict] = []
    for it in items:
        q = it.get("question", "")
        if q in seen:
            continue
        seen.add(q)
        result.append(it)
    return result


def _load_ai_agent(docx_path: str) -> list[dict]:
    """解析 AI Agent docx（按题号去重，题干不去重）。"""
    import re

    from docx import Document

    _Q_RE = re.compile(r"^\s*(\d+)\s*[.、．]\s*(.+)$")
    _A_RE = re.compile(r"^参考答案[:：]?\s*(.*)$")

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

    seen_nums: set[int] = set()
    result: list[dict] = []
    for it in items:
        num = it["_num"]
        if num in seen_nums:
            continue
        seen_nums.add(num)
        result.append(it)
    return result


def _unique_id(item: dict) -> str:
    identity = (
        f"{item.get('role', '')}|{item.get('_num', 0)}|{item.get('question', '')}"
    )
    return "exp_" + hashlib.md5(identity.encode("utf-8")).hexdigest()[:12]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    ai_pm_docx = r"C:\Users\byx15\Desktop\AI产品经理1000题面试题库（答案扩展版）.docx"
    ai_agent_docx = r"C:\Users\byx15\Downloads\AI_Agent工程师1000题面经总结.docx"

    ai_pm = _load_ai_pm(ai_pm_docx)
    ai_agent = _load_ai_agent(ai_agent_docx)
    print(f"AI PM: {len(ai_pm)} 题 | AI Agent: {len(ai_agent)} 题（题干不去重）")

    removed = clear_interview_kb()
    print(f"清空原库: {removed}")

    collection = _get_interview_collection()
    title_col = _get_interview_title_collection()
    ids, documents, metadatas = [], [], []
    title_ids, title_documents, title_metadatas = [], [], []
    for item in ai_pm + ai_agent:
        doc = _to_document(item)
        if not doc.strip():
            continue
        qid = _unique_id(item)
        ids.append(qid)
        documents.append(doc)
        metas = _to_metadata(item)
        metadatas.append(metas)
        # 同步写标题索引（短文本检索单元），避免重建后标题集合为空、
        # search_questions 回退全文集合查询（首查 ~2s 且召回差）
        title_ids.append(qid + _TITLE_ID_SUFFIX)
        title_documents.append(_to_title_document(item))
        title_metadatas.append(metas)

    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    try:
        title_col.upsert(
            ids=title_ids, documents=title_documents, metadatas=title_metadatas
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("写入标题索引失败（不影响全文）: %s", e)
    total = count_questions()
    print(json.dumps({"AI_PM": len(ai_pm), "AI_Agent": len(ai_agent), "新增": len(ids), "题库总数": total}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
