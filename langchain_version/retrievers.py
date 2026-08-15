"""
检索层 LangChain Retriever 抽象

把现有手写检索链路（标题索引 → 阈值过滤 → 关键词兜底 → Rerank 精排）
包成标准 `BaseRetriever`，供 Agent 工具通过 `retriever.invoke()` 调用，
替代直接调用 search_questions / search_jds 裸函数。

设计要点：
- 内部链路完全复用现有实现，只做标准接口化（薄封装）；
- 返回 Document，metadata 透传原始 dict 字段（前端依赖 question /
  reference_answer / key_points 等不变）；
- 懒加载 + 单例：模型/集合在首次检索时才初始化（与现有按需加载一致）。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever


class InterviewKBRetriever(BaseRetriever):
    """面试/笔试经验知识库检索器（封装 interview_knowledge_base.search_questions）。"""

    top_k: int = 5
    max_distance: float = 0.6

    def _get_relevant_documents(
        self, query: str, *, run_manager: Any = None, **kwargs: Any
    ) -> list[Document]:
        from interview_knowledge_base import search_questions

        hits = search_questions(
            query, top_k=self.top_k, max_distance=self.max_distance
        )
        return [
            Document(page_content=q.get("question", ""), metadata=q)
            for q in hits
        ]


class JDKBRetriever(BaseRetriever):
    """岗位知识库检索器（封装 jd_knowledge_base.search_jds）。"""

    top_k: int = 10
    filter_big_tech: bool = False

    def _get_relevant_documents(
        self, query: str, *, run_manager: Any = None, **kwargs: Any
    ) -> list[Document]:
        from jd_knowledge_base import search_jds

        jobs = search_jds(
            query, top_k=self.top_k, filter_big_tech=self.filter_big_tech
        )
        return [
            Document(
                page_content=j.get("jd_text") or j.get("title", ""),
                metadata=j,
            )
            for j in jobs
        ]


@lru_cache(maxsize=1)
def get_interview_retriever(top_k: int = 5, max_distance: float = 0.6) -> InterviewKBRetriever:
    """获取面试题库检索器（单例）。"""
    return InterviewKBRetriever(top_k=top_k, max_distance=max_distance)


@lru_cache(maxsize=1)
def get_jd_retriever(top_k: int = 10, filter_big_tech: bool = False) -> JDKBRetriever:
    """获取岗位知识库检索器（单例）。"""
    return JDKBRetriever(top_k=top_k, filter_big_tech=filter_big_tech)
