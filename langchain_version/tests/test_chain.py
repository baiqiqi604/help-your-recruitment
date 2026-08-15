"""LangChain LCEL 简历优化流水线的确定性测试（MOCK_LLM 模式，无真实 API 调用）。

对应 langgraph 版 tests/test_graph_flow.py，验证 chain.py（RunnableSequence 管道）
在 MOCK 模式下全流程走通，以及输入校验与截断逻辑。
"""

from __future__ import annotations

import pytest

import config
from chain import MAX_RESUME_CHARS, run_optimize

SAMPLE_RESUME = (
    "张三，3年Python后端开发经验，熟悉Django、MySQL、Redis，"
    "曾负责订单系统设计与数据库性能优化。"
)
SAMPLE_JD = (
    "岗位：Python后端开发工程师，3年以上经验，"
    "熟悉Django/Flask、MySQL、Redis、Docker，了解微服务架构。"
)


@pytest.fixture()
def isolated_output_dir(tmp_path, monkeypatch):
    """把 output 目录指向临时目录，避免测试污染真实 output/。"""
    out_dir = tmp_path / "output"
    monkeypatch.setitem(config.PATH_CONFIG, "output_dir", str(out_dir))
    return out_dir


# ──────────────────────────────────────────────
# 全流程测试（MOCK 模式走通整条 LCEL 管道）
# ──────────────────────────────────────────────
class TestRunOptimize:
    def test_full_pipeline_succeeds_in_mock_mode(self, isolated_output_dir) -> None:
        result = run_optimize(SAMPLE_RESUME, SAMPLE_JD, target_company="某科技有限公司")
        assert not result.get("error")
        assert result["optimized_text"].strip()
        assert result["jd_analysis"].get("required_skills")
        assert result["company_research"]
        assert result["matching_table"]
        assert result["interview_questions"]
        assert result["interview_advice"]
        assert result["resume_docx_path"]
        assert result["advice_docx_path"]

    def test_empty_resume_returns_error(self, isolated_output_dir) -> None:
        result = run_optimize("", SAMPLE_JD, target_company="某科技有限公司")
        assert result["error"]
        assert not result["optimized_text"]

    def test_empty_jd_returns_error(self, isolated_output_dir) -> None:
        result = run_optimize(SAMPLE_RESUME, "", target_company="某科技有限公司")
        assert result["error"]

    def test_missing_company_returns_error(self, isolated_output_dir) -> None:
        result = run_optimize(SAMPLE_RESUME, SAMPLE_JD, target_company="")
        assert result["error"]

    def test_long_resume_truncated(self, isolated_output_dir) -> None:
        """超长简历在 load 节点被截断，流水线仍可走通。"""
        long_resume = "A" * (MAX_RESUME_CHARS + 500)
        result = run_optimize(long_resume, SAMPLE_JD, target_company="某科技有限公司")
        assert not result.get("error")
        assert len(result.get("resume_text", "")) <= MAX_RESUME_CHARS
