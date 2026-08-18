"""
LangGraph 简历定制流水线（图编排核心，依据《定制化简历大师》Skill）

流程：
    简历 + JD + 目标公司 → 拆解岗位 → 公司分析/判断 → 优化 → LLM 审核
    →（不达标则循环重试）→ 面试建议 → 输出定制化简历与面试建议 Word 文档

节点：
    load_resume        校验/归一化输入（简历、JD、目标公司）
    analyze_jd         调用大模型拆解岗位（要求分级/岗位类型/隐含目标/风险项）
    research_company   分析目标公司公开信息并给出求职判断
    optimize           按 JD 定制简历 + 构建四级匹配关系表
    review             LLM 审核优化结果是否达标（pass/fail + 意见）
    interview          按岗位类型生成面试问题 + 生成完整面试建议
    write_output       生成定制化简历与面试建议 Word 文档

条件边：
    review 判 pass              → interview → write_output → END
    review 判 fail 且 attempts<3 → optimize（回到 optimize，attempts+1）
    review 判 fail 且 attempts>=3 → interview → write_output → END（超限仍必产出结果）

默认交付物（SKILL）：
    定制化简历_公司名_岗位名.docx
    面试建议_公司名_岗位名.docx

依赖：langgraph>=0.2.0、langgraph-checkpoint>=2.0.0
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, TypedDict

import llm_client

logger = logging.getLogger(__name__)

# langgraph 懒加载（避免未安装依赖时模块导入即崩溃）
try:
    from langgraph.graph import END, StateGraph  # noqa: F401
except ImportError:  # pragma: no cover - 依赖缺失时给出明确提示
    StateGraph = None  # type: ignore[assignment]
    END = "END"
    _LANGGRAPH_IMPORT_ERROR = None
else:
    _LANGGRAPH_IMPORT_ERROR = None


# 最大重试次数（review 不达标时最多回到 optimize 的次数）
# 说明：当前 deepseek-chat 单次调用快（~7s），3 次重试仅多耗时约 1 分钟，
# 恢复完整重试以保障审核质量（review 不达标时最多回退优化 3 次）。
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
        resume_text:        简历纯文本
        jd_text:            岗位描述全文
        target_company:     目标公司名称
        jd_analysis:        岗位拆解结果（analyze_jd 节点产出）
        company_research:   公司分析/求职判断（research_company 节点产出）
        optimized_text:     优化后的简历全文
        matching_table:     简历-JD 匹配关系表（四级强度）
        interview_questions: 面试问题清单（interview 节点产出）
        interview_advice:   面试建议全文（Markdown）
        resume_docx_path:   定制化简历 Word 文档路径
        advice_docx_path:   面试建议 Word 文档路径
        photo_base64:       用户上传的照片（data URI / 纯 base64，可选），
                            由 write_output 写入简历文档
        error:              处理过程中的错误信息
        attempts:           当前重试次数（review 不达标时累加）
        review_verdict:     review 节点审核结论 {"pass": bool, "feedback": str}
    """

    resume_text: str
    jd_text: str
    target_company: str
    jd_analysis: dict[str, Any]
    company_research: dict[str, Any]
    optimized_text: str
    matching_table: list[dict[str, Any]]
    interview_questions: list[dict[str, str]]
    interview_advice: str
    resume_docx_path: str
    resume_html_path: str          # HTML 简历路径（resume-formatter Skill 产出）
    resume_yaml_path: str          # 结构化 YAML 数据路径
    resume_check_report: str       # 简历质量检查报告（Markdown）
    advice_docx_path: str
    photo_base64: str
    error: str
    attempts: int
    review_verdict: dict[str, Any]


# ──────────────────────────────────────────────
# 节点实现
# ──────────────────────────────────────────────
def load_resume(state: OptimizeState) -> dict[str, Any]:
    """节点：校验并归一化输入（简历文本 + JD 文本 + 目标公司）。"""
    resume_text = (state.get("resume_text") or "").strip()
    jd_text = (state.get("jd_text") or "").strip()
    target_company = (state.get("target_company") or "").strip()

    if not resume_text:
        return {"error": "简历文本不能为空"}
    if not jd_text:
        return {"error": "岗位描述（JD）不能为空"}
    if not target_company:
        return {"error": "目标公司名称不能为空"}

    # 超长截断，保护模型上下文
    if len(resume_text) > MAX_RESUME_CHARS:
        logger.warning("简历过长（%d 字），截断到 %d 字", len(resume_text), MAX_RESUME_CHARS)
        resume_text = resume_text[:MAX_RESUME_CHARS]
    if len(jd_text) > MAX_JD_CHARS:
        logger.warning("JD 过长（%d 字），截断到 %d 字", len(jd_text), MAX_JD_CHARS)
        jd_text = jd_text[:MAX_JD_CHARS]

    logger.info("load_resume：简历 %d 字，JD %d 字，目标公司=%s", len(resume_text), len(jd_text), target_company)
    return {"resume_text": resume_text, "jd_text": jd_text, "target_company": target_company, "error": ""}


def analyze_jd(state: OptimizeState) -> dict[str, Any]:
    """节点：调用大模型拆解岗位需求（要求分级/岗位类型/隐含目标/风险项）。"""
    from jd_analyzer import analyze_jd as analyze_jd_text

    logger.info("analyze_jd：开始拆解岗位需求...")
    try:
        analysis = analyze_jd_text(state["jd_text"], resume_text=state.get("resume_text", ""))
    except Exception as e:  # noqa: BLE001
        logger.exception("岗位分析失败")
        return {"error": f"岗位分析失败: {e}"}
    return {"jd_analysis": analysis}


def research_company(state: OptimizeState) -> dict[str, Any]:
    """节点：分析目标公司并给出求职判断。"""
    from company_researcher import research_company as research

    logger.info("research_company：分析目标公司 %s ...", state.get("target_company", ""))
    try:
        company_research = research(
            target_company=state["target_company"],
            jd_analysis=state.get("jd_analysis") or {},
            resume_text=state.get("resume_text", ""),
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("公司分析失败")
        return {"error": f"公司分析失败: {e}"}
    return {"company_research": company_research}


def optimize(state: OptimizeState) -> dict[str, Any]:
    """节点：按 JD 分析结果定制简历，并构建四级匹配关系表。"""
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


def review(state: OptimizeState) -> dict[str, Any]:
    """节点：LLM 审核优化结果是否达标，返回 pass/fail + 意见。"""
    optimized_text = (state.get("optimized_text") or "").strip()
    if not optimized_text:
        return {"review_verdict": {"pass": False, "feedback": "优化结果为空"}}

    jd_analysis = state.get("jd_analysis") or {}
    resume_text = (state.get("resume_text") or "")[:MAX_RESUME_CHARS]
    optimized_text = optimized_text[:MAX_OPTIMIZED_CHARS]

    prompt = REVIEW_PROMPT.format(
        role_position=jd_analysis.get("role_position", "") or "未提供",
        required_skills=", ".join(jd_analysis.get("required_skills", [])) or "未提供",
        preferred_skills=", ".join(jd_analysis.get("preferred_skills", [])) or "未提供",
        responsibilities=", ".join(jd_analysis.get("responsibilities", [])) or "未提供",
        experience_years=jd_analysis.get("experience_years", "") or "未提供",
        resume_text=resume_text,
        optimized_text=optimized_text,
    )

    logger.info("review：调用 LLM 审核优化结果...")
    try:
        raw = llm_client.chat_json(prompt, mock_scenario="resume_review")
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


def interview(state: OptimizeState) -> dict[str, Any]:
    """节点：按岗位类型生成面试问题 + 生成完整面试建议。"""
    from interview_advisor import build_interview_advice, generate_interview_questions

    jd_analysis = state.get("jd_analysis") or {}
    role_type = jd_analysis.get("role_type", "tech")
    resume_text = state.get("resume_text", "")
    target_company = state.get("target_company", "")

    # 1. 生成面试问题清单（失败不阻塞，置空）
    try:
        questions = generate_interview_questions(role_type, jd_analysis, resume_text)
    except Exception as e:  # noqa: BLE001
        logger.warning("面试问题生成失败: %s", e)
        questions = []

    # 2. 生成完整面试建议
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
    return {"interview_questions": questions, "interview_advice": advice}


def _sanitize_filename(name: str) -> str:
    """清洗文件名中的非法字符。"""
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "未知"


def write_output(state: OptimizeState) -> dict[str, Any]:
    """节点：生成定制化简历（Word + HTML + YAML）与面试建议 Word 文档。

    新增产出（对应《resume-formatter》Skill）：
    - resume_html_path：精美 HTML 简历（浏览器打开 Ctrl+P 可导出 PDF）
    - resume_yaml_path：结构化数据 YAML（便于后续迭代修改）
    - resume_check_report：简历质量检查清单报告（Markdown）
    """
    from resume_writer import (
        write_customized_resume,
        write_customized_resume_html,
        write_interview_advice_docx,
    )

    from config import PATH_CONFIG

    target_company = _sanitize_filename(state.get("target_company", "") or "未知公司")
    role_position = _sanitize_filename((state.get("jd_analysis") or {}).get("role_position", "") or "目标岗位")

    # 模板风格：统一使用 classic（匹配用户提供的 PDF 简历版式）
    # 如需按岗位类型切换，可在此处恢复 product→modern / tech→tech 等逻辑
    default_template = "classic"

    out_dir = Path(PATH_CONFIG["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    resume_docx_path = ""
    resume_html_path = ""
    resume_yaml_path = ""
    resume_check_report = ""
    advice_docx_path = ""
    error = ""

    optimized_text = (state.get("optimized_text") or "").strip()
    if optimized_text:
        # 1) 原 Word 输出
        try:
            resume_docx_path = write_customized_resume(
                optimized_text, str(out_dir / f"定制化简历_{target_company}_{role_position}.docx")
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("定制化简历 Word 生成失败: %s", e)
            error = f"定制化简历 Word 生成失败: {e}"

        # 2) 新增 HTML + YAML + 检查报告（《resume-formatter》Skill）
        #    同时输出一页 A4 精美 Word 简历（共用同一次结构化解析）
        try:
            html_out = write_customized_resume_html(
                optimized_text,
                output_html=str(out_dir / f"定制化简历_{target_company}_{role_position}_{default_template}.html"),
                output_yaml=str(out_dir / f"定制化简历_{target_company}_{role_position}_data.yaml"),
                template=default_template,
                output_docx=str(out_dir / f"定制化简历_{target_company}_{role_position}_{default_template}.docx"),
                photo_base64=state.get("photo_base64", ""),
            )
            resume_html_path = html_out["html_path"]
            resume_yaml_path = html_out["yaml_path"]
            resume_check_report = html_out["check_report"]
            # 精美 Word 简历：优先于纯文本 Word（resume_formatter 产物更精美且一页 A4）
            if html_out.get("docx_path"):
                resume_docx_path = html_out["docx_path"]
        except Exception as e:  # noqa: BLE001
            logger.warning("HTML 简历生成失败: %s", e)
            error = (error + "；" if error else "") + f"HTML 简历生成失败: {e}"

    advice_text = (state.get("interview_advice") or "").strip()
    if advice_text:
        try:
            advice_docx_path = write_interview_advice_docx(
                advice_text,
                str(out_dir / f"面试建议_{target_company}_{role_position}.docx"),
                questions=state.get("interview_questions"),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("面试建议文档生成失败: %s", e)
            error = (error + "；" if error else "") + f"面试建议文档生成失败: {e}"

    logger.info(
        "write_output：Word=%s，HTML=%s，YAML=%s，面试建议=%s",
        resume_docx_path or "（未生成）",
        resume_html_path or "（未生成）",
        resume_yaml_path or "（未生成）",
        advice_docx_path or "（未生成）",
    )
    return {
        "resume_docx_path": resume_docx_path,
        "resume_html_path": resume_html_path,
        "resume_yaml_path": resume_yaml_path,
        "resume_check_report": resume_check_report,
        "advice_docx_path": advice_docx_path,
        "error": error,
    }


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
    - pass                → interview（生成面试建议）
    - fail 且 attempts<3  → optimize（重试）
    - fail 且 attempts>=3 → interview（重试超限，仍产出面试建议 + 文档，不给用户留空）
    """
    verdict = state.get("review_verdict") or {"pass": False}
    if verdict.get("pass"):
        logger.info("条件边：审核通过 → interview")
        return "interview"
    if (state.get("attempts") or 0) < MAX_ATTEMPTS:
        logger.info("条件边：审核未达标，第 %d 次重试 → optimize", state.get("attempts", 0))
        return "optimize"
    logger.warning("条件边：重试超限（%d 次），仍进入 interview + write_output，确保用户拿到结果", MAX_ATTEMPTS)
    return "interview"


# ──────────────────────────────────────────────
# 图构建
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
    graph.add_node("research_company", research_company)
    graph.add_node("optimize", optimize)
    graph.add_node("review", review)
    graph.add_node("interview", interview)
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
        {"continue": "research_company", END: END},
    )
    graph.add_conditional_edges(
        "research_company",
        route_after_stage,
        {"continue": "optimize", END: END},
    )
    graph.add_conditional_edges(
        "optimize",
        route_after_stage,
        {"continue": "review", END: END},
    )

    # 条件边：review → (interview | optimize)
    #   pass → interview
    #   fail & attempts<3 → optimize（重试）
    #   fail & attempts>=3 → interview（超限仍产出）
    graph.add_conditional_edges(
        "review",
        route_after_review,
        {"interview": "interview", "optimize": "optimize"},
    )

    # 面试建议生成后直接输出文档（失败也走 write_output，由节点兜底）
    graph.add_edge("interview", "write_output")

    # 终点
    graph.add_edge("write_output", END)

    logger.info("build_graph：LangGraph StateGraph 编译完成")
    return graph.compile()


def run_optimize(
    resume_text: str,
    jd_text: str,
    target_company: str = "",
    photo_base64: str = "",
) -> dict[str, Any]:
    """运行完整简历定制流水线。

    Args:
        resume_text: 简历纯文本
        jd_text: 岗位描述全文
        target_company: 目标公司名称
        photo_base64: 可选，用户上传的照片（data URI / 纯 base64），
            由 write_output 写入生成的简历文档

    Returns:
        dict，包含 resume_text / jd_text / target_company / jd_analysis /
        company_research / optimized_text / matching_table / interview_questions /
        interview_advice / resume_docx_path / advice_docx_path / error / attempts 等
    """
    graph = build_graph()
    initial_state: OptimizeState = {
        "resume_text": resume_text,
        "jd_text": jd_text,
        "target_company": target_company,
        "photo_base64": photo_base64 or "",
        "jd_analysis": {},
        "company_research": {},
        "optimized_text": "",
        "matching_table": [],
        "interview_questions": [],
        "interview_advice": "",
        "resume_docx_path": "",
        "resume_html_path": "",
        "resume_yaml_path": "",
        "resume_check_report": "",
        "advice_docx_path": "",
        "error": "",
        "attempts": 0,
    }
    logger.info("run_optimize：开始执行 LangGraph 流水线（公司=%s）", target_company)
    result = graph.invoke(initial_state)

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
        ("resume_html_path", ""),
        ("resume_yaml_path", ""),
        ("resume_check_report", ""),
        ("advice_docx_path", ""),
        ("error", ""),
    ):
        output.setdefault(key, default)
    return output


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    sample_resume = "张三，3年Python后端开发经验，熟悉Django、MySQL、Redis。"
    sample_jd = "岗位：Python后端开发工程师，3年以上经验，熟悉Django/Flask、MySQL、Redis、Docker。"
    result = run_optimize(sample_resume, sample_jd, target_company="某科技有限公司")
    print("=" * 50)
    print("优化结果：", result.get("optimized_text", "")[:300])
    print("匹配表条数：", len(result.get("matching_table", [])))
    print("面试问题数：", len(result.get("interview_questions", [])))
    print("简历文档：", result.get("resume_docx_path", ""))
    print("面试建议文档：", result.get("advice_docx_path", ""))
    print("错误信息：", result.get("error", ""))
