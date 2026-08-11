"""用《AI产品经理1000题面试题库（答案扩展版）.docx》完全替换 interview_kb 题库。

流程：清空现有 interview_kb → 解析扩展版 docx（1000 题，含详细参考答案）→ 全部重新入库。

格式（答案扩展版）：
    模块一：岗位认知与通用PM能力（第1-150题）
    1. AI产品经理核心职责是什么？...
    参考答案：我可以从职责和区别两个层面来回答。
    （多行答案续行，直到下一个题号行）

用法: python _replace_ai_pm_bank.py <docx_path>
"""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

from interview_knowledge_base import add_experiences, clear_interview_kb, count_questions

logger = logging.getLogger(__name__)

# 模块 → (stage, question_type) 映射（按题库结构说明）
MODULE_MAP = {
    "模块一": ("专业面", "面试问答"),      # 岗位认知与通用PM能力
    "模块二": ("专业面", "面试问答"),      # 大模型技术产品理解
    "模块三": ("专业面", "面试问答"),      # RAG/Agent/Prompt 专项
    "模块四": ("专业面", "面试问答"),      # 模型评估、数据闭环
    "模块五": ("业务面", "行为面"),        # 产品设计场景题
    "模块六": ("专业面", "面试问答"),      # 安全合规与风险管理
    "模块七": ("HR面", "面试问答"),        # 商业化、行业应用与 HR/压力题
}

_MODULE_RE = re.compile(r"^(模块[一二三四五六七])[:：]")
_Q_RE = re.compile(r"^\s*(\d+)\s*[.、．]\s*(.+)$")
_A_RE = re.compile(r"^参考答案[:：]?\s*(.*)$")


def parse_bank(docx_path: str) -> list[dict]:
    """解析扩展版题库文档为结构化题目列表（role=AI产品经理）。"""
    from docx import Document

    doc = Document(docx_path)
    paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    items: list[dict] = []
    current_module = "模块一"
    cur: dict | None = None
    in_answer = False

    for line in paras:
        # 模块标题
        module_match = _MODULE_RE.match(line)
        if module_match:
            current_module = module_match.group(1)
            continue

        # 题号行
        m = _Q_RE.match(line)
        if m and int(m.group(1)) <= 1000 and not line.startswith("第"):
            if cur:
                items.append(cur)
            stage, qtype = MODULE_MAP.get(current_module, ("专业面", "面试问答"))
            cur = {
                "company": "",
                "role": "AI产品经理",
                "stage": stage,
                "question_type": qtype,
                "question": m.group(2).strip(),
                "key_points": [],
                "reference_answer": "",
                "quality": 4,
                "is_algorithm": False,
                "source": "AI产品经理1000题面试题库（答案扩展版）",
                "source_url": "",
                "collected_at": datetime.now().strftime("%Y-%m-%d"),
            }
            in_answer = False
            continue

        # 参考答案（可能独立成行，答案跨多行）
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
        print("用法: python _replace_ai_pm_bank.py <docx_path>")
        sys.exit(1)

    docx_path = sys.argv[1]
    if not Path(docx_path).exists():
        print(f"文件不存在: {docx_path}")
        sys.exit(1)

    items = parse_bank(docx_path)
    # 按题干去重（题库含少量重复题，保留首次出现）
    seen: set[str] = set()
    deduped: list[dict] = []
    for item in items:
        q = item.get("question", "")
        if q in seen:
            continue
        seen.add(q)
        deduped.append(item)

    print(f"解析到 {len(items)} 题（按题干去重后 {len(deduped)} 题）")
    if not deduped:
        sys.exit(1)

    removed = clear_interview_kb()
    logger.info("已清空原 interview_kb：%d 题", removed)

    added = add_experiences(deduped)
    total = count_questions()
    print(json.dumps(
        {"解析": len(items), "去重": len(deduped), "新增": added, "清空": removed, "题库总数": total},
        ensure_ascii=False, indent=2,
    ))


if __name__ == "__main__":
    main()
