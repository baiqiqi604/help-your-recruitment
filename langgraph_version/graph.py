"""
LangGraph 简历优化流水线（图编排核心）

将传统线性流程改造成 LangGraph StateGraph：
    简历文本 + JD 文本 → 分析 JD → 优化 → LLM 审核 →（不达标则循环重试）→ 输出

流程节点：
    load_resume   校验/归一化输入简历与 JD 文本
    analyze_jd    调用大模型分析岗位需求（结构化 JSON）
    optimize      调用大模型按 JD 优化简历 + 构建匹配关系表
    review        LLM 审核优化结果是否达标（pass/fail + 意见）
    write_output  汇总最终输出结果

条件边：
    review 判 pass              → write_output → END
    review 判 fail 且 attempts<3 → 回到 optimize（attempts+1）
    review 判 fail 且 attempts>=3 → END（重试超限）

依赖：langgraph>=0.2.0、langgraph-checkpoint>=2.0.0
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, TypedDict

import llm_client

logger = logging.getLogger(__name__)

# langgraph 懒加载（避免未安装依赖时模块导入即崩溃）
try:
    from langgraph.graph import StateGraph, END  # noqa: F401
except ImportError:  # pragma: no cover - 依赖缺失时给出明确提示
    StateGraph = None  # type: ignore[assignment]
    END = "END"
    _LANGGRAPH_IMPORT_ERROR = None
else:
    _LANGGRAPH_IMPORT_ERROR = None


# 最大重试次数（review 不达标时最多回到 optimize 的次数）
MAX_ATTEMPTS = 3

# 文本安全长度（防止超出模型上下文）
MAX_RESUME_CHARS = 12000
MAX_JD_CHARS = 6000
MAX_OPTIMIZED_CHARS = 12000


# ──────────────────────────────────────────────
# State 定义（TypedDict）
# ──────────────────────────────────────────────
class OptimizeState(TypedDict, total=False):
    """Graph 状态（节点间流转的共享字典）。

    核心字段：
        resume_text:    简历纯文本
        jd_text:        岗位描述全文
        jd_analysis:    岗位分析结果（来自 analyze_jd 节点）
        optimized_text: 优化后的简历全文
        matching_table: 简历-JD 匹配关系表（列表）
        error:          处理过程中的错误信息
        attempts:       当前重试次数（review 不达标时累加）
        review_verdict: 内部字段，review 节点的审核结论 {"pass": bool, "feedback": str}
    """

    resume_text: str
    jd_text: str
    jd_analysis: dict[str, Any]
    optimized_text: str
    matching_table: list[dict[str, Any]]
    error: str
    attempts: int
    review_verdict: dict[str, Any]


# ──────────────────────────────────────────────
# 节点实现
# ──────────────────────────────────────────────
def load_resume(state: OptimizeState) -> dict[str, Any]:
    """节点：校验并归一化输入（简历文本 + JD 文本）。"""
    resume_text = (state.get("resume_text") or "").strip()
    jd_text = (state.get("jd_text") or "").strip()

    if not resume_text:
        return {"error": "简历文本不能为空"}
    if not jd_text:
        return {"error": "岗位描述（JD）不能为空"}

    # 超长截断，保护模型上下文
    if len(resume_text) > MAX_RESUME_CHARS:
        logger.warning("简历过长（%d 字），截断到 %d 字", len(resume_text), MAX_RESUME_CHARS)
        resume_text = resume_text[:MAX_RESUME_CHARS]
    if len(jd_text) > MAX_JD_CHARS:
        logger.warning("JD 过长（%d 字），截断到 %d 字", len(jd_text), MAX_JD_CHARS)
        jd_text = jd_text[:MAX_JD_CHARS]

    logger.info("load_resume：简历 %d 字，JD %d 字", len(resume_text), len(jd_text))
    return {"resume_text": resume_text, "jd_text": jd_text, "error": ""}


def analyze_jd(state: OptimizeState) -> dict[str, Any]:
    """节点：调用大模型分析岗位需求，得到结构化 jd_analysis。"""
    from jd_analyzer import analyze_jd as analyze_jd_text

    logger.info("analyze_jd：开始分析岗位需求...")
    try:
        analysis = analyze_jd_text(state["jd_text"])
    except Exception as e:  # noqa: BLE001
        logger.exception("岗位分析失败")
        return {"error": f"岗位分析失败: {e}"}
    return {"jd_analysis": analysis}


def optimize(state: OptimizeState) -> dict[str, Any]:
    """节点：按 JD 分析结果优化简历，并构建匹配关系表。"""
    from content_optimizer import build_matching_table, optimize_resume_content

    resume_text = state["resume_text"]
    jd_analysis = state.get("jd_analysis") or {}

    logger.info("optimize：第 %d 轮优化...", state.get("attempts", 0) + 1)
    try:
        optimized_text = optimize_resume_content(resume_text, jd_analysis).strip()
    except Exception as e:  # noqa: BLE001
        logger.exception("简历优化失败")
        return {"error": f"简历优化失败: {e}"}

    # 构建匹配关系表（失败不阻塞主流程，置空即可）
    try:
        matching_table = build_matching_table(resume_text, jd_analysis)
    except Exception as e:  # noqa: BLE001
        logger.warning("匹配关系表构建失败: %s", e)
        matching_table = []

    if len(optimized_text) > MAX_OPTIMIZED_CHARS:
        optimized_text = optimized_text[:MAX_OPTIMIZED_CHARS]

    logger.info("optimize：完成，输出 %d 字", len(optimized_text))
    return {"optimized_text": optimized_text, "matching_table": matching_table, "error": ""}


# 审核 Prompt 模板
REVIEW_PROMPT = """你是一位严格的简历审核专家。请审核优化后的简历是否达标。

【目标岗位分析】
- 核心技能要求：{required_skills}
- 加分技能：{preferred_skills}
- 岗位职责：{responsibilities}
- 经验要求：{experience_years}

【原始简历】
{resume_text}

【优化后简历】
{optimized_text}

请从以下维度评估优化结果是否达标：
1. 是否突出与目标岗位匹配的经历与核心技能
2. 是否基于真实经历、未虚构/夸大（遵守"不编造"原则）
3. 是否存在明显错误、遗漏、乱码或低质量输出
4. 结构是否清晰、ATS 友好

请以 JSON 格式返回：
{{"pass": true 或 false, "feedback": "具体的审核意见（指出不足与修改方向）"}}
只返回 JSON，不要其他内容。"""


def review(state: OptimizeState) -> dict[str, Any]:
    """节点：LLM 审核优化结果是否达标，返回 pass/fail + 意见。"""
    optimized_text = (state.get("optimized_text") or "").strip()
    if not optimized_text:
        return {"review_verdict": {"pass": False, "feedback": "优化结果为空"}}

    jd_analysis = state.get("jd_analysis") or {}
    resume_text = (state.get("resume_text") or "")[:MAX_RESUME_CHARS]
    optimized_text = optimized_text[:MAX_OPTIMIZED_CHARS]

    prompt = REVIEW_PROMPT.format(
        required_skills=", ".join(jd_analysis.get("required_skills", [])) or "未提供",
        preferred_skills=", ".join(jd_analysis.get("preferred_skills", [])) or "未提供",
        responsibilities=", ".join(jd_analysis.get("responsibilities", [])) or "未提供",
        experience_years=jd_analysis.get("experience_years", "") or "未提供",
        resume_text=resume_text,
        optimized_text=optimized_text,
    )

    logger.info("review：调用 LLM 审核优化结果...")
    try:
        raw = llm_client.chat_json(prompt)
    except Exception as e:  # noqa: BLE001
        logger.warning("审核调用失败: %s，默认按不达标处理", e)
        raw = {}

    passed = bool(raw.get("pass", False))
    feedback = str(raw.get("feedback", "")).strip()

    if not passed:
        # 不达标：尝试次数 +1，供条件边判断是否继续重试
        attempts = state.get("attempts", 0) + 1
        logger.info("review：未达标（第 %d 次）feedback=%s", attempts, feedback[:100])
        return {
            "review_verdict": {"pass": False, "feedback": feedback},
            "attempts": attempts,
        }

    logger.info("review：审核通过")
    return {"review_verdict": {"pass": True, "feedback": feedback}, "error": ""}


def write_output(state: OptimizeState) -> dict[str, Any]:
    """节点：汇总最终输出（写入最终状态快照，供 run_optimize 返回）。"""
    logger.info(
        "write_output：优化文本 %d 字，匹配表 %d 条",
        len(state.get("optimized_text", "")),
        len(state.get("matching_table", [])),
    )
    return {}


def route_after_stage(state: OptimizeState) -> str:
    """Stop the graph immediately when an upstream stage reports an error."""
    if state.get("error"):
        logger.warning("Stage failed; stopping workflow: %s", state["error"])
        return END
    return "continue"


# ──────────────────────────────────────────────
# 条件边路由
# ──────────────────────────────────────────────
def route_after_review(state: OptimizeState) -> str:
    """review 后的条件边：
    - pass                → write_output
    - fail 且 attempts<3  → optimize（重试）
    - fail 且 attempts>=3 → END（重试超限）
    """
    verdict = state.get("review_verdict") or {"pass": False}
    if verdict.get("pass"):
        logger.info("条件边：审核通过 → write_output")
        return "write_output"

    attempts = state.get("attempts", 0)
    if attempts < MAX_ATTEMPTS:
        logger.info("条件边：未达标（第 %d 次）→ 回到 optimize 重试", attempts)
        return "optimize"

    logger.info("条件边：重试次数超限（%d 次）→ END", attempts)
    return END


# ──────────────────────────────────────────────
# 构建图
# ──────────────────────────────────────────────
@lru_cache(maxsize=1)
def build_graph():
    """构建并编译 LangGraph StateGraph（单例缓存）。

    Returns:
        CompiledStateGraph（langgraph 编译后的图对象）
    """
    if StateGraph is None:
        raise ImportError(
            "缺少依赖 langgraph，请执行: pip install langgraph langgraph-checkpoint"
        )

    graph = StateGraph(OptimizeState)

    # 注册节点
    graph.add_node("load_resume", load_resume)
    graph.add_node("analyze_jd", analyze_jd)
    graph.add_node("optimize", optimize)
    graph.add_node("review", review)
    graph.add_node("write_output", write_output)

    # 入口
    graph.set_entry_point("load_resume")

    # Stop immediately after a failed stage instead of retrying with invalid state.
    graph.add_conditional_edges(
        "load_resume",
        route_after_stage,
        {"continue": "analyze_jd", END: END},
    )
    graph.add_conditional_edges(
        "analyze_jd",
        route_after_stage,
        {"continue": "optimize", END: END},
    )
    graph.add_conditional_edges(
        "optimize",
        route_after_stage,
        {"continue": "review", END: END},
    )

    # 条件边：review → (write_output | optimize | END)
    graph.add_conditional_edges(
        "review",
        route_after_review,
        {"write_output": "write_output", "optimize": "optimize", END: END},
    )

    # 终点
    graph.add_edge("write_output", END)

    logger.info("build_graph：LangGraph StateGraph 编译完成")
    return graph.compile()


def run_optimize(resume_text: str, jd_text: str) -> dict[str, Any]:
    """运行完整优化流水线。

    Args:
        resume_text: 简历纯文本
        jd_text: 岗位描述全文

    Returns:
        dict，包含 resume_text / jd_text / jd_analysis / optimized_text /
        matching_table / error / attempts 等完整状态快照
    """
    graph = build_graph()
    initial_state: OptimizeState = {
        "resume_text": resume_text,
        "jd_text": jd_text,
        "jd_analysis": {},
        "optimized_text": "",
        "matching_table": [],
        "error": "",
        "attempts": 0,
    }
    logger.info("run_optimize：开始执行 LangGraph 流水线")
    result = graph.invoke(initial_state)

    # 规整输出（保证调用方拿到的字段齐全）
    output = dict(result)
    output.setdefault("optimized_text", "")
    output.setdefault("matching_table", [])
    output.setdefault("jd_analysis", {})
    output.setdefault("error", "")
    return output


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    sample_resume = "张三，3年Python后端开发经验，熟悉Django、MySQL、Redis。"
    sample_jd = "岗位：Python后端开发工程师，3年以上经验，熟悉Django/Flask、MySQL、Redis、Docker。"
    result = run_optimize(sample_resume, sample_jd)
    print("=" * 50)
    print("优化结果：", result.get("optimized_text", "")[:300])
    print("匹配表条数：", len(result.get("matching_table", [])))
    print("错误信息：", result.get("error", ""))
