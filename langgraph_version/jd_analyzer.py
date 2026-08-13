"""
岗位分析模块（升级版：完整岗位拆解）

职责：
1. 接收岗位描述文本（可选附带简历文本）
2. 调用大模型提取结构化信息
3. 输出：岗位定位/职级、核心职责、必备能力、加分项、技术栈、
   行业经验/软技能、高频关键词、隐含目标、要求分级（必须/强相关/加分/风险）

依据《定制化简历大师》Skill：拆解岗位 JD 需区分必须匹配、强相关、加分项、风险项，
并识别岗位类型与隐含目标，供简历定制与面试建议生成使用。

依赖：llm_client（OpenAI 兼容多 Provider）
"""

from __future__ import annotations

import logging
from typing import Any

import llm_client

logger = logging.getLogger(__name__)

# 模型上下文安全长度（超过则截断 JD 文本）
MAX_JD_CHARS = 6000
# 用于风险项识别的简历截断长度
MAX_RESUME_CHARS_FOR_JD = 8000

# 岗位类型（面试问题生成规则按此分发）
ROLE_TYPES = [
    "tech",          # 技术岗
    "product",       # 产品岗
    "operation",     # 运营岗
    "market_sales",  # 市场/销售岗
    "management",    # 管理岗
    "design",        # 设计岗
    "support",       # 职能岗
]

# 要求分级取值
TIER_VALUES = ("must_match", "strongly_related", "bonus", "risk")


# 岗位分析 Prompt 模板
JD_ANALYZE_PROMPT = """你是一位资深招聘分析师。请完整拆解以下岗位描述，为简历定制与面试准备提供依据。

岗位描述：
{jd_text}

{resume_block}

请以 JSON 格式返回，字段如下：
- role_position: 岗位定位与职级（字符串，如 "高级 Python 后端开发工程师"）
- role_type: 岗位类型，只能取以下之一：tech（技术岗）/ product（产品岗）/ operation（运营岗）/ market_sales（市场销售岗）/ management（管理岗）/ design（设计岗）/ support（职能岗）
- responsibilities: 核心职责（字符串列表）
- required_skills: 必备能力（字符串列表）
- preferred_skills: 加分项（字符串列表）
- tech_stack: 技术/工具/平台（字符串列表）
- industry_experience: 行业经验、业务能力、软技能（字符串列表）
- keywords: 高频关键词（字符串列表）
- hidden_goals: 岗位隐含目标（字符串列表，例如增长、降本、效率、稳定性、转化率、客户满意度等）
- experience_years: 经验要求（字符串，如 "3-5年"）
- requirement_tiers: 要求分级（对象数组），每项包含：
    - tier: 只能取 must_match（必须匹配：硬性要求/高频要求/筛选项）/ strongly_related（强相关：岗位核心职责和重要能力）/ bonus（加分项：非必要但能显著提高竞争力）/ risk（风险项：简历中证据不足或容易被追问的部分）
    - requirement: 该条要求描述
    - reason: 分级理由（一句话）

要求分级应覆盖 JD 中的主要要求，数量 5-12 条。风险项需要结合简历证据判断；若未提供简历，风险项可标注"待结合简历确认"。

只返回 JSON，不要其他内容。"""


def analyze_jd(jd_text: str, resume_text: str = "") -> dict[str, Any]:
    """分析岗位描述，提取结构化信息（含要求分级与岗位类型）。

    Args:
        jd_text: 岗位描述全文
        resume_text: 可选简历文本，用于识别风险项（证据不足/易被追问）

    Returns:
        {
            "role_position": "高级 Python 后端开发工程师",
            "role_type": "tech",
            "responsibilities": [...],
            "required_skills": [...],
            "preferred_skills": [...],
            "tech_stack": [...],
            "industry_experience": [...],
            "keywords": [...],
            "hidden_goals": [...],
            "experience_years": "3-5年",
            "requirement_tiers": [{"tier": "...", "requirement": "...", "reason": "..."}],
        }

    Raises:
        ValueError: 岗位描述为空
    """
    if not jd_text or not jd_text.strip():
        raise ValueError("岗位描述不能为空")

    text = jd_text.strip()
    if len(text) > MAX_JD_CHARS:
        logger.warning("岗位描述过长（%d 字），截断到 %d 字", len(text), MAX_JD_CHARS)
        text = text[:MAX_JD_CHARS]

    resume_block = ""
    if resume_text and resume_text.strip():
        resume = resume_text.strip()
        if len(resume) > MAX_RESUME_CHARS_FOR_JD:
            resume = resume[:MAX_RESUME_CHARS_FOR_JD]
        resume_block = f"【用户简历（用于识别风险项）】\n{resume}"

    prompt = JD_ANALYZE_PROMPT.format(jd_text=text, resume_block=resume_block)
    logger.info("调用 LLM 完整拆解岗位需求...")
    result = llm_client.chat_json(prompt, mock_scenario="analyze_jd")

    analysis = _normalize_analysis(result)
    logger.info(
        "岗位拆解完成：必备 %d 项、加分 %d 项、分级 %d 条，岗位类型=%s",
        len(analysis["required_skills"]),
        len(analysis["preferred_skills"]),
        len(analysis["requirement_tiers"]),
        analysis["role_type"],
    )
    return analysis


def _normalize_analysis(raw: dict[str, Any]) -> dict[str, Any]:
    """校验并补齐岗位分析结果字段。"""

    def _as_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    # 归一化岗位类型（非法值按 tech 兜底，面试生成时可再修正）
    role_type = str(raw.get("role_type", "")).strip().lower()
    if role_type not in ROLE_TYPES:
        role_type = "tech"

    # 归一化要求分级
    tiers: list[dict[str, str]] = []
    raw_tiers = raw.get("requirement_tiers")
    if isinstance(raw_tiers, list):
        for item in raw_tiers:
            if not isinstance(item, dict):
                continue
            tier = str(item.get("tier", "")).strip().lower()
            if tier not in TIER_VALUES:
                continue
            tiers.append(
                {
                    "tier": tier,
                    "requirement": str(item.get("requirement", "")).strip(),
                    "reason": str(item.get("reason", "")).strip(),
                }
            )

    return {
        "role_position": str(raw.get("role_position", "")).strip(),
        "role_type": role_type,
        "responsibilities": _as_list(raw.get("responsibilities")),
        "required_skills": _as_list(raw.get("required_skills")),
        "preferred_skills": _as_list(raw.get("preferred_skills")),
        "tech_stack": _as_list(raw.get("tech_stack")),
        "industry_experience": _as_list(raw.get("industry_experience")),
        "keywords": _as_list(raw.get("keywords")),
        "hidden_goals": _as_list(raw.get("hidden_goals")),
        "experience_years": str(raw.get("experience_years", "")).strip(),
        "requirement_tiers": tiers,
    }


if __name__ == "__main__":
    import json

    sample_jd = """岗位：Python 后端开发工程师
要求：3年以上 Python 开发经验，熟悉 Django/Flask 框架，
熟悉 MySQL、Redis，了解微服务架构，有 Docker 使用经验优先。"""
    print(json.dumps(analyze_jd(sample_jd), ensure_ascii=False, indent=2))
