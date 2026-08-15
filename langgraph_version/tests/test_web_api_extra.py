"""FastAPI Web 接口补充测试：SSE 流式 / 上传大小限制 / 检索 top_k 钳制 / 下载。"""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

import config  # noqa: E402
import web_app  # noqa: E402

client = TestClient(web_app.app)

MAX_UPLOAD_BYTES = web_app.MAX_UPLOAD_BYTES


@pytest.fixture()
def isolated_output_dir(tmp_path, monkeypatch):
    """把 output 目录指向临时目录，避免测试污染真实 output/。"""
    out_dir = tmp_path / "output"
    monkeypatch.setitem(config.PATH_CONFIG, "output_dir", str(out_dir))
    return out_dir


# ──────────────────────────────────────────────
# SSE 流式对话接口
# ──────────────────────────────────────────────
class TestChatStream:
    def test_stream_missing_message_400(self) -> None:
        resp = client.post("/api/chat/stream", json={"messages": []})
        assert resp.status_code == 400

    def test_stream_miss_falls_back_to_llm(self) -> None:
        # 知识库桩返回空 → 未命中 → 走 MOCK LLM 流式
        resp = client.post(
            "/api/chat/stream",
            json={"messages": [{"role": "user", "content": "你好"}]},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        text = resp.text
        assert '"event": "start"' in text
        assert '"source": "llm"' in text
        assert '"event": "done"' in text

    def test_stream_rag_hit_emits_questions(self, monkeypatch) -> None:
        fake_hits = [
            {"question": "GIL 是什么？", "key_points": ["GIL"], "reference_answer": "全局解释器锁"}
        ]
        monkeypatch.setattr(
            "interview_knowledge_base.search_questions", lambda *a, **k: fake_hits
        )
        resp = client.post(
            "/api/chat/stream",
            json={"messages": [{"role": "user", "content": "GIL 是什么？"}]},
        )
        assert resp.status_code == 200
        text = resp.text
        assert '"source": "rag"' in text
        assert '"event": "questions"' in text


# ──────────────────────────────────────────────
# 简历上传接口（大小限制 / 扩展名校验）
# ──────────────────────────────────────────────
class TestUpload:
    def test_upload_txt_ok(self) -> None:
        resp = client.post(
            "/api/upload",
            files={"file": ("resume.txt", "张三，Python 后端开发", "text/plain")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "张三" in body["text"]
        assert body["filename"] == "resume.txt"

    def test_upload_invalid_extension_400(self) -> None:
        resp = client.post(
            "/api/upload",
            files={"file": ("resume.exe", b"MZ", "application/octet-stream")},
        )
        assert resp.status_code == 400

    def test_upload_oversized_413(self) -> None:
        big = b"x" * (MAX_UPLOAD_BYTES + 1)
        resp = client.post(
            "/api/upload",
            files={"file": ("big.pdf", big, "application/pdf")},
        )
        assert resp.status_code == 413


# ──────────────────────────────────────────────
# 下载接口（成功路径 / 不存在 404）
# ──────────────────────────────────────────────
class TestDownloadFile:
    def test_download_existing_file(self, isolated_output_dir) -> None:
        isolated_output_dir.mkdir(parents=True, exist_ok=True)
        target = isolated_output_dir / "定制化简历_测试公司.docx"
        target.write_bytes(b"fake docx content")

        resp = client.get("/api/download", params={"filename": target.name})
        assert resp.status_code == 200
        assert resp.content == b"fake docx content"

    def test_download_missing_file_404(self, isolated_output_dir) -> None:
        resp = client.get("/api/download", params={"filename": "不存在.docx"})
        assert resp.status_code == 404


# ──────────────────────────────────────────────
# 岗位检索接口（空查询 / top_k 钳制）
# ──────────────────────────────────────────────
class TestJobsSearch:
    def test_search_jobs_empty_query(self) -> None:
        resp = client.get("/api/jobs/search", params={"q": ""})
        assert resp.status_code == 200
        assert resp.json()["jobs"] == []

    def test_search_jobs_top_k_clamped(self, monkeypatch) -> None:
        captured: dict[str, int] = {}

        def fake_search_jds(query, top_k=10, **kwargs):
            captured["top_k"] = top_k
            return []

        monkeypatch.setattr("jd_knowledge_base.search_jds", fake_search_jds)
        resp = client.get("/api/jobs/search", params={"q": "Python", "top_k": 999999})
        assert resp.status_code == 200
        assert captured["top_k"] == web_app.MAX_TOP_K

    def test_premium_jobs(self) -> None:
        resp = client.get("/api/jobs/premium")
        assert resp.status_code == 200
        assert "jobs" in resp.json()


# ──────────────────────────────────────────────
# 面经题库检索接口
# ──────────────────────────────────────────────
class TestExpSearch:
    def test_exp_search_empty_query(self) -> None:
        resp = client.get("/api/exp/search", params={"q": ""})
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_exp_search_returns_questions(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "interview_knowledge_base.search_questions",
            lambda *a, **k: [{"question": "GIL 是什么？"}],
        )
        resp = client.get("/api/exp/search", params={"q": "GIL"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_exp_company(self) -> None:
        resp = client.get("/api/exp/company", params={"company": "字节跳动"})
        assert resp.status_code == 200
        assert "questions" in resp.json()

    def test_exp_algorithm(self) -> None:
        resp = client.get("/api/exp/algorithm")
        assert resp.status_code == 200
        assert "questions" in resp.json()

    def test_exp_count(self) -> None:
        resp = client.get("/api/exp/count")
        assert resp.status_code == 200
        assert "count" in resp.json()


# ──────────────────────────────────────────────
# 面经入库接口（成功路径）
# ──────────────────────────────────────────────
class TestExpUploadSuccess:
    def test_exp_upload_empty_text_400(self) -> None:
        resp = client.post("/api/exp/upload", json={"text": ""})
        assert resp.status_code == 400

    def test_exp_upload_success(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "experience_crawler.save_manual_experience",
            lambda **k: {"source": "manual", "content": "面经内容"},
        )
        monkeypatch.setattr(
            "experience_processor.process_raw_item",
            lambda item: [{"question": "Q1", "answer": "A1"}],
        )
        monkeypatch.setattr(
            "interview_knowledge_base.add_experiences", lambda qs: len(qs)
        )

        resp = client.post("/api/exp/upload", json={"text": "面经内容"})
        assert resp.status_code == 200
        assert resp.json()["saved"] == 1
