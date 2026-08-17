"""
Resume Formatter 模块单元测试（《resume-formatter》Skill）。

覆盖：
- 三套 HTML 模板渲染（modern/professional/tech）
- 纯文本 → 结构化数据的规则兜底解析
- 简历质量检查清单
- YAML 序列化 / 反序列化往返
- write_resume_outputs 写文件

注意：不走 LLM 结构化路径，完全离线可跑（匹配 MOCK_LLM 测试环境）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Type

from resume_formatter import (
    TEMPLATE_CLASSIC,
    TEMPLATE_MODERN,
    TEMPLATE_PROFESSIONAL,
    TEMPLATE_TECH,
    _heuristic_parse,
    fit_resume_to_one_page,
    format_check_report,
    render_resume_html,
    resume_from_yaml,
    resume_to_yaml,
    run_resume_check,
    write_resume_outputs,
)
from schemas import (
    BasicInfo,
    EducationEntry,
    ExperienceEntry,
    ProjectEntry,
    ResumeData,
    SkillCategory,
)


def _assert_raises(exc_type: Type[BaseException], fn, *args: Any, **kwargs: Any) -> None:
    """等价于 pytest.raises，但不依赖 pytest（离线也可跑）。"""
    try:
        fn(*args, **kwargs)
    except exc_type:
        return
    except Exception as e:  # noqa: BLE001
        raise AssertionError(
            f"期望抛出 {exc_type.__name__}，实际抛出 {type(e).__name__}: {e}"
        ) from e
    raise AssertionError(f"期望抛出 {exc_type.__name__}，但函数正常返回")


# ── 测试数据：一份完整的结构化 ResumeData ──────────────────────────
SAMPLE_DATA = ResumeData(
    basic=BasicInfo(
        name="李小明",
        title="AI产品经理",
        location="北京",
        email="lixiaoming@example.com",
        phone="138-1234-5678",
        github="github.com/lixiaoming",
        linkedin="linkedin.com/in/lixiaoming",
        summary="5年AI产品经验，主导过3个大模型应用从0到1落地，精通RAG、Prompt工程、AIGC产品设计，DAU最高达500万，擅长跨团队协调推动复杂项目。",
    ),
    education=[
        EducationEntry(
            school="清华大学",
            degree="硕士",
            major="计算机科学与技术",
            period="2018.09 - 2021.06",
            gpa="3.8/4.0",
            highlights=["国家奖学金", "主修：机器学习、NLP、产品设计"],
        ),
        EducationEntry(
            school="北京大学",
            degree="本科",
            major="软件工程",
            period="2014.09 - 2018.06",
        ),
    ],
    experience=[
        ExperienceEntry(
            company="字节跳动",
            position="AI产品经理（高级）",
            period="2023.03 - 至今",
            location="北京",
            points=[
                "主导豆包大模型垂直行业产品从0到1搭建，上线3个月DAU突破500万，用户次日留存提升30%",
                "设计RAG检索增强方案，引入多路召回+精排架构，答案准确率从72%提升至91%，幻觉率下降45%",
                "跨团队协调算法/工程/设计/运营5个团队，推动3个核心大版本按期上线，里程碑达成率100%",
            ],
        ),
        ExperienceEntry(
            company="阿里巴巴",
            position="产品经理",
            period="2021.07 - 2023.02",
            location="杭州",
            points=[
                "负责阿里通义千问电商助手模块，订单转化率提升18%，月GMV增加2.3亿元",
                "搭建产品数据看板与A/B测试体系，累计完成42次A/B实验，决策效率提升2倍",
            ],
        ),
    ],
    projects=[
        ProjectEntry(
            name="智能简历优化Agent",
            role="产品负责人 & 开发者",
            period="2024.06 - 2024.08",
            tech_stack=["LangChain", "RAG", "FastAPI", "Vue", "ChromaDB"],
            link="github.com/example/resume-agent",
            points=[
                "基于LLM多Agent协作架构的简历内容优化系统，支持JD匹配度评分，GitHub 2k+ Stars",
                "设计LangGraph工作流，拆解岗位→公司分析→优化→审核→面试建议5个核心Agent",
            ],
        ),
    ],
    skills=[
        SkillCategory(name="产品技能", items=["需求分析", "PRD撰写", "用户研究", "A/B测试", "数据分析", "项目管理"]),
        SkillCategory(name="AI能力", items=["RAG架构", "Prompt Engineering", "大模型评估", "微调策略", "Agent设计"]),
        SkillCategory(name="技术能力", items=["Python", "SQL", "LangChain", "ChromaDB", "FastAPI"]),
    ],
)


# ─────────── 1. HTML 模板渲染 ──────────────────────────────────────
class TestTemplates:
    def _assert_html_skeleton(self, html: str, name: str) -> None:
        assert "<!DOCTYPE html>" in html
        assert f"<title>{name}" in html
        assert "</html>" in html
        # A4 打印优化必须存在
        assert "@media print" in html
        assert "size: A4" in html

    def test_modern_render(self) -> None:
        html = render_resume_html(SAMPLE_DATA, TEMPLATE_MODERN)
        self._assert_html_skeleton(html, "李小明")
        # 现代简约特征：双栏 + 蓝紫渐变
        assert "linear-gradient" in html
        assert "sidebar" in html
        assert "main-content" in html
        # 数据必须出现
        assert "字节跳动" in html
        assert "AI产品经理" in html
        assert "智能简历优化Agent" in html
        assert "lixiaoming@example.com" in html

    def test_professional_render(self) -> None:
        html = render_resume_html(SAMPLE_DATA, TEMPLATE_PROFESSIONAL)
        self._assert_html_skeleton(html, "李小明")
        # 商务正式特征：宋体类字体 + letter-spacing
        assert "SimSun" in html or "Songti" in html
        assert "letter-spacing" in html
        # 章节标题带汉字间隔
        assert "自 我 评 价" in html or "工 作 经 历" in html

    def test_tech_render(self) -> None:
        html = render_resume_html(SAMPLE_DATA, TEMPLATE_TECH)
        self._assert_html_skeleton(html, "李小明")
        # 技术导向特征：代码风关键字
        assert "const " in html
        assert "JetBrains Mono" in html or "Consolas" in html
        # 技术芯片 / 代码标记
        assert "tech-chip" in html
        assert "skill-chip" in html

    def test_classic_render(self) -> None:
        html = render_resume_html(SAMPLE_DATA, TEMPLATE_CLASSIC)
        self._assert_html_skeleton(html, "李小明")
        # 经典朴素特征：灰色标题条 + 微软雅黑 + 单栏
        assert "D8D9D8" in html  # 灰色背景色
        assert "Microsoft YaHei" in html  # 微软雅黑字体
        assert "section-bar" in html  # 章节标题条
        assert "entry-date" in html  # 日期+内容行布局
        assert "proj-name" in html  # 项目名称
        assert "bullet-row" in html  # 要点列表
        # 数据必须出现
        assert "字节跳动" in html
        assert "AI产品经理" in html
        assert "智能简历优化Agent" in html

    def test_invalid_template_rejected(self) -> None:
        _assert_raises(ValueError, render_resume_html, SAMPLE_DATA, "not_a_template")

    def test_empty_data_safe(self) -> None:
        """空 ResumeData 不应崩溃。"""
        html = render_resume_html(ResumeData(), TEMPLATE_CLASSIC)
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html


# ─────────── 2. 规则兜底解析 ──────────────────────────────────────
class TestHeuristicParse:
    SAMPLE_TEXT = """姓名：李小明
求职目标：高级后端开发工程师
手机：139-9876-5432
邮箱：lixiaoming_dev@163.com
github.com/lixm-dev

个人摘要
7年后端开发经验，精通Java/Go、分布式架构、MySQL调优，主导过3个高并发系统，熟悉Kafka、Redis、ES。

工作经历
字节跳动 | 高级后端工程师 | 2022.05 - 至今
负责订单核心系统重构，QPS从5000提升到20000，P99延迟下降60%
推动微服务治理升级，全年可用性达99.99%，故障数减少75%

阿里巴巴 | 后端工程师 | 2019.08 - 2022.04
负责商品搜索服务，引入ES向量召回，搜索点击率提升22%
搭建数据同步链路，日处理增量数据10亿条

教育背景
清华大学 | 硕士 | 计算机科学与技术 | 2017.09 - 2019.06

核心技能
Java, Go, MySQL, Redis, Kafka, ElasticSearch, Spring, gRPC, Docker
"""

    def test_basic_info_extracted(self) -> None:
        data = _heuristic_parse(self.SAMPLE_TEXT)
        assert data.basic.name == "李小明"
        assert "139-9876-5432" in data.basic.phone
        assert data.basic.email == "lixiaoming_dev@163.com"
        assert "github.com/lixm-dev" in data.basic.github
        assert len(data.basic.summary) > 20  # 摘要被提取
        assert "后端" in data.basic.summary

    def test_experience_section(self) -> None:
        data = _heuristic_parse(self.SAMPLE_TEXT)
        assert len(data.experience) == 2
        assert data.experience[0].company == "字节跳动"
        assert data.experience[0].position == "高级后端工程师"
        assert "2022.05" in data.experience[0].period
        # 要点被切分
        assert len(data.experience[0].points) >= 1
        # 有量化内容
        assert any("QPS" in p or "可用性" in p for p in data.experience[0].points)

    def test_education_section(self) -> None:
        data = _heuristic_parse(self.SAMPLE_TEXT)
        assert len(data.education) == 1
        assert data.education[0].school == "清华大学"
        assert "硕士" in data.education[0].degree
        assert "计算机" in data.education[0].major
        assert "2017.09" in data.education[0].period

    def test_skills_extracted(self) -> None:
        data = _heuristic_parse(self.SAMPLE_TEXT)
        assert len(data.skills) >= 1
        flat = [s for sc in data.skills for s in sc.items]
        assert "Java" in flat or "Go" in flat or "MySQL" in flat

    def test_minimal_empty_text(self) -> None:
        """空白输入不应崩溃。"""
        data = _heuristic_parse("")
        assert isinstance(data, ResumeData)
        assert data.basic.name == ""


# ─────────── 3. 简历检查清单 ──────────────────────────────────────
class TestResumeCheck:
    def test_sample_data_checks(self) -> None:
        results = run_resume_check(SAMPLE_DATA)
        # 4 大类 * 若干项
        categories = {r.category for r in results}
        assert "基础信息" in categories
        assert "内容质量" in categories
        assert "格式排版" in categories
        assert "ATS友好" in categories
        # 总条数合理
        assert 10 <= len(results) <= 20
        # 基础信息：示例数据邮箱/姓名/电话都齐全 → 通过
        basic_name_phone_email = [
            r for r in results if "姓名 + 手机号 + 邮箱" in r.item
        ]
        assert basic_name_phone_email and basic_name_phone_email[0].passed is True
        # 量化数据比例（示例数据要点几乎全含数字 → 通过）
        quant = [r for r in results if "量化数据" in r.item]
        assert quant and quant[0].passed is True
        # 报告可读
        report = format_check_report(results)
        assert "综合评分" in report
        assert "简历质量检查报告" in report
        assert "# 基础信息" in report or "## 基础信息" in report

    def test_bad_resume_fails_checks(self) -> None:
        bad = ResumeData(basic=BasicInfo(name="", phone="", email=""))
        results = run_resume_check(bad)
        basic_required = [r for r in results if "姓名 + 手机号 + 邮箱" in r.item]
        assert basic_required and basic_required[0].passed is False
        # 有改进建议
        assert any(r.suggestion for r in results if not r.passed)


# ─────────── 3.5 一页 A4 内容裁剪（fit_resume_to_one_page）────────────
class TestFitToOnePage:
    """fit_resume_to_one_page 的边界行为：学生/真实工作识别、条目上限、裁剪规则。"""

    def _make_data(self) -> ResumeData:
        return ResumeData(
            basic=BasicInfo(name="张三", title="后端工程师", summary="S" * 300),
            experience=[
                ExperienceEntry(company="字节跳动", position="后端", points=["a1", "a2", "a3", "a4"]),
                ExperienceEntry(company="腾讯", position="后端", points=["b1", "b2", "b3"]),
                ExperienceEntry(company="美团", position="后端", points=["c1"]),
                # 学生工作经历（公司名含「校」，应被识别并优先裁掉）
                ExperienceEntry(company="XX大学校团委", position="干事", points=["s1", "s2", "s3", "s4", "s5"]),
            ],
            projects=[
                ProjectEntry(name="项目A", role="开发", points=["p1", "p2", "p3"]),
                ProjectEntry(name="项目B", role="开发", points=["q1", "q2"]),
                ProjectEntry(name="项目C", role="开发", points=["r1"]),
            ],
            skills=[SkillCategory(name=f"技能{i}", items=["x"]) for i in range(6)],
        )

    def test_student_work_dropped_when_real_work_sufficient(self) -> None:
        fit = fit_resume_to_one_page(self._make_data())
        companies = [e.company for e in fit.experience]
        assert "XX大学校团委" not in companies  # 真实工作足够（3 段）→ 学生工作整体裁掉
        assert len(fit.experience) == 3

    def test_student_work_kept_when_real_work_insufficient(self) -> None:
        data = self._make_data()
        # 只剩 2 段真实工作 + 1 段学生工作（真实工作不足 max_entries=3）
        data.experience = data.experience[:2] + data.experience[3:]
        fit = fit_resume_to_one_page(data)
        assert len(fit.experience) == 3
        assert fit.experience[-1].company == "XX大学校团委"  # 补足到 max_entries=3
        # 学生工作每段要点上限收紧到 2 条
        assert len(fit.experience[-1].points) <= 2

    def test_experience_points_capped(self) -> None:
        fit = fit_resume_to_one_page(self._make_data())
        for exp in fit.experience:
            assert len(exp.points) <= 3

    def test_projects_capped_at_two(self) -> None:
        fit = fit_resume_to_one_page(self._make_data())
        assert len(fit.projects) == 2
        for proj in fit.projects:
            assert len(proj.points) <= 3

    def test_skills_capped_at_four(self) -> None:
        fit = fit_resume_to_one_page(self._make_data())
        assert len(fit.skills) <= 4

    def test_summary_trimmed_to_limit(self) -> None:
        fit = fit_resume_to_one_page(self._make_data())
        # 无句读长摘要按 160 字截断，尾部追加省略号 → 160 字主干 + 1 个"…"
        assert len(fit.basic.summary) <= 161
        assert fit.basic.summary.endswith("…")

    def test_long_point_truncated_with_ellipsis(self) -> None:
        data = self._make_data()
        long_point = "长" * 100
        data.experience[0].points = [long_point]
        fit = fit_resume_to_one_page(data)
        kept = fit.experience[0].points[0]
        assert kept.endswith("…")
        assert len(kept) <= 81  # 80 字主干 + 省略号

    def test_original_data_unchanged(self) -> None:
        data = self._make_data()
        original_summary = data.basic.summary
        original_projects = len(data.projects)
        fit_resume_to_one_page(data)
        assert data.basic.summary == original_summary
        assert len(data.projects) == original_projects  # model_copy(deep=True) 不修改原对象


# ─────────── 4. YAML 序列化往返 ──────────────────────────────────────
class TestYamlRoundTrip:
    def test_to_and_from_yaml(self) -> None:
        yaml_text = resume_to_yaml(SAMPLE_DATA)
        # 至少有关键字段
        assert "李小明" in yaml_text
        assert "字节跳动" in yaml_text
        # 反序列化
        restored = resume_from_yaml(yaml_text)
        assert restored.basic.name == "李小明"
        assert restored.basic.email == SAMPLE_DATA.basic.email
        assert len(restored.experience) == len(SAMPLE_DATA.experience)
        assert restored.experience[0].company == "字节跳动"
        assert len(restored.skills) == len(SAMPLE_DATA.skills)
        assert restored.projects[0].link == SAMPLE_DATA.projects[0].link


# ─────────── 5. 写文件集成 ──────────────────────────────────────
class TestWriteFiles:
    def test_write_resume_outputs(self, tmp_path: Path) -> None:
        result = write_resume_outputs(
            SAMPLE_DATA,
            output_dir=tmp_path,
            base_name="lixm_resume",
            template=TEMPLATE_MODERN,
        )
        html_path = Path(result["html_path"])
        yaml_path = Path(result["yaml_path"])
        assert html_path.exists()
        assert yaml_path.exists()
        # HTML 必须可被浏览器解析（至少有标签闭合）
        content = html_path.read_text(encoding="utf-8")
        assert content.count("<!DOCTYPE html>") == 1
        assert content.rstrip().endswith("</html>")
        # YAML 里有姓名
        assert "李小明" in yaml_path.read_text(encoding="utf-8")
        # 文件名匹配
        assert "lixm_resume_modern.html" in html_path.name
        assert "lixm_resume_data.yaml" in yaml_path.name

    def test_all_templates_write(self, tmp_path: Path) -> None:
        for tpl in (TEMPLATE_MODERN, TEMPLATE_PROFESSIONAL, TEMPLATE_TECH):
            out = write_resume_outputs(SAMPLE_DATA, output_dir=tmp_path / tpl, base_name="r", template=tpl)
            assert Path(out["html_path"]).stat().st_size > 1000  # 至少 1KB，不为空


# ─────────── 6. resume_writer 入口（HTML 生成函数） ──────────────────
class TestWriteCustomizedResumeHtml:
    def test_end_to_end_from_text(self, tmp_path: Path) -> None:
        """从规则解析的示例纯文本直接产出 HTML/YAML/检查报告。"""
        from resume_writer import write_customized_resume_html

        resume_text = TestHeuristicParse.SAMPLE_TEXT
        html_path = tmp_path / "out.html"
        yaml_path = tmp_path / "out_data.yaml"

        result = write_customized_resume_html(
            resume_text, output_html=str(html_path), output_yaml=str(yaml_path),
            template=TEMPLATE_MODERN,
        )

        assert Path(result["html_path"]).exists()
        assert Path(result["yaml_path"]).exists()
        assert "check_report" in result
        report = result["check_report"]
        # 检查报告至少包含基础信息 + 内容质量两个一级标题
        assert "基础信息" in report
        assert "内容质量" in report
        # 不能为空白
        assert len(html_path.read_text(encoding="utf-8")) > 2000

    def test_empty_text_raises(self, tmp_path: Path) -> None:
        from resume_writer import write_customized_resume_html

        _assert_raises(
            ValueError,
            write_customized_resume_html,
            "   ",
            None,
            str(tmp_path / "x.html"),
        )


# 如果直接运行此文件，也可以通过简单的 print 自测
if __name__ == "__main__":
    import tempfile

    print("✓ Resume Formatter 模块自检开始")
    # 1. 三套模板
    for t in (TEMPLATE_MODERN, TEMPLATE_PROFESSIONAL, TEMPLATE_TECH):
        size = len(render_resume_html(SAMPLE_DATA, template=t))
        print(f"  模板 {t}: {size} bytes")
    # 2. 检查清单
    r = run_resume_check(SAMPLE_DATA)
    passed = sum(1 for x in r if x.passed)
    print(f"  检查清单：{passed}/{len(r)} 通过")
    # 3. 写文件
    with tempfile.TemporaryDirectory() as d:
        out = write_resume_outputs(SAMPLE_DATA, d, base_name="demo")
        print(f"  文件输出：{Path(out['html_path']).name}，{Path(out['yaml_path']).name}")
    print("✓ Resume Formatter 模块自检通过")
