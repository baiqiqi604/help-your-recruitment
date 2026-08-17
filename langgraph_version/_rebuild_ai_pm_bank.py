"""用「扩展版 AI 产品经理题库」（expanded_模块*.txt）完全重建 interview_kb 向量库。

流程：清空现有 interview_kb 集合 → 解析 7 个模块的扩展题库 txt → 全部重新入库。

用法:
    python _rebuild_ai_pm_bank.py <toolkit_dir>
    默认 toolkit_dir = C:/Users/byx15/Desktop/ai_pm_toolkit

说明:
    - 扩展版 docx 由 build_docx.py 生成，但答案段落被替换为纯文本（多行），
      _ingest_ai_pm_bank.py 的 "参考答案：" 行匹配无法取到答案，因此改为
      直接解析 expanded_模块*.txt（格式: === 题号 === / 题目行 / 参考答案：...）。
    - 题库中少量重复题（同题干出现在多个题号）按题干去重，保留首次出现。
"""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

from interview_knowledge_base import (
    add_experiences,
    clear_interview_kb,
    count_questions,
)

logger = logging.getLogger(__name__)

DEFAULT_TOOLKIT_DIR = Path(r"C:/Users/byx15/Desktop/ai_pm_toolkit")

# 模块 → (stage, question_type) 映射（与 _ingest_ai_pm_bank.py 一致）
MODULE_MAP = {
    "模块一": ("专业面", "面试问答"),      # 岗位认知与通用PM能力
    "模块二": ("专业面", "面试问答"),      # 大模型技术产品理解
    "模块三": ("专业面", "面试问答"),      # RAG/Agent/Prompt 专项
    "模块四": ("专业面", "面试问答"),      # 模型评估、数据闭环
    "模块五": ("业务面", "行为面"),        # 产品设计场景题
    "模块六": ("专业面", "面试问答"),      # 安全合规与风险管理
    "模块七": ("HR面", "面试问答"),        # 商业化、行业应用与 HR/压力题
}

_BLOCK_RE = re.compile(r"^=== (\d+) ===\s*$", re.M)
_Q_RE = re.compile(r"^\s*(\d+)\s*[.、．]\s*(.+)$")
_A_RE = re.compile(r"^参考答案[:：]?\s*(.*)$")


def _parse_module_file(path: Path, module_name: str) -> list[dict]:
    """解析单个 expanded_模块*.txt 文件为结构化题目列表。"""
    text = path.read_text(encoding="utf-8")
    stage, qtype = MODULE_MAP.get(module_name, ("专业面", "面试问答"))

    items: list[dict] = []
    blocks = re.split(_BLOCK_RE, text)
    # blocks: ['前置文本', '题号1', '正文1', '题号2', '正文2', ...]
    for i in range(1, len(blocks), 2):
        num = int(blocks[i])
        body = blocks[i + 1]
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        if not lines:
            continue
        m = _Q_RE.match(lines[0])
        if not m:
            logger.warning("题目行未匹配 %s 第 %d 题: %s", path.name, num, lines[0][:50])
            continue
        question = m.group(2).strip()

        # 参考答案：从 "参考答案：" 行开始收集到下一分隔符前
        answer_parts: list[str] = []
        for line in lines[1:]:
            am = _A_RE.match(line)
            if am:
                if am.group(1).strip():
                    answer_parts.append(am.group(1).strip())
            else:
                answer_parts.append(line)
        reference_answer = " ".join(answer_parts).strip()

        items.append({
            "company": "",
            "role": "AI产品经理",
            "stage": stage,
            "question_type": qtype,
            "question": question,
            "key_points": [],
            "reference_answer": reference_answer,
            "quality": 4,
            "is_algorithm": False,
            "source": "AI产品经理1000题题库（答案扩展版）",
            "source_url": "",
            "collected_at": datetime.now().strftime("%Y-%m-%d"),
        })
    return items


def load_items(toolkit_dir: Path) -> list[dict]:
    """按 modules.json 顺序加载全部扩展题库题目，并按题干去重。"""
    modules_cfg = json.loads((toolkit_dir / "modules.json").read_text(encoding="utf-8"))

    all_items: list[dict] = []
    for mod in modules_cfg:
        name = mod["name"]  # 形如 "模块一_岗位认知与通用PM能力"
        module_name = name.split("_", 1)[0]
        fp = toolkit_dir / f"expanded_{name}.txt"
        if not fp.exists():
            logger.warning("缺少扩展文件: %s", fp)
            continue
        items = _parse_module_file(fp, module_name)
        logger.info("%s: 解析 %d 题", name, len(items))
        all_items.extend(items)

    # 按题干去重（保留首次出现）
    seen: set[str] = set()
    deduped: list[dict] = []
    for item in all_items:
        q = item.get("question", "")
        if q in seen:
            continue
        seen.add(q)
        deduped.append(item)
    logger.info("总计解析 %d 题，按题干去重后 %d 题", len(all_items), len(deduped))
    return deduped


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    toolkit_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TOOLKIT_DIR
    if not toolkit_dir.exists():
        print(f"素材目录不存在: {toolkit_dir}")
        sys.exit(1)

    items = load_items(toolkit_dir)
    if not items:
        print("未解析到任何题目，中止")
        sys.exit(1)

    removed = clear_interview_kb()
    logger.info("已清空原 interview_kb：%d 题", removed)

    added = add_experiences(items)
    total = count_questions()
    print(json.dumps(
        {"解析": len(items), "新增": added, "清空": removed, "题库总数": total},
        ensure_ascii=False, indent=2,
    ))


if __name__ == "__main__":
    main()
