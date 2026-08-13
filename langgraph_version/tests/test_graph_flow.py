"""LangGraph 简历优化流水线的确定性测试（MOCK_LLM 模式，无真实 API 调用）。"""

from __future__ import annotations

import pytest

import config
from graph import (
    END,
    MAX_ATTEMPTS,
    load_resume,
    route_after_review,
    route_after_stage,
    run_optimize,
)

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
# 节点级测试（load_resume / 条件路由）
# ──────────────────────────────────────────────
class TestStageNodes:
    def test_invalid_resume_stops_workflow(self) -> None:
        state = load_resume({"resume_text": "", "jd_text": SAMPLE_JD, "target_company": "某公司"})
        assert state["error"]
        assert route_after_stage(state) != "continue"

    def test_invalid_jd_stops_workflow(self) -> None:
        state = load_resume({"resume_text": SAMPLE_RESUME, "jd_text": "", "target_company": "某公司"})
        assert state["error"]
        assert route_after_stage(state) != "continue"

    def test_missing_company_stops_workflow(self) -> None:
        state = load_resume({"resume_text": SAMPLE_RESUME, "jd_text": SAMPLE_JD, "target_company": ""})
        assert state["error"]

    def test_valid_input_continues(self) -> None:
        state = load_resume({"resume_text": SAMPLE_RESUME, "jd_text": SAMPLE_JD, "target_company": "某公司"})
        assert not state["error"]
        assert route_after_stage(state) == "continue"


class TestReviewRouting:
    def test_pass_goes_to_interview(self) -> None:
        assert route_after_review({"review_verdict": {"pass": True}, "attempts": 0}) == "interview"

    def test_fail_below_limit_retries(self) -> None:
        assert route_after_review({"review_verdict": {"pass": False}, "attempts": 0}) == "optimize"
        assert (
            route_after_review({"review_verdict": {"pass": False}, "attempts": MAX_ATTEMPTS - 1})
            == "optimize"
        )

    def test_fail_at_limit_stops(self) -> None:
        assert (
            route_after_review({"review_verdict": {"pass": False}, "attempts": MAX_ATTEMPTS})
            == END
        )


# ──────────────────────────────────────────────
# 全流程测试（MOCK 模式走通整条流水线）
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
