"""
LangChain Tool-calling Agent 模块（核心）

职责：
1. 组合 岗位检索 / 优质岗位 / 岗位分析 / 简历优化 四个工具
2. 用 create_tool_calling_agent 构建 Tool-calling Agent
3. 会话级记忆 ConversationBufferMemory（按 session_id 缓存）
4. 导出 get_agent() 单例 与 chat_with_agent() 对话入口

依赖：langchain、langchain-openai（经 llm_client）
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain.memory import ConversationBufferMemory
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.tools import tool

import content_optimizer
import jd_analyzer
import jd_knowledge_base
import llm_client

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 系统提示词
# ──────────────────────────────────────────────
SYSTEM_PROMPT = """你是一位专业的「简历优化 + 求职」智能 Agent。

你拥有以下能力：
1. search_jds_tool：在岗位知识库中按语义检索岗位
2. get_premium_jobs_tool：获取优质岗位（大厂或高频）列表
3. analyze_jd_tool：分析岗位描述，提取技能 / 职责 / 经验要求
4. optimize_resume_tool：根据岗位分析结果优化简历内容

回答要求：
- 全程使用中文，语气专业、友好、简洁
- 检索岗位时，主动总结岗位要点（公司、薪资、城市、平台、JD 摘要）
- 优化简历时，先说明优化思路与要点，再给出优化后的简历全文
- 不要编造工具返回之外的信息；不确定时明确说明"""


# ──────────────────────────────────────────────
# 工具定义
# ──────────────────────────────────────────────
@tool
def search_jds_tool(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """在岗位知识库中按语义检索岗位。

    Args:
        query: 检索关键词（如 "Python 后端 北京"）
        top_k: 返回条数（默认 5）

    Returns:
        岗位列表（含 id/title/company/city/salary/jd_text/url/platform）
    """
    return jd_knowledge_base.search_jds(query, top_k=top_k)


@tool
def get_premium_jobs_tool(limit: int = 20) -> list[dict[str, Any]]:
    """获取优质岗位列表（大厂或高频岗位）。

    Args:
        limit: 返回条数（默认 20）

    Returns:
        优质岗位列表
    """
    return jd_knowledge_base.get_premium_jobs(limit=limit)


@tool
def analyze_jd_tool(jd_text: str) -> dict[str, Any]:
    """分析岗位描述文本，提取结构化要求。

    Args:
        jd_text: 岗位描述全文

    Returns:
        包含 required_skills / preferred_skills / responsibilities /
        experience_years / keywords 的字典
    """
    return jd_analyzer.analyze_jd(jd_text)


@tool
def optimize_resume_tool(resume_text: str, jd_analysis: dict[str, Any]) -> str:
    """根据岗位分析结果优化简历文本。

    Args:
        resume_text: 简历全文
        jd_analysis: 岗位分析结果（来自 analyze_jd_tool）

    Returns:
        优化后的简历全文
    """
    return content_optimizer.optimize_resume_content(resume_text, jd_analysis)


TOOLS = [
    search_jds_tool,
    get_premium_jobs_tool,
    analyze_jd_tool,
    optimize_resume_tool,
]


# ──────────────────────────────────────────────
# Agent 构建（单例）
# ──────────────────────────────────────────────
def _build_prompt() -> ChatPromptTemplate:
    """构造 Tool-calling Agent 提示词模板。

    模板必须包含 chat_history（记忆）与 agent_scratchpad（推理过程）占位符。
    """
    return ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ]
    )


@lru_cache(maxsize=1)
def get_agent():
    """获取 Tool-calling Agent 单例（无记忆，供各会话复用）。

    Returns:
        langchain.agents.Agent 实例
    """
    llm = llm_client.get_llm()
    prompt = _build_prompt()
    agent = create_tool_calling_agent(llm, TOOLS, prompt)
    logger.info(
        "Tool-calling Agent 已创建（provider=%s model=%s）",
        llm_client.LLM_CONFIG["provider"],
        llm_client.LLM_CONFIG["model_name"],
    )
    return agent


# ──────────────────────────────────────────────
# 会话级记忆与对话入口
# ──────────────────────────────────────────────
# 会话缓存：session_id → AgentExecutor（含独立 ConversationBufferMemory）
_sessions: dict[str, AgentExecutor] = {}


def _get_session_executor(session_id: str) -> AgentExecutor:
    """按 session_id 获取（或创建）会话级 AgentExecutor。"""
    if session_id not in _sessions:
        memory = ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True,
        )
        _sessions[session_id] = AgentExecutor(
            agent=get_agent(),
            tools=TOOLS,
            memory=memory,
            verbose=False,
            max_iterations=6,
            handle_parsing_errors=True,
        )
        logger.info("创建会话记忆: %s", session_id)
    return _sessions[session_id]


def chat_with_agent(user_input: str, session_id: str) -> str:
    """与 Agent 对话（带会话级记忆）。

    Args:
        user_input: 用户输入
        session_id: 会话标识，同一会话共享记忆（dict 缓存）

    Returns:
        Agent 回复文本
    """
    if not user_input or not user_input.strip():
        return "请输入有效内容后再试。"

    # Mock 模式（无 API Key）：不构建真实 Agent，直接返回模拟回复
    if llm_client.mock_enabled():
        logger.info("[MOCK] 对话模式：返回模拟回复")
        return llm_client.chat(user_input)

    session_id = session_id or "default"
    try:
        executor = _get_session_executor(session_id)
        result = executor.invoke({"input": user_input.strip()})
        output = result.get("output")
        return str(output) if output else "（Agent 未返回有效内容）"
    except Exception as e:  # noqa: BLE001
        logger.exception("Agent 调用失败（session=%s）: %s", session_id, e)
        return f"抱歉，处理时出错了：{e}"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(chat_with_agent("你好，请帮我推荐 3 个 Python 后端岗位", "demo"))
