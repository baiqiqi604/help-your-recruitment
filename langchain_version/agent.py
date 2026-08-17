"""
LangChain Agent 模块（RAG 优先答疑模式）— 已迁移至 langchain 1.x

职责：
1. 组合 答疑检索 / 岗位分析 / 简历优化 三个工具
2. 用 langchain.agents.create_agent 构建 Tool-calling Agent（1.x API）
3. 多轮记忆：LangGraph checkpoint（MemorySaver），按 session_id / thread_id 隔离
4. 导出 get_agent() 单例 与 chat_with_agent() 对话入口

答疑流程（RAG 优先）：
    用户提问 → 先检索面试/笔试经验知识库（answer_from_kb）
    → 命中：整理参考答案回答 + 推荐 5 道相关题目
    → 未命中：大模型直接回答，注明"题库暂无收录，以下为模型回答"
简历/JD 相关请求走 analyze_jd / optimize_resume。

依赖：langchain、langchain-openai（经 llm_client）、langgraph（checkpoint 记忆）
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import content_optimizer
import jd_analyzer
from langchain.agents import create_agent
from langchain.tools import tool
from langgraph.checkpoint.memory import MemorySaver

import llm_client

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 系统提示词（RAG 优先答疑）
# ──────────────────────────────────────────────
SYSTEM_PROMPT = """你是一位专业的求职答疑助手，服务求职者与面试准备者。回答用户问题时遵循以下流程：

【答疑流程】
1. 用户提出问题时，**优先调用 answer_from_kb 工具**，从面试/笔试经验知识库检索相关内容。
2. 如果题库有命中（检索结果非空）：
   - 基于命中的参考答案，用通俗清晰的语言整理回答用户的问题。
   - 回答末尾**推荐 5 道相关题目**（从命中的题目中挑选，列出题目名称，可附简要考察点）。
3. 如果题库未命中（检索结果为空）：
   - 直接用你自身的大模型知识回答用户问题。
   - 回答开头注明「本题库暂无收录，以下为模型回答」。
4. 如果用户请求与简历优化 / 岗位分析相关（如"帮我改简历""分析这段 JD"），
   则调用 analyze_jd / optimize_resume 工具处理，不套用答疑流程。

【回答要求】
- 回答准确、克制、结构化，必要时用列表分点。
- 引用题库内容时基于检索结果，不要编造题目或答案。
- 推荐题目仅从检索命中的题目中选择。
- 不确定的内容明确说明。"""


# ──────────────────────────────────────────────
# 工具定义
# ──────────────────────────────────────────────
@tool
def answer_from_kb(question: str, top_k: int = 8) -> list[dict[str, Any]]:
    """从面试/笔试经验知识库（RAG）检索与 question 相关的题目及答案。

    用于回答用户提出的面试/求职/技术类问题：先查题库看是否已有收录，
    命中则返回题目、参考答案、考察点，供整理回答与推荐相关题目。
    """
    from retrievers import get_interview_retriever

    try:
        # 通过 LangChain Retriever 抽象检索（内部仍是标题索引→阈值→关键词→Rerank 链路）
        docs = get_interview_retriever(top_k=top_k, max_distance=0.45).invoke(question)
        hits = [dict(d.metadata) for d in docs]
        # 截断超长参考答案，控制送入 Agent 的 prompt 长度以加快响应
        for q in hits:
            ans = q.get("reference_answer") or ""
            if len(ans) > 600:
                q["reference_answer"] = ans[:600] + "…（已截断）"
        return hits
    except Exception as e:  # noqa: BLE001
        logger.warning("answer_from_kb 检索失败: %s", e)
        return []


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
    answer_from_kb,
    analyze_jd_tool,
    optimize_resume_tool,
]


# ──────────────────────────────────────────────
# Agent 构建（单例）
# ──────────────────────────────────────────────
@lru_cache(maxsize=1)
def get_agent():
    """获取带 MemorySaver 检查点的 Tool-calling Agent（单例，供各会话复用）。

    Returns:
        langchain.agents.create_agent 构建的 Agent 实例
    """
    llm = llm_client.get_llm()
    agent = create_agent(
        model=llm,
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=MemorySaver(),
    )
    logger.info(
        "RAG 优先答疑 Tool-calling Agent 已创建（provider=%s model=%s）",
        llm_client.LLM_CONFIG["provider"],
        llm_client.LLM_CONFIG["model_name"],
    )
    return agent


# ──────────────────────────────────────────────
# 会话级记忆与对话入口
# ──────────────────────────────────────────────
def _extract_reply_text(content: Any) -> str:
    """从 Agent 返回的 content 中安全提取纯文本（委托 llm_client 公共实现）。"""
    from llm_client import extract_text_content

    return extract_text_content(content)


def chat_with_agent(user_input: str, session_id: str) -> str:
    """与 Agent 对话（多轮记忆由 checkpoint 按 thread_id 隔离）。

    Args:
        user_input: 用户输入
        session_id: 会话标识，同一会话通过 thread_id 共享上下文

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
        agent = get_agent()
        result = agent.invoke(
            {"messages": [{"role": "user", "content": user_input.strip()}]},
            config={"configurable": {"thread_id": session_id}},
        )
        messages = result.get("messages") or []
        if not messages:
            return "（Agent 未返回有效内容）"
        return _extract_reply_text(messages[-1].content)
    except Exception as e:  # noqa: BLE001
        logger.exception("Agent 调用失败（session=%s）: %s", session_id, e)
        return f"抱歉，处理时出错了：{e}"


async def astream_chat(user_input: str, session_id: str):
    """Agent 流式对话：逐块产出回复文本（async generator，SSE 用，与 langgraph 版对齐）。

    通过 create_agent 的 astream_events 监听模型流式事件
    （on_chat_model_stream），只产出最终回复的文本增量。

    Yields:
        文本增量片段（str）
    """
    if not user_input or not user_input.strip():
        yield "（请输入内容后再发送）"
        return

    if llm_client.mock_enabled():
        logger.info("[MOCK] 流式对话：返回模拟回复")
        reply = llm_client.chat(user_input)
        for i in range(0, len(reply), 12):
            yield reply[i : i + 12]
        return

    agent = get_agent()
    config = {"configurable": {"thread_id": session_id or "default"}}
    logger.info("astream_chat：session=%s 收到输入 %d 字", session_id, len(user_input))

    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": user_input.strip()}]},
        config=config,
        version="v2",
    ):
        if event["event"] == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            if chunk and chunk.content:
                yield chunk.content


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(chat_with_agent("什么是RAG？", "demo"))
