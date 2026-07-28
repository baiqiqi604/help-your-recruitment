"""
LLM 客户端公共模块

统一封装 DeepSeek（OpenAI 兼容接口）的调用逻辑，
供 jd_analyzer、content_optimizer 等模块复用。

依赖：langchain-openai
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Any

from config import LLM_CONFIG

logger = logging.getLogger(__name__)


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
