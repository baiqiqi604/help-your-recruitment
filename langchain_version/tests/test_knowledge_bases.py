"""interview_knowledge_base / jd_knowledge_base 的真实检索测试。

conftest 默认把这两个模块整体桩掉（避免依赖真实 ChromaDB/模型），
本文件在模块作用域内把桩替换为真实模块，并注入：
  - 临时目录的 ChromaDB PersistentClient（无需联网/模型）
  - 确定性 hash embedding（字符 bigram → 512 维归一化向量）
从而真正覆盖：写入去重、语义检索、阈值过滤、关键词兜底、company/algorithm 筛选、
clear/统计，以及岗位库的 premium 标记与检索。测试结束后还原 conftest 桩。
"""

from __future__ import annotations

import hashlib
import math
import re
import sys
from typing import Any
from unittest import mock

import pytest

_STUB_MODULES = ("interview_knowledge_base", "jd_knowledge_base")

SAMPLE_ITEMS: list[dict[str, Any]] = [
    {
        "company": "某公司",
        "role": "Python后端",
        "stage": "专业面",
        "question_type": "面试问答",
        "question": "Python 中 GIL 是什么？",
        "key_points": ["GIL", "多线程"],
        "reference_answer": "GIL 是 CPython 的全局解释器锁，限制了多线程并行执行 Python 字节码。",
        "quality": 4,
        "is_algorithm": False,
        "source": "manual",
        "source_url": "",
        "collected_at": "2026-08-13",
    },
    {
        "company": "某公司",
        "role": "Python后端",
        "stage": "笔试",
        "question_type": "手撕代码",
        "question": "实现一个 LRU 缓存",
        "key_points": ["LRU", "缓存"],
        "reference_answer": (
            "使用 OrderedDict：get 时把 key 移到末尾，put 时插入末尾并淘汰队首，"
            "保证 get/put 均为 O(1) 复杂度，容量满时移除最久未使用的条目。"
        ),
        "quality": 5,
        "is_algorithm": True,
        "source": "manual",
        "source_url": "",
        "collected_at": "2026-08-13",
    },
    {
        "company": "另一家公司",
        "role": "前端",
        "stage": "业务面",
        "question_type": "面试问答",
        "question": "如何做前端性能优化？",
        "key_points": ["性能", "优化"],
        "reference_answer": "从资源加载、渲染路径、缓存三个层面回答。",
        "quality": 3,
        "is_algorithm": False,
        "source": "manual",
        "source_url": "",
        "collected_at": "2026-08-13",
    },
]

SAMPLE_JOBS: list[dict[str, Any]] = [
    {
        "job_id": "jd_1",
        "platform": "boss",
        "title": "Python后端开发",
        "company": "腾讯",
        "city": "深圳",
        "salary": "30k",
        "experience": "3-5年",
        "education": "本科",
        "skills": ["Python", "Django"],
        "jd_text": "负责 Python 后端服务开发，熟悉 Django/MySQL/Redis",
        "match_count": 6,
        "url": "",
    },
    {
        "job_id": "jd_2",
        "platform": "boss",
        "title": "前端工程师",
        "company": "某小厂",
        "city": "北京",
        "salary": "20k",
        "experience": "1-3年",
        "education": "本科",
        "skills": ["JavaScript"],
        "jd_text": "负责前端页面开发",
        "match_count": 1,
        "url": "",
    },
]


class DeterministicEmbedding:
    """字符 bigram 哈希向量：文本共享子串越多，cosine 相似度越高（可复现）。"""

    DIM = 512

    @staticmethod
    def name() -> str:
        return "deterministic-test"

    @staticmethod
    def _vectors(texts: list[str]) -> list[list[float]]:
        vecs: list[list[float]] = []
        for text in texts:
            vec = [0.0] * DeterministicEmbedding.DIM
            compact = re.sub(r"\s+", "", text or "")
            for i in range(len(compact) - 1):
                idx = int(
                    hashlib.md5(compact[i : i + 2].encode("utf-8")).hexdigest(), 16
                ) % DeterministicEmbedding.DIM
                vec[idx] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vecs.append([v / norm for v in vec])
        return vecs

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        return self._vectors(input)

    def embed_query(self, input: str | list[str]) -> list[float] | list[list[float]]:
        texts = [input] if isinstance(input, str) else list(input)
        result = self._vectors(texts)
        return result[0] if isinstance(input, str) else result


@pytest.fixture(scope="module")
def kb_modules(tmp_path_factory):
    """把 conftest 的 KB 桩换成真实模块（仅本文件生效），结束后还原。"""
    stubs = {name: sys.modules.get(name) for name in _STUB_MODULES}
    for name in _STUB_MODULES:
        sys.modules.pop(name, None)
    try:
        import interview_knowledge_base  # noqa: F401
        import jd_knowledge_base  # noqa: F401
    finally:
        pass
    yield {"interview": interview_knowledge_base, "jd": jd_knowledge_base}
    for name, stub in stubs.items():
        if stub is not None:
            sys.modules[name] = stub
        else:
            sys.modules.pop(name, None)


@pytest.fixture(scope="module")
def chroma_env(kb_modules, tmp_path_factory):
    """临时 ChromaDB + 确定性 embedding，替换两个模块的 client/embedding 单例。"""
    import chromadb
    from chromadb.config import Settings

    client = chromadb.PersistentClient(
        path=str(tmp_path_factory.mktemp("chroma")),
        settings=Settings(anonymized_telemetry=False),
    )
    embed = DeterministicEmbedding()
    patches = [
        mock.patch.object(kb_modules["jd"], "_get_chroma_client", lambda: client),
        mock.patch.object(kb_modules["jd"], "_get_embedding_function", lambda: embed),
        mock.patch.object(kb_modules["interview"], "_get_chroma_client", lambda: client),
        mock.patch.object(kb_modules["interview"], "_get_embedding_function", lambda: embed),
    ]
    for p in patches:
        p.start()
    yield {"client": client, "embed": embed}
    for p in patches:
        p.stop()
    kb_modules["interview"]._get_interview_collection.cache_clear()


# ──────────────────────────────────────────────
# interview_knowledge_base：写入 / 统计 / 检索
# ──────────────────────────────────────────────
class TestInterviewKb:
    def test_add_and_count(self, kb_modules, chroma_env) -> None:
        kb = kb_modules["interview"]
        assert kb.add_experiences(SAMPLE_ITEMS) == 3
        assert kb.count_questions() == 3

    def test_add_is_idempotent(self, kb_modules, chroma_env) -> None:
        kb = kb_modules["interview"]
        kb.add_experiences(SAMPLE_ITEMS)
        assert kb.add_experiences(SAMPLE_ITEMS) == 0
        assert kb.count_questions() == 3

    def test_add_skips_blank_question(self, kb_modules, chroma_env) -> None:
        kb = kb_modules["interview"]
        added = kb.add_experiences([{"question": "   ", "company": "某公司"}])
        assert added == 0

    def test_search_hit_returns_structured_item(self, kb_modules, chroma_env) -> None:
        kb = kb_modules["interview"]
        kb.add_experiences(SAMPLE_ITEMS)
        results = kb.search_questions("GIL 是什么", top_k=3)
        assert results
        assert "GIL" in results[0]["question"]
        # 长文档 + 短查询的向量距离必然偏高，命中由关键词兜底保证；阈值过滤见
        # test_search_vector_hit_passes_threshold（短文档场景）
        assert "distance" in results[0]
        assert "key_points" in results[0] and "reference_answer" in results[0]

    def test_search_empty_query_returns_empty(self, kb_modules, chroma_env) -> None:
        kb = kb_modules["interview"]
        assert kb.search_questions("") == []
        assert kb.search_questions("   ") == []

    def test_search_unrelated_query_returns_empty(self, kb_modules, chroma_env) -> None:
        kb = kb_modules["interview"]
        kb.add_experiences(SAMPLE_ITEMS)
        # 向量不命中 + 关键词兜底也不命中
        assert kb.search_questions("完全不相关的内容", top_k=3) == []

    def test_search_keyword_fallback_recovers_short_token(self, kb_modules, chroma_env) -> None:
        kb = kb_modules["interview"]
        kb.add_experiences(SAMPLE_ITEMS)
        # "LRU" 在长文档中向量相似度不足（distance>0.6），应被关键词兜底召回
        results = kb.search_questions("LRU", top_k=3)
        assert results
        assert "LRU" in results[0]["question"]

    def test_search_company_filter(self, kb_modules, chroma_env) -> None:
        kb = kb_modules["interview"]
        kb.add_experiences(SAMPLE_ITEMS)
        results = kb.search_questions("前端性能优化", company="另一家公司", top_k=3)
        assert results
        assert all(r["company"] == "另一家公司" for r in results)

    def test_get_questions_by_company(self, kb_modules, chroma_env) -> None:
        kb = kb_modules["interview"]
        kb.add_experiences(SAMPLE_ITEMS)
        results = kb.get_questions_by_company("另一家公司")
        assert len(results) == 1
        assert results[0]["company"] == "另一家公司"
        assert kb.get_questions_by_company("   ") == []

    def test_get_algorithm_questions(self, kb_modules, chroma_env) -> None:
        kb = kb_modules["interview"]
        kb.add_experiences(SAMPLE_ITEMS)
        results = kb.get_algorithm_questions()
        assert len(results) == 1
        assert results[0]["is_algorithm"] is True
        assert "LRU" in results[0]["question"]

    def test_clear_interview_kb(self, kb_modules, chroma_env) -> None:
        kb = kb_modules["interview"]
        kb.add_experiences(SAMPLE_ITEMS)
        assert kb.clear_interview_kb() == 3
        assert kb.count_questions() == 0
        # 已空时再次清空返回 0
        assert kb.clear_interview_kb() == 0

    def test_search_vector_hit_passes_threshold(self, kb_modules, chroma_env) -> None:
        """短文档场景：查询与文档 bigram 高度重合，向量命中且 distance <= 0.6。"""
        kb = kb_modules["interview"]
        # 只提供 question 字段 → _to_document 输出短文档，向量距离可信
        short_item = {
            "question": "Redis 缓存策略",
            "key_points": [],
            "reference_answer": "",
        }
        kb.add_experiences([short_item])
        results = kb.search_questions("Redis 缓存策略", top_k=3)
        assert results
        assert results[0]["question"] == "Redis 缓存策略"
        assert results[0]["distance"] <= 0.6


# ──────────────────────────────────────────────
# interview_knowledge_base：纯函数（无 ChromaDB）
# ──────────────────────────────────────────────
class TestInterviewKbPure:
    def test_extract_keywords(self, kb_modules) -> None:
        kb = kb_modules["interview"]
        assert kb._extract_keywords("Python GIL 是什么？") == ["Python", "GIL", "是什么"]
        assert kb._extract_keywords("") == []
        assert kb._extract_keywords("AI Agent 工程师", max_kw=2) == ["AI", "Agent"]

    def test_extract_field(self, kb_modules) -> None:
        kb = kb_modules["interview"]
        doc = "公司：某公司\n题目：什么是 RAG？\n考察点：RAG, 检索\n参考思路：先检索后生成"
        assert kb._extract_field(doc, "题目") == "什么是 RAG？"
        assert kb._extract_field(doc, "参考思路") == "先检索后生成"
        assert kb._extract_list_field(doc, "考察点") == ["RAG", "检索"]
        assert kb._extract_field(doc, "不存在的标签") == ""

    def test_question_id_stable(self, kb_modules) -> None:
        kb = kb_modules["interview"]
        item = {"company": "某公司", "role": "Python后端", "question": "GIL 是什么"}
        assert kb._question_id(item) == kb._question_id(dict(item))


# ──────────────────────────────────────────────
# jd_knowledge_base：纯函数（去重 / premium 标记）
# ──────────────────────────────────────────────
class TestJdKbPure:
    def test_deduplicate_jobs(self, kb_modules) -> None:
        jdkb = kb_modules["jd"]
        jobs = [
            {"job_id": "a", "title": "Python", "company": "腾讯", "city": "深圳", "url": "x"},
            {"job_id": "a", "title": "Python", "company": "腾讯", "city": "深圳", "url": "y"},  # 同 ID
            {"job_id": "b", "title": "Python", "company": "腾讯", "city": "深圳", "url": "z"},  # 跨平台同组合
            {"job_id": "", "title": "", "company": "", "city": "", "url": ""},  # 空记录保留
        ]
        result = jdkb.deduplicate_jobs(jobs)
        assert len(result) == 2
        assert result[0]["job_id"] == "a"
        assert result[1]["job_id"] == ""

    def test_mark_premium_jobs(self, kb_modules) -> None:
        jdkb = kb_modules["jd"]
        jobs = [
            {"company": "腾讯科技", "match_count": 6},
            {"company": "某小厂", "match_count": 3},
            {"company": "某中厂", "match_count": 5},
        ]
        marked = jdkb.mark_premium_jobs(jobs)
        assert marked[0]["is_big_tech"] is True
        assert marked[0]["is_high_frequency"] is True
        assert marked[1]["is_big_tech"] is False
        assert marked[1]["is_high_frequency"] is False
        assert marked[2]["is_big_tech"] is False
        assert marked[2]["is_high_frequency"] is True


# ──────────────────────────────────────────────
# jd_knowledge_base：真实 ChromaDB 写入 / 检索
# ──────────────────────────────────────────────
class TestJdKb:
    def test_add_jobs_and_search(self, kb_modules, chroma_env) -> None:
        jdkb = kb_modules["jd"]
        assert jdkb.add_jobs(SAMPLE_JOBS) == 2
        assert jdkb.add_jobs(SAMPLE_JOBS) == 0  # 幂等

        results = jdkb.search_jds("Python 后端", top_k=5)
        assert results
        assert results[0]["job_id"] == "jd_1"
        assert "jd_text" in results[0] and "score" in results[0]

    def test_get_job_by_id(self, kb_modules, chroma_env) -> None:
        jdkb = kb_modules["jd"]
        jdkb.add_jobs(SAMPLE_JOBS)
        job = jdkb.get_job_by_id("jd_1")
        assert job is not None
        assert job["company"] == "腾讯"
        assert "Python" in job["jd_text"]
        assert jdkb.get_job_by_id("not_exists") is None

    def test_premium_jobs_and_big_tech_filter(self, kb_modules, chroma_env) -> None:
        jdkb = kb_modules["jd"]
        jdkb.add_jobs(SAMPLE_JOBS)
        premium = jdkb.get_premium_jobs(limit=10)
        assert [j["job_id"] for j in premium] == ["jd_1"]  # 腾讯 + match_count>=5

        big_tech = jdkb.search_jds("开发", top_k=5, filter_big_tech=True)
        assert big_tech
        assert all(j["is_big_tech"] for j in big_tech)
        assert {j["job_id"] for j in big_tech} == {"jd_1"}

    def test_increment_update_adds_only_new(self, kb_modules, chroma_env) -> None:
        jdkb = kb_modules["jd"]
        jdkb.add_jobs(SAMPLE_JOBS)
        new_job = {
            "job_id": "jd_3",
            "platform": "boss",
            "title": "测试工程师",
            "company": "某测试公司",
            "city": "上海",
            "salary": "25k",
            "skills": ["pytest"],
            "jd_text": "负责测试平台建设",
            "match_count": 1,
            "url": "",
        }
        jdkb.increment_update([new_job])
        assert jdkb.get_job_by_id("jd_3") is not None
        # 已存在的岗位不重复写入
        jdkb.increment_update([SAMPLE_JOBS[0]])
        assert jdkb.get_job_by_id("jd_1")["company"] == "腾讯"

    def test_job_document_and_metadata(self, kb_modules) -> None:
        jdkb = kb_modules["jd"]
        # 注意：SAMPLE_JOBS 会被 add_jobs→mark_premium_jobs 原地修改，
        # 这里用全新字面量验证未标记状态
        job = {
            "job_id": "jd_x",
            "platform": "boss",
            "title": "后端开发",
            "company": "某中厂",
            "city": "深圳",
            "skills": ["Python"],
            "jd_text": "负责后端服务",
            "match_count": 6,
            "url": "",
        }
        doc = jdkb._job_to_document(job)
        assert "后端开发" in doc and "某中厂" in doc
        meta = jdkb._job_to_metadata(job)
        assert meta["job_id"] == "jd_x"
        assert meta["is_big_tech"] is False  # 未标记前为 False
        assert meta["match_count"] == 6
