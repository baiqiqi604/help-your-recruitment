"""
面试/笔试经验知识库检索层（依据《面试笔试经验知识库设计》）

职责：
1. 将加工层产出的结构化题目存入 ChromaDB `interview_kb` 集合
2. 支持按公司/岗位/轮次/关键词语义检索
3. 供面试建议生成（interview_advisor）检索真实题目

集合结构：
- 集合名：interview_kb
- Document：公司/岗位/轮次/题目类型/题目/考察点/参考思路/来源
- Metadata：company / role / stage / question_type / source / source_url / quality / is_algorithm / collected_at
- ID：exp_{内容MD5}（去重键）

复用 jd_knowledge_base 的 ChromaDB 客户端与 BGE embedding（避免重复加载模型）。
"""

from __future__ import annotations

import hashlib
import logging
from functools import lru_cache
from typing import Any

from config import CHROMA_CONFIG

# 复用岗位知识库的 ChromaDB 客户端与 BGE Embedding（单例）
from jd_knowledge_base import _get_chroma_client, _get_embedding_function  # noqa: F401

logger = logging.getLogger(__name__)

INTERVIEW_COLLECTION = "interview_kb"

VALID_STAGES = ("HR面", "业务面", "专业面", "主管面", "终面", "笔试")


@lru_cache(maxsize=1)
def _get_interview_collection():
    """获取或创建 interview_kb 集合（单例缓存）。"""
    client = _get_chroma_client()
    return client.get_or_create_collection(
        name=INTERVIEW_COLLECTION,
        embedding_function=_get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )


def _question_id(item: dict[str, Any]) -> str:
    """基于（公司, 岗位, 题目）生成稳定 ID。"""
    identity = (
        f"{item.get('company', '')}|{item.get('role', '')}|{item.get('question', '')}"
    )
    digest = hashlib.md5(identity.encode("utf-8")).hexdigest()[:12]
    return f"exp_{digest}"


def _to_document(item: dict[str, Any]) -> str:
    """将结构化题目拼接为用于向量化的文本文档。"""
    parts = [
        f"公司：{item.get('company', '')}",
        f"岗位：{item.get('role', '')}",
        f"轮次：{item.get('stage', '')}",
        f"题目类型：{item.get('question_type', '')}",
        f"题目：{item.get('question', '')}",
        f"考察点：{', '.join(item.get('key_points', []))}",
        f"参考思路：{item.get('reference_answer', '')}",
        f"来源：{item.get('source_url', '')}",
    ]
    return "\n".join(p for p in parts if p.split("：", 1)[-1].strip())


def _to_metadata(item: dict[str, Any]) -> dict[str, Any]:
    """提取 metadata（ChromaDB 仅支持标量值）。"""
    return {
        "company": str(item.get("company", "")),
        "role": str(item.get("role", "")),
        "stage": str(item.get("stage", "")),
        "question_type": str(item.get("question_type", "")),
        "source": str(item.get("source", "")),
        "source_url": str(item.get("source_url", "")),
        "quality": int(item.get("quality", 3)),
        "is_algorithm": bool(item.get("is_algorithm", False)),
        "collected_at": str(item.get("collected_at", "")),
    }


def init_interview_kb() -> None:
    """初始化面试经验知识库（确保集合存在，等价于 build）。"""
    _get_interview_collection()
    logger.info("面试经验知识库初始化完成（%s）", INTERVIEW_COLLECTION)


def clear_interview_kb() -> int:
    """清空 interview_kb 集合的全部内容（保留集合结构）。

    Returns:
        被删除的题目数量
    """
    collection = _get_interview_collection()
    try:
        existing = collection.get()
    except Exception as e:  # noqa: BLE001
        logger.warning("查询已有题目失败: %s", e)
        return 0

    ids = (existing or {}).get("ids") or []
    if not ids:
        logger.info("clear_interview_kb：知识库已为空")
        return 0

    try:
        collection.delete(ids=ids)
    except Exception as e:  # noqa: BLE001
        logger.warning("清空知识库失败: %s", e)
        return 0

    logger.info("clear_interview_kb：已清空 %d 道题（保留集合 %s）", len(ids), INTERVIEW_COLLECTION)
    return len(ids)


def add_experiences(items: list[dict[str, Any]]) -> int:
    """向面试经验知识库增量写入结构化题目。

    Args:
        items: 加工层产出的结构化题目列表（experience_processor 产物）

    Returns:
        实际新增数量
    """
    if not items:
        logger.info("add_experiences：无题目数据，跳过")
        return 0

    collection = _get_interview_collection()
    existing_ids: set[str] = set()
    try:
        existing = collection.get()
        if existing and existing.get("ids"):
            existing_ids = set(existing["ids"])
    except Exception as e:  # noqa: BLE001
        logger.warning("查询已有题目失败: %s", e)

    ids, documents, metadatas = [], [], []
    for item in items:
        question = str(item.get("question", "")).strip()
        if not question:
            continue
        qid = _question_id(item)
        if qid in existing_ids:
            continue
        doc = _to_document(item)
        if not doc.strip():
            continue
        ids.append(qid)
        documents.append(doc)
        metadatas.append(_to_metadata(item))

    if not ids:
        logger.info("add_experiences：全部题目已存在，无新增")
        return 0

    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    logger.info("add_experiences：新增 %d 道题", len(ids))
    return len(ids)


def search_questions(
    query: str,
    company: str = "",
    role: str = "",
    stage: str = "",
    top_k: int = 10,
    max_distance: float = 0.6,
) -> list[dict[str, Any]]:
    """按关键词/题目语义检索面试题。

    Args:
        query: 检索内容（如 "高并发下单" / "MySQL 优化"）
        company: 按公司过滤（可选）
        role: 按岗位过滤（可选）
        stage: 按轮次过滤（可选，HR面/业务面/专业面/主管面/终面/笔试）
        top_k: 返回条数
        max_distance: 相似度阈值（cosine 距离，越小越相关；超过该值的条目视为无关，丢弃）

    Returns:
        匹配的题目 dict 列表（按相关度排序，仅含 distance <= max_distance 的条目）
    """
    if not query or not query.strip():
        return []

    where_filters = []
    if company:
        where_filters.append({"company": company})
    if role:
        where_filters.append({"role": role})
    if stage:
        where_filters.append({"stage": stage})

    where = None
    if len(where_filters) == 1:
        where = where_filters[0]
    elif len(where_filters) > 1:
        where = {"$and": where_filters}

    try:
        collection = _get_interview_collection()
        results = collection.query(
            query_texts=[query.strip()],
            n_results=top_k,
            where=where,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("面试题检索失败: %s", e)
        return []

    questions = _format_results(results)
    # 相似度阈值过滤：只保留相关的条目
    filtered = [q for q in questions if q.get("distance") is None or q["distance"] <= max_distance]
    if len(filtered) < len(questions):
        logger.info("相似度过滤：%d 条 → %d 条（阈值 %.2f）", len(questions), len(filtered), max_distance)
    return filtered


def get_questions_by_company(company: str, top_k: int = 20) -> list[dict[str, Any]]:
    """面试前查"这家公司面什么"：按公司名获取题目。"""
    if not company or not company.strip():
        return []
    try:
        collection = _get_interview_collection()
        results = collection.get(
            where={"company": company.strip()},
            limit=top_k,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("按公司获取题目失败: %s", e)
        return []
    return _format_get_results(results)


def get_algorithm_questions(role: str = "", top_k: int = 20) -> list[dict[str, Any]]:
    """获取笔试算法题（可选按岗位过滤）。"""
    where = {"is_algorithm": True}
    if role:
        where = {"$and": [{"is_algorithm": True}, {"role": role}]}
    try:
        collection = _get_interview_collection()
        results = collection.get(where=where, limit=top_k)
    except Exception as e:  # noqa: BLE001
        logger.warning("获取算法题失败: %s", e)
        return []
    return _format_get_results(results)


def count_questions() -> int:
    """统计知识库题目总数。"""
    try:
        collection = _get_interview_collection()
        existing = collection.get()
        return len(existing.get("ids", [])) if existing else 0
    except Exception as e:  # noqa: BLE001
        logger.warning("统计题目数失败: %s", e)
        return 0


def _format_results(results: Any) -> list[dict[str, Any]]:
    """格式化 query 结果（按距离排序，还原题目）。"""
    questions: list[dict[str, Any]] = []
    if not results:
        return questions
    ids = results.get("ids", [[]])[0] if results.get("ids") else []
    documents = results.get("documents", [[]])[0] if results.get("documents") else []
    metadatas = results.get("metadatas", [[]])[0] if results.get("metadatas") else []
    distances = results.get("distances", [[]])[0] if results.get("distances") else []
    for i, doc in enumerate(documents):
        meta = metadatas[i] if i < len(metadatas) and metadatas[i] else {}
        questions.append(
            {
                "id": ids[i] if i < len(ids) else "",
                "question": _extract_field(doc, "题目"),
                "company": meta.get("company", ""),
                "role": meta.get("role", ""),
                "stage": meta.get("stage", ""),
                "question_type": meta.get("question_type", ""),
                "key_points": _extract_list_field(doc, "考察点"),
                "reference_answer": _extract_field(doc, "参考思路"),
                "quality": meta.get("quality", 3),
                "is_algorithm": meta.get("is_algorithm", False),
                "source_url": meta.get("source_url", ""),
                "distance": float(distances[i]) if i < len(distances) else None,
            }
        )
    return questions


def _format_get_results(results: Any) -> list[dict[str, Any]]:
    """格式化 get 结果（无距离信息）。"""
    questions: list[dict[str, Any]] = []
    if not results:
        return questions
    ids = results.get("ids") or []
    documents = results.get("documents") or []
    metadatas = results.get("metadatas") or []
    for i, doc in enumerate(documents):
        meta = metadatas[i] if i < len(metadatas) and metadatas[i] else {}
        questions.append(
            {
                "id": ids[i] if i < len(ids) else "",
                "question": _extract_field(doc, "题目"),
                "company": meta.get("company", ""),
                "role": meta.get("role", ""),
                "stage": meta.get("stage", ""),
                "question_type": meta.get("question_type", ""),
                "key_points": _extract_list_field(doc, "考察点"),
                "reference_answer": _extract_field(doc, "参考思路"),
                "quality": meta.get("quality", 3),
                "is_algorithm": meta.get("is_algorithm", False),
                "source_url": meta.get("source_url", ""),
            }
        )
    return questions


def _extract_field(doc: str, label: str) -> str:
    """从 Document 文本中提取指定标签字段。"""
    for line in (doc or "").splitlines():
        if line.startswith(f"{label}："):
            return line.split("：", 1)[1].strip()
    return ""


def _extract_list_field(doc: str, label: str) -> list[str]:
    value = _extract_field(doc, label)
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


if __name__ == "__main__":
    import json

    sample_items = [
        {
            "company": "某公司",
            "role": "Python后端",
            "stage": "专业面",
            "question_type": "面试问答",
            "question": "Python 中 GIL 是什么？",
            "key_points": ["GIL", "多线程"],
            "reference_answer": "GIL 是 CPython 的全局解释器锁。",
            "quality": 4,
            "is_algorithm": False,
            "source": "manual",
            "source_url": "",
            "collected_at": "2026-08-09",
        }
    ]
    print("新增:", add_experiences(sample_items), "道题")
    print("总数:", count_questions())
    res = search_questions("GIL 多线程", top_k=3)
    print("检索:", json.dumps(res, ensure_ascii=False)[:300])
