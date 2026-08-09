"""将《AI产品经理1000题面试题库（带参考答案）.docx》直接解析入库 interview_kb。

策略：文档已是「题号.题干 + 参考答案」的结构化格式，无需 LLM 加工，
直接解析为结构化题目（role=AI产品经理）写入 interview_kb，按模块映射 stage/question_type。

用法: python _ingest_ai_pm_bank.py <docx_path>
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


def parse_bank(docx_path: str) -> list[dict]:
    """解析题库文档为结构化题目列表。"""
    from docx import Document

    doc = Document(docx_path)
    paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    items: list[dict] = []
    current_module = "模块一"
    question_re = re.compile(r"^(\d+)\.\s+(.+)$")
    answer_re = re.compile(r"^参考答案[:：]?\s*(.+)$")

    current_question: dict | None = None

    def flush() -> None:
        nonlocal current_question
        if current_question and current_question.get("question"):
            items.append(current_question)
        current_question = None

    for line in paras:
        # 模块标题
        module_match = re.match(r"^(模块[一二三四五六七])[:：]?", line)
        if module_match:
            current_module = module_match.group(1)
            flush()
            continue
        # 题号行（跳过"第X-X题"小节标题）
        q_match = question_re.match(line)
        if q_match and not line.startswith("第") and int(q_match.group(1)) <= 1000:
            flush()
            stage, qtype = MODULE_MAP.get(current_module, ("专业面", "面试问答"))
            current_question = {
                "company": "",
                "role": "AI产品经理",
                "stage": stage,
                "question_type": qtype,
                "question": q_match.group(2).strip(),
                "key_points": [],
                "reference_answer": "",
                "quality": 4,
                "is_algorithm": False,
                "source": "AI产品经理1000题题库",
                "source_url": "",
                "collected_at": datetime.now().strftime("%Y-%m-%d"),
            }
            continue
        # 参考答案
        a_match = answer_re.match(line)
        if a_match and current_question:
            current_question["reference_answer"] = a_match.group(1).strip()
            continue
        # 其他行（续行等）忽略

    flush()
    return items


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    if len(sys.argv) < 2:
        print("用法: python _ingest_ai_pm_bank.py <docx_path>")
        sys.exit(1)

    docx_path = sys.argv[1]
    if not Path(docx_path).exists():
        print(f"文件不存在: {docx_path}")
        sys.exit(1)

    items = parse_bank(docx_path)
    # 按题干去重（题库文档本身含少量重复题，保留首次出现）
    seen: set[str] = set()
    deduped: list[dict] = []
    for item in items:
        q = item.get("question", "")
        if q in seen:
            logger.info("跳过重复题: %s", q[:40])
            continue
        seen.add(q)
        deduped.append(item)
    items = deduped
    print(f"解析到 {len(items)} 道题（去重后）")
    if not items:
        sys.exit(1)

    added = add_experiences(items)
    total = count_questions()
    print(json.dumps({"解析": len(items), "新增": added, "题库总数": total}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
