"""llm_client：LLM JSON 容错解析与 MOCK 场景分发的确定性测试。"""

from __future__ import annotations

import pytest

from llm_client import (
    MOCK_SCENARIOS,
    _mock_chat,
    mock_enabled,
    parse_llm_json,
    parse_llm_json_array,
)


# ──────────────────────────────────────────────
# parse_llm_json / parse_llm_json_array 容错解析
# ──────────────────────────────────────────────
class TestParseLlmJson:
    def test_plain_object(self) -> None:
        assert parse_llm_json('{"a": 1}') == {"a": 1}

    def test_fenced_code_block(self) -> None:
        raw = '```json\n{"pass": true}\n```'
        assert parse_llm_json(raw) == {"pass": True}

    def test_text_around_object(self) -> None:
        raw = "结果如下：{\"a\": [1, 2]} 请查收。"
        assert parse_llm_json(raw) == {"a": [1, 2]}

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_llm_json("")

    def test_no_json_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_llm_json("这是纯文本，没有 JSON 对象")


class TestParseLlmJsonArray:
    def test_plain_array(self) -> None:
        assert parse_llm_json_array("[1, 2, 3]") == [1, 2, 3]

    def test_array_with_objects(self) -> None:
        raw = '[{"stage": "HR面", "question": "q1"}, {"stage": "业务面", "question": "q2"}]'
        result = parse_llm_json_array(raw)
        assert len(result) == 2
        assert result[0]["question"] == "q1"

    def test_object_not_array_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_llm_json_array('{"a": 1}')


# ──────────────────────────────────────────────
# MOCK 场景注册表
# ──────────────────────────────────────────────
class TestMockScenarios:
    def test_registry_covers_pipeline_scenarios(self) -> None:
        expected = {
            "analyze_jd", "analyze_jd_basic", "company_research",
            "interview_questions", "interview_advice", "experience_processing",
            "matching_table", "resume_review", "optimize_resume",
        }
        assert expected <= set(MOCK_SCENARIOS)

    def test_explicit_scenario_wins_over_keywords(self) -> None:
        # 显式场景名优先于 prompt 关键字匹配
        raw = _mock_chat(
            "jd_requirement 岗位描述", None, mock_scenario="interview_questions"
        )
        assert isinstance(parse_llm_json_array(raw), list)

    def test_unregistered_scenario_falls_back_to_generic(self) -> None:
        raw = _mock_chat("随便什么内容", None, mock_scenario="not_registered")
        assert "MOCK" in raw

    def test_generic_reply_for_unknown_prompt(self) -> None:
        raw = _mock_chat("完全无关的内容")
        assert "MOCK" in raw

    def test_mock_enabled_in_test_env(self) -> None:
        assert mock_enabled() is True
