"""
LLM 客户端公共模块（多 Provider 版）

统一封装 OpenAI 兼容接口的调用逻辑（DeepSeek / OpenAI / 通义 / 智谱），
供 jd_analyzer、content_optimizer、agent 等模块复用。

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
    # 1. JD 结构化分析（jd_analyzer）
    if "required_skills" in prompt and "岗位描述" in prompt:
        return json.dumps(
            {
                "required_skills": ["Python", "Django", "MySQL", "Redis"],
                "preferred_skills": ["Docker", "微服务架构"],
                "responsibilities": [
                    "负责后端服务设计与开发",
                    "参与系统架构设计与性能优化",
                    "负责数据库设计与优化",
                ],
                "experience_years": "3-5年",
                "keywords": ["Python后端", "Django", "MySQL", "Redis"],
            },
            ensure_ascii=False,
        )
    # 2. 简历-JD 匹配关系表（content_optimizer.build_matching_table）
    if "jd_requirement" in prompt:
        return json.dumps(
            [
                {
                    "jd_requirement": "熟悉 Django 或 Flask 框架",
                    "user_evidence": "使用 Django REST Framework 开发后端接口",
                    "match_strength": "strong",
                    "suggested_expression": "使用 Django REST Framework 独立完成订单模块接口开发",
                },
                {
                    "jd_requirement": "熟悉 MySQL、Redis",
                    "user_evidence": "维护 MySQL 表结构并做慢查询优化，使用 Redis 缓存热点数据",
                    "match_strength": "strong",
                    "suggested_expression": "负责 MySQL 表结构设计与慢查询优化，落地 Redis 缓存方案降低 30% 响应时间",
                },
                {
                    "jd_requirement": "了解微服务架构与 Docker",
                    "user_evidence": "无明确证据",
                    "match_strength": "weak",
                    "suggested_expression": "【待确认】补充微服务 / Docker 相关实践经验",
                },
            ],
            ensure_ascii=False,
        )
    # 3. Resume quality review (graph.review)
    if "严格的简历审核专家" in prompt and '"pass"' in prompt:
        return json.dumps(
            {
                "pass": True,
                "feedback": "MOCK 审核通过：输出结构完整，未发现明显虚构内容。",
            },
            ensure_ascii=False,
        )
    # 4. 简历优化（content_optimizer.optimize_resume_content）
    if "优化后的简历" in prompt or "简历优化顾问" in prompt:
        return (
            "张三 | 13800001234 | zhangsan@example.com | 北京\n\n"
            "求职目标：Python 后端开发工程师\n\n"
            "个人摘要：\n"
            "3 年 Python 后端开发经验，熟练使用 Django/Flask 构建业务系统，"
            "具备 MySQL 性能优化与 Redis 缓存设计实战经验，追求高质量、可维护的工程实践。\n\n"
            "核心技能：\n"
            "Python（熟练）｜Django / Django REST Framework（熟练）｜MySQL（熟练）｜"
            "Redis（熟练）｜Flask（熟悉）｜Linux / Git（熟练）\n\n"
            "工作经历：\n"
            "2022.07 - 至今 某科技有限公司 后端开发工程师\n"
            "- 使用 Django REST Framework 独立完成订单模块接口设计开发，支撑日均万级请求\n"
            "- 落地 MySQL 慢查询优化与 Redis 热点缓存，核心接口响应时间降低 30%\n"
            "2021.06 - 2022.06 某网络公司 初级开发工程师\n"
            "- 基于 Flask 开发 RESTful API 并持续迭代维护\n\n"
            "项目经历：\n"
            "订单管理系统（Django + MySQL + Redis）\n"
            "- 设计订单状态机与库存扣减接口，保证数据一致性\n"
            "- 使用 Redis 缓存热点数据，有效减轻数据库压力\n\n"
            "教育背景：\n"
            "2017.09 - 2021.06 某某大学 计算机科学与技术 本科\n\n"
            "证书 / 奖项：\n"
            "- CET-6\n"
            "\n（本条为 MOCK 演示输出，配置真实 API Key 后由模型生成）"
        )
    # 5. 其他（Agent 对话等）
    return "（MOCK）你好，我是简历优化助手。当前为演示模式，配置 API Key 后可提供真实分析与优化服务。"


@lru_cache(maxsize=1)
def get_llm():
    """获取当前 Provider 的 ChatOpenAI 客户端（单例缓存）。"""
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as e:
        raise ImportError(
            "缺少依赖 langchain-openai，请执行: pip install langchain-openai"
        ) from e

    api_key = LLM_CONFIG["api_key"]
    if not api_key:
        raise ValueError(
            f"未配置 {LLM_CONFIG['provider']} 的 API Key，"
            f"请在 .env 或环境变量中设置，例如 "
            f"{LLM_CONFIG['provider'].upper()}_API_KEY=..."
        )

    logger.info(
        "初始化 LLM 客户端: %s (%s) model=%s",
        LLM_CONFIG["provider_label"],
        LLM_CONFIG["base_url"],
        LLM_CONFIG["model_name"],
    )
    return ChatOpenAI(
        model=LLM_CONFIG["model_name"],
        api_key=api_key,
        base_url=LLM_CONFIG["base_url"],
        temperature=LLM_CONFIG["temperature"],
        max_tokens=LLM_CONFIG["max_tokens"],
        timeout=LLM_CONFIG["timeout"],
    )


def chat(prompt: str, system: str | None = None) -> str:
    """发送单轮对话请求，返回模型文本响应。"""
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
    """发送对话请求并解析返回的 JSON 对象。"""
    raw = chat(prompt, system)
    return parse_llm_json(raw)


def chat_json_array(prompt: str, system: str | None = None) -> list[Any]:
    """发送对话请求并解析返回的 JSON 数组。"""
    raw = chat(prompt, system)
    return parse_llm_json_array(raw)


def parse_llm_json(response_text: str) -> dict[str, Any]:
    """解析大模型返回的 JSON 对象，带容错（剥离代码块、提取首个对象）。"""
    if not response_text:
        raise ValueError("模型返回内容为空")

    text = response_text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        try:
            result = json.loads(brace.group(0))
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError as e:
            raise ValueError(f"无法解析模型返回的 JSON: {e}\n原文: {response_text}")

    raise ValueError(f"模型返回内容不含有效 JSON 对象:\n{response_text}")


def parse_llm_json_array(response_text: str) -> list[Any]:
    """解析大模型返回的 JSON 数组，带容错。"""
    if not response_text:
        raise ValueError("模型返回内容为空")

    text = response_text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    bracket = re.search(r"\[.*\]", text, re.DOTALL)
    if bracket:
        try:
            result = json.loads(bracket.group(0))
            if isinstance(result, list):
                return result
        except json.JSONDecodeError as e:
            raise ValueError(f"无法解析模型返回的 JSON 数组: {e}\n原文: {response_text}")

    raise ValueError(f"模型返回内容不含有效 JSON 数组:\n{response_text}")
