"""
公司与岗位判断模块（依据《定制化简历大师》Skill）

职责：
1. 围绕求职判断与面试准备，分析目标公司的公开信息
2. 覆盖：公司基本情况、正面信息、负面信息、网络评价、招聘信息、与目标岗位相关业务
3. 结合公司信息、JD 要求与用户履历，给出求职判断
4. 判断内容：推荐程度、匹配理由、主要机会、主要风险、投递策略、面试反向确认问题

信息处理原则：
- 官方信息用于确认事实；媒体/平台信息补充判断；网络评价仅作参考
- 负面信息谨慎表述，避免夸大、诽谤或定性过度
- 信息来源有限时明确说明不确定性，不把未证实信息写成确定事实

依赖：llm_client（OpenAI 兼容多 Provider）
"""

from __future__ import annotations

import logging
from typing import Any

import llm_client

logger = logging.getLogger(__name__)

MAX_COMPANY_CHARS = 4000  # 用户补充公司信息的截断长度
MAX_RESUME_CHARS = 8000   # 用于判断的简历截断长度

# 推荐程度取值
RECOMMENDATION_VALUES = ("recommend", "cautious", "not_recommend", "insufficient")


# 公司研究与求职判断 Prompt 模板
COMPANY_RESEARCH_PROMPT = """你是一位职业咨询顾问，正在帮求职者评估目标公司与目标岗位。请基于已知信息做出基于证据的判断，并明确说明不确定性。

【目标公司】{target_company}
【目标岗位】{role_position}（{role_type}）
【岗位分析摘要】
- 核心职责：{responsibilities}
- 必备能力：{required_skills}
- 加分项：{preferred_skills}
- 隐含目标：{hidden_goals}
{extra_info_block}

【用户简历摘要】
{resume_text}

请以 JSON 格式返回，字段如下：
- company_overview: 公司基本情况（主营业务、产品服务、商业模式、客户群体、行业位置等，对象，字段 name/industry/business/position）
- positive_info: 正面信息列表（增长、融资、产品优势、技术实力、市场影响力、品牌、发展机会）
- negative_info: 负面信息与潜在风险列表（裁员、业务收缩、经营压力、诉讼、合规风险、负面舆情等；仅基于已知公开信息，谨慎表述，不使用绝对化断言）
- online_reviews: 网络评价与候选人反馈摘要列表（员工评价、面试体验、社区口碑；每条应使用"公开评价中有人提到""部分候选人反馈"等限定语；无信息来源时填"暂无可靠来源"）
- hiring_observation: 招聘信息观察（当前岗位数量、招聘方向、岗位分布、是否持续招聘、扩招或收缩信号；信息来源有限则注明）
- recommendation: 推荐程度，只能取 recommend（推荐）/ cautious（谨慎推荐）/ not_recommend（不推荐）/ insufficient（信息不足需进一步确认）
- matching_reasons: 匹配理由列表（用户背景与岗位要求的匹配点）
- opportunities: 主要机会列表（岗位带来的成长、业务、能力或平台价值）
- risks: 主要风险列表（公司经营、团队稳定性、工作强度、薪酬预期、岗位边界、口碑评价等）
- application_strategy: 投递策略（是否建议投递、是否建议内推、简历应突出什么、是否建议同时投递相邻岗位；一段话）
- questions_to_confirm: 面试中建议反向确认的问题列表
- uncertainties: 信息不确定项列表（信息来源有限、无法核实的事项，必须如实列出）

要求：
1. 不替用户做绝对决策，给出基于证据的建议并说明不确定性
2. 负面信息必须谨慎表述，避免夸大、诽谤或定性过度
3. 网络评价只作为参考，注明限定语，不得当作绝对事实
4. 若对目标公司掌握的信息很少，应在 uncertainties 中明确说明，并将 recommendation 设为 insufficient 或 cautious

只返回 JSON，不要其他内容。"""


def research_company(
    target_company: str,
    jd_analysis: dict[str, Any],
    resume_text: str = "",
    extra_company_info: str = "",
) -> dict[str, Any]:
    """分析目标公司并给出求职判断。

    Args:
        target_company: 目标公司名称（必填）
        jd_analysis: 岗位拆解结果（来自 jd_analyzer.analyze_jd）
        resume_text: 用户简历文本（可选，用于匹配理由与机会判断）
        extra_company_info: 用户补充的公司公开信息（可选）

    Returns:
        {
            "company_overview": {...},
            "positive_info": [...],
            "negative_info": [...],
            "online_reviews": [...],
            "hiring_observation": "...",
            "recommendation": "recommend/cautious/not_recommend/insufficient",
            "matching_reasons": [...],
            "opportunities": [...],
            "risks": [...],
            "application_strategy": "...",
            "questions_to_confirm": [...],
            "uncertainties": [...],
        }

    Raises:
        ValueError: 目标公司名称为空
    """
    if not target_company or not target_company.strip():
        raise ValueError("目标公司名称不能为空")

    company = target_company.strip()

    resume = (resume_text or "").strip()
    if len(resume) > MAX_RESUME_CHARS:
        resume = resume[:MAX_RESUME_CHARS]

    extra_info_block = ""
    extra = (extra_company_info or "").strip()
    if extra:
        if len(extra) > MAX_COMPANY_CHARS:
            extra = extra[:MAX_COMPANY_CHARS]
        extra_info_block = f"【用户补充的公司公开信息】\n{extra}"

    analysis = jd_analysis or {}
    prompt = COMPANY_RESEARCH_PROMPT.format(
        target_company=company,
        role_position=analysis.get("role_position", "") or "未知岗位",
        role_type=analysis.get("role_type", "tech"),
        responsibilities=", ".join(analysis.get("responsibilities", [])) or "未提供",
        required_skills=", ".join(analysis.get("required_skills", [])) or "未提供",
        preferred_skills=", ".join(analysis.get("preferred_skills", [])) or "未提供",
        hidden_goals=", ".join(analysis.get("hidden_goals", [])) or "未提供",
        extra_info_block=extra_info_block,
        resume_text=resume or "未提供",
    )

    logger.info("research_company：分析目标公司 %s ...", company)
    result = llm_client.chat_json(prompt)
    return _normalize_research(result)


def _normalize_research(raw: dict[str, Any]) -> dict[str, Any]:
    """校验并补齐公司研究结果字段。"""

    def _as_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    recommendation = str(raw.get("recommendation", "")).strip().lower()
    if recommendation not in RECOMMENDATION_VALUES:
        recommendation = "insufficient"

    overview = raw.get("company_overview")
    if not isinstance(overview, dict):
        overview = {}

    return {
        "company_overview": {
            "name": str(overview.get("name", "")).strip() or "",
            "industry": str(overview.get("industry", "")).strip() or "",
            "business": str(overview.get("business", "")).strip() or "",
            "position": str(overview.get("position", "")).strip() or "",
        },
        "positive_info": _as_list(raw.get("positive_info")),
        "negative_info": _as_list(raw.get("negative_info")),
        "online_reviews": _as_list(raw.get("online_reviews")),
        "hiring_observation": str(raw.get("hiring_observation", "")).strip(),
        "recommendation": recommendation,
        "matching_reasons": _as_list(raw.get("matching_reasons")),
        "opportunities": _as_list(raw.get("opportunities")),
        "risks": _as_list(raw.get("risks")),
        "application_strategy": str(raw.get("application_strategy", "")).strip(),
        "questions_to_confirm": _as_list(raw.get("questions_to_confirm")),
        "uncertainties": _as_list(raw.get("uncertainties")),
    }


if __name__ == "__main__":
    import json

    sample_analysis = {
        "role_position": "Python 后端开发工程师",
        "role_type": "tech",
        "responsibilities": ["负责后端服务设计与开发", "参与架构设计"],
        "required_skills": ["Python", "Django", "MySQL", "Redis"],
        "preferred_skills": ["Docker", "微服务"],
        "hidden_goals": ["稳定性", "效率"],
    }
    print(json.dumps(research_company("某科技有限公司", sample_analysis), ensure_ascii=False, indent=2))
