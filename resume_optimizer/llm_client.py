"""
LLM 客户端公共模块

统一封装 DeepSeek（OpenAI 兼容接口）的调用逻辑，
供 jd_analyzer、content_optimizer 等模块复用。

依赖：langchain-openai
"""

from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from typing import Any

from config import LLM_CONFIG

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Mock 模式（无 API Key 时用于演示 / 测试）
# 设置环境变量 MOCK_LLM=1 开启：chat() 返回模拟响应
# ──────────────────────────────────────────────
def mock_enabled() -> bool:
    return os.getenv("MOCK_LLM", "").strip().lower() in ("1", "true", "yes")


def _mock_chat(prompt: str, system: str | None = None) -> str:
    """根据 prompt 特征返回模拟 LLM 响应（保证流水线可完整走通）。"""
    # JD 结构化分析（jd_analyzer.analyze_jd）
    if "required_skills" in prompt and "岗位描述" in prompt:
        return json.dumps(
            {
                "required_skills": ["Python", "Django", "MySQL", "Redis"],
                "preferred_skills": ["Docker", "微服务架构"],
                "responsibilities": [
                    "负责后端服务设计与开发",
                    "参与系统架构设计与性能优化",
                ],
                "experience_years": "3-5年",
                "keywords": ["Python后端", "Django", "MySQL", "Redis"],
            },
            ensure_ascii=False,
        )
    # 简历-JD 匹配关系表（content_optimizer.build_matching_table）
    if "jd_requirement" in prompt:
        return json.dumps(
            [
                {
                    "jd_requirement": "熟悉 Django 或 Flask 框架",
                    "user_evidence": "使用 Django REST Framework 开发后端接口",
                    "match_strength": "strong",
                    "suggested_expression": "使用 Django REST Framework 独立完成订单模块接口开发",
                }
            ],
            ensure_ascii=False,
        )
    # 简历优化（content_optimizer.optimize_resume_content）
    if "优化后的简历" in prompt or "简历优化顾问" in prompt:
        return (
            "张三 | 13800001234 | zhangsan@example.com\n\n"
            "求职目标：Python 后端开发工程师\n\n"
            "个人摘要：\n3 年 Python 后端开发经验，熟练使用 Django/Flask 构建业务系统。\n\n"
            "核心技能：\nPython（熟练）｜Django（熟练）｜MySQL（熟练）｜Redis（熟练）\n\n"
            "工作经历：\n2022.07 - 至今 某科技有限公司 后端开发工程师\n"
            "- 使用 Django REST Framework 完成订单模块接口设计开发\n\n"
            "项目经历：\n订单管理系统（Django + MySQL + Redis）\n"
            "- 设计订单状态机与库存扣减接口，保证数据一致性\n\n"
            "教育背景：\n2017.09 - 2021.06 某某大学 计算机科学与技术 本科\n\n"
            "（本条为 MOCK 演示输出，配置真实 API Key 后由模型生成）"
        )
    return "（MOCK）你好，我是简历优化助手。当前为演示模式，配置 API Key 后可提供真实分析与优化服务。"


@lru_cache(maxsize=1)
def get_llm():
    """获取 DeepSeek LLM 客户端（单例缓存）。

    基于 LangChain 的 ChatOpenAI，指向 DeepSeek 的 OpenAI 兼容接口。
    """
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as e:
        raise ImportError(
            "缺少依赖 langchain-openai，请执行: pip install langchain-openai"
        ) from e

    api_key = LLM_CONFIG["api_key"]
    if not api_key or api_key == "your-deepseek-api-key-here":
        raise ValueError(
            "未配置 DeepSeek API Key，请在 config.py 中设置，"
            "或通过环境变量 DEEPSEEK_API_KEY 注入"
        )

    logger.info("初始化 DeepSeek LLM 客户端: %s", LLM_CONFIG["model_name"])
    return ChatOpenAI(
        model=LLM_CONFIG["model_name"],
        api_key=api_key,
        base_url=LLM_CONFIG["base_url"],
        temperature=LLM_CONFIG["temperature"],
        max_tokens=LLM_CONFIG["max_tokens"],
        timeout=LLM_CONFIG["timeout"],
    )


def chat(prompt: str, system: str | None = None) -> str:
    """发送单轮对话请求，返回模型文本响应。

    Args:
        prompt: 用户消息
        system: 可选的系统消息

    Returns:
        模型返回的纯文本
    """
    if mock_enabled():
        logger.info("[MOCK] 返回模拟 LLM 响应")
        return _mock_chat(prompt, system)

    from langchain_core.messages import HumanMessage, SystemMessage

    llm = get_llm()
    messages = []
    if system:
        messages.append(SystemMessage(content=system))
    messages.append(HumanMessage(content=prompt))

    response = llm.invoke(messages)
    return response.content


def chat_json(prompt: str, system: str | None = None) -> dict[str, Any]:
    """发送对话请求并解析返回的 JSON。

    Args:
        prompt: 用户消息
        system: 可选的系统消息

    Returns:
        解析后的字典

    Raises:
        ValueError: 模型返回内容无法解析为 JSON
    """
    raw = chat(prompt, system)
    return parse_llm_json(raw)


def parse_llm_json(response_text: str) -> dict[str, Any]:
    """解析大模型返回的 JSON 文本，带容错处理。

    支持剥离 ```json 代码块标记、提取首个 JSON 对象。
    """
    if not response_text:
        raise ValueError("模型返回内容为空")

    text = response_text.strip()

    # 1. 剥离 markdown 代码块标记
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    # 2. 直接尝试解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 3. 提取首个 { ... } 对象（贪婪到最后一个 }）
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group(0))
        except json.JSONDecodeError as e:
            raise ValueError(f"无法解析模型返回的 JSON: {e}\n原文: {response_text}")

    raise ValueError(f"模型返回内容不含有效 JSON:\n{response_text}")
