"""
面试经验加工层（依据《面试笔试经验知识库设计》）

职责：
1. 接收入库层的原始面经/笔试素材
2. LLM 去噪、归并、结构化：提取 公司/岗位/轮次/题目/考察点/参考思路
3. 输出符合 interview_kb 集合结构的题库条目（供检索层入库）

结构化输出字段：
    company / role / stage / question_type / question / key_points /
    reference_answer / quality / source_url / is_algorithm

合规：
- 输出保留来源 URL；不确定内容标注【待确认】
- 参考思路标注【AI 整理，仅供参考】
- 不虚构来源，不把猜测写成确定事实

依赖：llm_client（OpenAI 兼容多 Provider）
"""

from __future__ import annotations

import logging
from typing import Any

import llm_client

logger = logging.getLogger(__name__)

# 单条素材最大处理长度（防止超出模型上下文）
MAX_RAW_CHARS = 6000
# 单条素材最多提取题目数
MAX_QUESTIONS_PER_ITEM = 10

# 合法取值
STAGE_VALUES = ("HR面", "业务面", "专业面", "主管面", "终面", "笔试")
QUESTION_TYPE_VALUES = ("面试问答", "手撕算法", "系统设计", "行为面")


# LLM 结构化 Prompt 模板
PROCESS_PROMPT = """你是一位资深面试题库编辑。请将下面这段面试/笔试经验素材，拆解为结构化的面试题目。

【素材来源】{source_label}
【素材内容】
{raw_text}

请以 JSON 数组格式返回题目列表（1-{max_questions} 条），每条包含：
- company: 公司名（素材未指明则填 ""）
- role: 岗位名（如 "Python后端"/"前端"，未指明则填 ""）
- stage: 面试轮次，只能取 "HR面" / "业务面" / "专业面" / "主管面" / "终面" / "笔试" 之一（无法判断时填 "业务面"）
- question_type: 题目类型，只能取 "面试问答" / "手撕算法" / "系统设计" / "行为面" 之一
- question: 题目内容（简洁完整）
- key_points: 考察点列表（2-5 个）
- reference_answer: 参考思路/答案要点（若素材无答案，给出 AI 整理的思路要点，标注"【AI 整理，仅供参考】"；信息不足则填"【待确认】"）
- quality: 质量分（1-5 整数，基于素材详实度与多源程度）
- is_algorithm: 是否笔试算法题（true/false）

要求：
1. 去噪：忽略广告、无关讨论、纯情绪表达，只保留真正的面试/笔试题目
2. 尽量从素材中提取完整题目；素材提及但未展开的题目，可保留题目并标注参考思路为【待确认】
3. 同一素材内重复题目只保留一次
4. 不虚构题目，只基于素材内容

只返回 JSON 数组，不要其他内容。"""


def process_raw_item(item: dict[str, Any]) -> list[dict[str, Any]]:
    """将单条原始素材结构化为一组题库条目。

    Args:
        item: 入库层素材 dict（含 source/title/url/content 及可选 company/role/stage）

    Returns:
        结构化题目列表（可直接入库 interview_kb）
    """
    content = (item.get("content") or "").strip()
    if not content:
        return []
    if len(content) > MAX_RAW_CHARS:
        content = content[:MAX_RAW_CHARS]

    source_label = f"{item.get('source', 'unknown')}：{item.get('title', '')}"
    prompt = PROCESS_PROMPT.format(
        source_label=source_label,
        raw_text=content,
        max_questions=MAX_QUESTIONS_PER_ITEM,
    )
    logger.info("process_raw_item：结构化素材 %s（%d 字）", source_label, len(content))
    try:
        raw = llm_client.chat_json_array(prompt)
    except Exception as e:  # noqa: BLE001
        logger.warning("素材结构化失败 %s: %s", source_label, e)
        return []

    questions = _normalize_questions(raw, item)
    logger.info("素材 %s 提取出 %d 道题", source_label, len(questions))
    return questions


def process_raw_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """批量结构化原始素材。

    Args:
        items: 原始素材列表（load_raw_experiences 的产物）

    Returns:
        全部结构化题目（已去重）
    """
    all_questions: list[dict[str, Any]] = []
    for item in items:
        all_questions.extend(process_raw_item(item))
    return _deduplicate_questions(all_questions)


def _normalize_questions(
    raw: Any, source_item: dict[str, Any]
) -> list[dict[str, Any]]:
    """校验并补齐结构化题目字段。"""
    questions: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return questions

    for q in raw:
        if not isinstance(q, dict):
            continue
        question = str(q.get("question", "")).strip()
        if not question:
            continue

        stage = str(q.get("stage", "")).strip()
        if stage not in STAGE_VALUES:
            stage = "业务面"

        question_type = str(q.get("question_type", "")).strip()
        if question_type not in QUESTION_TYPE_VALUES:
            question_type = "面试问答"

        quality = q.get("quality", 3)
        try:
            quality = int(quality)
        except (TypeError, ValueError):
            quality = 3
        quality = max(1, min(5, quality))

        questions.append(
            {
                "company": str(q.get("company", "")).strip() or "",
                "role": str(q.get("role", "")).strip() or "",
                "stage": stage,
                "question_type": question_type,
                "question": question,
                "key_points": _as_str_list(q.get("key_points")),
                "reference_answer": str(q.get("reference_answer", "")).strip(),
                "quality": quality,
                "is_algorithm": bool(q.get("is_algorithm", False)),
                "source": str(source_item.get("source", "")),
                "source_url": str(source_item.get("url", "")).strip(),
                "collected_at": str(source_item.get("collected_at", "")),
            }
        )
    return questions


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _deduplicate_questions(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按（公司, 岗位, 题目）去重。"""
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for q in questions:
        key = (q.get("company", ""), q.get("role", ""), q.get("question", ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(q)
    return result


if __name__ == "__main__":
    import json

    sample = {
        "source": "csdn",
        "title": "Python 面试题示例",
        "url": "https://blog.csdn.net/example",
        "content": (
            "1. 请介绍 Python 中 GIL 是什么？\n"
            "2. Django 中如何处理数据库事务？\n"
            "3. 手撕：实现一个 LRU 缓存。"
        ),
    }
    print(json.dumps(process_raw_item(sample), ensure_ascii=False, indent=2))
