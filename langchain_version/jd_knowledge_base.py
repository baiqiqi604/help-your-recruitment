"""
岗位知识库模块（ChromaDB + sentence-transformers BGE）

职责：
1. 用 sentence-transformers 加载 BGE 中文 Embedding 模型
2. 实现 BGEEmbeddingFunction，兼容 ChromaDB EmbeddingFunction 协议
3. 岗位全文检索 / 优质岗位（大厂 + 高频）/ 按 id 查询

依赖：chromadb、sentence-transformers
"""

from __future__ import annotations

import hashlib
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from config import (
    BIG_TECH_COMPANIES,
    CHROMA_CONFIG,
    EMBEDDING_CONFIG,
    HIGH_FREQUENCY_THRESHOLD,
)

logger = logging.getLogger(__name__)

# ChromaDB 类型（兼容不同版本，失败时退化为本地最小协议）
try:  # pragma: no cover
    from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
except Exception:  # pragma: no cover
    Documents = list  # type: ignore[assignment,misc]
    Embeddings = list  # type: ignore[assignment,misc]

    class EmbeddingFunction:  # type: ignore[no-redef]
        """最小 EmbeddingFunction 协议兜底实现。"""

        def __call__(self, input: Documents) -> Embeddings:  # pragma: no cover
            raise NotImplementedError


# ──────────────────────────────────────────────
# BGE Embedding 封装
# ──────────────────────────────────────────────
class BGEEmbeddingFunction(EmbeddingFunction):
    """BGE 中文 Embedding，兼容 ChromaDB EmbeddingFunction 协议。

    基于 sentence-transformers 的 BAAI/bge-large-zh-v1.5 模型，
    输出归一化向量（配合余弦相似度检索）。
    """

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
    ) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name or EMBEDDING_CONFIG["model_name"]
        self.device = device or EMBEDDING_CONFIG["device"]
        logger.info("加载 Embedding 模型: %s (device=%s)", self.model_name, self.device)
        self._model = SentenceTransformer(self.model_name, device=self.device)
        # BGE 系列官方建议在检索/查询侧加上指令前缀
        self.query_prefix = "为这个句子生成表示以用于检索相关文章："

    def __call__(self, input: Documents) -> Embeddings:
        """将文本列表编码为向量列表（ChromaDB 回调入口）。"""
        texts = list(input)
        if not texts:
            return []
        vectors = self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vectors.tolist()


# ──────────────────────────────────────────────
# ChromaDB 客户端与集合（懒初始化）
# ──────────────────────────────────────────────
_db_client: Any = None
_fulltext_collection: Any = None
_premium_collection: Any = None
_embed_fn: BGEEmbeddingFunction | None = None
_kb_available: bool = True  # 缺 chromadb / embedding 模型时置 False，查询返回空


def init_kb() -> None:
    """初始化 ChromaDB 客户端与集合（幂等，可重复调用）。

    依赖缺失（chromadb / embedding 模型）时不抛异常，
    记 warning 并将知识库标记为不可用，查询接口降级返回空。
    """
    global _db_client, _fulltext_collection, _premium_collection, _embed_fn, _kb_available
    if _db_client is not None:
        return

    try:
        import chromadb
    except ImportError as e:
        logger.warning("缺少依赖 chromadb，知识库功能不可用: %s", e)
        _kb_available = False
        return

    persist_dir = CHROMA_CONFIG["persist_directory"]
    Path(persist_dir).mkdir(parents=True, exist_ok=True)

    try:
        _embed_fn = BGEEmbeddingFunction()
    except Exception as e:  # noqa: BLE001
        logger.warning("Embedding 模型加载失败，知识库功能不可用: %s", e)
        _kb_available = False
        return

    _db_client = chromadb.PersistentClient(path=persist_dir)

    _fulltext_collection = _db_client.get_or_create_collection(
        name=CHROMA_CONFIG["collection_fulltext"],
        embedding_function=_embed_fn,
        metadata={"hnsw:space": "cosine"},
    )
    _premium_collection = _db_client.get_or_create_collection(
        name=CHROMA_CONFIG["collection_premium"],
        embedding_function=_embed_fn,
        metadata={"hnsw:space": "cosine"},
    )
    logger.info("知识库初始化完成: %s", persist_dir)


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────
def _job_key(job: dict[str, Any]) -> str:
    """岗位去重键：标题 + 公司 + 城市。"""
    return f"{job.get('title')}|{job.get('company')}|{job.get('city')}"


def _make_id(job: dict[str, Any]) -> str:
    """为缺少 id 的岗位生成稳定 id。"""
    raw = f"{job.get('title')}|{job.get('company')}|{job.get('city')}|{job.get('jd_text', '')}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _exists(job_id: str) -> bool:
    """判断岗位 id 是否已存在于全文集合。"""
    result = _fulltext_collection.get(ids=[job_id])
    return bool(result.get("ids"))


def _is_premium(job: dict[str, Any], freq: int) -> bool:
    """判断岗位是否优质：公司命中大厂名单，或出现频次达阈值。"""
    company = str(job.get("company") or "")
    if any(keyword in company for keyword in BIG_TECH_COMPANIES):
        return True
    return freq >= HIGH_FREQUENCY_THRESHOLD


def _to_job_item(job_id: str, meta: dict[str, Any], jd_text: str) -> dict[str, Any]:
    """拼装对外返回的岗位字典。"""
    item = dict(meta or {})
    item["id"] = job_id
    item["jd_text"] = jd_text
    return item


# ──────────────────────────────────────────────
# 核心接口
# ──────────────────────────────────────────────
def add_jobs(jobs: list[dict[str, Any]]) -> int:
    """将岗位批量写入知识库。

    去重规则：
    - 入参内按 id（或 标题|公司|城市 键）去重
    - 与库中已有 id 去重，已存在则跳过

    优质标记（premium）：公司命中 config.BIG_TECH_COMPANIES，
    或同一岗位在入参中出现频次 >= config.HIGH_FREQUENCY_THRESHOLD。

    Args:
        jobs: 岗位列表（字段见 jd_crawler.crawl_jobs 返回结构）

    Returns:
        实际新增的岗位数量
    """
    if not jobs:
        return 0
    init_kb()

    # 本地去重
    seen_local: set[str] = set()
    uniq_jobs: list[dict[str, Any]] = []
    for job in jobs:
        job_id = str(job.get("id") or _make_id(job))
        if job_id in seen_local:
            continue
        seen_local.add(job_id)
        uniq_jobs.append({**job, "id": job_id})

    # 统计频次（用于高频标记）
    freq: dict[str, int] = {}
    for job in uniq_jobs:
        key = _job_key(job)
        freq[key] = freq.get(key, 0) + 1

    added = 0
    for job in uniq_jobs:
        job_id = str(job["id"])
        if _exists(job_id):
            continue
        jd_text = str(job.get("jd_text") or "").strip()
        if not jd_text:
            continue

        premium = _is_premium(job, freq.get(_job_key(job), 1))
        meta = {
            "id": job_id,
            "title": str(job.get("title") or ""),
            "company": str(job.get("company") or ""),
            "city": str(job.get("city") or ""),
            "salary": str(job.get("salary") or ""),
            "url": str(job.get("url") or ""),
            "platform": str(job.get("platform") or ""),
            "crawled_at": str(job.get("crawled_at") or ""),
            "premium": premium,
        }
        _fulltext_collection.add(ids=[job_id], documents=[jd_text], metadatas=[meta])
        if premium:
            _premium_collection.add(ids=[job_id], documents=[jd_text], metadatas=[meta])
        added += 1

    logger.info("知识库新增 %d 个岗位（去重后共 %d 个待写入）", added, len(uniq_jobs))
    return added


def search_jds(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """按语义相似度在全文集合中检索岗位。

    Returns:
        [{id, title, company, city, salary, jd_text, url, platform,
          crawled_at, premium, score}, ...]，score 为余弦相似度
    """
    if not query or not query.strip():
        return []
    init_kb()

    try:
        result = _fulltext_collection.query(
            query_texts=[query],
            n_results=min(max(top_k, 1), 50),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("知识库检索失败: %s", e)
        return []

    ids = (result.get("ids") or [[]])[0]
    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]

    jobs: list[dict[str, Any]] = []
    for i, job_id in enumerate(ids or []):
        meta = dict(metas[i] or {})
        dist = distances[i] if i < len(distances or []) else None
        item = _to_job_item(job_id, meta, docs[i] if i < len(docs or []) else "")
        item["score"] = round(1.0 - float(dist), 4) if dist is not None else None
        jobs.append(item)
    return jobs


def get_job_by_id(job_id: str) -> dict[str, Any] | None:
    """按 id 获取岗位详情（含 jd_text）。

    Returns:
        岗位字典；不存在时返回 None
    """
    if not job_id:
        return None
    init_kb()
    if not _kb_available:
        return None

    result = _fulltext_collection.get(
        ids=[job_id], include=["documents", "metadatas"]
    )
    ids = result.get("ids") or []
    if not ids:
        return None

    meta = dict((result.get("metadatas") or [{}])[0] or {})
    jd_text = (result.get("documents") or [""])[0]
    return _to_job_item(ids[0], meta, jd_text or "")


def get_premium_jobs(limit: int = 20) -> list[dict[str, Any]]:
    """获取优质岗位列表（大厂 + 高频岗位）。

    Returns:
        [{id, title, company, city, salary, jd_text, url, platform,
          crawled_at, premium}, ...]
    """
    init_kb()
    if not _kb_available:
        return []

    result = _premium_collection.get(
        include=["documents", "metadatas"], limit=max(limit, 1)
    )
    ids = result.get("ids") or []
    docs = result.get("documents") or []
    metas = result.get("metadatas") or []

    jobs = [
        _to_job_item(job_id, metas[i] or {}, docs[i] if i < len(docs) else "")
        for i, job_id in enumerate(ids)
    ]
    return jobs


@lru_cache(maxsize=1)
def _count_jobs() -> int:
    """知识库岗位总数（缓存版，供状态展示用）。"""
    init_kb()
    if not _kb_available:
        return 0
    return _fulltext_collection.count()


def count_jobs() -> int:
    """获取知识库岗位总数。"""
    return _count_jobs()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sample_job = {
        "title": "Python 后端开发工程师",
        "company": "字节跳动",
        "city": "北京",
        "salary": "30-50K",
        "jd_text": "负责电商中台服务端研发，熟悉 Python/Django，熟悉 MySQL、Redis。",
        "url": "https://example.com/job/1",
        "platform": "boss",
        "crawled_at": "2025-01-01T00:00:00",
    }
    print("新增:", add_jobs([sample_job]))
    print("检索:", search_jds("Python 后端 北京", top_k=3))
    print("优质:", get_premium_jobs(limit=5))
