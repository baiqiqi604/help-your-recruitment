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


# ──────────────────────────────────────────────
# 简历格式化模块（Resume Formatter）
# 结构化简历数据模型：与《resume-formatter》SKILL 的 YAML 格式一一对应
# ──────────────────────────────────────────────
class BasicInfo(BaseModel):
    """基本信息（姓名、联系方式、个人简介）。"""

    name: str = Field(default="", description="姓名")
    title: str = Field(default="", description="目标岗位 / 当前职位")
    avatar: str = Field(default="", description="头像URL或base64（可选）")
    location: str = Field(default="", description="所在地，如北京")
    email: str = Field(default="", description="邮箱")
    phone: str = Field(default="", description="电话")
    website: str = Field(default="", description="个人网站")
    github: str = Field(default="", description="GitHub链接")
    linkedin: str = Field(default="", description="LinkedIn链接")
    summary: str = Field(default="", description="个人摘要 / 自我评价，2-3句话")


class EducationEntry(BaseModel):
    """教育经历条目。"""

    school: str = Field(default="", description="学校名称")
    degree: str = Field(default="", description="学位，如本科/硕士/博士")
    major: str = Field(default="", description="专业")
    period: str = Field(default="", description="时间段，如 2018.09 - 2021.06")
    gpa: str = Field(default="", description="GPA（可选）")
    highlights: list[str] = Field(default_factory=list, description="亮点：奖项、课程、成就等（可选）")


class ExperienceEntry(BaseModel):
    """工作经历条目。"""

    company: str = Field(default="", description="公司名称")
    position: str = Field(default="", description="职位")
    period: str = Field(default="", description="在职时间段")
    location: str = Field(default="", description="工作地点（可选）")
    points: list[str] = Field(
        default_factory=list,
        description="工作成果要点（建议每段2-5条，STAR法则+量化数据）",
    )


class ProjectEntry(BaseModel):
    """项目经历条目。"""

    name: str = Field(default="", description="项目名称")
    role: str = Field(default="", description="担任角色")
    period: str = Field(default="", description="项目时间段")
    tech_stack: list[str] = Field(default_factory=list, description="技术栈")
    link: str = Field(default="", description="项目链接（可选）")
    points: list[str] = Field(default_factory=list, description="项目要点与成果")


class SkillCategory(BaseModel):
    """技能分组。"""

    name: str = Field(default="", description="分组名称，如产品技能/技术能力/工具软件")
    items: list[str] = Field(default_factory=list, description="该分组下的技能列表")


class AwardEntry(BaseModel):
    """荣誉奖项条目。"""

    name: str = Field(default="", description="奖项名称")
    issuer: str = Field(default="", description="颁发机构 / 组织")
    date: str = Field(default="", description="获奖时间")


class CertificationEntry(BaseModel):
    """证书资质条目。"""

    name: str = Field(default="", description="证书名称")
    issuer: str = Field(default="", description="颁发机构")
    date: str = Field(default="", description="获得时间")


class LanguageEntry(BaseModel):
    """语言能力条目。"""

    name: str = Field(default="", description="语言名称，如中文/英语")
    level: str = Field(default="", description="水平描述")


class ResumeData(BaseModel):
    """结构化简历完整数据（Resume Formatter 标准输入）。

    典型生成路径：
    1. 用户直接按 YAML 填写 → 转为此模型；
    2. 纯文本简历（优化后的 optimized_text）→ LLM 结构化抽取
       （resume_formatter.parse_resume_text_to_data）。
    """

    basic: BasicInfo = Field(default_factory=BasicInfo, description="基本信息")
    education: list[EducationEntry] = Field(default_factory=list, description="教育经历（按时间倒序）")
    experience: list[ExperienceEntry] = Field(default_factory=list, description="工作经历（按时间倒序）")
    projects: list[ProjectEntry] = Field(default_factory=list, description="项目经历（可选）")
    skills: list[SkillCategory] = Field(default_factory=list, description="技能专长（按分组）")
    awards: list[AwardEntry] = Field(default_factory=list, description="荣誉奖项（可选）")
    certifications: list[CertificationEntry] = Field(default_factory=list, description="证书资质（可选）")
    languages: list[LanguageEntry] = Field(default_factory=list, description="语言能力（可选）")


class ResumeCheckResult(BaseModel):
    """简历检查清单结果。"""

    category: str = Field(default="", description="检查大类（内容质量/格式排版/ATS友好/基础信息）")
    item: str = Field(default="", description="检查项目描述")
    passed: bool = Field(default=False, description="是否通过")
    suggestion: str = Field(default="", description="未通过时的改进建议")


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
