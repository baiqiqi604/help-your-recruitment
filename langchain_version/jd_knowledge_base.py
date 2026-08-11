"""
岗位知识库模块（RAG + ChromaDB）

职责：
1. 管理爬取到的岗位数据，存入向量数据库
2. 标记大厂岗位和高频匹配岗位，优先检索
3. 支持按关键词、技能、公司名检索岗位
4. 每日增量更新，避免重复

ChromaDB Collection 结构：
- jd_fulltext: 岗位全文 JD（去重后），按语义检索匹配岗位
- jd_premium: 大厂 + 高频岗位（子集），优先推荐给用户

依赖：chromadb, sentence-transformers, langchain
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from config import (
    CHROMA_CONFIG,
    EMBEDDING_CONFIG,
    PATH_CONFIG,
    BIG_TECH_COMPANIES,
    HIGH_FREQUENCY_THRESHOLD,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 工具函数（原来自 jd_crawler，岗位爬虫删除后内联）
# ──────────────────────────────────────────────
def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _clean_url(value: Any) -> str:
    return "".join(str(value or "").split())


def deduplicate_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按岗位 ID 去重，同平台去重 + 跨平台去重。

    跨平台去重策略：按「岗位名称 + 公司名 + 地点」组合判断。
    """
    seen_ids: set[str] = set()
    seen_cross: set[str] = set()
    result: list[dict[str, Any]] = []

    for job in jobs:
        job = dict(job)
        for field in ("job_id", "title", "company", "city", "url"):
            job[field] = _clean_url(job.get(field, "")) if field == "url" else _clean_text(job.get(field, ""))

        job_id = str(job.get("job_id", ""))
        # 同平台按 job_id 去重
        if job_id:
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

        # 跨平台按 (title, company, city) 组合去重
        cross_key = "|".join(
            [
                job["title"].lower(),
                job["company"].lower(),
                job["city"],
            ]
        )
        if cross_key != "||" and cross_key in seen_cross:
            continue
        seen_cross.add(cross_key)

        result.append(job)

    return result


def mark_premium_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """标记大厂（BAT/字节/华为等）和高频匹配岗位。"""
    for job in jobs:
        company = job.get("company", "")
        job["is_big_tech"] = any(big in company for big in BIG_TECH_COMPANIES)
        job["is_high_frequency"] = (
            job.get("match_count", 0) >= HIGH_FREQUENCY_THRESHOLD
        )
    return jobs


# ──────────────────────────────────────────────
# Embedding 封装（兼容 ChromaDB 的 EmbeddingFunction 协议）
# ──────────────────────────────────────────────
class BGEEmbeddingFunction:
    """基于 sentence-transformers 的 BGE 中文 Embedding。

    实现 ChromaDB 的 EmbeddingFunction 协议（__call__）。
    """

    def __init__(self, model_name: str, device: str = "cpu"):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise ImportError(
                "缺少依赖 sentence-transformers，请执行: "
                "pip install sentence-transformers"
            ) from e

        logger.info("加载 Embedding 模型: %s (device=%s)", model_name, device)
        self._model = SentenceTransformer(model_name, device=device)

    @staticmethod
    def name() -> str:
        """chromadb EmbeddingFunction 协议要求：返回该 embedding 函数名。"""
        return "bge-zh"

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        """将文本列表转为向量列表。"""
        # BGE 模型推荐对 query 加前缀，但入库文本不加；这里统一不加，检索时也不加
        embeddings = self._model.encode(
            input, normalize_embeddings=True, show_progress_bar=False
        )
        return embeddings.tolist()

    def embed_query(self, input: str | list[str]) -> list[float] | list[list[float]]:
        """chromadb query 时调用；入参可能是单个字符串或字符串列表。

        BGE 官方建议检索 query 加指令前缀（入库文档不加），可提升命中率。
        """
        texts = [input] if isinstance(input, str) else list(input)
        prefixed = ["为这个句子生成表示以用于检索相关文章：" + t for t in texts]
        return self(prefixed)


@lru_cache(maxsize=1)
def _get_embedding_function() -> BGEEmbeddingFunction:
    """获取 BGE Embedding 函数（单例缓存）。"""
    return BGEEmbeddingFunction(
        model_name=EMBEDDING_CONFIG["model_name"],
        device=EMBEDDING_CONFIG["device"],
    )


@lru_cache(maxsize=1)
def _get_chroma_client():
    """获取 ChromaDB 持久化客户端（单例缓存）。"""
    try:
        import chromadb
    except ImportError as e:
        raise ImportError("缺少依赖 chromadb，请执行: pip install chromadb") from e

    persist_dir = CHROMA_CONFIG["persist_directory"]
    Path(persist_dir).mkdir(parents=True, exist_ok=True)
    logger.info("初始化 ChromaDB: %s", persist_dir)
    return chromadb.PersistentClient(path=persist_dir)


def _get_collection(name: str):
    """获取或创建指定名称的 Collection。"""
    client = _get_chroma_client()
    return client.get_or_create_collection(
        name=name,
        embedding_function=_get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )


def build_jd_knowledge_base() -> None:
    """从爬取的 JSON 数据构建岗位知识库。

    流程：
    1. 读取爬取的岗位数据（data/raw 或 data/crawled_jobs）
    2. 去重
    3. 标记大厂（BAT/字节/华为/美团/京东等）
    4. 向量化存入 ChromaDB（按 JD 全文 + 技能标签）
    5. 建立关键词索引（按岗位名称、公司名、技能）
    """
    jobs = _load_jobs_from_disk()
    if not jobs:
        logger.warning("未找到任何岗位数据，知识库为空")
        return

    # 去重 + 标记
    jobs = deduplicate_jobs(jobs)
    jobs = mark_premium_jobs(jobs)

    # 全量写入（先清空再写入，适合重建场景）
    _upsert_jobs(jobs, clear_existing=True)
    logger.info("岗位知识库构建完成，共入库 %d 个岗位", len(jobs))


def init_kb() -> None:
    """初始化岗位知识库（兼容接口，等价于 build_jd_knowledge_base）。

    流程：
    1. 读取磁盘上爬取的岗位 JSON 数据
    2. 去重、标记大厂/高频岗位
    3. 全量写入 ChromaDB（fulltext + premium 两个 Collection）
    """
    build_jd_knowledge_base()


def add_jobs(jobs: list[dict[str, Any]]) -> int:
    """向知识库增量写入岗位数据（兼容接口，等价于 increment_update）。

    Args:
        jobs: 待写入的岗位列表

    Returns:
        实际新增（写入）的岗位数量
    """
    if not jobs:
        logger.info("add_jobs：无岗位数据，跳过")
        return 0

    jobs = mark_premium_jobs(jobs)
    collection = _get_collection(CHROMA_CONFIG["collection_fulltext"])
    existing_ids: set[str] = set()
    try:
        existing = collection.get()
        if existing and existing.get("ids"):
            existing_ids = set(existing["ids"])
    except Exception as e:  # noqa: BLE001
        logger.warning("查询已有岗位失败: %s", e)

    new_jobs = [
        job for job in jobs
        if str(job.get("job_id", "")) and str(job.get("job_id")) not in existing_ids
    ]
    if not new_jobs:
        logger.info("add_jobs：全部岗位已存在，无新增")
        return 0

    _upsert_jobs(new_jobs, clear_existing=False)
    logger.info("add_jobs：新增 %d 个岗位", len(new_jobs))
    return len(new_jobs)


def _load_jobs_from_disk() -> list[dict[str, Any]]:
    """从 data/raw 和 data/crawled_jobs 加载所有 JSON 岗位数据。"""
    jobs: list[dict[str, Any]] = []
    dirs = [PATH_CONFIG["raw_data_dir"], PATH_CONFIG["crawled_jobs_dir"]]

    for directory in dirs:
        dir_path = Path(directory)
        if not dir_path.exists():
            continue
        for json_file in dir_path.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    jobs.extend(data)
                elif isinstance(data, dict):
                    jobs.append(data)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("读取岗位文件失败 %s: %s", json_file, e)

    logger.info("从磁盘加载到 %d 个原始岗位", len(jobs))
    return jobs


def _job_to_document(job: dict[str, Any]) -> str:
    """将岗位字典拼接为用于向量化的文本文档。"""
    parts = [
        f"岗位：{job.get('title', '')}",
        f"公司：{job.get('company', '')}",
        f"城市：{job.get('city', '')}",
        f"薪资：{job.get('salary', '')}",
        f"经验：{job.get('experience', '')}",
        f"学历：{job.get('education', '')}",
        f"技能：{', '.join(job.get('skills', []))}",
        f"职位描述：{job.get('jd_text', '')}",
    ]
    return "\n".join(p for p in parts if p.split("：", 1)[-1].strip())


def _job_to_metadata(job: dict[str, Any]) -> dict[str, Any]:
    """提取岗位的 metadata（ChromaDB 只支持标量值）。"""
    return {
        "job_id": str(job.get("job_id", "")),
        "platform": str(job.get("platform", "")),
        "title": str(job.get("title", "")),
        "company": str(job.get("company", "")),
        "city": str(job.get("city", "")),
        "salary": str(job.get("salary", "")),
        "skills": ",".join(job.get("skills", [])),
        "is_big_tech": bool(job.get("is_big_tech", False)),
        "is_high_frequency": bool(job.get("is_high_frequency", False)),
        "match_count": int(job.get("match_count", 0)),
        "url": str(job.get("url", "")),
    }


def _upsert_jobs(jobs: list[dict[str, Any]], clear_existing: bool = False) -> None:
    """将岗位列表写入 ChromaDB。"""
    fulltext_col = _get_collection(CHROMA_CONFIG["collection_fulltext"])
    premium_col = _get_collection(CHROMA_CONFIG["collection_premium"])

    if clear_existing:
        # 清空重建（忽略空集合报错）
        for col in (fulltext_col, premium_col):
            try:
                existing = col.get()
                if existing and existing.get("ids"):
                    col.delete(ids=existing["ids"])
            except Exception as e:  # noqa: BLE001
                logger.warning("清空 Collection 失败: %s", e)

    ids, documents, metadatas = [], [], []
    premium_ids, premium_docs, premium_metas = [], [], []

    for job in jobs:
        job_id = str(job.get("job_id") or f"{job.get('platform')}_{job.get('title')}_{job.get('company')}")
        doc = _job_to_document(job)
        meta = _job_to_metadata(job)
        if not doc.strip():
            continue

        ids.append(job_id)
        documents.append(doc)
        metadatas.append(meta)

        # 大厂或高频岗位进入 premium 集合
        if meta["is_big_tech"] or meta["is_high_frequency"]:
            premium_ids.append(job_id)
            premium_docs.append(doc)
            premium_metas.append(meta)

    if ids:
        fulltext_col.upsert(ids=ids, documents=documents, metadatas=metadatas)
    if premium_ids:
        premium_col.upsert(ids=premium_ids, documents=premium_docs, metadatas=premium_metas)

    logger.info("写入 fulltext %d 条，premium %d 条", len(ids), len(premium_ids))


def search_jds(
    query: str, top_k: int = 10, filter_big_tech: bool = False
) -> list[dict[str, Any]]:
    """检索岗位知识库，返回最匹配的岗位列表。

    Args:
        query: 检索关键词/技能/岗位名
        top_k: 返回数量
        filter_big_tech: 是否只返回大厂岗位

    Returns:
        匹配的岗位字典列表（按相关度排序）
    """
    try:
        collection = _get_collection(
            CHROMA_CONFIG["collection_premium"] if filter_big_tech
            else CHROMA_CONFIG["collection_fulltext"]
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("知识库不可用（缺 chromadb/embedding 依赖）: %s", e)
        return []

    where_filter = {"is_big_tech": True} if filter_big_tech else None

    try:
        results = collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where_filter,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("岗位检索失败: %s", e)
        return []

    return _format_query_results(results)


def _format_query_results(results: dict[str, Any]) -> list[dict[str, Any]]:
    """将 ChromaDB query 结果转为岗位字典列表。"""
    jobs: list[dict[str, Any]] = []
    if not results or not results.get("ids"):
        return jobs

    ids = results["ids"][0]
    metadatas = results.get("metadatas", [[]])[0]
    documents = results.get("documents", [[]])[0]
    distances = results.get("distances", [[]])[0]

    for idx, job_id in enumerate(ids):
        meta = metadatas[idx] if idx < len(metadatas) else {}
        job = dict(meta)
        job["job_id"] = job_id
        job["jd_text"] = documents[idx] if idx < len(documents) else ""
        if idx < len(distances):
            job["score"] = 1 - distances[idx]  # cosine 距离转相似度
        jobs.append(job)

    return jobs


def get_premium_jobs(limit: int = 50) -> list[dict[str, Any]]:
    """获取大厂和高频匹配岗位。

    Args:
        limit: 返回数量上限

    Returns:
        优质岗位列表（大厂 + 高频）
    """
    try:
        collection = _get_collection(CHROMA_CONFIG["collection_premium"])
    except Exception as e:  # noqa: BLE001
        logger.warning("知识库不可用（缺 chromadb/embedding 依赖）: %s", e)
        return []
    try:
        results = collection.get(limit=limit)
    except Exception as e:  # noqa: BLE001
        logger.warning("获取优质岗位失败: %s", e)
        return []

    jobs: list[dict[str, Any]] = []
    if not results or not results.get("ids"):
        return jobs

    ids = results["ids"]
    metadatas = results.get("metadatas", [])
    documents = results.get("documents", [])

    for idx, job_id in enumerate(ids):
        meta = metadatas[idx] if idx < len(metadatas) else {}
        job = dict(meta)
        job["job_id"] = job_id
        job["jd_text"] = documents[idx] if idx < len(documents) else ""
        jobs.append(job)

    return jobs


def increment_update(jobs: list[dict[str, Any]]) -> None:
    """增量更新知识库，按 job_id 去重。

    Args:
        jobs: 新爬取的岗位列表
    """
    if not jobs:
        logger.info("增量更新：无新岗位")
        return

    jobs = mark_premium_jobs(jobs)

    collection = _get_collection(CHROMA_CONFIG["collection_fulltext"])
    existing_ids = set()
    try:
        existing = collection.get()
        if existing and existing.get("ids"):
            existing_ids = set(existing["ids"])
    except Exception as e:  # noqa: BLE001
        logger.warning("查询已有岗位失败: %s", e)

    new_jobs = [
        job for job in jobs
        if str(job.get("job_id", "")) and str(job.get("job_id")) not in existing_ids
    ]

    if not new_jobs:
        logger.info("增量更新：无新增岗位（全部已存在）")
        return

    _upsert_jobs(new_jobs, clear_existing=False)
    logger.info("增量更新完成，新增 %d 个岗位", len(new_jobs))


def get_job_by_id(job_id: str) -> dict[str, Any] | None:
    """按 job_id 从知识库获取单个岗位全文。"""
    try:
        collection = _get_collection(CHROMA_CONFIG["collection_fulltext"])
    except Exception as e:  # noqa: BLE001
        logger.warning("知识库不可用（缺 chromadb/embedding 依赖）: %s", e)
        return None
    try:
        results = collection.get(ids=[job_id])
    except Exception as e:  # noqa: BLE001
        logger.warning("按 ID 获取岗位失败: %s", e)
        return None

    if not results or not results.get("ids"):
        return None

    meta = results.get("metadatas", [{}])[0] or {}
    job = dict(meta)
    job["job_id"] = job_id
    docs = results.get("documents", [])
    job["jd_text"] = docs[0] if docs else ""
    return job


if __name__ == "__main__":
    print("jd_knowledge_base 模块自测")
    # build_jd_knowledge_base()
    # print(search_jds("Python 后端", top_k=5))
