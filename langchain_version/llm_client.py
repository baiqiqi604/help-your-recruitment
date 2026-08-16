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
from typing import Any, Callable

from config import LLM_CONFIG, validate_config

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Mock 模式（无 API Key 时用于演示 / 测试）
# 设置环境变量 MOCK_LLM=1 开启：chat() 返回模拟响应
# ──────────────────────────────────────────────
def mock_enabled() -> bool:
    return os.getenv("MOCK_LLM", "").strip().lower() in ("1", "true", "yes")


_MOCK_GENERIC_REPLY = (
    "（MOCK）你好，我是简历优化助手。当前为演示模式，"
    "配置 API Key 后可提供真实分析与优化服务。"
)


# ──────────────────────────────────────────────
# Mock 场景注册表
# 每个业务场景一个确定性响应函数；调用方通过
#     chat(..., mock_scenario="analyze_jd")
# 显式指定场景，不再依赖 prompt 关键字匹配 —— prompt 模板改动
# 不会静默破坏 mock（旧关键字兜底仅用于未显式传场景的调用点）。
# ──────────────────────────────────────────────
def _mock_scene_analyze_jd(_prompt: str, _system: str | None = None) -> str:
    """jd_analyzer 完整岗位拆解（升级版）。"""
    return json.dumps(
        {
            "role_position": "Python 后端开发工程师",
            "role_type": "tech",
            "responsibilities": [
                "负责后端服务设计与开发",
                "参与系统架构设计与性能优化",
                "负责数据库设计与优化",
            ],
            "required_skills": ["Python", "Django", "MySQL", "Redis"],
            "preferred_skills": ["Docker", "微服务架构"],
            "tech_stack": ["Python", "Django", "MySQL", "Redis", "Docker"],
            "industry_experience": ["互联网", "高并发业务"],
            "keywords": ["Python后端", "Django", "MySQL", "Redis"],
            "hidden_goals": ["稳定性", "效率", "性能优化"],
            "experience_years": "3-5年",
            "requirement_tiers": [
                {"tier": "must_match", "requirement": "Python 开发经验", "reason": "硬性要求"},
                {"tier": "must_match", "requirement": "熟悉 Django/Flask", "reason": "核心框架要求"},
                {"tier": "must_match", "requirement": "熟悉 MySQL、Redis", "reason": "核心数据组件"},
                {"tier": "strongly_related", "requirement": "了解微服务架构", "reason": "架构相关"},
                {"tier": "bonus", "requirement": "Docker 使用经验", "reason": "加分项"},
                {"tier": "risk", "requirement": "高并发性能优化", "reason": "简历中证据不足，易被追问"},
            ],
        },
        ensure_ascii=False,
    )


def _mock_scene_company_research(_prompt: str, _system: str | None = None) -> str:
    """company_researcher 公司研究与求职判断。"""
    return json.dumps(
        {
            "company_overview": {
                "name": "某科技有限公司",
                "industry": "互联网/企业服务",
                "business": "提供 SaaS 软件与行业解决方案",
                "position": "细分领域头部",
            },
            "positive_info": ["公开信息显示业务增长稳健", "官方渠道披露近期融资"],
            "negative_info": ["公开评价中有人提到部分业务线调整（来源有限，需进一步确认）"],
            "online_reviews": ["公开评价中有人提到面试流程较为规范", "部分候选人反馈笔试有一定难度"],
            "hiring_observation": "公开招聘平台显示该岗位近期持续在招（信息来源有限）",
            "recommendation": "cautious",
            "matching_reasons": ["用户 3 年 Python 后端经验与岗位核心要求匹配", "Django/MySQL/Redis 技能栈重合度高"],
            "opportunities": ["参与核心业务系统建设", "技术栈与用户经验高度一致，上手快"],
            "risks": ["部分业务线调整带来的不确定性", "岗位边界可能需要面试确认"],
            "application_strategy": "建议投递，可尝试内推；简历突出后端服务与数据库优化经验，并准备相邻岗位备选。",
            "questions_to_confirm": ["当前团队规模与业务线方向", "岗位考核指标与成长路径"],
            "uncertainties": ["公司最新经营数据以官方披露为准", "岗位编制情况需以招聘方确认为准"],
        },
        ensure_ascii=False,
    )


def _mock_scene_interview_questions(_prompt: str, _system: str | None = None) -> str:
    """interview_advisor 面试问题清单。"""
    return json.dumps(
        [
            {"stage": "HR面", "question": "请简单介绍自己，为什么选择应聘我们公司？", "prepare_hint": "结合公司业务与自身经历，准备 1 分钟版本。"},
            {"stage": "业务面", "question": "请介绍你的订单管理系统项目，你在其中承担什么职责？", "prepare_hint": "用 STAR 结构，突出订单状态机与库存扣减设计。"},
            {"stage": "专业面", "question": "MySQL 慢查询你是如何定位与优化的？", "prepare_hint": "准备 explain 分析、索引优化、慢日志定位的实战案例。"},
            {"stage": "专业面", "question": "Redis 在项目里解决了什么问题？如何设计缓存策略？", "prepare_hint": "结合热点数据缓存与过期策略讲清收益与取舍。"},
            {"stage": "主管面", "question": "如果让你设计一个高并发下单接口，你会怎么设计？", "prepare_hint": "从限流、库存扣减一致性、幂等角度准备。"},
        ],
        ensure_ascii=False,
    )


def _mock_scene_interview_advice(_prompt: str, _system: str | None = None) -> str:
    """interview_advisor 面试建议全文。"""
    return (
        "# 面试建议_某科技有限公司_Python后端开发工程师\n\n"
        "## 一、公司判断与求职建议\n"
        "### 1. 公司概况\n- 主营业务：提供 SaaS 软件与行业解决方案\n"
        "### 2. 正面信息\n- 公开信息显示业务增长稳健\n"
        "### 3. 负面信息与风险\n- 公开评价中有人提到部分业务线调整（来源有限，需进一步确认）\n"
        "### 4. 网络评价摘要\n- 公开评价中有人提到面试流程较为规范\n"
        "### 5. 招聘信息观察\n- 公开招聘平台显示该岗位近期持续在招（信息来源有限）\n"
        "### 6. 综合判断\n- 谨慎推荐，建议投递前进一步确认业务线情况\n"
        "### 7. 给用户的求职建议\n- 简历突出后端服务与数据库优化经验，可尝试内推\n"
        "### 8. 面试中建议反向确认的问题\n- 当前团队规模与业务线方向\n\n"
        "## 二、面试准备建议\n"
        "### 1. JD 核心能力拆解\n- Python/Django/MySQL/Redis 为核心要求\n"
        "### 2. 用户优势与匹配点\n- 3 年 Python 后端经验，技能栈重合度高\n"
        "### 3. 用户短板与风险问题\n- 高并发性能优化证据不足，需提前准备案例\n"
        "### 4. 需要提前准备的面试问题\n- 业务面：订单系统项目深挖\n- 专业面：MySQL 慢查询优化、Redis 缓存设计\n"
        "### 5. 建议重点准备的案例\n- 订单状态机与库存扣减（STAR）\n"
        "### 6. 可向面试官反问的问题\n- 团队技术栈与成长路径\n"
        "### 7. 面试表达策略\n- 用数据说话，量化成果\n\n"
        "## 附录：信息来源与待确认事项\n- 公司最新经营数据以官方披露为准\n\n"
        "（本条为 MOCK 演示输出，配置真实 API Key 后由模型生成）"
    )


def _mock_scene_experience_processing(_prompt: str, _system: str | None = None) -> str:
    """experience_processor 面经结构化加工。"""
    return json.dumps(
        [
            {
                "company": "",
                "role": "Python后端",
                "stage": "专业面",
                "question_type": "面试问答",
                "question": "Python 中 GIL 是什么？对多线程性能有何影响？",
                "key_points": ["GIL", "多线程", "IO密集", "CPU密集"],
                "reference_answer": "GIL 是 CPython 的全局解释器锁，同一时刻仅一个线程执行字节码。IO 密集可用多线程，CPU 密集建议多进程。【AI 整理，仅供参考】",
                "quality": 4,
                "is_algorithm": False,
            },
            {
                "company": "",
                "role": "Python后端",
                "stage": "笔试",
                "question_type": "手撕算法",
                "question": "实现一个 LRU 缓存",
                "key_points": ["哈希表", "双向链表", "O(1)访问"],
                "reference_answer": "使用 dict + 双向链表，访问/插入 O(1)，淘汰最久未使用节点。【AI 整理，仅供参考】",
                "quality": 3,
                "is_algorithm": True,
            },
            {
                "company": "",
                "role": "Python后端",
                "stage": "业务面",
                "question_type": "系统设计",
                "question": "如何设计高并发下单接口？",
                "key_points": ["限流", "库存一致性", "幂等"],
                "reference_answer": "从限流、库存扣减一致性、幂等设计角度展开。【AI 整理，仅供参考】",
                "quality": 4,
                "is_algorithm": False,
            },
        ],
        ensure_ascii=False,
    )


def _mock_scene_analyze_jd_basic(_prompt: str, _system: str | None = None) -> str:
    """jd_analyzer 旧版结构化分析（兼容）。"""
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


def _mock_scene_matching_table(_prompt: str, _system: str | None = None) -> str:
    """content_optimizer 简历-JD 匹配关系表。"""
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


def _mock_scene_resume_review(_prompt: str, _system: str | None = None) -> str:
    """graph.review 简历审核。"""
    return json.dumps(
        {
            "pass": True,
            "feedback": "MOCK 审核通过：输出结构完整，未发现明显虚构内容。",
        },
        ensure_ascii=False,
    )


def _mock_scene_optimize_resume(_prompt: str, _system: str | None = None) -> str:
    """content_optimizer 简历优化。"""
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


def _mock_scene_parse_resume_data(_prompt: str, _system: str | None = None) -> str:
    """resume_formatter 简历结构化解析（纯文本 → ResumeData JSON）。"""
    return json.dumps(
        {
            "basic": {
                "name": "李小明",
                "title": "AI产品经理",
                "location": "北京",
                "email": "lixiaoming@example.com",
                "phone": "138-1234-5678",
                "website": "",
                "github": "github.com/lixiaoming",
                "linkedin": "linkedin.com/in/lixiaoming",
                "summary": "5年AI产品经验，主导过3个大模型应用从0到1落地，精通RAG、Prompt工程、AIGC产品设计，DAU最高达500万，擅长跨团队协调推动复杂项目。",
            },
            "education": [
                {"school": "清华大学", "degree": "硕士", "major": "计算机科学与技术", "period": "2018.09 - 2021.06", "gpa": "3.8/4.0", "highlights": ["国家奖学金"]},
                {"school": "北京大学", "degree": "本科", "major": "软件工程", "period": "2014.09 - 2018.06", "gpa": "", "highlights": []},
            ],
            "experience": [
                {
                    "company": "字节跳动",
                    "position": "AI产品经理（高级）",
                    "period": "2023.03 - 至今",
                    "location": "北京",
                    "points": [
                        "主导豆包大模型垂直行业产品从0到1搭建，上线3个月DAU突破500万，用户次日留存提升30%",
                        "设计RAG检索增强方案，引入多路召回+精排架构，答案准确率从72%提升至91%，幻觉率下降45%",
                        "跨团队协调算法/工程/设计/运营5个团队，推动3个核心大版本按期上线，里程碑达成率100%",
                    ],
                },
                {
                    "company": "阿里巴巴",
                    "position": "产品经理",
                    "period": "2021.07 - 2023.02",
                    "location": "杭州",
                    "points": [
                        "负责阿里通义千问电商助手模块，订单转化率提升18%，月GMV增加2.3亿元",
                        "搭建产品数据看板与A/B测试体系，累计完成42次A/B实验，决策效率提升2倍",
                    ],
                },
            ],
            "projects": [
                {
                    "name": "智能简历优化Agent",
                    "role": "产品负责人 & 开发者",
                    "period": "2024.06 - 2024.08",
                    "tech_stack": ["LangChain", "RAG", "FastAPI", "Vue", "ChromaDB"],
                    "link": "github.com/example/resume-agent",
                    "points": [
                        "基于LLM多Agent协作架构的简历内容优化系统，支持JD匹配度评分，GitHub 2k+ Stars",
                        "设计LangGraph工作流，拆解岗位→公司分析→优化→审核→面试建议5个核心Agent",
                    ],
                },
            ],
            "skills": [
                {"name": "产品技能", "items": ["需求分析", "PRD撰写", "用户研究", "A/B测试", "数据分析", "项目管理"]},
                {"name": "AI能力", "items": ["RAG架构", "Prompt Engineering", "大模型评估", "微调策略", "Agent设计"]},
                {"name": "技术能力", "items": ["Python", "SQL", "LangChain", "ChromaDB", "FastAPI"]},
            ],
            "awards": [],
            "certifications": [],
            "languages": [],
        },
        ensure_ascii=False,
    )


MOCK_SCENARIOS: dict[str, Callable[[str, str | None], str]] = {
    "analyze_jd": _mock_scene_analyze_jd,
    "analyze_jd_basic": _mock_scene_analyze_jd_basic,
    "company_research": _mock_scene_company_research,
    "interview_questions": _mock_scene_interview_questions,
    "interview_advice": _mock_scene_interview_advice,
    "experience_processing": _mock_scene_experience_processing,
    "matching_table": _mock_scene_matching_table,
    "resume_review": _mock_scene_resume_review,
    "optimize_resume": _mock_scene_optimize_resume,
    "parse_resume_data": _mock_scene_parse_resume_data,
}


def _mock_chat(
    prompt: str,
    system: str | None = None,
    mock_scenario: str | None = None,
) -> str:
    """返回模拟 LLM 响应。

    优先按显式 mock_scenario 分发；未指定或未注册时回退到
    旧的 prompt 关键字匹配（兼容历史调用点），最后回退通用回复。
    """
    if mock_scenario:
        handler = MOCK_SCENARIOS.get(mock_scenario)
        if handler is None:
            logger.warning("[MOCK] 未注册的场景: %s，回退关键字匹配", mock_scenario)
        else:
            return handler(prompt, system)

    # 兼容兜底：按 prompt 特征匹配（旧调用点 / web_app 自由聊天）
    if "requirement_tiers" in prompt and "岗位描述" in prompt:
        return _mock_scene_analyze_jd(prompt, system)
    if "推荐程度" in prompt or "recommendation" in prompt:
        return _mock_scene_company_research(prompt, system)
    if "prepare_hint" in prompt and "面试问题" in prompt:
        return _mock_scene_interview_questions(prompt, system)
    if "面试建议" in prompt and "公司判断" in prompt:
        return _mock_scene_interview_advice(prompt, system)
    if "question_type" in prompt and "素材内容" in prompt:
        return _mock_scene_experience_processing(prompt, system)
    if "required_skills" in prompt and "岗位描述" in prompt:
        return _mock_scene_analyze_jd_basic(prompt, system)
    if "jd_requirement" in prompt:
        return _mock_scene_matching_table(prompt, system)
    if "严格的简历审核专家" in prompt and '"pass"' in prompt:
        return _mock_scene_resume_review(prompt, system)
    if "优化后的简历" in prompt or "简历优化顾问" in prompt:
        return _mock_scene_optimize_resume(prompt, system)
    return _MOCK_GENERIC_REPLY


def extract_text_content(content: Any) -> str:
    """从 LangChain 消息 content 中安全提取纯文本。

    langchain 1.x 的 message.content 可能是：
      - str：普通文本（最常见）
      - list[dict]：content blocks（如 [{"type": "text", "text": "..."}]）
    直接 str() 会把 blocks 的原始结构打出来，这里统一提取文本。
    供 chat() / stream_chat() / agent 回复提取共用。
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                else:
                    # 非文本块（如 tool_use / image），至少保留可见字段
                    text = block.get("text") or block.get("content") or ""
                    if text:
                        parts.append(str(text))
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)


def _make_llm(max_tokens: int | None = None):
    """构建 ChatOpenAI 客户端；max_tokens 可覆盖全局配置（用于短输出场景提速）。"""
    validate_config()  # 非法 provider 在此显式校验（import config 不再抛错）
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
        max_tokens=max_tokens or LLM_CONFIG["max_tokens"],
        timeout=LLM_CONFIG["timeout"],
    )


@lru_cache(maxsize=1)
def get_llm():
    """获取当前 Provider 的 ChatOpenAI 客户端（单例缓存）。"""
    return _make_llm()


def chat(
    prompt: str,
    system: str | None = None,
    max_tokens: int | None = None,
    mock_scenario: str | None = None,
) -> str:
    """发送单轮对话请求，返回模型文本响应。

    max_tokens: 可选覆盖输出上限（默认用全局配置 4096；总结/答疑类短回答
    可传更小值以显著加快响应）。
    mock_scenario: MOCK 模式下的显式场景名（见 MOCK_SCENARIOS），
    用于替代 prompt 关键字匹配，保证 mock 行为稳定。
    """
    if mock_enabled():
        logger.info("[MOCK] 返回模拟 LLM 响应（场景=%s）", mock_scenario or "auto")
        return _mock_chat(prompt, system, mock_scenario)

    from langchain_core.messages import HumanMessage, SystemMessage

    llm = get_llm() if max_tokens is None else _make_llm(max_tokens=max_tokens)
    messages = []
    if system:
        messages.append(SystemMessage(content=system))
    messages.append(HumanMessage(content=prompt))

    response = llm.invoke(messages)
    return extract_text_content(response.content)


def stream_chat(
    prompt: str,
    system: str | None = None,
    max_tokens: int | None = None,
    mock_scenario: str | None = None,
) -> Any:
    """发送单轮对话请求，逐块产出文本（生成器，供 SSE 流式输出）。

    MOCK 模式下按固定长度切块模拟流式（保持测试确定性）；
    真实模式下走 ChatOpenAI.stream() 逐 token 产出。

    Args:
        prompt: 用户输入
        system: 系统提示词（可选）
        max_tokens: 可选覆盖输出上限
        mock_scenario: MOCK 模式下的显式场景名

    Yields:
        文本增量片段（str）
    """
    if mock_enabled():
        text = _mock_chat(prompt, system, mock_scenario)
        for i in range(0, len(text), 12):  # 每块 12 字符，模拟打字机
            yield text[i : i + 12]
        return

    from langchain_core.messages import HumanMessage, SystemMessage

    llm = get_llm() if max_tokens is None else _make_llm(max_tokens=max_tokens)
    messages = []
    if system:
        messages.append(SystemMessage(content=system))
    messages.append(HumanMessage(content=prompt))

    for chunk in llm.stream(messages):
        text = extract_text_content(chunk.content)
        if text:
            yield text


def chat_json(
    prompt: str,
    system: str | None = None,
    mock_scenario: str | None = None,
) -> dict[str, Any]:
    """发送对话请求并解析返回的 JSON 对象。"""
    raw = chat(prompt, system, mock_scenario=mock_scenario)
    return parse_llm_json(raw)


def chat_json_array(
    prompt: str,
    system: str | None = None,
    mock_scenario: str | None = None,
) -> list[Any]:
    """发送对话请求并解析返回的 JSON 数组。"""
    raw = chat(prompt, system, mock_scenario=mock_scenario)
    return parse_llm_json_array(raw)


def chat_structured(
    prompt: str,
    system: str | None = None,
    model_cls: type | None = None,
    mock_scenario: str | None = None,
) -> Any:
    """发送对话请求并用 PydanticOutputParser 解析为结构化模型。

    Args:
        prompt: 用户输入（prompt 模板已内置字段说明，不追加 format instructions）
        system: 系统提示词（可选）
        model_cls: Pydantic 模型类（BaseModel 或 RootModel[list[...]]）；
            为 None 时降级为 parse_llm_json（dict）
        mock_scenario: MOCK 模式下的显式场景名

    Returns:
        解析成功返回模型实例；解析失败降级返回 dict / list（与旧路径一致），
        保证 MOCK 与不稳定输出下行为不回退。
    """
    raw = chat(prompt, system, mock_scenario=mock_scenario)
    if model_cls is None:
        return parse_llm_json(raw)

    try:
        from langchain_core.output_parsers import PydanticOutputParser

        parser = PydanticOutputParser(pydantic_object=model_cls)
        return parser.invoke(raw)
    except Exception as e:  # noqa: BLE001
        logger.warning("结构化解析失败，降级手写解析: %s", e)
        import pydantic

        if isinstance(model_cls, type) and issubclass(model_cls, pydantic.RootModel):
            return parse_llm_json_array(raw)
        return parse_llm_json(raw)


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
