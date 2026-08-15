"""
定制化简历优化 LCEL 管道（LangChain 版）

把原「裸线性函数调用」升级为 LCEL（RunnableSequence，`|` 组合）：
    load → analyze → research → optimize → matching → review → interview → write

设计要点：
- 每个环节是普通函数，用 RunnableLambda 包成 LCEL 节点，`|` 顺序组合；
- 节点间通过共享 state dict 流转（与 langgraph 版 OptimizeState 字段对齐，
  便于两版并行开发时对照）；
- review 环节移植自 langgraph 版 graph.py：LLM 审核不达标时回退重新优化，
  最多重试 MAX_ATTEMPTS 次（对应 graph 版条件边「review → optimize」回路）；
- 整条链支持 .invoke() / .astream()（LCEL 天然能力）。

依赖：langchain_core.runnables（langchain 1.x）
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableLambda

from config import PATH_CONFIG
import llm_client

logger = logging.getLogger(__name__)

# 最大重试次数（review 不达标时最多回到 optimize 的次数，与 graph.py 对齐）
MAX_ATTEMPTS = 3

# 文本安全长度（防止超出模型上下文）
MAX_RESUME_CHARS = 12000
MAX_JD_CHARS = 6000
MAX_OPTIMIZED_CHARS = 12000

# 审核 Prompt 模板（移植自 graph.py）
REVIEW_PROMPT = """你是一位严格的简历审核专家。请审核优化后的简历是否达标。

【目标岗位分析】
- 岗位定位：{role_position}
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


# ──────────────────────────────────────────────
# LCEL 节点（普通函数，输入/输出均为共享 state dict）
# ──────────────────────────────────────────────
def _load(state: dict[str, Any]) -> dict[str, Any]:
    """load：校验并归一化输入（简历文本 + JD 文本 + 目标公司）。"""
    resume_text = (state.get("resume_text") or "").strip()
    jd_text = (state.get("jd_text") or "").strip()
    target_company = (state.get("target_company") or "").strip()

    if not resume_text:
        return {**state, "error": "简历文本不能为空"}
    if not jd_text:
        return {**state, "error": "岗位描述（JD）不能为空"}
    if not target_company:
        return {**state, "error": "目标公司名称不能为空"}

    if len(resume_text) > MAX_RESUME_CHARS:
        logger.warning("简历过长（%d 字），截断到 %d 字", len(resume_text), MAX_RESUME_CHARS)
        resume_text = resume_text[:MAX_RESUME_CHARS]
    if len(jd_text) > MAX_JD_CHARS:
        logger.warning("JD 过长（%d 字），截断到 %d 字", len(jd_text), MAX_JD_CHARS)
        jd_text = jd_text[:MAX_JD_CHARS]

    logger.info("load：简历 %d 字，JD %d 字，目标公司=%s", len(resume_text), len(jd_text), target_company)
    return {
        **state,
        "resume_text": resume_text,
        "jd_text": jd_text,
        "target_company": target_company,
        "error": "",
    }


def _analyze(state: dict[str, Any]) -> dict[str, Any]:
    """analyze：调用大模型拆解岗位需求（要求分级/岗位类型/隐含目标/风险项）。"""
    if state.get("error"):
        return state  # 前置节点已失败，短路（对齐 graph 版条件边语义）
    from jd_analyzer import analyze_jd as analyze_jd_text

    logger.info("analyze：开始拆解岗位需求...")
    try:
        analysis = analyze_jd_text(state["jd_text"], resume_text=state.get("resume_text", ""))
    except Exception as e:  # noqa: BLE001
        logger.exception("岗位分析失败")
        return {**state, "error": f"岗位分析失败: {e}"}
    return {**state, "jd_analysis": analysis}


def _research(state: dict[str, Any]) -> dict[str, Any]:
    """research：分析目标公司并给出求职判断。"""
    if state.get("error"):
        return state  # 短路
    from company_researcher import research_company as research

    logger.info("research：分析目标公司 %s ...", state.get("target_company", ""))
    try:
        company_research = research(
            target_company=state["target_company"],
            jd_analysis=state.get("jd_analysis") or {},
            resume_text=state.get("resume_text", ""),
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("公司分析失败")
        return {**state, "error": f"公司分析失败: {e}"}
    return {**state, "company_research": company_research}


def _optimize(state: dict[str, Any]) -> dict[str, Any]:
    """optimize：按 JD 分析结果定制简历内容。"""
    if state.get("error"):
        return state  # 短路
    from content_optimizer import optimize_resume_content

    resume_text = state["resume_text"]
    jd_analysis = state.get("jd_analysis") or {}

    logger.info("optimize：第 %d 轮优化...", state.get("attempts", 0) + 1)
    try:
        optimized_text = optimize_resume_content(resume_text, jd_analysis).strip()
    except Exception as e:  # noqa: BLE001
        logger.exception("简历优化失败")
        return {**state, "error": f"简历优化失败: {e}"}

    if len(optimized_text) > MAX_OPTIMIZED_CHARS:
        optimized_text = optimized_text[:MAX_OPTIMIZED_CHARS]

    logger.info("optimize：完成，输出 %d 字", len(optimized_text))
    return {**state, "optimized_text": optimized_text}


def _matching(state: dict[str, Any]) -> dict[str, Any]:
    """matching：构建简历-JD 四级匹配关系表（失败不阻塞主流程，置空即可）。"""
    if state.get("error"):
        return state  # 短路
    from content_optimizer import build_matching_table

    try:
        matching_table = build_matching_table(state["resume_text"], state.get("jd_analysis") or {})
    except Exception as e:  # noqa: BLE001
        logger.warning("匹配关系表构建失败: %s", e)
        matching_table = []
    return {**state, "matching_table": matching_table}


def _review(state: dict[str, Any]) -> dict[str, Any]:
    """review：LLM 审核优化结果，不达标时回退重新优化（≤ MAX_ATTEMPTS 次）。

    对应 langgraph 版 graph.py 的「review 条件边 → optimize 回路」：
    LCEL 为线性管道，重试逻辑收敛在本节点内实现，对外仍是单一链。
    """
    optimized_text = (state.get("optimized_text") or "").strip()
    if not optimized_text:
        return {**state, "review_verdict": {"pass": False, "feedback": "优化结果为空"}}
    if state.get("error"):
        return state  # 前置节点已失败，短路

    jd_analysis = state.get("jd_analysis") or {}
    resume_text = (state.get("resume_text") or "")[:MAX_RESUME_CHARS]

    for attempt in range(MAX_ATTEMPTS + 1):
        prompt = REVIEW_PROMPT.format(
            role_position=jd_analysis.get("role_position", "") or "未提供",
            required_skills=", ".join(jd_analysis.get("required_skills", [])) or "未提供",
            preferred_skills=", ".join(jd_analysis.get("preferred_skills", [])) or "未提供",
            responsibilities=", ".join(jd_analysis.get("responsibilities", [])) or "未提供",
            experience_years=jd_analysis.get("experience_years", "") or "未提供",
            resume_text=resume_text,
            optimized_text=optimized_text[:MAX_OPTIMIZED_CHARS],
        )

        logger.info("review：调用 LLM 审核优化结果（第 %d 次）...", attempt + 1)
        try:
            raw = llm_client.chat_json(prompt, mock_scenario="resume_review")
        except Exception as e:  # noqa: BLE001
            logger.warning("审核调用失败: %s，默认按不达标处理", e)
            raw = {}

        passed = bool(raw.get("pass", False))
        feedback = str(raw.get("feedback", "")).strip()

        if passed:
            logger.info("review：审核通过")
            return {
                **state,
                "review_verdict": {"pass": True, "feedback": feedback},
                "error": "",
            }

        attempts = state.get("attempts", 0) + 1
        logger.info("review：未达标（第 %d 次）feedback=%s", attempts, feedback[:100])
        state = {**state, "review_verdict": {"pass": False, "feedback": feedback}, "attempts": attempts}

        if attempt >= MAX_ATTEMPTS:
            break

        # 回退重新优化后继续审核
        state = _optimize(state)
        if state.get("error"):
            break
        optimized_text = (state.get("optimized_text") or "").strip()

    return state


def _interview(state: dict[str, Any]) -> dict[str, Any]:
    """interview：按岗位类型生成面试问题 + 生成完整面试建议。"""
    if state.get("error"):
        return state  # 短路
    from interview_advisor import build_interview_advice, generate_interview_questions

    jd_analysis = state.get("jd_analysis") or {}
    role_type = jd_analysis.get("role_type", "tech")
    resume_text = state.get("resume_text", "")
    target_company = state.get("target_company", "")

    try:
        questions = generate_interview_questions(role_type, jd_analysis, resume_text)
    except Exception as e:  # noqa: BLE001
        logger.warning("面试问题生成失败: %s", e)
        questions = []

    try:
        advice = build_interview_advice(
            target_company=target_company,
            jd_analysis=jd_analysis,
            resume_text=resume_text,
            company_research=state.get("company_research") or {},
            questions=questions,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("面试建议生成失败: %s", e)
        advice = ""

    logger.info("interview：问题 %d 条，建议 %d 字", len(questions), len(advice))
    return {**state, "interview_questions": questions, "interview_advice": advice}


def _sanitize_filename(name: str) -> str:
    """清洗文件名中的非法字符。"""
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "未知"


def _write(state: dict[str, Any]) -> dict[str, Any]:
    """write：生成定制化简历与面试建议 Word 文档。"""
    if state.get("error"):
        return state  # 前置节点已失败，短路（不再覆盖 error）
    from resume_writer import write_customized_resume, write_interview_advice_docx

    target_company = _sanitize_filename(state.get("target_company", "") or "未知公司")
    role_position = _sanitize_filename((state.get("jd_analysis") or {}).get("role_position", "") or "目标岗位")

    out_dir = Path(PATH_CONFIG["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    resume_docx_path = ""
    advice_docx_path = ""
    error = ""

    optimized_text = (state.get("optimized_text") or "").strip()
    if optimized_text:
        try:
            resume_docx_path = write_customized_resume(
                optimized_text, str(out_dir / f"定制化简历_{target_company}_{role_position}.docx")
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("定制化简历文档生成失败: %s", e)
            error = f"定制化简历文档生成失败: {e}"

    advice_text = (state.get("interview_advice") or "").strip()
    if advice_text:
        try:
            advice_docx_path = write_interview_advice_docx(
                advice_text, str(out_dir / f"面试建议_{target_company}_{role_position}.docx")
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("面试建议文档生成失败: %s", e)
            error = (error + "；" if error else "") + f"面试建议文档生成失败: {e}"

    logger.info(
        "write：简历文档=%s，面试建议文档=%s",
        resume_docx_path or "（未生成）",
        advice_docx_path or "（未生成）",
    )
    return {
        **state,
        "resume_docx_path": resume_docx_path,
        "advice_docx_path": advice_docx_path,
        "error": error,
    }


# ──────────────────────────────────────────────
# LCEL 管道组合（RunnableSequence）
# ──────────────────────────────────────────────
resume_chain = (
    RunnableLambda(_load)
    | RunnableLambda(_analyze)
    | RunnableLambda(_research)
    | RunnableLambda(_optimize)
    | RunnableLambda(_matching)
    | RunnableLambda(_review)
    | RunnableLambda(_interview)
    | RunnableLambda(_write)
)


def run_optimize(
    resume_text: str,
    jd_text: str,
    target_company: str = "",
) -> dict[str, Any]:
    """运行完整简历定制流水线（LCEL 管道入口）。

    Args:
        resume_text: 简历纯文本
        jd_text: 岗位描述全文
        target_company: 目标公司名称

    Returns:
        dict，包含 resume_text / jd_text / target_company / jd_analysis /
        company_research / optimized_text / matching_table / interview_questions /
        interview_advice / resume_docx_path / advice_docx_path / error / attempts 等
    """
    initial_state: dict[str, Any] = {
        "resume_text": resume_text,
        "jd_text": jd_text,
        "target_company": target_company,
        "jd_analysis": {},
        "company_research": {},
        "optimized_text": "",
        "matching_table": [],
        "interview_questions": [],
        "interview_advice": "",
        "resume_docx_path": "",
        "advice_docx_path": "",
        "error": "",
        "attempts": 0,
    }
    logger.info("run_optimize：开始执行 LCEL 流水线（公司=%s）", target_company)
    result = resume_chain.invoke(initial_state)

    # 规整输出（保证调用方拿到的字段齐全）
    output = dict(result)
    for key, default in (
        ("optimized_text", ""),
        ("matching_table", []),
        ("jd_analysis", {}),
        ("company_research", {}),
        ("interview_questions", []),
        ("interview_advice", ""),
        ("resume_docx_path", ""),
        ("advice_docx_path", ""),
        ("error", ""),
    ):
        output.setdefault(key, default)
    return output


if __name__ == "__main__":
    import json

    sample = {
        "resume_text": "张三，3年Python后端开发经验，熟悉Django、MySQL、Redis，曾负责订单系统设计。",
        "jd_text": "岗位：Python 后端开发工程师\n要求：3年以上经验，熟悉 Django/Flask、MySQL、Redis。",
        "target_company": "某科技有限公司",
    }
    print(json.dumps(run_optimize(**sample), ensure_ascii=False, indent=2))
