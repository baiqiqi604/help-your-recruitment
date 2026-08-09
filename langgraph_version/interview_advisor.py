"""
面试建议生成模块（依据《定制化简历大师》Skill）

职责：
1. 结合"公司情况 + 岗位 JD + 用户简历"生成面试建议（非通用模板）
2. 按岗位类型生成针对性面试问题（HR面/业务面/专业面/主管面/终面）
3. 输出结构化面试建议，供 resume_writer 生成 Word 文档

面试问题生成规则（按岗位类型）：
- tech（技术岗）：技术原理、系统设计、项目深挖、性能优化、故障排查、工程实践、代码质量
- product（产品岗）：用户洞察、需求分析、优先级判断、指标体系、增长策略、跨团队协作、失败案例
- operation（运营岗）：活动策划、用户增长、数据分析、内容/社群/渠道策略、复盘方法
- market_sales（市场/销售岗）：客户洞察、线索转化、行业理解、竞品分析、业绩达成、谈判案例
- management（管理岗）：团队管理、目标拆解、组织协同、冲突处理、绩效改进、战略落地
- design（设计岗）：作品集讲解、设计方法、用户体验、业务目标、协作流程、设计取舍
- support（职能岗）：流程优化、跨部门沟通、合规意识、效率提升、服务意识、复杂问题处理

依赖：llm_client（OpenAI 兼容多 Provider）
"""

from __future__ import annotations

import logging
from typing import Any

import llm_client

logger = logging.getLogger(__name__)

MAX_RESUME_CHARS = 8000  # 用于面试建议的简历截断长度

# 岗位类型 → 面试关注维度（用于 Prompt 提示）
ROLE_TYPE_DIMENSIONS = {
    "tech": "技术原理、系统设计、项目深挖、性能优化、故障排查、工程实践、代码质量",
    "product": "用户洞察、需求分析、优先级判断、指标体系、增长策略、跨团队协作、失败案例",
    "operation": "活动策划、用户增长、数据分析、内容/社群/渠道策略、复盘方法",
    "market_sales": "客户洞察、线索转化、行业理解、竞品分析、业绩达成、谈判案例",
    "management": "团队管理、目标拆解、组织协同、冲突处理、绩效改进、战略落地",
    "design": "作品集讲解、设计方法、用户体验、业务目标、协作流程、设计取舍",
    "support": "流程优化、跨部门沟通、合规意识、效率提升、服务意识、复杂问题处理",
}

# 面试轮次
INTERVIEW_STAGES = ["HR面", "业务面", "专业面", "主管面", "终面"]


# 面试问题生成 Prompt 模板
INTERVIEW_QUESTIONS_PROMPT = """你是一位资深面试辅导专家。请为目标岗位生成针对性面试问题清单，帮助求职者提前准备。

【目标岗位】{role_position}（{role_type_label}）
【岗位职责】{responsibilities}
【必备能力】{required_skills}
【加分项】{preferred_skills}
【岗位关注维度】{dimensions}

【题库中检索到的真实题目（优先采用，可补充整理）】
{kb_questions}

【用户简历摘要】
{resume_text}

请以 JSON 数组格式返回面试问题清单，每项包含：
- stage: 面试轮次，只能取 "HR面" / "业务面" / "专业面" / "主管面" / "终面" 之一
- question: 具体面试问题（结合岗位与简历，优先采用题库真实题目，可适当改写更贴合用户背景）
- prepare_hint: 准备提示（一句话，建议如何回答或准备哪些案例）

要求：
1. 共 10-16 个问题，覆盖各轮次，且贴合目标岗位的关注维度
2. 题库命中的真实题目应优先纳入清单（标注其考察点作为准备提示素材）
3. 问题要结合用户简历中的真实经历（项目、数据、职责），便于引导 STAR 案例
4. 至少包含 2 个针对用户短板或风险项的追问问题（若简历中有弱匹配项）

只返回 JSON 数组，不要其他内容。"""


# 面试建议生成 Prompt 模板
INTERVIEW_ADVICE_PROMPT = """你是一位资深职业顾问。请基于以下材料，生成一份完整的《面试建议》文本，供写入 Word 文档。

【目标公司】{target_company}
【目标岗位】{role_position}

【一、公司判断与求职建议】
{company_research}

【二、面试问题清单】
{questions_json}

【用户简历】
{resume_text}

请输出面试建议全文，严格按以下结构与 Markdown 标题组织（不要输出 JSON，直接输出文本）：

# 面试建议_{target_company}_{role_position}

## 一、公司判断与求职建议
### 1. 公司概况
### 2. 正面信息
### 3. 负面信息与风险
### 4. 网络评价摘要
### 5. 招聘信息观察
### 6. 综合判断
### 7. 给用户的求职建议
### 8. 面试中建议反向确认的问题

## 二、面试准备建议
### 1. JD 核心能力拆解
### 2. 用户优势与匹配点
### 3. 用户短板与风险问题
### 4. 需要提前准备的面试问题（按轮次列出：HR面/业务面/专业面/主管面/终面）
### 5. 建议重点准备的案例（结合用户真实经历，给出 STAR 案例要点）
### 6. 可向面试官反问的问题
### 7. 面试表达策略

## 附录：信息来源与待确认事项

要求：
1. 必须结合公司情况、JD 要求与用户简历，不能只给通用模板
2. 负面信息谨慎表述，注明"公开评价中有人提到""部分候选人反馈"等限定语
3. 不确定内容标注【待确认】
4. 不得编造用户经历，案例建议必须基于用户简历中的真实内容"""


def generate_interview_questions(
    role_type: str,
    jd_analysis: dict[str, Any],
    resume_text: str = "",
) -> list[dict[str, str]]:
    """按岗位类型生成针对性面试问题清单。

    Args:
        role_type: 岗位类型（tech/product/operation/market_sales/management/design/support）
        jd_analysis: 岗位拆解结果
        resume_text: 用户简历文本（可选）

    Returns:
        [{"stage": "业务面", "question": "...", "prepare_hint": "..."}, ...]
    """
    analysis = jd_analysis or {}
    role_type = role_type if role_type in ROLE_TYPE_DIMENSIONS else "tech"
    dimensions = ROLE_TYPE_DIMENSIONS.get(role_type, "")

    resume = (resume_text or "").strip()
    if len(resume) > MAX_RESUME_CHARS:
        resume = resume[:MAX_RESUME_CHARS]

    # 从面试/笔试经验知识库检索真实题目（失败降级为空，不阻塞主流程）
    kb_questions = _search_kb_questions(analysis, top_k=8)

    prompt = INTERVIEW_QUESTIONS_PROMPT.format(
        role_position=analysis.get("role_position", "") or "未知岗位",
        role_type_label=role_type,
        responsibilities=", ".join(analysis.get("responsibilities", [])) or "未提供",
        required_skills=", ".join(analysis.get("required_skills", [])) or "未提供",
        preferred_skills=", ".join(analysis.get("preferred_skills", [])) or "未提供",
        dimensions=dimensions,
        kb_questions=kb_questions or "（知识库暂无命中题目）",
        resume_text=resume or "未提供",
    )
    logger.info("generate_interview_questions：岗位类型=%s，题库命中 %d 条", role_type, len(kb_questions))
    raw = llm_client.chat_json_array(prompt)
    return _normalize_questions(raw)


def _search_kb_questions(jd_analysis: dict[str, Any], top_k: int = 8) -> list[str]:
    """从面试经验知识库检索与目标岗位相关的真实题目。

    检索策略：
    1. 用核心技能/职责关键词语义检索
    2. 若知识库不可用（缺依赖/未建库），返回空列表（降级）

    Returns:
        格式化后的题目文本列表
    """
    analysis = jd_analysis or {}
    query = " ".join(
        list(analysis.get("required_skills", []))[:4]
        + list(analysis.get("responsibilities", []))[:2]
        + list(analysis.get("hidden_goals", []))[:2]
    ).strip()
    if not query:
        return []

    try:
        from interview_knowledge_base import search_questions
    except ImportError:
        logger.info("面试经验知识库模块不可用，跳过题库检索")
        return []

    try:
        results = search_questions(query, top_k=top_k)
    except Exception as e:  # noqa: BLE001
        logger.warning("面试题检索失败（降级）: %s", e)
        return []

    lines = []
    for r in results:
        question = str(r.get("question", "")).strip()
        if not question:
            continue
        company = str(r.get("company", "")).strip()
        stage = str(r.get("stage", "")).strip()
        key_points = r.get("key_points") or []
        prefix = f"[{company or '通用'}/{stage or '通用'}] {question}"
        if key_points:
            prefix += f"（考察点：{', '.join(str(k) for k in key_points[:4])}）"
        lines.append(prefix)
    return lines[:top_k]


def _normalize_questions(raw: Any) -> list[dict[str, str]]:
    """校验并补齐面试问题清单。"""
    questions: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return questions
    for item in raw:
        if not isinstance(item, dict):
            continue
        stage = str(item.get("stage", "")).strip()
        if stage not in INTERVIEW_STAGES:
            # 宽松处理：非标准轮次则按业务面兜底
            stage = "业务面"
        question = str(item.get("question", "")).strip()
        if not question:
            continue
        questions.append(
            {
                "stage": stage,
                "question": question,
                "prepare_hint": str(item.get("prepare_hint", "")).strip(),
            }
        )
    return questions


def build_interview_advice(
    target_company: str,
    jd_analysis: dict[str, Any],
    resume_text: str,
    company_research: dict[str, Any],
    questions: list[dict[str, str]],
) -> str:
    """生成完整面试建议文本（Markdown 结构，供写入 Word 文档）。

    Args:
        target_company: 目标公司名称
        jd_analysis: 岗位拆解结果
        resume_text: 用户简历文本
        company_research: 公司研究/求职判断结果
        questions: 面试问题清单（generate_interview_questions 的产物）

    Returns:
        面试建议全文（Markdown 文本）
    """
    if not target_company or not target_company.strip():
        raise ValueError("目标公司名称不能为空")

    analysis = jd_analysis or {}
    role_position = analysis.get("role_position", "") or "目标岗位"

    resume = (resume_text or "").strip()
    if len(resume) > MAX_RESUME_CHARS:
        resume = resume[:MAX_RESUME_CHARS]

    # 公司研究结果转为可读文本（供模型组织措辞）
    company_research_text = _format_company_research(company_research or {})

    prompt = INTERVIEW_ADVICE_PROMPT.format(
        target_company=target_company.strip(),
        role_position=role_position,
        company_research=company_research_text or "（无公司研究数据）",
        questions_json=_format_questions(questions),
        resume_text=resume or "（未提供简历）",
    )
    logger.info("build_interview_advice：生成面试建议（公司=%s）", target_company)
    advice = llm_client.chat(prompt).strip()
    if not advice:
        raise ValueError("模型返回的面试建议为空")
    return advice


def _format_company_research(research: dict[str, Any]) -> str:
    """将公司研究结果格式化为文本摘要。"""
    overview = research.get("company_overview") or {}
    lines = []
    if overview.get("name"):
        lines.append(f"- 公司：{overview.get('name')}")
    if overview.get("industry"):
        lines.append(f"- 行业：{overview.get('industry')}")
    if overview.get("business"):
        lines.append(f"- 业务：{overview.get('business')}")
    if overview.get("position"):
        lines.append(f"- 行业位置：{overview.get('position')}")
    if research.get("positive_info"):
        lines.append(f"- 正面信息：{'; '.join(research['positive_info'])}")
    if research.get("negative_info"):
        lines.append(f"- 负面信息与风险：{'; '.join(research['negative_info'])}")
    if research.get("online_reviews"):
        lines.append(f"- 网络评价：{'; '.join(research['online_reviews'])}")
    if research.get("hiring_observation"):
        lines.append(f"- 招聘信息观察：{research['hiring_observation']}")
    if research.get("recommendation"):
        lines.append(f"- 综合判断：{research['recommendation']}")
    if research.get("matching_reasons"):
        lines.append(f"- 匹配理由：{'; '.join(research['matching_reasons'])}")
    if research.get("opportunities"):
        lines.append(f"- 主要机会：{'; '.join(research['opportunities'])}")
    if research.get("risks"):
        lines.append(f"- 主要风险：{'; '.join(research['risks'])}")
    if research.get("application_strategy"):
        lines.append(f"- 投递策略：{research['application_strategy']}")
    if research.get("questions_to_confirm"):
        lines.append(f"- 反向确认问题：{'; '.join(research['questions_to_confirm'])}")
    if research.get("uncertainties"):
        lines.append(f"- 信息不确定项：{'; '.join(research['uncertainties'])}")
    return "\n".join(lines) if lines else "（无公司研究数据）"


def _format_questions(questions: list[dict[str, str]]) -> str:
    """将面试问题清单格式化为可读文本。"""
    if not questions:
        return "（无面试问题数据）"
    lines = []
    for q in questions:
        line = f"- [{q.get('stage', '业务面')}] {q.get('question', '')}"
        if q.get("prepare_hint"):
            line += f"（准备提示：{q['prepare_hint']}）"
        lines.append(line)
    return "\n".join(lines)


if __name__ == "__main__":
    sample_analysis = {
        "role_position": "Python 后端开发工程师",
        "role_type": "tech",
        "responsibilities": ["负责后端服务设计与开发", "参与架构设计"],
        "required_skills": ["Python", "Django", "MySQL", "Redis"],
        "preferred_skills": ["Docker", "微服务"],
    }
    sample_resume = "张三，3年Python后端开发经验，熟悉Django、MySQL、Redis。"
    qs = generate_interview_questions("tech", sample_analysis, sample_resume)
    print("问题数:", len(qs))
    print(qs[:2])
