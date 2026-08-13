"""
简历优化模块（核心）

职责：
1. 接收简历文本和岗位分析结果
2. 按定制简历原则，用大模型优化简历内容
3. 突出与岗位匹配的经历，调整措辞，不虚构经历
4. 输出 ATS 友好的简历格式

依赖：llm_client
"""

from __future__ import annotations

import logging
from typing import Any

import llm_client

logger = logging.getLogger(__name__)

# 简历文本安全长度（超过则截断）
MAX_RESUME_CHARS = 12000


# 简历优化 Prompt 模板（内置定制简历原则，依据《定制化简历大师》Skill）
OPTIMIZE_PROMPT = """你是一位专业的简历优化顾问，遵循以下定制简历原则：

1. 只基于用户真实经历，不虚构工作经历、项目、学历、证书、数据、工具或结果
2. 将最匹配目标岗位的经历前置
3. 个人摘要直接回应目标岗位最核心的能力要求
4. 技能清单按 JD 重要性重排，但不得添加用户不具备的技能
5. 工作经历使用"行动 + 场景/规模 + 方法 + 结果"的表达
6. 项目经历突出与目标岗位相关的业务、技术、协作、数据和结果
7. 对缺失或不确定内容使用【待确认】标记，不要自行补全
8. 语言专业、具体、克制，避免夸大
9. 格式 ATS 友好，使用清晰标题和标准结构

【岗位定位】{role_position}
【简历-JD匹配分析】
- 核心技能要求：{required_skills}
- 加分技能：{preferred_skills}
- 岗位职责：{responsibilities}
- 经验要求：{experience_years}
- 岗位隐含目标：{hidden_goals}
- 要求分级：
{must_match}
{strongly_related}
{bonus}
{risk}

【原始简历】
{resume_text}

请输出优化后的简历全文，按以下结构：
姓名 / 联系方式
求职目标
个人摘要
核心技能
工作经历
项目经历
教育背景
证书 / 奖项 / 其他"""


def _format_tier_lines(tier_name: str, items: list[str]) -> str:
    """将要求分级项格式化为 Prompt 文本行（无内容时输出占位提示）。"""
    if not items:
        return f"- {tier_name}：（未识别）"
    return "\n".join(f"- {tier_name}：{item}" for item in items)


def _extract_tiers(jd_analysis: dict[str, Any]) -> dict[str, list[str]]:
    """从岗位分析中提取按分级归类的要求列表。"""
    tiers: dict[str, list[str]] = {
        "must_match": [], "strongly_related": [], "bonus": [], "risk": [],
    }
    for item in jd_analysis.get("requirement_tiers") or []:
        if not isinstance(item, dict):
            continue
        tier = str(item.get("tier", "")).strip()
        requirement = str(item.get("requirement", "")).strip()
        if tier in tiers and requirement:
            tiers[tier].append(requirement)
    return tiers


def optimize_resume_content(resume_text: str, jd_analysis: dict[str, Any]) -> str:
    """根据岗位分析结果，优化简历内容。

    Args:
        resume_text: 简历纯文本
        jd_analysis: 岗位分析结果（来自 jd_analyzer.analyze_jd）

    Returns:
        优化后的简历全文

    Raises:
        ValueError: 简历文本或岗位分析为空
    """
    if not resume_text or not resume_text.strip():
        raise ValueError("简历文本不能为空")
    if not jd_analysis:
        raise ValueError("岗位分析结果不能为空")

    text = resume_text.strip()
    if len(text) > MAX_RESUME_CHARS:
        logger.warning("简历文本过长（%d 字），截断到 %d 字", len(text), MAX_RESUME_CHARS)
        text = text[:MAX_RESUME_CHARS]

    tiers = _extract_tiers(jd_analysis)
    prompt = OPTIMIZE_PROMPT.format(
        role_position=jd_analysis.get("role_position", "") or "未提供",
        required_skills=", ".join(jd_analysis.get("required_skills", [])) or "未提供",
        preferred_skills=", ".join(jd_analysis.get("preferred_skills", [])) or "未提供",
        responsibilities=", ".join(jd_analysis.get("responsibilities", [])) or "未提供",
        experience_years=jd_analysis.get("experience_years", "") or "未提供",
        hidden_goals=", ".join(jd_analysis.get("hidden_goals", [])) or "未提供",
        must_match=_format_tier_lines("必须匹配", tiers["must_match"]),
        strongly_related=_format_tier_lines("强相关", tiers["strongly_related"]),
        bonus=_format_tier_lines("加分项", tiers["bonus"]),
        risk=_format_tier_lines("风险项", tiers["risk"]),
        resume_text=text,
    )

    logger.info("调用 LLM 优化简历内容...")
    optimized = llm_client.chat(prompt, mock_scenario="optimize_resume").strip()

    if not optimized:
        raise ValueError("模型返回的优化结果为空")

    logger.info("简历优化完成，输出 %d 字", len(optimized))
    return optimized


def build_matching_table(
    resume_text: str, jd_analysis: dict[str, Any]
) -> list[dict[str, Any]]:
    """建立简历-JD 匹配关系表。

    Returns:
        [
            {
                "jd_requirement": "JD 要求",
                "user_evidence": "用户对应经历证据",
                "match_strength": "strong/partial/weak/missing",
                "resume_position": "应放入简历的位置",
                "suggested_expression": "推荐表达",
                "needs_confirmation": True/False,
            },
            ...
        ]
    """
    if not resume_text or not resume_text.strip():
        raise ValueError("简历文本不能为空")
    if not jd_analysis:
        raise ValueError("岗位分析结果不能为空")

    tiers = _extract_tiers(jd_analysis)
    prompt = f"""你是一位招聘匹配分析师。请建立「岗位需求」与「简历经历」的匹配关系表。

【岗位核心技能】{", ".join(jd_analysis.get("required_skills", []))}
【岗位职责】{", ".join(jd_analysis.get("responsibilities", []))}
【要求分级】
- 必须匹配：{", ".join(tiers["must_match"]) or "（未识别）"}
- 强相关：{", ".join(tiers["strongly_related"]) or "（未识别）"}
- 加分项：{", ".join(tiers["bonus"]) or "（未识别）"}
- 风险项：{", ".join(tiers["risk"]) or "（未识别）"}

【简历全文】
{resume_text[:MAX_RESUME_CHARS]}

请以 JSON 数组格式返回，每个元素包含：
- jd_requirement: JD 要求
- user_evidence: 简历中对应的经历证据（找不到则填"无明确证据"）
- match_strength: 匹配强度（strong=强 / partial=部分 / weak=弱 / missing=缺失）
- resume_position: 应放入简历的位置（个人摘要/核心技能/工作经历/项目经历/教育背景/其他）
- suggested_expression: 推荐的简历表达（弱或缺失项建议用【待确认】标注）
- needs_confirmation: 是否需要用户确认（true/false，证据不足或不确定时为 true）

只返回 JSON 数组，不要其他内容。"""

    logger.info("调用 LLM 构建匹配关系表...")
    try:
        raw_rows = llm_client.chat_json_array(prompt, mock_scenario="matching_table")
        return _normalize_matching_rows(raw_rows)
    except ValueError as e:
        logger.warning("匹配关系表解析失败: %s", e)
        return []


def _normalize_matching_rows(raw: Any) -> list[dict[str, Any]]:
    """校验并补齐匹配关系表字段（四级强度 + 位置 + 确认标记）。"""
    valid_strengths = {"strong", "partial", "weak", "missing"}
    valid_positions = {"个人摘要", "核心技能", "工作经历", "项目经历", "教育背景", "其他"}
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows

    for item in raw:
        if not isinstance(item, dict):
            continue
        jd_requirement = str(item.get("jd_requirement", "")).strip()
        if not jd_requirement:
            continue

        strength = str(item.get("match_strength", "")).strip().lower()
        if strength not in valid_strengths:
            strength = "weak"

        position = str(item.get("resume_position", "")).strip()
        if position not in valid_positions:
            position = "其他"

        rows.append(
            {
                "jd_requirement": jd_requirement,
                "user_evidence": str(item.get("user_evidence", "")).strip(),
                "match_strength": strength,
                "resume_position": position,
                "suggested_expression": str(item.get("suggested_expression", "")).strip(),
                "needs_confirmation": bool(item.get("needs_confirmation", False)),
            }
        )
    return rows


if __name__ == "__main__":
    sample_analysis = {
        "required_skills": ["Python", "Django"],
        "preferred_skills": ["Docker"],
        "responsibilities": ["负责后端开发"],
        "experience_years": "3-5年",
        "keywords": ["Python后端"],
    }
    print(optimize_resume_content("示例简历内容...", sample_analysis))
