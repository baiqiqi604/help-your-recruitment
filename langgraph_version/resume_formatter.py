"""
简历格式化 / HTML 生成模块（对应《resume-formatter》Skill）。

职责：
1. 纯文本简历 → 结构化 ResumeData（LLM 结构化抽取 + 规则兜底）
2. ResumeData → YAML / YAML → ResumeData（便于版本管理）
3. ResumeData → 多套精美 HTML 简历（现代简约 / 商务正式 / 技术导向，A4 打印优化）
4. 简历质量检查清单（内容质量 / 格式排版 / ATS 友好 / 基础信息）
5. 一键输出 HTML + YAML 数据文件

依赖：
- 必选：pydantic（已由 schemas 引入）
- 可选：PyYAML（缺失时退回 JSON 存储）
"""

from __future__ import annotations

import html
import json
import logging
import re
from pathlib import Path
from typing import Any

from schemas import (
    AwardEntry,
    BasicInfo,
    CertificationEntry,
    EducationEntry,
    ExperienceEntry,
    LanguageEntry,
    ProjectEntry,
    ResumeCheckResult,
    ResumeData,
    SkillCategory,
)

logger = logging.getLogger(__name__)

# 支持的模板风格枚举
TEMPLATE_MODERN = "modern"          # 现代简约（双栏蓝紫）
TEMPLATE_PROFESSIONAL = "professional"  # 商务正式（单栏宋体）
TEMPLATE_TECH = "tech"              # 技术导向（代码风深色）
TEMPLATE_CLASSIC = "classic"        # 经典朴素（灰条单栏，匹配 Word 版白宇轩简历）
VALID_TEMPLATES = {TEMPLATE_MODERN, TEMPLATE_PROFESSIONAL, TEMPLATE_TECH, TEMPLATE_CLASSIC}

DEFAULT_TEMPLATE = TEMPLATE_CLASSIC


# ──────────────────────────────────────────────
# 一页 A4 约束（经典模板）
# 1) fit_resume_to_one_page：渲染前对结构化数据做温和裁剪（限制条目/要点数量）
# 2) _ONE_PAGE_FIT_JS：HTML 内嵌自适应脚本，测量真实渲染高度，
#    超出一页时先启用紧凑样式，仍超则按比例缩放（zoom），保证打印/预览恰好一页 A4。
# ──────────────────────────────────────────────
# A4 打印可用高度：297mm - 上下 padding（15mm*2）= 267mm；留 3mm 容差
_A4_AVAILABLE_MM = 264.0
# zoom 下限（0.6 时文字约 6.4pt，过小则说明内容确实超量，需人工精简）
_FIT_ZOOM_MIN = 0.6

_ONE_PAGE_FIT_JS = """<script>
(function () {
  "use strict";
  var MM_PX = 96 / 25.4;          // 1mm ≈ 3.78px（96dpi）
  var AVAILABLE_MM = %(avail_mm).1f;
  var ZOOM_MIN = %(zoom_min).1f;

  function measure() {
    var el = document.querySelector('.resume');
    if (!el) return null;
    return el.getBoundingClientRect().height;
  }

  function fit() {
    var el = document.querySelector('.resume');
    if (!el) return;
    // 先复位自适应（避免重复累乘 zoom）
    el.style.zoom = '';
    el.classList.remove('resume-compact');
    var limit = AVAILABLE_MM * MM_PX;

    // 第 1 档：启用紧凑样式（缩小边距/行距/字号）
    el.classList.add('resume-compact');
    if (measure() <= limit) return;

    // 第 2 档：等比缩放（zoom 会真实改变布局尺寸，打印同样生效）
    var h = measure();
    if (h > limit) {
      var scale = Math.max(ZOOM_MIN, limit / h);
      el.style.zoom = String(scale);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { setTimeout(fit, 0); });
  } else {
    setTimeout(fit, 0);
  }
  window.addEventListener('load', function () { setTimeout(fit, 50); });
  window.addEventListener('beforeprint', fit);
})();
</script>
""" % {"avail_mm": _A4_AVAILABLE_MM, "zoom_min": _FIT_ZOOM_MIN}


def fit_resume_to_one_page(data: ResumeData, max_entries: int = 3, max_points: int = 3) -> ResumeData:
    """对结构化简历做温和裁剪，使内容量控制在一页 A4 以内（尽力而为）。

    只削减"数量与长度"，不重写内容：
    - summary：保留前 2 句，总长 ≤ 160 字
    - experience：最多保留最近 max_entries 段（默认 3），每段要点 ≤ max_points 条（默认 3）
    - projects：最多保留 2 个，每个要点 ≤ max_points 条
    - skills：最多保留 4 个分组，每组最多 10 项
    - awards / certifications：各最多 5 条
    - 单条要点超过 80 字时截断（保留语义完整的主干，尾部加 …）

    一页 A4（A4=297mm，打印 padding 上下各 15mm → 可用约 264mm）按经验可容纳：
    约 3 段经历 × 3 要点 + 2 个项目 × 3 要点 + 教育 + 技能 ≈ 15-18 条要点。
    裁剪后仍由模板内嵌自适应脚本兜底（紧凑样式 + zoom），保证最终恰好一页。

    Returns:
        裁剪后的新 ResumeData（原对象不变）
    """
    if data is None:
        return data

    def _cut_points(points: list[str], limit: int) -> list[str]:
        out: list[str] = []
        for p in points:
            p = (p or "").strip()
            if not p:
                continue
            if len(p) > 80:
                p = p[:80].rstrip("，。；、 ") + "…"
            out.append(p)
            if len(out) >= limit:
                break
        return out

    def _cut_summary(text: str, limit: int = 160) -> str:
        text = (text or "").strip()
        if not text:
            return text
        if len(text) <= limit:
            return text
        # 按句切分，保留前 2 句
        sentences = [s.strip() for s in re.split(r"(?<=[。！？；])", text) if s.strip()]
        kept = ""
        for s in sentences:
            if len(kept) + len(s) > limit:
                break
            kept += s
        kept = kept.strip()
        return kept + "…" if kept and kept != text else (text[:limit].rstrip("，。；、 ") + "…")

    fit = data.model_copy(deep=True)

    b = fit.basic
    b.summary = _cut_summary(b.summary)

    # 学生工作经历识别（与渲染时"学生工作经历"标题判断一致）
    def _is_student_work(exp: Any) -> bool:
        company = str(getattr(exp, "company", "") or "")
        return any(k in company for k in ("学生", "校", "学术"))

    student_work = [e for e in fit.experience if _is_student_work(e)]
    real_work = [e for e in fit.experience if not _is_student_work(e)]

    # 优先保留真实工作经历：
    # 1) 真实工作经历足够（≥ max_entries）时，学生工作经历整体裁掉；
    # 2) 不够时补足：学生工作经历最多保留 1 段，且每段要点上限收紧到 2 条。
    kept: list[Any] = []
    kept.extend(real_work[:max_entries])
    if len(kept) < max_entries and student_work:
        kept.append(student_work[0])
    fit.experience = kept

    for exp in fit.experience:
        exp_limit = 2 if _is_student_work(exp) else max_points
        exp.points = _cut_points(exp.points, exp_limit)

    if len(fit.projects) > 2:
        fit.projects = fit.projects[:2]
    for proj in fit.projects:
        proj.points = _cut_points(proj.points, max_points)

    if len(fit.skills) > 4:
        fit.skills = fit.skills[:4]
    for sc in fit.skills:
        if len(sc.items) > 10:
            sc.items = sc.items[:10]

    if len(fit.awards) > 5:
        fit.awards = fit.awards[:5]
    if len(fit.certifications) > 5:
        fit.certifications = fit.certifications[:5]

    logger.info(
        "一页适配：经验 %d 段 / 项目 %d 个 / 要点共 %d 条",
        len(fit.experience), len(fit.projects),
        sum(len(e.points) for e in fit.experience) + sum(len(p.points) for p in fit.projects),
    )
    return fit


# ──────────────────────────────────────────────
# 1. 纯文本简历 → 结构化 ResumeData
# ──────────────────────────────────────────────

_PARSE_PROMPT = """你是一位简历结构化分析师。请将下面的纯文本简历解析为标准的 JSON 结构。

【解析规则】
- 严格只使用简历中提到的内容，不要猜测、不要补充、不要虚构。
- 找不到的字段填空字符串或空数组。
- 教育经历、工作经历、项目经历都按简历中的**实际顺序**排列（通常是倒序）。
- 工作/项目的要点 points 必须是数组，每一条按语义切分，不要把多件事写在同一条里。
- 技能 skills 按分类返回，找不到分类就放到"其他"中。
- 联系方式：邮箱匹配 xxx@xxx.xx，电话匹配 1XX-XXXX-XXXX / 1XXXXXXXXXX 等模式；
  GitHub 匹配 github.com/xxx；LinkedIn 匹配 linkedin.com/in/xxx。
- summary 为个人摘要/自我评价的连续段落，找不到就填空。

【简历纯文本】
{resume_text}

【返回 JSON Schema】
{{
  "basic": {{
    "name": "", "title": "", "location": "", "email": "",
    "phone": "", "website": "", "github": "", "linkedin": "", "summary": ""
  }},
  "education": [
    {{"school": "", "degree": "", "major": "", "period": "", "gpa": "", "highlights": []}}
  ],
  "experience": [
    {{"company": "", "position": "", "period": "", "location": "", "points": []}}
  ],
  "projects": [
    {{"name": "", "role": "", "period": "", "tech_stack": [], "link": "", "points": []}}
  ],
  "skills": [
    {{"name": "", "items": []}}
  ],
  "awards": [
    {{"name": "", "issuer": "", "date": ""}}
  ],
  "certifications": [
    {{"name": "", "issuer": "", "date": ""}}
  ],
  "languages": [
    {{"name": "", "level": ""}}
  ]
}}

只返回 JSON 对象，不要其他解释，不要 Markdown 代码块。"""


def parse_resume_text_to_data(resume_text: str) -> ResumeData:
    """将纯文本简历解析为结构化 ResumeData。

    策略：优先 LLM 结构化抽取；解析失败退回**规则兜底**。
    """
    text = (resume_text or "").strip()
    if not text:
        return ResumeData()

    # ── 路径 1：LLM 结构化抽取 ──────────────────
    try:
        import llm_client  # 延迟导入，避免循环依赖

        logger.info("调用 LLM 解析简历为结构化数据...")
        prompt = _PARSE_PROMPT.format(resume_text=text[:8000])
        raw = llm_client.chat_json(prompt, mock_scenario="parse_resume_data")
        if raw and isinstance(raw, dict):
            data = _normalize_resume_data(raw)
            logger.info(
                "简历结构化解析完成：经历 %d 段 / 项目 %d 段 / 技能 %d 组",
                len(data.experience), len(data.projects), len(data.skills),
            )
            return data
        logger.warning("LLM 解析返回非 dict，退回规则兜底")
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM 解析简历失败（%s），退回规则兜底", e)

    # ── 路径 2：规则兜底（保证最低限度产出） ──
    return _heuristic_parse(text)


def _normalize_resume_data(raw: dict[str, Any]) -> ResumeData:
    """对 LLM 返回的 JSON 字段做清洗与类型校验，确保能构造 ResumeData。"""
    def _to_list(x) -> list:
        if isinstance(x, list):
            return [i for i in x if isinstance(i, (dict, str))]
        return []

    def _to_str(x) -> str:
        if x is None:
            return ""
        if isinstance(x, list):
            return "、".join(str(i) for i in x if i is not None)
        return str(x).strip()

    basic = raw.get("basic") or {}
    if not isinstance(basic, dict):
        basic = {}

    education = [
        EducationEntry(
            school=_to_str(e.get("school")),
            degree=_to_str(e.get("degree")),
            major=_to_str(e.get("major")),
            period=_to_str(e.get("period")),
            gpa=_to_str(e.get("gpa")),
            highlights=[_to_str(h) for h in _to_list(e.get("highlights")) if _to_str(h)],
        )
        for e in _to_list(raw.get("education"))
        if isinstance(e, dict) and _to_str(e.get("school"))
    ]

    experience = [
        ExperienceEntry(
            company=_to_str(e.get("company")),
            position=_to_str(e.get("position")),
            period=_to_str(e.get("period")),
            location=_to_str(e.get("location")),
            points=[_to_str(p) for p in _to_list(e.get("points")) if _to_str(p)],
        )
        for e in _to_list(raw.get("experience"))
        if isinstance(e, dict) and (_to_str(e.get("company")) or _to_str(e.get("position")))
    ]

    projects = [
        ProjectEntry(
            name=_to_str(p.get("name")),
            role=_to_str(p.get("role")),
            period=_to_str(p.get("period")),
            tech_stack=[_to_str(t) for t in _to_list(p.get("tech_stack")) if _to_str(t)],
            link=_to_str(p.get("link")),
            points=[_to_str(x) for x in _to_list(p.get("points")) if _to_str(x)],
        )
        for p in _to_list(raw.get("projects"))
        if isinstance(p, dict) and _to_str(p.get("name"))
    ]

    skills = [
        SkillCategory(
            name=_to_str(s.get("name")) or "其他",
            items=[_to_str(i) for i in _to_list(s.get("items")) if _to_str(i)],
        )
        for s in _to_list(raw.get("skills"))
        if isinstance(s, dict) and _to_list(s.get("items"))
    ]

    awards = [
        AwardEntry(
            name=_to_str(a.get("name")),
            issuer=_to_str(a.get("issuer")),
            date=_to_str(a.get("date")),
        )
        for a in _to_list(raw.get("awards"))
        if isinstance(a, dict) and _to_str(a.get("name"))
    ]

    certifications = [
        CertificationEntry(
            name=_to_str(c.get("name")),
            issuer=_to_str(c.get("issuer")),
            date=_to_str(c.get("date")),
        )
        for c in _to_list(raw.get("certifications"))
        if isinstance(c, dict) and _to_str(c.get("name"))
    ]

    languages = [
        LanguageEntry(name=_to_str(lang.get("name")), level=_to_str(lang.get("level")))
        for lang in _to_list(raw.get("languages"))
        if isinstance(lang, dict) and _to_str(lang.get("name"))
    ]

    return ResumeData(
        basic=BasicInfo(
            name=_to_str(basic.get("name")),
            title=_to_str(basic.get("title")),
            avatar=_to_str(basic.get("avatar")),
            location=_to_str(basic.get("location")),
            email=_to_str(basic.get("email")),
            phone=_to_str(basic.get("phone")),
            website=_to_str(basic.get("website")),
            github=_to_str(basic.get("github")),
            linkedin=_to_str(basic.get("linkedin")),
            summary=_to_str(basic.get("summary")),
        ),
        education=education,
        experience=experience,
        projects=projects,
        skills=skills,
        awards=awards,
        certifications=certifications,
        languages=languages,
    )


def _heuristic_parse(text: str) -> ResumeData:
    """规则兜底解析：从纯文本抽取姓名、邮箱、电话、内容分段。"""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    basic = BasicInfo()
    # 姓名：找首行或出现"姓名："关键字的行
    for ln in lines:
        if ln.startswith("姓名"):
            basic.name = re.sub(r"^姓名[：:\s]*", "", ln).strip()
            break
    if not basic.name and lines:
        first = lines[0]
        if 2 <= len(first) <= 10 and "，" not in first and "。" not in first:
            basic.name = first

    # 邮箱
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    if m:
        basic.email = m.group(0)

    # 电话：1XX-XXXX-XXXX 或 1XXXXXXXXXX
    m = re.search(r"1\d{2}[\s-]?\d{4}[\s-]?\d{4}", text)
    if m:
        basic.phone = m.group(0)

    # GitHub / LinkedIn
    m = re.search(r"github\.com/[\w-]+", text)
    if m:
        basic.github = m.group(0)
    m = re.search(r"linkedin\.com/in/[\w-]+", text, re.IGNORECASE)
    if m:
        basic.linkedin = m.group(0)

    # 摘要：优先匹配"个人摘要 / 自我评价"之后到下一个标题之前
    summary_match = re.search(
        r"(个人摘要|自我评价|求职意向|个人简介)[\s：:]*\n([\s\S]*?)\n(工作经历|项目经历|教育背景|核心技能|技能|$)",
        text,
    )
    if summary_match:
        basic.summary = summary_match.group(2).strip().replace("\n", " ")[:400]

    # 经历段（简单规则：含"经历"标题后按空行拆分）
    experience: list[ExperienceEntry] = []
    exp_match = re.search(r"工作经历[\s：:]*\n([\s\S]*?)(项目经历|教育背景|核心技能|技能|证书|奖项|$)", text)
    if exp_match:
        exp_block = exp_match.group(1).strip()
        blocks = re.split(r"\n\s*\n", exp_block)
        for blk in blocks[:5]:
            sub_lines = [ln for ln in blk.splitlines() if ln.strip()]
            if not sub_lines:
                continue
            first_line = sub_lines[0]
            # 首行格式：公司 | 职位 | 时间（多种分隔符）
            parts = re.split(r"\s*[|｜\t]\s*", first_line, maxsplit=3)
            company = parts[0].strip() if len(parts) > 0 else ""
            position = parts[1].strip() if len(parts) > 1 else ""
            period = parts[2].strip() if len(parts) > 2 else ""
            points = [ln.strip(" -\u2022•·") for ln in sub_lines[1:] if ln.strip(" -\u2022•·")]
            if company or position:
                experience.append(ExperienceEntry(
                    company=company, position=position, period=period, points=points,
                ))

    # 教育背景
    education: list[EducationEntry] = []
    edu_match = re.search(r"教育背景[\s：:]*\n([\s\S]*?)(工作经历|项目经历|核心技能|技能|证书|奖项|$)", text)
    if edu_match:
        for ln in edu_match.group(1).splitlines():
            ln = ln.strip()
            if not ln:
                continue
            parts = re.split(r"\s*[|｜\t]\s*", ln, maxsplit=4)
            if len(parts) >= 2:
                education.append(EducationEntry(
                    school=parts[0].strip(), degree=parts[1].strip(),
                    major=parts[2].strip() if len(parts) > 2 else "",
                    period=parts[3].strip() if len(parts) > 3 else "",
                ))

    # 技能
    skills: list[SkillCategory] = []
    skill_match = re.search(r"(核心技能|技能专长|专业技能)[\s：:]*\n([\s\S]*?)(工作经历|项目经历|教育背景|证书|奖项|$)", text)
    if skill_match:
        skill_block = skill_match.group(2).replace("\n", " ")
        items = [s.strip() for s in re.split(r"[，,、;；/]", skill_block) if s.strip()]
        if items:
            skills.append(SkillCategory(name="专业技能", items=items[:30]))

    logger.info("规则兜底解析：姓名=%s，经历=%d，教育=%d", basic.name, len(experience), len(education))
    return ResumeData(
        basic=basic, education=education, experience=experience, skills=skills,
    )


# ──────────────────────────────────────────────
# 2. YAML 序列化 / 反序列化
# ──────────────────────────────────────────────

def resume_to_yaml(data: ResumeData) -> str:
    """将 ResumeData 转为 YAML 字符串；无 PyYAML 时退回 JSON（兼容解析）。"""
    try:
        import yaml  # type: ignore

        return yaml.safe_dump(
            data.model_dump(mode="json"),
            allow_unicode=True, sort_keys=False, default_flow_style=False,
        )
    except ImportError:
        logger.info("PyYAML 未安装，使用 JSON 格式保存数据")
        return json.dumps(data.model_dump(mode="json"), ensure_ascii=False, indent=2)


def resume_from_yaml(yaml_text: str) -> ResumeData:
    """从 YAML / JSON 文本加载 ResumeData。"""
    try:
        import yaml  # type: ignore

        raw = yaml.safe_load(yaml_text) or {}
    except ImportError:
        raw = json.loads(yaml_text)
    if not isinstance(raw, dict):
        raise ValueError("简历数据文件格式错误，根节点必须是对象")
    return _normalize_resume_data(raw)


# ──────────────────────────────────────────────
# 3. HTML 模板渲染（3 套）
# ──────────────────────────────────────────────

def render_resume_html(data: ResumeData, template: str = DEFAULT_TEMPLATE) -> str:
    """将结构化 ResumeData 渲染为完整的 HTML 字符串。

    Args:
        data: 结构化简历数据
        template: 模板风格（modern / professional / tech）

    Returns:
        完整 HTML 字符串，浏览器打开后 Ctrl+P 可直接导出 A4 PDF

    Raises:
        ValueError: template 不在 VALID_TEMPLATES 内
    """
    if template not in VALID_TEMPLATES:
        raise ValueError(
            f"不支持的模板：{template}，可选：{sorted(VALID_TEMPLATES)}"
        )
    if template == TEMPLATE_MODERN:
        return _render_modern(data)
    if template == TEMPLATE_PROFESSIONAL:
        return _render_professional(data)
    if template == TEMPLATE_TECH:
        return _render_tech(data)
    return _render_classic(data)


def _h(s: str) -> str:
    """HTML 转义（空字符串安全）。"""
    return html.escape(s or "", quote=True)


def _join_points(points: list[str]) -> str:
    """将要点列表转为 <li>...</li>。"""
    if not points:
        return ""
    lis = []
    for p in points:
        p = (p or "").strip()
        if not p:
            continue
        # 简单处理：**xxx** 转为 <strong>xxx</strong>，数字自动加粗
        p2 = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", p)
        p2 = re.sub(r"(\d+(?:\.\d+)?%?)", r"<strong>\1</strong>", p2)
        lis.append(f"<li>{_h(p2).replace('&lt;strong&gt;', '<strong>').replace('&lt;/strong&gt;', '</strong>')}</li>")
    return "".join(lis)


# ────────── 模板 1：现代简约 ──────────
def _render_modern(data: ResumeData) -> str:
    """模板一：双栏蓝紫渐变 / 图标点缀 / 清爽现代。"""
    b = data.basic
    name = b.name or "未命名"
    avatar_html = (
        f'<img src="{b.avatar}" class="avatar-img">' if b.avatar else
        f'<div class="avatar">{_h(name[:1])}</div>'
    )

    # 联系方式（按有值的顺序拼接）
    contact_items = []
    for label, icon, value in [
        ("定位", "📍", b.location), ("邮箱", "✉️", b.email),
        ("电话", "📞", b.phone), ("网站", "🌐", b.website),
        ("GitHub", "", b.github), ("LinkedIn", "in", b.linkedin),
    ]:
        if not value:
            continue
        if "http" in value or value.startswith("github.com") or value.startswith("linkedin.com"):
            val_html = f'<a href="{("https://" if not value.startswith("http") else "") + _h(value)}" target="_blank">{_h(value)}</a>'
        else:
            val_html = _h(value)
        contact_items.append(
            f'<div class="contact-item"><span class="icon">{icon}</span>{val_html}</div>'
        )
    contact_html = "\n      ".join(contact_items)

    # 技能（侧栏）
    skill_html = ""
    for sc in data.skills:
        tags = "".join(f'<span class="skill-tag">{_h(s)}</span>' for s in sc.items)
        skill_html += f'''<div class="skill-cat">
        <div class="skill-cat-name">{_h(sc.name)}</div>
        <div class="skill-tags">{tags}</div>
      </div>\n'''

    # 语言
    lang_html = ""
    if data.languages:
        lang_items = "".join(
            f'<div class="lang-item"><span class="lang-name">{_h(lang.name)}</span><span class="lang-level">{_h(lang.level)}</span></div>'
            for lang in data.languages
        )
        lang_html = f'''<div class="sidebar-section">
      <h3>语言能力</h3>
      {lang_items}
    </div>'''

    # 证书
    cert_html = ""
    if data.certifications:
        items = "".join(
            f'<div class="cert-item"><span><b>{_h(c.name)}</b> <span style="opacity:0.8;font-size:11px">{_h(c.issuer)}</span></span><span>{_h(c.date)}</span></div>'
            for c in data.certifications
        )
        cert_html = f'''<div class="sidebar-section">
      <h3>证书资质</h3>
      {items}
    </div>'''

    # 主内容：个人摘要
    sections_html = ""
    if b.summary:
        sections_html += f'''<section class="section">
      <div class="section-title">个人简介</div>
      <p class="summary-text">{_h(b.summary)}</p>
    </section>
    '''

    # 工作经历
    exp_html = ""
    for exp in data.experience:
        exp_html += f'''<div class="entry">
        <div class="entry-header">
          <span class="entry-company">{_h(exp.company)}</span>
          <span class="entry-position">{_h(exp.position)}</span>
          <span class="entry-period">{_h(exp.period)}</span>
          <span class="entry-location">{_h(exp.location)}</span>
        </div>
        <ul class="entry-points">
          {_join_points(exp.points)}
        </ul>
      </div>
      '''
    if exp_html:
        sections_html += f'''<section class="section">
      <div class="section-title">工作经历</div>
      {exp_html}
    </section>
    '''

    # 项目经历
    proj_html = ""
    for p in data.projects:
        tech_badges = "".join(f'<span class="tech-badge">{_h(t)}</span>' for t in p.tech_stack)
        link_html = f' <a class="project-link" href="{("https://" if not p.link.startswith("http") else "") + _h(p.link)}" target="_blank">↗ 链接</a>' if p.link else ""
        proj_html += f'''<div class="entry">
        <div class="entry-header">
          <span class="entry-company">{_h(p.name)}</span>
          <span class="entry-position">{_h(p.role)}</span>
          <span class="entry-period">{_h(p.period)}</span>
          {link_html}
        </div>
        <div class="project-meta">
          <span class="tech-badges">{tech_badges}</span>
        </div>
        <ul class="entry-points">
          {_join_points(p.points)}
        </ul>
      </div>
      '''
    if proj_html:
        sections_html += f'''<section class="section">
      <div class="section-title">项目经历</div>
      {proj_html}
    </section>
    '''

    # 教育经历
    edu_html = ""
    for edu in data.education:
        highlights = ""
        if edu.highlights:
            highlights = f'<div class="entry-subtitle">{" · ".join(_h(h) for h in edu.highlights)}</div>'
        gpa_html = f"<div class='entry-subtitle'>GPA：{_h(edu.gpa)}</div>" if edu.gpa else ""
        edu_html += f'''<div class="entry">
        <div class="entry-header">
          <span class="entry-school">{_h(edu.school)}</span>
          <span class="entry-degree">{_h(edu.degree)} · {_h(edu.major)}</span>
          <span class="entry-period">{_h(edu.period)}</span>
        </div>
        {highlights}
        {gpa_html}
      </div>
      '''
    if edu_html:
        sections_html += f'''<section class="section">
      <div class="section-title">教育背景</div>
      {edu_html}
    </section>
    '''

    # 奖项
    if data.awards:
        awards_items = "".join(
            f'<div class="award-item"><span><span class="award-name">{_h(a.name)}</span> <span class="award-issuer">{_h(a.issuer)}</span></span><span class="award-date">{_h(a.date)}</span></div>'
            for a in data.awards
        )
        sections_html += f'''<section class="section">
      <div class="section-title">荣誉奖项</div>
      {awards_items}
    </section>
    '''

    html_str = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{_h(name)} - 简历</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 13px; line-height: 1.6; color: #1f2937; background: #f5f5f5;
  }}
  .resume {{
    max-width: 210mm; min-height: 297mm; margin: 0 auto;
    background: #fff; display: grid; grid-template-columns: 230px 1fr;
    box-shadow: 0 4px 24px rgba(0,0,0,0.08);
  }}
  .sidebar {{
    background: linear-gradient(160deg, #2563eb 0%, #1e40af 100%);
    color: #fff; padding: 32px 22px;
  }}
  .sidebar .avatar, .sidebar .avatar-img {{
    width: 110px; height: 110px; border-radius: 50%;
    border: 3px solid rgba(255,255,255,0.3);
    margin: 0 auto 18px; display: flex; align-items: center; justify-content: center;
    background: rgba(255,255,255,0.1); font-size: 40px; font-weight: 600;
    object-fit: cover;
  }}
  .sidebar h1 {{ font-size: 22px; text-align: center; margin-bottom: 4px; }}
  .sidebar .title {{ font-size: 13px; text-align: center; opacity: 0.9; margin-bottom: 24px; }}
  .sidebar-section {{ margin-bottom: 22px; }}
  .sidebar-section h3 {{
    font-size: 13px; font-weight: 600; margin-bottom: 10px;
    padding-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.25);
    letter-spacing: 1px;
  }}
  .sidebar-section a {{ color: #dbeafe; text-decoration: none; }}
  .contact-item {{ font-size: 12px; margin-bottom: 8px; display: flex; align-items: flex-start; gap: 7px; word-break: break-all; }}
  .contact-item .icon {{ width: 14px; flex-shrink: 0; opacity: 0.85; }}
  .skill-cat {{ margin-bottom: 12px; }}
  .skill-cat-name {{ font-size: 12px; opacity: 0.9; margin-bottom: 5px; }}
  .skill-tags {{ display: flex; flex-wrap: wrap; gap: 5px; }}
  .skill-tag {{
    background: rgba(255,255,255,0.18); padding: 3px 9px; border-radius: 10px; font-size: 11px;
  }}
  .main-content {{ padding: 32px 30px; }}
  .section {{ margin-bottom: 22px; page-break-inside: avoid; }}
  .section-title {{
    font-size: 16px; font-weight: 700; color: #1e40af;
    margin-bottom: 12px; padding-bottom: 6px;
    border-bottom: 2px solid #2563eb; display: flex; align-items: center; gap: 8px;
  }}
  .section-title::before {{
    content: ''; width: 4px; height: 16px; background: #2563eb; border-radius: 2px;
  }}
  .summary-text {{ color: #374151; line-height: 1.75; text-align: justify; }}
  .entry {{ margin-bottom: 16px; }}
  .entry:last-child {{ margin-bottom: 0; }}
  .entry-header {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 4px; gap: 12px; flex-wrap: wrap; }}
  .entry-company, .entry-school {{ font-size: 14px; font-weight: 700; color: #111827; }}
  .entry-position, .entry-degree {{ font-size: 13px; color: #2563eb; font-weight: 600; margin-right: auto; }}
  .entry-period {{ font-size: 12px; color: #6b7280; white-space: nowrap; }}
  .entry-location {{ font-size: 12px; color: #6b7280; white-space: nowrap; }}
  .entry-subtitle {{ font-size: 12px; color: #6b7280; margin-bottom: 6px; }}
  .entry-points {{ padding-left: 18px; }}
  .entry-points li {{
    font-size: 12.5px; line-height: 1.65; margin-bottom: 3px;
    color: #374151; text-align: justify;
  }}
  .entry-points li::marker {{ color: #2563eb; }}
  .entry-points strong {{ color: #dc2626; }}
  .project-meta {{ font-size: 12px; color: #6b7280; margin-bottom: 6px; display: flex; gap: 10px; flex-wrap: wrap; }}
  .tech-badges {{ display: inline-flex; flex-wrap: wrap; gap: 4px; }}
  .tech-badge {{
    background: #eff6ff; color: #1e40af; padding: 1px 7px; border-radius: 3px;
    font-size: 11px; font-family: Consolas, Monaco, monospace;
  }}
  .project-link {{
    font-size: 11px; color: #2563eb; text-decoration: none;
    background: #eff6ff; padding: 2px 8px; border-radius: 4px;
  }}
  .award-item, .cert-item {{
    display: flex; justify-content: space-between; align-items: baseline;
    padding: 5px 0; font-size: 12.5px; border-bottom: 1px dashed #e5e7eb; gap: 12px;
  }}
  .award-item:last-child, .cert-item:last-child {{ border-bottom: none; }}
  .award-name {{ font-weight: 600; color: #111827; }}
  .award-issuer {{ color: #6b7280; font-size: 12px; }}
  .award-date {{ color: #6b7280; font-size: 12px; white-space: nowrap; }}
  .lang-item {{ margin-bottom: 7px; }}
  .lang-name {{ font-weight: 600; font-size: 12.5px; display: inline-block; min-width: 50px; }}
  .lang-level {{ opacity: 0.85; font-size: 12px; margin-left: 6px; }}
  @media print {{
    @page {{ size: A4; margin: 0; }}
    body {{ background: #fff; }}
    .resume {{ box-shadow: none; }}
  }}
</style>
</head>
<body>
<div class="resume">
  <aside class="sidebar">
    {avatar_html}
    <h1>{_h(name)}</h1>
    <div class="title">{_h(b.title)}</div>
    <div class="sidebar-section">
      <h3>联系方式</h3>
      {contact_html}
    </div>
    <div class="sidebar-section">
      <h3>技能专长</h3>
      {skill_html}
    </div>
    {lang_html}
    {cert_html}
  </aside>
  <main class="main-content">
    {sections_html}
  </main>
</div>
</body>
</html>"""
    return html_str


# ────────── 模板 2：商务正式 ──────────
def _render_professional(data: ResumeData) -> str:
    """模板二：单栏宋体 / 黑白灰 / 严谨商务风。"""
    b = data.basic
    name = b.name or "未命名"

    contact_parts = []
    for val in [b.location, b.phone, b.email, b.website, b.github, b.linkedin]:
        if val:
            contact_parts.append(_h(val))
    contact_html = '<span class="sep"> | </span>'.join(contact_parts)

    sections_html = ""
    if b.summary:
        sections_html += f'''<section class="section">
      <div class="section-title">自 我 评 价</div>
      <p class="summary-text">{_h(b.summary)}</p>
    </section>
    '''

    exp_html = ""
    for exp in data.experience:
        sub_parts = []
        if exp.location:
            sub_parts.append(_h(exp.location))
        sub_html = f"<div class='entry-sub'>{'  '.join(sub_parts)}</div>" if sub_parts else ""
        exp_html += f'''<div class="entry">
        <div class="entry-header">
          <span class="entry-company">{_h(exp.company)}</span>
          <span class="entry-position">{_h(exp.position)}</span>
          <span class="entry-period">{_h(exp.period)}</span>
        </div>
        {sub_html}
        <ul class="entry-points">
          {_join_points(exp.points)}
        </ul>
      </div>
      '''
    if exp_html:
        sections_html += f'''<section class="section">
      <div class="section-title">工 作 经 历</div>
      {exp_html}
    </section>
    '''

    proj_html = ""
    for p in data.projects:
        meta_parts = []
        if p.tech_stack:
            meta_parts.append("技术栈：" + "、".join(_h(t) for t in p.tech_stack))
        meta_html = "<div class=\"project-meta\">" + " | ".join(meta_parts) + "</div>" if meta_parts else ""
        proj_html += f'''<div class="entry">
        <div class="project-title-row">
          <span class="project-name">{_h(p.name)}</span>
          <span class="project-role">{_h(p.role)}</span>
          <span class="entry-period">{_h(p.period)}</span>
        </div>
        {meta_html}
        <ul class="entry-points">
          {_join_points(p.points)}
        </ul>
      </div>
      '''
    if proj_html:
        sections_html += f'''<section class="section">
      <div class="section-title">项 目 经 历</div>
      {proj_html}
    </section>
    '''

    edu_html = ""
    for edu in data.education:
        sub_parts = [_h(edu.degree), _h(edu.major)]
        if edu.gpa:
            sub_parts.append("GPA: " + _h(edu.gpa))
        if edu.highlights:
            sub_parts.extend(_h(h) for h in edu.highlights)
        edu_html += f'''<div class="entry">
        <div class="entry-header">
          <span class="entry-school">{_h(edu.school)}</span>
          <span class="entry-degree">{" · ".join(s for s in sub_parts if s)}</span>
          <span class="entry-period">{_h(edu.period)}</span>
        </div>
      </div>
      '''
    if edu_html:
        sections_html += f'''<section class="section">
      <div class="section-title">教 育 背 景</div>
      {edu_html}
    </section>
    '''

    # 技能：两列表格样式
    skill_rows = ""
    for sc in data.skills:
        skill_rows += f'''<tr>
        <td>{_h(sc.name)}</td>
        <td>{'、'.join(_h(i) for i in sc.items)}</td>
      </tr>
      '''
    if skill_rows:
        sections_html += f'''<section class="section">
      <div class="section-title">专 业 技 能</div>
      <table class="skills-table">
        {skill_rows}
      </table>
    </section>
    '''

    # 证书 + 奖项合并展示
    honor_list = []
    for a in data.awards:
        line_parts = [f'<span class="name">{_h(a.name)}</span>']
        if a.issuer:
            line_parts.append(f'<span class="sub">{_h(a.issuer)}</span>')
        honor_list.append(
            f'<li><span class="left">{"".join(line_parts)}</span><span class="date">{_h(a.date)}</span></li>'
        )
    for c in data.certifications:
        line_parts = [f'<span class="name">{_h(c.name)}</span>']
        if c.issuer:
            line_parts.append(f'<span class="sub">{_h(c.issuer)}</span>')
        honor_list.append(
            f'<li><span class="left">{"".join(line_parts)}</span><span class="date">{_h(c.date)}</span></li>'
        )
    if data.languages:
        for lang in data.languages:
            honor_list.append(
                f'<li><span class="left"><span class="name">语言能力 - {_h(lang.name)}</span><span class="sub">{_h(lang.level)}</span></span></li>'
            )
    if honor_list:
        sections_html += f'''<section class="section">
      <div class="section-title">荣 誉 证 书</div>
      <ul class="simple-list">
        {''.join(honor_list)}
      </ul>
    </section>
    '''

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{_h(name)} - 个人简历</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: "SimSun", "Songti SC", "Times New Roman", "Noto Serif SC", serif;
    font-size: 12.5px; line-height: 1.7; color: #1a1a1a; background: #f3f3f3;
  }}
  .resume {{
    max-width: 210mm; min-height: 297mm; margin: 0 auto;
    background: #fff; padding: 28mm 22mm;
    box-shadow: 0 4px 24px rgba(0,0,0,0.06);
  }}
  .header {{
    text-align: center; padding-bottom: 16px;
    border-bottom: 2px solid #333; margin-bottom: 20px;
  }}
  .header h1 {{
    font-size: 30px; font-weight: 700; letter-spacing: 6px;
    margin-bottom: 6px; color: #1a1a1a;
  }}
  .header .position {{
    font-size: 15px; color: #555; letter-spacing: 2px; margin-bottom: 12px;
  }}
  .header .contact {{
    font-size: 12px; color: #444;
  }}
  .header .contact .sep {{ color: #bbb; }}
  .section {{ margin-bottom: 18px; page-break-inside: avoid; }}
  .section-title {{
    font-size: 14px; font-weight: 700; color: #1a1a1a;
    padding-bottom: 4px; border-bottom: 1px solid #333;
    margin-bottom: 10px; letter-spacing: 2px;
  }}
  .summary-text {{ text-indent: 2em; text-align: justify; color: #2a2a2a; }}
  .entry {{ margin-bottom: 14px; }}
  .entry-header, .project-title-row {{
    display: flex; justify-content: space-between; align-items: baseline;
    margin-bottom: 3px; gap: 10px; flex-wrap: wrap;
  }}
  .entry-company {{ font-size: 13px; font-weight: 700; color: #1a1a1a; }}
  .entry-position {{ font-size: 13px; font-weight: 600; color: #333; margin-right: auto; }}
  .entry-school {{ font-size: 13px; font-weight: 700; }}
  .entry-degree {{ font-size: 13px; font-weight: 600; color: #333; margin-right: auto; }}
  .project-name {{ font-size: 13px; font-weight: 700; }}
  .project-role {{ font-size: 12px; color: #555; margin-right: auto; }}
  .entry-period {{ font-size: 12px; color: #666; white-space: nowrap; }}
  .entry-sub, .project-meta {{
    font-size: 11.5px; color: #555; margin-bottom: 4px;
  }}
  .project-meta {{ font-style: italic; }}
  .entry-points {{ padding-left: 20px; }}
  .entry-points li {{ text-align: justify; margin-bottom: 3px; color: #2a2a2a; }}
  .entry-points strong {{ color: #b91c1c; font-weight: 700; }}
  .skills-table {{ width: 100%; border-collapse: collapse; }}
  .skills-table td {{
    padding: 6px 10px; border-bottom: 1px solid #e0e0e0; vertical-align: top;
    font-size: 12px;
  }}
  .skills-table td:first-child {{
    width: 90px; font-weight: 700; color: #333; white-space: nowrap; background: #fafafa;
  }}
  .simple-list {{ list-style: none; }}
  .simple-list li {{
    padding: 4px 0; display: flex; justify-content: space-between;
    align-items: baseline; gap: 12px; border-bottom: 1px dotted #ddd;
  }}
  .simple-list li:last-child {{ border-bottom: none; }}
  .simple-list .left {{ flex: 1; }}
  .simple-list .name {{ font-weight: 600; }}
  .simple-list .sub {{ color: #666; font-size: 11.5px; margin-left: 8px; }}
  .simple-list .date {{ color: #666; font-size: 11.5px; white-space: nowrap; }}
  ul {{ list-style: disc; }}
  @media print {{
    @page {{ size: A4; margin: 0; }}
    body {{ background: #fff; }}
    .resume {{ box-shadow: none; }}
  }}
</style>
</head>
<body>
<div class="resume">
  <header class="header">
    <h1>{_h(name)}</h1>
    <div class="position">{_h(b.title)}</div>
    <div class="contact">{contact_html}</div>
  </header>
  {sections_html}
</div>
</body>
</html>"""


# ────────── 模板 3：技术导向 ──────────
def _render_tech(data: ResumeData) -> str:
    """模板三：代码风格 / 深浅配色 / 技术芯片 / 程序员专属。"""
    b = data.basic
    name = b.name or "dev"

    contact_items = []
    if b.location:
        contact_items.append(f"<span>📍 {_h(b.location)}</span>")
    if b.email:
        contact_items.append(f"<span>📧 {_h(b.email)}</span>")
    if b.phone:
        contact_items.append(f"<span>📞 {_h(b.phone)}</span>")
    if b.github:
        gh_link = ("https://" if not b.github.startswith("http") else "") + _h(b.github)
        contact_items.append(f"<span>🐙 <a href=\"{gh_link}\" target=\"_blank\">{_h(b.github)}</a></span>")
    if b.website:
        ws_link = ("https://" if not b.website.startswith("http") else "") + _h(b.website)
        contact_items.append(f"<span>🌐 <a href=\"{ws_link}\" target=\"_blank\">{_h(b.website)}</a></span>")
    if b.linkedin:
        li_link = ("https://" if not b.linkedin.startswith("http") else "") + _h(b.linkedin)
        contact_items.append(f"<span>💼 <a href=\"{li_link}\" target=\"_blank\">{_h(b.linkedin)}</a></span>")
    contact_bar = "\n      ".join(contact_items)

    # 主内容列
    main_col = ""
    if data.experience:
        items_html = ""
        for exp in data.experience:
            loc_html = f"<span class='exp-loc'>{_h(exp.location)}</span>" if exp.location else ""
            items_html += f'''<div class="experience-item">
          <div class="exp-head">
            <span class="exp-company">{_h(exp.company)}</span>
            <span class="exp-position">{_h(exp.position)}</span>
            {loc_html}
            <span class="exp-period">{_h(exp.period)}</span>
          </div>
          <ul class="exp-points">
            {_join_points(exp.points)}
          </ul>
        </div>
        '''
        main_col += f'''<section class="section">
        <div class="section-title">EXPERIENCE <span class="section-title-code">// 工作经历</span></div>
        {items_html}
      </section>
      '''

    if data.projects:
        cards_html = ""
        for p in data.projects:
            chips = "".join(f'<span class="tech-chip">{_h(t)}</span>' for t in p.tech_stack)
            link_html = ""
            if p.link:
                plink = ("https://" if not p.link.startswith("http") else "") + _h(p.link)
                link_html = f'<a href="{plink}" class="project-link" target="_blank">repo ↗</a>'
            cards_html += f'''<div class="project-card">
          <div class="project-head">
            <span class="project-name">{_h(p.name)}</span>
            {link_html}
          </div>
          <div class="project-role">{_h(p.role)} · {_h(p.period)}</div>
          <div class="project-tech">{chips}</div>
          <ul class="project-desc">
            {_join_points(p.points)}
          </ul>
        </div>
        '''
        main_col += f'''<section class="section">
        <div class="section-title">PROJECTS <span class="section-title-code">// 项目经历</span></div>
        {cards_html}
      </section>
      '''

    # 侧栏列
    side_col = ""
    if data.skills:
        groups_html = ""
        for sc in data.skills:
            chips = "".join(
                f'<span class="skill-chip level-high">{_h(i)}</span>' for i in sc.items[:6]
            ) + "".join(
                f'<span class="skill-chip level-mid">{_h(i)}</span>' for i in sc.items[6:12]
            ) + "".join(
                f'<span class="skill-chip level-basic">{_h(i)}</span>' for i in sc.items[12:]
            )
            groups_html += f'''<div class="skill-group">
          <div class="skill-group-name">{_h(sc.name)}</div>
          <div class="skill-list">{chips}</div>
        </div>
        '''
        side_col += f'''<div class="side-section">
        <div class="side-title">SKILLS / 技能栈</div>
        {groups_html}
      </div>
      '''

    if data.education:
        edu_html = ""
        for edu in data.education:
            sub_parts = [_h(edu.degree), _h(edu.major)]
            if edu.gpa:
                sub_parts.append("GPA " + _h(edu.gpa))
            edu_html += f'''<div class="edu-item">
          <div class="edu-school">{_h(edu.school)}</div>
          <div class="edu-detail">{' · '.join(s for s in sub_parts if s)}</div>
          <div class="edu-period">{_h(edu.period)}</div>
        </div>
        '''
        side_col += f'''<div class="side-section">
        <div class="side-title">EDUCATION / 教育背景</div>
        {edu_html}
      </div>
      '''

    # 奖项 / GitHub 统计区
    stats_rows = ""
    for a in data.awards:
        stats_rows += f'''<div class="gh-stat">
        <span class="gh-label">{_h(a.name)}</span>
        <span class="gh-value">{_h(a.date or a.issuer)}</span>
      </div>
      '''
    for c in data.certifications:
        stats_rows += f'''<div class="gh-stat">
        <span class="gh-label">{_h(c.name)}</span>
        <span class="gh-value">{_h(c.date or c.issuer)}</span>
      </div>
      '''
    for lang in data.languages:
        stats_rows += f'''<div class="gh-stat">
        <span class="gh-label">Lang: {_h(lang.name)}</span>
        <span class="gh-value">{_h(lang.level)}</span>
      </div>
      '''
    if b.summary:
        stats_rows += f'''<div class="gh-stat">
        <span class="gh-label" style="line-height:1.5">{_h(b.summary[:80] + ("..." if len(b.summary) > 80 else ""))}</span>
      </div>
      '''
    if stats_rows:
        side_col += f'''<div class="side-section">
        <div class="side-title">STATS / 概况</div>
        {stats_rows}
      </div>
      '''

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{_h(name)} - Resume</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: "JetBrains Mono", "SF Mono", "Fira Code", Consolas, "PingFang SC", "Microsoft YaHei", monospace, sans-serif;
    font-size: 13px; line-height: 1.6; color: #0f172a; background: #0f172a;
  }}
  .resume {{
    max-width: 210mm; min-height: 297mm; margin: 0 auto;
    background: #ffffff; border: 3px solid #1e293b;
    display: grid; grid-template-columns: 1fr 260px;
  }}
  .top-header {{
    grid-column: 1 / -1;
    background: #0f172a; color: #e2e8f0;
    padding: 26px 30px; border-bottom: 3px solid #334155;
  }}
  .top-header .name-line {{
    font-size: 26px; font-weight: 700; color: #38bdf8;
    font-family: "JetBrains Mono", "SF Mono", Consolas, monospace;
  }}
  .top-header .name-line::before {{ content: "const "; color: #94a3b8; font-size: 18px; }}
  .top-header .name-line::after {{ content: " = {{"; color: #94a3b8; font-size: 18px; margin-left: 4px; }}
  .top-header .subtitle {{
    color: #fbbf24; font-size: 14px; margin: 4px 0 0 64px;
  }}
  .top-header .subtitle::before {{ content: "role: "; color: #94a3b8; }}
  .top-header .contact-bar {{
    margin-top: 14px; display: flex; flex-wrap: wrap; gap: 16px;
    margin-left: 64px; font-size: 12px;
  }}
  .top-header .contact-bar span {{ color: #cbd5e1; }}
  .top-header .contact-bar a {{ color: #7dd3fc; text-decoration: none; }}
  .main-col {{ padding: 26px 28px; }}
  .side-col {{
    padding: 26px 20px;
    background: #f8fafc; border-left: 2px solid #e2e8f0;
  }}
  .section {{ margin-bottom: 22px; page-break-inside: avoid; }}
  .section-title {{
    font-family: "JetBrains Mono", Consolas, monospace;
    font-size: 14px; font-weight: 700;
    color: #1e293b; margin-bottom: 12px;
    display: flex; align-items: center; gap: 8px;
  }}
  .section-title::before {{ content: "#"; color: #0ea5e9; font-weight: 700; }}
  .section-title-code {{ font-size: 12px; color: #64748b; font-weight: normal; }}
  .experience-item {{
    margin-bottom: 18px; padding-left: 14px;
    border-left: 2px solid #cbd5e1; position: relative;
  }}
  .experience-item::before {{
    content: ''; position: absolute; left: -6px; top: 4px;
    width: 10px; height: 10px; background: #0ea5e9;
    border-radius: 50%; border: 2px solid #fff;
  }}
  .exp-head {{
    display: flex; justify-content: space-between; align-items: baseline;
    margin-bottom: 3px; gap: 10px; flex-wrap: wrap;
  }}
  .exp-company {{
    font-family: "JetBrains Mono", Consolas, monospace;
    font-size: 14px; font-weight: 700; color: #0f172a;
  }}
  .exp-company::before {{ content: "@"; color: #0ea5e9; margin-right: 3px; }}
  .exp-position {{ font-size: 13px; color: #0369a1; font-weight: 600; margin-right: auto; }}
  .exp-period {{
    font-family: "JetBrains Mono", Consolas, monospace;
    font-size: 11px; color: #64748b; background: #f1f5f9;
    padding: 2px 8px; border-radius: 3px;
  }}
  .exp-loc {{ font-size: 11px; color: #64748b; }}
  .exp-points {{ padding-left: 18px; margin-top: 6px; }}
  .exp-points li {{ margin-bottom: 4px; font-size: 12.5px; text-align: justify; color: #1e293b; }}
  .exp-points li::marker {{ color: #0ea5e9; content: "▸ "; }}
  .exp-points strong {{ color: #dc2626; }}
  .exp-points code {{
    background: #f1f5f9; padding: 1px 5px; border-radius: 3px;
    font-family: "JetBrains Mono", Consolas, monospace; font-size: 11px; color: #7c3aed;
  }}
  .project-card {{
    border: 1px solid #e2e8f0; border-radius: 5px;
    padding: 12px 14px; margin-bottom: 12px; background: #fff;
  }}
  .project-head {{
    display: flex; justify-content: space-between; align-items: baseline;
    margin-bottom: 5px; gap: 10px;
  }}
  .project-name {{
    font-family: "JetBrains Mono", Consolas, monospace; font-weight: 700; color: #111827;
  }}
  .project-name::before {{ content: "$ "; color: #0ea5e9; }}
  .project-link {{
    font-family: "JetBrains Mono", Consolas, monospace;
    font-size: 11px; color: #2563eb; text-decoration: none;
    background: #eff6ff; padding: 2px 7px; border-radius: 3px;
  }}
  .project-role {{ font-size: 12px; color: #475569; margin-bottom: 5px; }}
  .project-tech {{ display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 7px; }}
  .tech-chip {{
    font-family: "JetBrains Mono", Consolas, monospace;
    font-size: 10.5px; padding: 2px 7px; border-radius: 3px;
    background: #0f172a; color: #38bdf8;
  }}
  .project-desc {{ padding-left: 16px; list-style: none; }}
  .project-desc li {{ margin-bottom: 3px; font-size: 12px; color: #334155; }}
  .project-desc li::before {{ content: "✓ "; color: #10b981; font-weight: 700; }}
  .project-desc strong {{ color: #dc2626; }}
  .side-section {{ margin-bottom: 20px; }}
  .side-title {{
    font-family: "JetBrains Mono", Consolas, monospace;
    font-size: 13px; font-weight: 700; color: #0f172a;
    margin-bottom: 10px; padding-bottom: 5px;
    border-bottom: 2px solid #0ea5e9;
  }}
  .side-title::before {{ content: "// "; color: #64748b; font-weight: normal; }}
  .skill-group {{ margin-bottom: 12px; }}
  .skill-group-name {{
    font-size: 11px; color: #475569; font-weight: 600;
    margin-bottom: 5px; text-transform: uppercase; letter-spacing: 0.5px;
  }}
  .skill-list {{ display: flex; flex-wrap: wrap; gap: 5px; }}
  .skill-chip {{
    font-family: "JetBrains Mono", Consolas, monospace;
    font-size: 11px; padding: 3px 8px; border-radius: 3px;
    background: #0f172a; color: #e2e8f0;
  }}
  .skill-chip.level-high {{ background: #065f46; color: #a7f3d0; border-left: 2px solid #10b981; }}
  .skill-chip.level-mid {{ background: #78350f; color: #fde68a; border-left: 2px solid #f59e0b; }}
  .skill-chip.level-basic {{ background: #334155; color: #cbd5e1; }}
  .edu-item {{ margin-bottom: 12px; }}
  .edu-school {{ font-weight: 700; font-size: 13px; }}
  .edu-detail {{ font-size: 11.5px; color: #475569; margin: 2px 0; }}
  .edu-period {{
    font-family: "JetBrains Mono", Consolas, monospace;
    font-size: 10.5px; color: #64748b; background: #e2e8f0;
    padding: 1px 6px; border-radius: 2px; display: inline-block;
  }}
  .gh-stat {{
    display: flex; justify-content: space-between; align-items: center;
    padding: 5px 0; font-size: 12px; border-bottom: 1px dashed #cbd5e1; gap: 8px;
  }}
  .gh-stat:last-child {{ border-bottom: none; }}
  .gh-label {{ color: #475569; flex: 1; }}
  .gh-value {{
    font-family: "JetBrains Mono", Consolas, monospace;
    font-weight: 700; color: #0369a1; font-size: 11px; white-space: nowrap;
  }}
  @media print {{
    @page {{ size: A4; margin: 0; }}
    body {{ background: #fff; }}
    .resume {{ border: none; }}
  }}
</style>
</head>
<body>
<div class="resume">
  <header class="top-header">
    <div class="name-line">{_h(name)}</div>
    <div class="subtitle">{_h(b.title or "Software Engineer")}</div>
    <div class="contact-bar">{contact_bar}</div>
  </header>
  <div class="main-col">{main_col}</div>
  <div class="side-col">{side_col}</div>
</div>
</body>
</html>"""


# ────────── 模板 4：经典朴素（匹配白宇轩简历 Word 版） ──────────
def _render_classic(data: ResumeData) -> str:
    """经典朴素模板：单栏 / 微软雅黑 / 灰色标题条 / 黑色正文。

    完全复刻用户提供的 PDF 简历版式：
    - 顶部姓名（大号粗体）+ 两列联系信息
    - 章节标题带浅灰背景条（#D8D9D8）
    - 教育/经历：左侧日期 + 右侧内容
    - 项目：粗体名称 + 右侧日期，角色标签，• 要点
    - 自我评价用 ⚫ 圆点
    - 纯黑白配色，A4 打印优化
    """
    b = data.basic
    name = b.name or "未命名"

    # ── 头部信息：两列布局 ──
    header_left = []   # 左列：求职意向 / 专业 / 电话
    header_right = []  # 右列：地址 / 邮箱 / GitHub

    if b.title:
        header_left.append(f"求职意向：{_h(b.title)}")
    if b.location:
        header_right.append(f"现居地址：{_h(b.location)}")
    # 从 summary 中提取专业（如果有）
    if data.education:
        edu0 = data.education[0]
        if edu0.major:
            header_left.append(f"专业：{_h(edu0.major)}")
    if b.phone:
        header_left.append(f"电话：{_h(b.phone)}")
    if b.email:
        header_right.append(f"邮箱：{_h(b.email)}")
    if b.github:
        header_right.append(f"GitHub：{_h(b.github)}")

    header_left_html = "".join(f"<div>{line}</div>" for line in header_left)
    header_right_html = "".join(f"<div>{line}</div>" for line in header_right)

    # ── 章节：自我评价 ──
    summary_html = ""
    if b.summary:
        # 按 ⚫ 圆点风格排版
        summary_lines = [s.strip() for s in b.summary.split("\n") if s.strip()]
        if len(summary_lines) <= 1:
            # 单段文本，按句号拆成要点
            import re as _re
            sentences = [s.strip() for s in _re.split(r"[。；！]", b.summary) if len(s.strip()) > 5]
            summary_lines = sentences if sentences else [b.summary]
        summary_items = "".join(
            f'<div class="bullet-row"><span class="dot">⚫</span><span class="bullet-text">{_h(line)}</span></div>'
            for line in summary_lines
        )
        summary_html = f"""
        <div class="section-bar">自我评价</div>
        <div class="section-body">
          {summary_items}
        </div>"""

    # ── 章节：教育背景 ──
    edu_html = ""
    if data.education:
        edu_rows = ""
        for edu in data.education:
            period = _h(edu.period)
            school_line = f"{_h(edu.school)}&emsp;&emsp;{_h(edu.degree)} {_h(edu.major)}"
            courses = ""
            if edu.highlights:
                courses = f'<div class="sub-line">主修课程：{"、".join(_h(h) for h in edu.highlights)}</div>'
            gpa_line = f'<div class="sub-line">GPA：{_h(edu.gpa)}</div>' if edu.gpa else ""
            edu_rows += f"""
            <div class="entry-row">
              <div class="entry-date">{period}</div>
              <div class="entry-content">
                <div class="entry-title">{school_line}</div>
                {courses}
                {gpa_line}
              </div>
            </div>"""
        edu_html = f"""
        <div class="section-bar">教育背景</div>
        <div class="section-body">
          {edu_rows}
        </div>"""

    # ── 章节：工作经历 / 学生工作经历 ──
    exp_html = ""
    if data.experience:
        exp_rows = ""
        for exp in data.experience:
            period = _h(exp.period)
            company_line = f"{_h(exp.company)}&emsp;&emsp;{_h(exp.position)}"
            points_html = ""
            if exp.points:
                points_html = "".join(
                    f'<div class="bullet-row"><span class="dot-sm">•</span><span class="bullet-text">{_h(p)}</span></div>'
                    for p in exp.points
                )
            exp_rows += f"""
            <div class="entry-row">
              <div class="entry-date">{period}</div>
              <div class="entry-content">
                <div class="entry-title">{company_line}</div>
                {points_html}
              </div>
            </div>"""
        # 判断用"工作经历"还是"学生工作经历"
        exp_title = "工作经历"
        if data.experience and any("学生" in e.company or "校" in e.company or "学术" in e.company for e in data.experience):
            exp_title = "学生工作经历"
        exp_html = f"""
        <div class="section-bar">{exp_title}</div>
        <div class="section-body">
          {exp_rows}
        </div>"""

    # ── 章节：项目经历 ──
    proj_html = ""
    if data.projects:
        proj_rows = ""
        for p in data.projects:
            proj_name = f"<strong>{_h(p.name)}</strong>"
            period = _h(p.period)
            # 角色标签
            role_tags = []
            if p.role:
                role_tags.append(_h(p.role))
            if p.tech_stack:
                role_tags.append("、".join(_h(t) for t in p.tech_stack))
            role_line = "&emsp;|&emsp;".join(role_tags) if role_tags else ""
            # 要点
            points_html = ""
            if p.points:
                points_html = "".join(
                    f'<div class="bullet-row"><span class="dot-sm">•</span><span class="bullet-text">{_h(pt)}</span></div>'
                    for pt in p.points
                )
            proj_rows += f"""
            <div class="proj-entry">
              <div class="proj-header">
                <span class="proj-name">{proj_name}</span>
                <span class="proj-date">{period}</span>
              </div>
              {f'<div class="proj-role">{role_line}</div>' if role_line else ''}
              {points_html}
            </div>"""
        proj_html = f"""
        <div class="section-bar">项目经历</div>
        <div class="section-body">
          {proj_rows}
        </div>"""

    # ── 章节：技能特长 ──
    skills_html = ""
    if data.skills:
        skill_rows = ""
        for sc in data.skills:
            items = "、".join(_h(item) for item in sc.items)
            skill_rows += f"""
            <div class="bullet-row"><span class="dot-sm">•</span><span class="bullet-text"><strong>{_h(sc.name)}：</strong>{items}</span></div>"""
        skills_html = f"""
        <div class="section-bar">技能特长</div>
        <div class="section-body">
          {skill_rows}
        </div>"""

    # ── 章节：荣誉奖项（如果有）──
    awards_html = ""
    if data.awards:
        award_rows = ""
        for a in data.awards:
            name = _h(a.name)
            issuer = f"&emsp;{_h(a.issuer)}" if a.issuer else ""
            date = _h(a.date)
            award_rows += f"""
            <div class="bullet-row"><span class="dot-sm">•</span><span class="bullet-text">{name}{issuer}</span><span class="award-date">{date}</span></div>"""
        awards_html = f"""
        <div class="section-bar">荣誉奖项</div>
        <div class="section-body">
          {award_rows}
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{name} - 个人简历</title>
<style>
  * {{
    margin: 0;
    padding: 0;
    box-sizing: border-box;
  }}
  body {{
    font-family: "Microsoft YaHei", "微软雅黑", "PingFang SC", "Hiragino Sans GB", sans-serif;
    font-size: 10pt;
    color: #000000;
    line-height: 1.7;
    background: #fff;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }}
  .resume {{
    width: 210mm;
    min-height: 297mm;
    margin: 0 auto;
    padding: 20mm 15mm 15mm 15mm;
    background: #fff;
  }}
  /* ── 头部 ── */
  .header {{
    margin-bottom: 8mm;
  }}
  .header-name {{
    font-size: 25pt;
    font-weight: bold;
    color: #000;
    margin-bottom: 6pt;
  }}
  .header-info {{
    display: flex;
    gap: 0;
    font-size: 10pt;
  }}
  .header-col {{
    flex: 1;
  }}
  .header-col > div {{
    margin-bottom: 2pt;
  }}
  /* ── 章节标题条 ── */
  .section-bar {{
    background-color: #D8D9D8;
    padding: 4pt 10pt;
    font-size: 12pt;
    font-weight: bold;
    color: #000;
    margin-top: 6mm;
    margin-bottom: 3mm;
    border-radius: 1pt;
  }}
  .section-body {{
    padding: 0 4pt;
  }}
  /* ── 日期 + 内容行（教育/工作经历）── */
  .entry-row {{
    display: flex;
    margin-bottom: 3mm;
  }}
  .entry-date {{
    width: 100pt;
    flex-shrink: 0;
    font-size: 10pt;
    color: #000;
  }}
  .entry-content {{
    flex: 1;
    font-size: 10pt;
  }}
  .entry-title {{
    font-size: 10pt;
    margin-bottom: 2pt;
  }}
  .sub-line {{
    font-size: 10pt;
    color: #333;
    margin-top: 1pt;
  }}
  /* ── 项目经历 ── */
  .proj-entry {{
    margin-bottom: 4mm;
  }}
  .proj-header {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 2pt;
  }}
  .proj-name {{
    font-size: 10pt;
    font-weight: bold;
  }}
  .proj-date {{
    font-size: 10pt;
    color: #000;
  }}
  .proj-role {{
    font-size: 10pt;
    color: #333;
    margin-bottom: 3pt;
  }}
  /* ── 要点列表 ── */
  .bullet-row {{
    display: flex;
    align-items: flex-start;
    margin-bottom: 2pt;
    line-height: 1.7;
  }}
  .dot {{
    color: #414141;
    font-size: 8pt;
    margin-right: 6pt;
    margin-top: 5pt;
    flex-shrink: 0;
  }}
  .dot-sm {{
    color: #000;
    font-size: 10pt;
    margin-right: 6pt;
    margin-top: 0;
    flex-shrink: 0;
  }}
  .bullet-text {{
    flex: 1;
    font-size: 10pt;
  }}
  .bullet-text strong {{
    font-weight: bold;
  }}
  .award-date {{
    margin-left: auto;
    font-size: 10pt;
    color: #333;
  }}
  /* ── 一页 A4 紧凑模式（由 fit 脚本按需启用）── */
  .resume.resume-compact {{
    padding: 12mm 12mm 8mm 12mm;
  }}
  .resume.resume-compact .header {{
    margin-bottom: 4mm;
  }}
  .resume.resume-compact .header-name {{
    font-size: 21pt;
    margin-bottom: 3pt;
  }}
  .resume.resume-compact .section-bar {{
    margin-top: 3mm;
    margin-bottom: 2mm;
    padding: 2.5pt 8pt;
    font-size: 11pt;
  }}
  .resume.resume-compact .entry-row {{
    margin-bottom: 2mm;
  }}
  .resume.resume-compact .proj-entry {{
    margin-bottom: 2.5mm;
  }}
  .resume.resume-compact .bullet-row {{
    margin-bottom: 1pt;
    line-height: 1.5;
  }}
  .resume.resume-compact .entry-title,
  .resume.resume-compact .proj-name,
  .resume.resume-compact .proj-role,
  .resume.resume-compact .bullet-text,
  .resume.resume-compact .entry-date,
  .resume.resume-compact .entry-content,
  .resume.resume-compact .sub-line,
  .resume.resume-compact .proj-date,
  .resume.resume-compact .award-date {{
    font-size: 9pt;
  }}
  /* ── 打印优化 ── */
  @media print {{
    body {{ background: #fff; }}
    .resume {{
      width: 210mm;
      min-height: auto;
      margin: 0;
      padding: 15mm 12mm;
      box-shadow: none;
    }}
    @page {{
      size: A4;
      margin: 0;
    }}
    .section-bar {{
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
  }}
</style>
</head>
<body>
<div class="resume">

  <!-- 头部 -->
  <div class="header">
    <div class="header-name">{_h(name)}</div>
    <div class="header-info">
      <div class="header-col">
        {header_left_html}
      </div>
      <div class="header-col">
        {header_right_html}
      </div>
    </div>
  </div>

  <!-- 自我评价 -->
  {summary_html}

  <!-- 教育背景 -->
  {edu_html}

  <!-- 工作/学生工作经历 -->
  {exp_html}

  <!-- 项目经历 -->
  {proj_html}

  <!-- 荣誉奖项 -->
  {awards_html}

  <!-- 技能特长 -->
  {skills_html}

</div>
{_ONE_PAGE_FIT_JS}
</body>
</html>"""


# ──────────────────────────────────────────────
# 4. 简历质量检查清单
# ──────────────────────────────────────────────

def run_resume_check(data: ResumeData, resume_text: str = "") -> list[ResumeCheckResult]:
    """运行简历检查清单，返回逐项结果。

    Args:
        data: 结构化简历数据
        resume_text: 可选，原始纯文本简历（用于统计长度 / 关键词等）

    Returns:
        ResumeCheckResult 列表
    """
    results: list[ResumeCheckResult] = []
    text = (resume_text or "").strip()

    # ── 基础信息 ──────────────────────────
    b = data.basic
    results.append(ResumeCheckResult(
        category="基础信息", item="姓名 + 手机号 + 邮箱三项必填",
        passed=bool(b.name and b.phone and b.email),
        suggestion="请补齐姓名、手机号、邮箱，这三项是招聘方联系你的基础。" if not (b.name and b.phone and b.email) else "",
    ))
    results.append(ResumeCheckResult(
        category="基础信息", item="期望岗位（title）明确标注",
        passed=bool(b.title),
        suggestion="建议在标题位置直接写明目标岗位名称，方便快速定位。" if not b.title else "",
    ))
    results.append(ResumeCheckResult(
        category="基础信息", item="邮箱格式专业（避免 xxx123 等非正式命名）",
        passed=bool(b.email and re.match(r"^[a-z][\w.+-]+@[\w-]+\.[\w.-]+$", b.email.lower())),
        suggestion="当前邮箱可能不够正式，建议使用「英文名/拼音缩写」格式的邮箱。"
        if b.email and not re.match(r"^[a-z][\w.+-]+@[\w-]+\.[\w.-]+$", b.email.lower()) else "",
    ))
    results.append(ResumeCheckResult(
        category="基础信息", item="无身份证号、婚姻状况、宗教等敏感信息",
        passed=not re.search(r"\b\d{17}[\dXx]\b|婚姻|民族|政治面貌|宗教|身高|体重|婚否", text + b.summary),
        suggestion="简历中建议避免敏感信息，减少不必要的偏见风险。"
        if re.search(r"\b\d{17}[\dXx]\b|婚姻|民族|政治面貌|宗教|身高|体重|婚否", text + b.summary) else "",
    ))

    # ── 内容质量 ──────────────────────────
    all_points = []
    for exp in data.experience:
        all_points.extend(exp.points)
    for p in data.projects:
        all_points.extend(p.points)

    total_exp_entries = len(data.experience)
    has_2to5_per_exp = all(2 <= len(e.points) <= 5 for e in data.experience) if total_exp_entries > 0 else True
    results.append(ResumeCheckResult(
        category="内容质量", item=f"共 {total_exp_entries} 段工作经历，每段 2-5 个要点",
        passed=has_2to5_per_exp and total_exp_entries > 0,
        suggestion="工作经历建议保留3-5段最相关的，每段写2-5个要点；过少信息不足，过多容易失焦。"
        if not has_2to5_per_exp or total_exp_entries == 0 else "",
    ))

    # 量化数据比例
    quantified = 0
    for p in all_points:
        if re.search(r"\d", p):
            quantified += 1
    ratio = quantified / len(all_points) if all_points else 0
    results.append(ResumeCheckResult(
        category="内容质量",
        item=f"要点中有量化数据（数字/百分比/金额）：{quantified}/{len(all_points)}（≥70% 为优）",
        passed=ratio >= 0.7,
        suggestion=f"当前量化比例仅 {ratio:.0%}，建议将成果改写为数字形式：提升/降低 X%，用户 X 万，节省 X 元，吞吐量 X QPS 等。"
        if ratio < 0.7 else "",
    ))

    # 动词开头 & 避免"参与""协助"
    weak_verbs = ["参与了", "协助", "配合", "帮助", "主要负责", "跟进了", "进行了"]
    strong_verbs = ["主导", "设计", "优化", "实现", "搭建", "推动", "制定", "构建", "落地",
                    "提升", "降低", "负责", "规划", "引入", "重构"]
    weak_count = sum(1 for p in all_points if any(v in p for v in weak_verbs))
    strong_count = sum(1 for p in all_points if any(v in p for v in strong_verbs))
    results.append(ResumeCheckResult(
        category="内容质量",
        item=f"要点动词开头：强动词 {strong_count} 条，弱动词（参与/协助）{weak_count} 条",
        passed=weak_count <= max(1, len(all_points) // 4),
        suggestion="建议将「参与/协助」类表述改写为「主导/设计/优化/推动」，突出自己的贡献而不是角色。"
        if weak_count > max(1, len(all_points) // 4) else "",
    ))

    # 个人摘要
    results.append(ResumeCheckResult(
        category="内容质量", item="包含个人摘要（2-3句，直接回应岗位核心要求）",
        passed=bool(b.summary and 40 <= len(b.summary) <= 400),
        suggestion="建议补充个人摘要，3句话讲清「年限+领域+最突出的2个成果+目标岗位」。"
        if not (b.summary and 40 <= len(b.summary) <= 400) else "",
    ))

    # ── 格式排版 ──────────────────────────
    results.append(ResumeCheckResult(
        category="格式排版", item="控制在1页以内（10年以下经验）",
        passed=len(all_points) <= 18 and len(data.experience) <= 4,
        suggestion="当前内容可能超过1页，建议优先压缩早期工作经历的要点，保留最相关的3段深度描述。"
        if len(all_points) > 18 or len(data.experience) > 4 else "",
    ))

    # 时间格式一致性
    periods = [e.period for e in data.experience if e.period] + \
              [e.period for e in data.education if e.period] + \
              [p.period for p in data.projects if p.period]
    patterns = set()
    for p in periods:
        if re.search(r"\d{4}\.\d{1,2}", p):
            patterns.add("YYYY.MM")
        elif re.search(r"\d{4}/\d{1,2}", p):
            patterns.add("YYYY/MM")
        elif re.search(r"\d{4}-\d{1,2}", p):
            patterns.add("YYYY-MM")
        elif re.search(r"\d{4}年\d{1,2}月", p):
            patterns.add("YYYY年MM月")
    results.append(ResumeCheckResult(
        category="格式排版",
        item=f"时间格式统一（检测到：{ '、'.join(sorted(patterns)) or '无' }）",
        passed=len(patterns) <= 1,
        suggestion="检测到多种时间格式混用，建议统一为「2023.03 - 至今」风格。" if len(patterns) > 1 else "",
    ))

    # ── ATS 友好 ──────────────────────────
    results.append(ResumeCheckResult(
        category="ATS友好", item="使用标准章节标题（工作经历/教育背景/技能...）",
        passed=bool(data.experience and data.education),
        suggestion="确保使用「工作经历」「教育背景」「核心技能」等常规标题，避免创意命名（如「我的故事」），方便机器解析。"
        if not (data.experience and data.education) else "",
    ))
    results.append(ResumeCheckResult(
        category="ATS友好", item="内容中包含 JD 关键词（优化流程已内嵌匹配）",
        passed=len(data.skills) >= 1 and sum(len(s.items) for s in data.skills) >= 5,
        suggestion="建议从目标 JD 提取 10+ 个关键技能与术语，按频次融入技能/经历中（简历优化流程已自动执行此步）。"
        if sum(len(s.items) for s in data.skills) < 5 else "",
    ))

    logger.info(
        "简历检查完成：%d 项，通过 %d 项",
        len(results), sum(1 for r in results if r.passed),
    )
    return results


def format_check_report(results: list[ResumeCheckResult]) -> str:
    """将检查清单结果格式化为可读的 Markdown 报告。"""
    if not results:
        return "（无检查结果）"
    categories: dict[str, list[ResumeCheckResult]] = {}
    for r in results:
        categories.setdefault(r.category, []).append(r)
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    lines = ["# 简历质量检查报告", "", f"**综合评分：{passed}/{total} 项通过**", ""]
    for cat, items in categories.items():
        cat_pass = sum(1 for r in items if r.passed)
        lines.append(f"## {cat}（{cat_pass}/{len(items)}）")
        lines.append("")
        for r in items:
            icon = "✅" if r.passed else "⚠️"
            lines.append(f"- {icon} {r.item}")
            if not r.passed and r.suggestion:
                lines.append(f"  - 💡 改进建议：{r.suggestion}")
        lines.append("")
    return "\n".join(lines)


# ──────────────────────────────────────────────
# 5. 一键输出文件（HTML + YAML）
# ──────────────────────────────────────────────

def write_resume_outputs(
    data: ResumeData,
    output_dir: str | Path,
    base_name: str = "resume",
    template: str = DEFAULT_TEMPLATE,
) -> dict[str, str]:
    """一键写出生成的简历文件。

    Args:
        data: 结构化简历数据
        output_dir: 输出目录（不存在会自动创建）
        base_name: 文件名前缀（不含扩展名）
        template: 模板风格

    Returns:
        dict，包含 html_path 和 yaml_path 的绝对路径
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    html_path = out / f"{base_name}_{template}.html"
    yaml_path = out / f"{base_name}_data.yaml"

    html_str = render_resume_html(data, template=template)
    html_path.write_text(html_str, encoding="utf-8")
    yaml_path.write_text(resume_to_yaml(data), encoding="utf-8")

    logger.info("简历文件已输出：HTML=%s，YAML=%s", html_path, yaml_path)
    return {"html_path": str(html_path), "yaml_path": str(yaml_path)}
