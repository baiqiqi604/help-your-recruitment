"""
结构化输出 Pydantic 模型（Output Parser 用）

配合 llm_client.chat_structured 将 LLM 输出解析为强类型模型，
替代手写 JSON 解析（parse_llm_json + _normalize_* 保留为降级兜底）。

设计要点：
- 字段均带默认值：LLM 输出缺字段时不抛错，交由 _normalize_* 补默认；
- 列表模型用 RootModel：匹配 LLM 返回 JSON 数组的场景；
- 只依赖 pydantic，不引入重依赖，可被两版共用。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, RootModel


class RequirementTier(BaseModel):
    """JD 要求分级条目。"""

    tier: str = Field(default="", description="must_match/strongly_related/bonus/risk")
    requirement: str = Field(default="", description="该条要求描述")
    reason: str = Field(default="", description="分级理由")


class JDAnalysis(BaseModel):
    """岗位描述拆解结果。"""

    role_position: str = Field(default="", description="岗位定位与职级")
    role_type: str = Field(default="tech", description="岗位类型（tech/product/...）")
    responsibilities: list[str] = Field(default_factory=list, description="核心职责")
    required_skills: list[str] = Field(default_factory=list, description="必备能力")
    preferred_skills: list[str] = Field(default_factory=list, description="加分项")
    tech_stack: list[str] = Field(default_factory=list, description="技术/工具/平台")
    industry_experience: list[str] = Field(default_factory=list, description="行业经验/软技能")
    keywords: list[str] = Field(default_factory=list, description="高频关键词")
    hidden_goals: list[str] = Field(default_factory=list, description="岗位隐含目标")
    experience_years: str = Field(default="", description="经验要求")
    requirement_tiers: list[RequirementTier] = Field(default_factory=list, description="要求分级")


class MatchingRow(BaseModel):
    """简历-JD 匹配关系表行。"""

    jd_requirement: str = Field(default="", description="JD 要求")
    user_evidence: str = Field(default="", description="简历中的对应经历证据")
    match_strength: str = Field(default="weak", description="strong/partial/weak/missing")
    resume_position: str = Field(default="其他", description="应放入简历的位置")
    suggested_expression: str = Field(default="", description="推荐的简历表达")
    needs_confirmation: bool = Field(default=False, description="是否需要用户确认")


class MatchingRowList(RootModel[list[MatchingRow]]):
    """匹配关系表（LLM 返回 JSON 数组）。"""

    root: list[MatchingRow]
