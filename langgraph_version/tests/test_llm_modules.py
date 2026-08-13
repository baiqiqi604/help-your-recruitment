"""jd_analyzer / content_optimizer / company_researcher / interview_advisor /
experience_processor 的确定性测试（MOCK_LLM 场景注册表，无真实 API 调用）。

每个模块都通过 llm_client.chat / chat_json / chat_json_array 显式指定
mock_scenario，因此 MOCK_LLM=1 时输出完全确定，可断言结构字段与兜底行为。
"""

from __future__ import annotations

from typing import Any

import pytest

import jd_analyzer
import company_researcher
import content_optimizer
import interview_advisor
import experience_processor

SAMPLE_JD_ANALYSIS: dict[str, Any] = {
    "role_position": "Python 后端开发工程师",
    "role_type": "tech",
    "responsibilities": ["负责后端服务设计与开发", "参与系统架构设计"],
    "required_skills": ["Python", "Django", "MySQL", "Redis"],
    "preferred_skills": ["Docker", "微服务架构"],
    "tech_stack": ["Python", "Django", "MySQL", "Redis", "Docker"],
    "industry_experience": ["互联网", "高并发业务"],
    "keywords": ["Python后端", "Django"],
    "hidden_goals": ["稳定性", "效率", "性能优化"],
    "experience_years": "3-5年",
    "requirement_tiers": [
        {"tier": "must_match", "requirement": "Python 开发经验", "reason": "硬性要求"},
        {"tier": "strongly_related", "requirement": "熟悉 Django/Flask", "reason": "核心框架"},
        {"tier": "bonus", "requirement": "Docker 使用经验", "reason": "加分项"},
        {"tier": "risk", "requirement": "高并发性能优化", "reason": "证据不足"},
    ],
}

SAMPLE_RESUME = (
    "张三，3年Python后端开发经验，熟悉Django、MySQL、Redis，"
    "曾负责订单系统设计与数据库性能优化。"
)


# ──────────────────────────────────────────────
# jd_analyzer
# ──────────────────────────────────────────────
class TestJdAnalyzer:
    def test_analyze_jd_mock_returns_normalized_analysis(self) -> None:
        result = jd_analyzer.analyze_jd("岗位：Python 后端开发工程师\n要求：熟悉 Django/MySQL")
        assert result["role_type"] == "tech"
        assert "Python" in result["required_skills"]
        assert result["requirement_tiers"]
        for tier in result["requirement_tiers"]:
            assert tier["tier"] in jd_analyzer.TIER_VALUES
            assert tier["requirement"] and tier["reason"]

    def test_analyze_jd_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            jd_analyzer.analyze_jd("")
        with pytest.raises(ValueError):
            jd_analyzer.analyze_jd("   ")

    def test_analyze_jd_accepts_resume_text(self) -> None:
        result = jd_analyzer.analyze_jd("岗位：Python 后端", resume_text=SAMPLE_RESUME)
        assert result["role_type"] == "tech"

    def test_normalize_analysis_fallback_values(self) -> None:
        raw = {
            "role_type": "bogus_type",
            "requirement_tiers": [
                {"tier": "bogus", "requirement": "x", "reason": "y"},
                {"tier": "must_match", "requirement": "Python", "reason": "硬性要求"},
            ],
            "responsibilities": "单条字符串也转列表",
            "preferred_skills": [],
        }
        result = jd_analyzer._normalize_analysis(raw)
        assert result["role_type"] == "tech"  # 非法类型兜底
        assert len(result["requirement_tiers"]) == 1
        assert result["requirement_tiers"][0]["tier"] == "must_match"
        assert result["responsibilities"] == ["单条字符串也转列表"]


# ──────────────────────────────────────────────
# content_optimizer
# ──────────────────────────────────────────────
class TestContentOptimizer:
    def test_optimize_resume_content_returns_text(self) -> None:
        result = content_optimizer.optimize_resume_content(SAMPLE_RESUME, SAMPLE_JD_ANALYSIS)
        assert isinstance(result, str)
        assert result.strip()

    def test_optimize_resume_content_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            content_optimizer.optimize_resume_content("", SAMPLE_JD_ANALYSIS)
        with pytest.raises(ValueError):
            content_optimizer.optimize_resume_content(SAMPLE_RESUME, None)

    def test_build_matching_table_mock_rows(self) -> None:
        rows = content_optimizer.build_matching_table(SAMPLE_RESUME, SAMPLE_JD_ANALYSIS)
        assert rows
        for row in rows:
            assert row["jd_requirement"]
            assert row["match_strength"] in {"strong", "partial", "weak", "missing"}
            assert row["resume_position"] in {"个人摘要", "核心技能", "工作经历", "项目经历", "教育背景", "其他"}

    def test_build_matching_table_parse_failure_returns_empty(self, monkeypatch) -> None:
        import llm_client

        monkeypatch.setattr(
            llm_client, "chat_json_array", lambda *a, **k: (_ for _ in ()).throw(ValueError("解析失败"))
        )
        rows = content_optimizer.build_matching_table(SAMPLE_RESUME, SAMPLE_JD_ANALYSIS)
        assert rows == []

    def test_normalize_matching_rows_fallback(self) -> None:
        raw = [
            {"jd_requirement": "Python 开发经验", "match_strength": "excellent", "resume_position": "表头"},
            {"jd_requirement": "", "match_strength": "strong"},  # 无 requirement 丢弃
            "not-a-dict",
        ]
        rows = content_optimizer._normalize_matching_rows(raw)
        assert len(rows) == 1
        assert rows[0]["match_strength"] == "weak"  # 非法强度兜底
        assert rows[0]["resume_position"] == "其他"  # 非法位置兜底


# ──────────────────────────────────────────────
# company_researcher
# ──────────────────────────────────────────────
class TestCompanyResearcher:
    def test_research_company_mock(self) -> None:
        result = company_researcher.research_company(
            "某科技有限公司", SAMPLE_JD_ANALYSIS, resume_text=SAMPLE_RESUME
        )
        assert result["company_overview"]["name"]
        assert result["recommendation"] in company_researcher.RECOMMENDATION_VALUES
        assert isinstance(result["positive_info"], list)
        assert result["application_strategy"]

    def test_research_company_with_extra_info(self) -> None:
        result = company_researcher.research_company(
            "某科技有限公司", SAMPLE_JD_ANALYSIS, extra_company_info="近期完成 B 轮融资"
        )
        assert result["recommendation"] in company_researcher.RECOMMENDATION_VALUES

    def test_research_company_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            company_researcher.research_company("", SAMPLE_JD_ANALYSIS)

    def test_normalize_research_invalid_recommendation(self) -> None:
        result = company_researcher._normalize_research({"recommendation": "bogus"})
        assert result["recommendation"] == "insufficient"
        assert result["company_overview"] == {"name": "", "industry": "", "business": "", "position": ""}
        result2 = company_researcher._normalize_research(
            {"recommendation": "recommend", "company_overview": "not-a-dict"}
        )
        assert result2["recommendation"] == "recommend"
        assert result2["company_overview"] == {"name": "", "industry": "", "business": "", "position": ""}


# ──────────────────────────────────────────────
# interview_advisor
# ──────────────────────────────────────────────
class TestInterviewAdvisor:
    def test_generate_interview_questions_mock(self) -> None:
        questions = interview_advisor.generate_interview_questions(
            "tech", SAMPLE_JD_ANALYSIS, resume_text=SAMPLE_RESUME
        )
        assert questions
        for q in questions:
            assert q["question"]
            assert "stage" in q and "prepare_hint" in q

    def test_generate_interview_questions_unknown_role_type(self) -> None:
        # 非法岗位类型按 tech 兜底，不报错
        questions = interview_advisor.generate_interview_questions(
            "hacker", SAMPLE_JD_ANALYSIS
        )
        assert questions

    def test_build_interview_advice_mock(self) -> None:
        research = company_researcher.research_company("某科技有限公司", SAMPLE_JD_ANALYSIS)
        advice = interview_advisor.build_interview_advice(
            "某科技有限公司",
            SAMPLE_JD_ANALYSIS,
            SAMPLE_RESUME,
            research,
            [{"stage": "业务面", "question": "介绍一个项目", "prepare_hint": "STAR"}],
        )
        assert isinstance(advice, str)
        assert advice.strip()

    def test_build_interview_advice_empty_company_raises(self) -> None:
        with pytest.raises(ValueError):
            interview_advisor.build_interview_advice("", SAMPLE_JD_ANALYSIS, SAMPLE_RESUME, {}, [])

    def test_normalize_questions_fallback(self) -> None:
        raw = [
            {"stage": "不明轮次", "question": "q1"},
            {"stage": "专业面", "question": "   "},  # 空题目丢弃
            "not-a-dict",
        ]
        questions = interview_advisor._normalize_questions(raw)
        assert len(questions) == 1
        assert questions[0]["stage"] == "业务面"  # 非法轮次兜底
        assert questions[0]["question"] == "q1"

    def test_format_company_research_and_questions(self) -> None:
        text = interview_advisor._format_company_research({})
        assert "无公司研究数据" in text
        formatted = interview_advisor._format_company_research(
            {"company_overview": {"name": "某公司"}, "positive_info": ["增长稳健"]}
        )
        assert "某公司" in formatted and "增长稳健" in formatted
        assert interview_advisor._format_questions([]) == "（无面试问题数据）"


# ──────────────────────────────────────────────
# experience_processor
# ──────────────────────────────────────────────
class TestExperienceProcessor:
    SAMPLE_RAW = {
        "source": "csdn",
        "title": "Python 面试题",
        "url": "https://blog.csdn.net/example",
        "content": "1. GIL 是什么？\n2. 手撕 LRU 缓存。",
        "collected_at": "2026-08-13",
    }

    def test_process_raw_item_mock(self) -> None:
        questions = experience_processor.process_raw_item(self.SAMPLE_RAW)
        assert questions
        for q in questions:
            assert q["question"]
            assert q["stage"] in experience_processor.STAGE_VALUES
            assert q["question_type"] in experience_processor.QUESTION_TYPE_VALUES
            assert 1 <= q["quality"] <= 5
            assert q["source"] == "csdn"
            assert q["source_url"] == "https://blog.csdn.net/example"

    def test_process_raw_item_empty_content(self) -> None:
        assert experience_processor.process_raw_item({}) == []
        assert experience_processor.process_raw_item({"content": "   "}) == []

    def test_process_raw_items_deduplicates(self) -> None:
        items = [self.SAMPLE_RAW, dict(self.SAMPLE_RAW)]
        questions = experience_processor.process_raw_items(items)
        assert questions
        assert experience_processor._deduplicate_questions(questions) == questions

    def test_normalize_questions_fallback(self) -> None:
        raw = [
            {"question": "q1", "stage": "电话面", "question_type": "脑筋急转弯", "quality": 99},
            {"question": "q2", "quality": "bad"},
        ]
        questions = experience_processor._normalize_questions(raw, {"source": "s", "url": "u"})
        assert len(questions) == 2
        assert questions[0]["stage"] == "业务面"  # 非法轮次兜底
        assert questions[0]["question_type"] == "面试问答"  # 非法类型兜底
        assert questions[0]["quality"] == 5  # 质量分封顶
        assert questions[1]["quality"] == 3  # 非法质量分兜底

    def test_deduplicate_questions(self) -> None:
        dup = [
            {"company": "A", "role": "后端", "question": "q1"},
            {"company": "A", "role": "后端", "question": "q1"},
            {"company": "A", "role": "后端", "question": "q2"},
        ]
        result = experience_processor._deduplicate_questions(dup)
        assert len(result) == 2
