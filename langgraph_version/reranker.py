"""Rerank 重排模块（bge-reranker-v2-m3 跨编码器精排）。

用法：检索函数先按向量粗召回 top_k*multiplier 条候选，
再调用 `rerank(query, docs, top_k)` 对 (query, doc) 逐对打分重排，
返回 [(原下标, 分数)] 降序列表，调用方按此顺序取前 top_k。

特性：
- 懒加载 + lru_cache：首次调用才加载模型；加载失败后缓存 None，不再重试；
- 优雅降级：模型加载失败 / 打分失败时返回空列表，调用方按向量原序返回，
  不影响检索功能；
- 测试环境通过 RERANK_ENABLED=0 跳过模型加载（tests/conftest.py 已设置）。
"""

from __future__ import annotations

import logging
from functools import lru_cache

from config import RERANK_CONFIG

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_reranker():
    """懒加载 CrossEncoder 模型（进程内单例）；失败返回 None 并缓存。"""
    if not RERANK_CONFIG["enabled"]:
        return None
    try:
        from sentence_transformers import CrossEncoder

        model = CrossEncoder(
            RERANK_CONFIG["model_name"],
            device=RERANK_CONFIG["device"],
        )
        logger.info(
            "Rerank 模型加载成功: %s (device=%s)",
            RERANK_CONFIG["model_name"],
            RERANK_CONFIG["device"],
        )
        return model
    except Exception as e:  # noqa: BLE001
        logger.warning("Rerank 模型加载失败（自动降级为不重排）: %s", e)
        return None


def rerank(query: str, docs: list[str], top_k: int) -> list[tuple[int, float]]:
    """对 (query, doc) 打分并降序返回 [(原下标, 分数)]，取前 top_k。

    模型不可用 / 打分失败时返回空列表（调用方保持原序返回）。
    """
    if not docs or top_k <= 0:
        return []
    model = _load_reranker()
    if model is None:
        return []
    try:
        # 截断超长文档（如完整 JD），避免长序列拖慢打分
        pairs = [(query, doc[:5000]) for doc in docs]
        scores = model.predict(pairs)
        # CrossEncoder 返回 numpy 标量，转原生 float（否则 pydantic/JSON 序列化报错）
        scores = [float(s) for s in scores]
        ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)
        return ranked[:top_k]
    except Exception as e:  # noqa: BLE001
        logger.warning("Rerank 打分失败（自动降级为不重排）: %s", e)
        return []
