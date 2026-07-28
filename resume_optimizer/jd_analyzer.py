"""
岗位分析模块

职责：
1. 接收岗位描述文本
2. 调用大模型提取结构化信息
3. 输出技能清单、关键词、经验要求

依赖：langchain, langchain-openai (DeepSeek 兼容接口)
"""

from __future__ import annotations

import json
import logging
from typing import Any

import llm_client
from config import LLM_CONFIG

logger = logging.getLogger(__name__)

# 模型上下文安全长度（超过则截断 JD 文本）
MAX_JD_CHARS = 6000


# 岗位分析 Prompt 模板
JD_ANALYZE_PROMPT = """你是一位招聘分析师。请分析以下岗位描述，提取关键信息。

岗位描述：
{jd_text}

请以 JSON 格式返回，包含以下字段：
- required_skills: 核心必备技能（列表）
- preferred_skills: 加分技能（列表）
- responsibilities: 岗位职责（列表）
- experience_years: 经验要求（字符串，如 "3-5年"）
- keywords: 关键词（列表）

只返回 JSON，不要其他内容。"""


def analyze_jd(jd_text: str) -> dict[str, Any]:
    """分析岗位描述，提取结构化信息。

    Args:
        jd_text: 岗位描述全文

    Returns:
        {
            "required_skills": ["Python", "Django", ...],
            "preferred_skills": ["Docker", "Redis", ...],
            "responsibilities": ["负责后端开发", ...],
            "experience_years": "3-5年",
            "keywords": ["Python后端", "微服务", ...]
        }

    Raises:
        ValueError: 岗位描述为空
    """
    if not jd_text or not jd_text.strip():
        raise ValueError("岗位描述不能为空")

    # 边界处理：岗位描述过长时截断到安全长度
    text = jd_text.strip()
    if len(text) > MAX_JD_CHARS:
        logger.warning("岗位描述过长（%d 字），截断到 %d 字", len(text), MAX_JD_CHARS)
        text = text[:MAX_JD_CHARS]

    prompt = JD_ANALYZE_PROMPT.format(jd_text=text)
    logger.info("调用 DeepSeek 分析岗位需求...")
    result = llm_client.chat_json(prompt)

    # 校验并补齐返回字段
    analysis = _normalize_analysis(result)
    logger.info(
        "岗位分析完成：核心技能 %d 项，加分技能 %d 项",
        len(analysis["required_skills"]),
        len(analysis["preferred_skills"]),
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

    return {
        "required_skills": _as_list(raw.get("required_skills")),
        "preferred_skills": _as_list(raw.get("preferred_skills")),
        "responsibilities": _as_list(raw.get("responsibilities")),
        "experience_years": str(raw.get("experience_years", "")).strip(),
        "keywords": _as_list(raw.get("keywords")),
    }


if __name__ == "__main__":
    sample_jd = """岗位：Python 后端开发工程师
要求：3年以上 Python 开发经验，熟悉 Django/Flask 框架，
熟悉 MySQL、Redis，了解微服务架构，有 Docker 使用经验优先。"""
    print(json.dumps(analyze_jd(sample_jd), ensure_ascii=False, indent=2))
