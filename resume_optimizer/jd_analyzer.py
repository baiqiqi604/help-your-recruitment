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

from config import LLM_CONFIG

logger = logging.getLogger(__name__)


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

    # TODO: 边界处理 - 岗位描述过长时截断到模型最大上下文长度
    # TODO: 调用 LLM 进行分析
    # 1. 构建 LLM 客户端（DeepSeek OpenAI 兼容接口）
    # 2. 填充 Prompt
    # 3. 调用模型，解析返回的 JSON
    # 4. 校验返回字段完整性
    raise NotImplementedError("analyze_jd 待实现")


def _build_llm():
    """构建 DeepSeek LLM 客户端（基于 LangChain ChatOpenAI）。"""
    # TODO: 使用 langchain_openai.ChatOpenAI 配置 DeepSeek
    # from langchain_openai import ChatOpenAI
    # return ChatOpenAI(
    #     model=LLM_CONFIG["model_name"],
    #     api_key=LLM_CONFIG["api_key"],
    #     base_url=LLM_CONFIG["base_url"],
    #     temperature=LLM_CONFIG["temperature"],
    # )
    raise NotImplementedError("_build_llm 待实现")


def _parse_llm_json(response_text: str) -> dict[str, Any]:
    """解析大模型返回的 JSON 文本，容错处理。"""
    # TODO: 剥离可能的 ```json 代码块标记，json.loads 解析
    raise NotImplementedError("_parse_llm_json 待实现")


if __name__ == "__main__":
    sample_jd = """岗位：Python 后端开发工程师
要求：3年以上 Python 开发经验，熟悉 Django/Flask 框架，
熟悉 MySQL、Redis，了解微服务架构，有 Docker 使用经验优先。"""
    print(json.dumps(analyze_jd(sample_jd), ensure_ascii=False, indent=2))
