"""FastAPI Web 接口的确定性测试（MOCK_LLM + 依赖桩，langchain 版）。

与 langgraph 版 tests/test_web_api.py 对齐；/api/optimize 经 graph.py 适配层
转发到 chain.run_optimize（LCEL 管道）。
"""

from __future__ import annotations

from unittest import mock

import pytest

fastapi = pytest.importorskip("fastapi")  # 未安装 fastapi 时跳过整个模块
httpx = pytest.importorskip("httpx")

import web_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import config  # noqa: E402

client = TestClient(web_app.app)


@pytest.fixture()
def isolated_output_dir(tmp_path, monkeypatch):
    """把 output 目录指向临时目录，避免测试污染真实 output/。"""
    out_dir = tmp_path / "output"
    monkeypatch.setitem(config.PATH_CONFIG, "output_dir", str(out_dir))
    return out_dir


# ──────────────────────────────────────────────
# 基础接口
# ──────────────────────────────────────────────
class TestHealth:
    def test_health_ok(self) -> None:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] in ("ok", "degraded")


class TestIndex:
    def test_index_returns_page(self) -> None:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "html" in resp.headers.get("content-type", "").lower()


# ──────────────────────────────────────────────
# 对话接口
# ──────────────────────────────────────────────
class TestChat:
    def test_chat_missing_message_400(self) -> None:
        resp = client.post("/api/chat", json={"messages": []})
        assert resp.status_code == 400

    def test_chat_rag_miss_falls_back_to_llm(self) -> None:
        # 知识库桩返回空 → 未命中 → 走 MOCK LLM
        resp = client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "什么是RAG？"}]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "llm"
        assert "MOCK" in body["reply"]

    def test_chat_rag_hit_uses_kb(self, monkeypatch) -> None:
        fake_hits = [
            {"question": "GIL 是什么？", "key_points": ["GIL"], "reference_answer": "全局解释器锁"}
        ]
        monkeypatch.setattr(
            "interview_knowledge_base.search_questions", lambda *a, **k: fake_hits
        )
        resp = client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "GIL 是什么？"}]},
        )
        assert resp.status_code == 200
        assert resp.json()["source"] == "rag"


# ──────────────────────────────────────────────
# 简历优化接口
# ──────────────────────────────────────────────
class TestOptimize:
    def test_optimize_requires_fields(self) -> None:
        resp = client.post("/api/optimize", json={"resume_text": "", "jd_text": "", "target_company": ""})
        assert resp.status_code == 400

    def test_optimize_full_flow(self, isolated_output_dir) -> None:
        resp = client.post(
            "/api/optimize",
            json={
                "resume_text": "张三，3年Python后端开发经验，熟悉Django、MySQL、Redis。",
                "jd_text": "岗位：Python后端开发工程师，3年以上经验，熟悉Django/MySQL/Redis。",
                "target_company": "某科技有限公司",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["optimized"]
        assert body["resume_docx"]


# ──────────────────────────────────────────────
# 下载接口（路径穿越防护）
# ──────────────────────────────────────────────
class TestDownload:
    def test_path_traversal_rejected(self) -> None:
        resp = client.get("/api/download", params={"filename": "../../../etc/passwd"})
        assert resp.status_code in (400, 404)

    def test_missing_filename_400(self) -> None:
        resp = client.get("/api/download", params={"filename": ""})
        assert resp.status_code == 400


# ──────────────────────────────────────────────
# 面经入库接口（失败时返回 warning）
# ──────────────────────────────────────────────
class TestExpUpload:
    def test_exp_upload_warning_on_processing_failure(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "experience_crawler.save_manual_experience",
            lambda **k: {"source": "manual", "content": "面经内容"},
        )
        monkeypatch.setattr(
            "experience_processor.process_raw_item",
            mock.Mock(side_effect=ValueError("mock 结构化失败")),
        )
        resp = client.post("/api/exp/upload", json={"text": "面经内容"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["saved"] == 0
        assert "结构化失败" in body["warning"]
