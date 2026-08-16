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
import re
from functools import lru_cache
from typing import Any

from config import CHROMA_CONFIG, RERANK_CONFIG

# 复用岗位知识库的 ChromaDB 客户端与 BGE Embedding（单例）
from jd_knowledge_base import _get_chroma_client, _get_embedding_function  # noqa: F401

# Rerank 重排（可选依赖：模型加载失败时自动降级为不重排）
from reranker import rerank

logger = logging.getLogger(__name__)

INTERVIEW_COLLECTION = "interview_kb"
# 标题索引集合：只存「题目 + 考察点」短文本作为检索单元，
# 命中后按 id 映射回全文集合（解决长文档 + 短查询向量距离偏高的问题）
INTERVIEW_TITLE_COLLECTION = "interview_kb_title"

VALID_STAGES = ("HR面", "业务面", "专业面", "主管面", "终面", "笔试")

# 标题文档 id 后缀（用于与全文文档 id 区分，检索后统一还原为全文 id）
_TITLE_ID_SUFFIX = "#t"


def _collection_metadata() -> dict[str, Any]:
    """ChromaDB Collection 元数据（cosine 空间 + 关闭 Python 侧 sync 阈值）。"""
    # 关键：hnsw:sync_threshold 必须远大于批量导入条数。
    # 默认 1000 时，单次导入 ≥1000 条会触发 Python 侧 _persist() 写出损坏的
    # index_metadata.pickle（dimensionality=None），导致 Rust 核心跨进程加载报
    # "Error loading hnsw index"；<1000 条不触发、由 Rust 核心从 sqlite 正常管理。
    # 本项目两库合并共 1973 条，故设为 100000 永不触发。
    return {"hnsw:space": "cosine", "hnsw:sync_threshold": 100000}


def _get_interview_collection_named(name: str):
    """获取或创建指定名称的面试知识库集合。"""
    client = _get_chroma_client()
    return client.get_or_create_collection(
        name=name,
        embedding_function=_get_embedding_function(),
        metadata=_collection_metadata(),
    )


@lru_cache(maxsize=1)
def _get_interview_collection():
    """获取或创建 interview_kb 全文集合（单例缓存）。"""
    return _get_interview_collection_named(INTERVIEW_COLLECTION)


@lru_cache(maxsize=1)
def _get_interview_title_collection():
    """获取或创建 interview_kb_title 标题索引集合（单例缓存）。"""
    return _get_interview_collection_named(INTERVIEW_TITLE_COLLECTION)


def rebuild_interview_title_index() -> int:
    """从全文集合重建标题索引集合（interview_kb_title）。

    场景：旧库或 _merge_import_banks 等重建脚本只写了全文集合、漏写标题索引，
    导致 search_questions 每次回退全文集合查询（长文档首查 ~2s、且召回差）。
    本函数从全文集合读取全部文档，解析出「题目 + 考察点」短文本重建标题集合。

    Returns:
        写入标题索引的条数（0 表示全文集合为空或失败）
    """
    collection = _get_interview_collection()
    try:
        existing = collection.get()
    except Exception as e:  # noqa: BLE001
        logger.warning("重建标题索引：读取全文集合失败: %s", e)
        return 0

    ids = (existing or {}).get("ids") or []
    documents = (existing or {}).get("documents") or []
    metadatas = (existing or {}).get("metadatas") or []
    if not ids:
        logger.info("重建标题索引：全文集合为空，跳过")
        return 0

    title_ids: list[str] = []
    title_docs: list[str] = []
    title_metas: list[dict[str, Any]] = []
    for i, doc in enumerate(documents):
        qid = str(ids[i])
        if qid.endswith(_TITLE_ID_SUFFIX):
            continue
        question = _extract_field(doc, "题目")
        if not question:
            continue
        key_points = _extract_list_field(doc, "考察点")
        parts = [f"题目：{question}"]
        if key_points:
            parts.append(f"考察点：{', '.join(key_points)}")
        title_doc = "\n".join(p for p in parts if p.split("：", 1)[-1].strip())
        title_ids.append(qid + _TITLE_ID_SUFFIX)
        title_docs.append(title_doc)
        title_metas.append(metadatas[i] if i < len(metadatas) else {})

    if not title_ids:
        logger.info("重建标题索引：无可重建条目")
        return 0

    title_col = _get_interview_title_collection()
    # 重建式写入：一次性 upsert 全部标题条目（与 _merge_import_banks 的
    # "清空后一次性 upsert 可正常落盘" 结论一致；分批增量 upsert 可能触发
    # ChromaDB 1.5.x compactor 落盘问题）
    try:
        title_col.upsert(
            ids=title_ids, documents=title_docs, metadatas=title_metas
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("重建标题索引失败: %s", e)
        return 0
    logger.info("重建标题索引完成：%d 条（全文 %d 条）", len(title_ids), len(ids))
    return len(title_ids)


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


def _to_title_document(item: dict[str, Any]) -> str:
    """将题目拼接为用于检索的短文本（仅题目 + 考察点，不含长答案）。

    短文档对短查询的向量距离显著更低，作为检索单元可大幅提升召回。
    """
    parts = [
        f"题目：{item.get('question', '')}",
        f"考察点：{', '.join(item.get('key_points', []))}",
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

    # 同步清空标题索引集合（保留集合结构）
    try:
        title_col = _get_interview_title_collection()
        title_existing = title_col.get()
        title_ids = (title_existing or {}).get("ids") or []
        if title_ids:
            title_col.delete(ids=title_ids)
    except Exception as e:  # noqa: BLE001
        logger.warning("清空标题索引集合失败: %s", e)

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
    title_ids, title_documents, title_metadatas = [], [], []
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
        meta = _to_metadata(item)
        ids.append(qid)
        documents.append(doc)
        metadatas.append(meta)
        # 标题索引：id 带后缀，短文本（题目+考察点）作为检索单元
        title_ids.append(qid + _TITLE_ID_SUFFIX)
        title_documents.append(_to_title_document(item))
        title_metadatas.append(meta)

    if not ids:
        logger.info("add_experiences：全部题目已存在，无新增")
        return 0

    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    try:
        title_col = _get_interview_title_collection()
        title_col.upsert(
            ids=title_ids, documents=title_documents, metadatas=title_metadatas
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("写入标题索引失败（不影响全文）: %s", e)

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

    检索策略（增强）：
    1. 先查「标题索引集合」（题目+考察点短文本）：短文档对短查询的向量距离
       更低，大幅提升召回（如 "LRU" 这类简写不再只靠关键词兜底）；
    2. 标题索引为空（旧库未重建）时自动回退全文集合检索，保持兼容；
    3. 命中后按 id 映射回全文集合，回填参考答案等长字段；
    4. 关键词兜底：向量命中不足时按词元子串匹配补召回；
    5. Rerank 精排：粗召回 top_k*multiplier 条后按 (query, 全文) 重排取 top_k。
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

    n_results = min(
        top_k * RERANK_CONFIG["candidate_multiplier"],
        RERANK_CONFIG["max_candidates"],
    )

    try:
        results = _get_interview_title_collection().query(
            query_texts=[query.strip()],
            n_results=n_results,
            where=where,
        )
        used_title = bool(results.get("ids") and results["ids"][0])
    except Exception as e:  # noqa: BLE001
        logger.warning("面试题标题检索失败: %s", e)
        return []

    questions = _format_results(results)
    if used_title:
        # 标题 id 带后缀，统一还原为全文 id（与关键词兜底结果去重一致）
        for q in questions:
            qid = str(q.get("id", ""))
            if qid.endswith(_TITLE_ID_SUFFIX):
                q["id"] = qid[: -len(_TITLE_ID_SUFFIX)]
    else:
        # 标题索引为空（旧库未重建）→ 回退全文集合检索
        try:
            results = _get_interview_collection().query(
                query_texts=[query.strip()],
                n_results=n_results,
                where=where,
            )
            questions = _format_results(results)
        except Exception as e:  # noqa: BLE001
            logger.warning("面试题全文检索失败: %s", e)
            return []

    # 相似度阈值过滤：只保留相关的条目
    filtered = [q for q in questions if q.get("distance") is None or q["distance"] <= max_distance]
    if len(filtered) < len(questions):
        logger.info("相似度过滤：%d 条 → %d 条（阈值 %.2f）", len(questions), len(filtered), max_distance)

    # 关键词兜底：向量命中不足时，按词元子串匹配补召回（解决简写/专有名词漏召回）
    if len(filtered) < min(top_k, 3):
        kw_hits = _keyword_search(query.strip(), where, top_k)
        seen_ids = {q.get("id") for q in filtered}
        for q in kw_hits:
            if q.get("id") and q["id"] not in seen_ids:
                filtered.append(q)
                seen_ids.add(q["id"])
            if len(filtered) >= top_k:
                break
        if len(kw_hits):
            logger.info("关键词兜底补充 %d 条", len(kw_hits))

    if not filtered:
        return []

    # 回填/汇总全文（标题命中时参考答案等长字段来自全文；重排打分也用全文）
    docs_by_id = _fetch_full_docs([str(q.get("id", "")) for q in filtered])
    rerank_texts: list[str] = []
    for q in filtered:
        full_doc = docs_by_id.get(str(q.get("id", "")), "")
        if full_doc:
            q["reference_answer"] = _extract_field(full_doc, "参考思路")
            rerank_texts.append(full_doc)
        else:
            rerank_texts.append(
                " ".join(
                    p
                    for p in (str(q.get("question", "")), str(q.get("reference_answer", "")))
                    if p
                )
            )

    # Rerank 精排：模型不可用（rerank 返回空）时按向量原序返回
    reranked = rerank(query, rerank_texts, top_k)
    if reranked:
        ordered: list[dict[str, Any]] = []
        for idx, score in reranked:
            item = dict(filtered[idx])
            item["rerank_score"] = score
            ordered.append(item)
        return ordered
    return filtered[:top_k]


def _extract_keywords(query: str, max_kw: int = 6) -> list[str]:
    """从查询中切出候选词元（英文词 / 中文连续片段），用于关键词兜底检索。"""
    tokens: list[str] = []
    # 英文/数字词
    tokens += re.findall(r"[A-Za-z0-9+#.]+", query)
    # 中文连续片段（按标点/空格切分）
    cn_chunks = re.split(r"[，。！？、；：,.!?;:\s/\\()（）\[\]【】\"'“”]+", query)
    for chunk in cn_chunks:
        chunk = chunk.strip()
        if chunk and len(chunk) >= 2 and chunk not in tokens:
            tokens.append(chunk)
    return tokens[:max_kw]


def _keyword_search(query: str, where: Any, top_k: int) -> list[dict[str, Any]]:
    """按词元子串（$contains）检索，作为向量检索的兜底。"""
    keywords = _extract_keywords(query)
    if not keywords:
        return []
    try:
        collection = _get_interview_collection()
        clauses = [{"$contains": kw} for kw in keywords]
        where_document = clauses[0] if len(clauses) == 1 else {"$or": clauses}
        results = collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where,
            where_document=where_document,
        )
        return _format_results(results)
    except Exception as e:  # noqa: BLE001
        logger.warning("关键词兜底检索失败: %s", e)
        return []


def _fetch_full_docs(ids: list[str]) -> dict[str, str]:
    """按全文 id 批量取回全文文档（id → 文档文本）。

    标题索引命中后需要映射回全文集合，以获取参考答案等长字段。
    """
    if not ids:
        return {}
    try:
        collection = _get_interview_collection()
        results = collection.get(ids=ids)
    except Exception as e:  # noqa: BLE001
        logger.warning("获取全文文档失败: %s", e)
        return {}
    if not results or not results.get("ids"):
        return {}
    return dict(zip(results["ids"], results["documents"]))


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


# 文档字段标签（用于多行字段提取时识别边界）
_FIELD_LABELS = ("公司：", "岗位：", "轮次：", "题目类型：", "题目：", "考察点：", "参考思路：", "来源：")


def _extract_field(doc: str, label: str) -> str:
    """从 Document 文本中提取指定标签字段（支持跨多行，遇到下一标签结束）。"""
    target = f"{label}："
    lines = (doc or "").splitlines()
    for i, line in enumerate(lines):
        if line.startswith(target):
            parts = [line.split("：", 1)[1].strip()]
            for j in range(i + 1, len(lines)):
                nxt = lines[j]
                if nxt.startswith(_FIELD_LABELS):
                    break
                parts.append(nxt.strip())
            return " ".join(p for p in parts if p).strip()
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
