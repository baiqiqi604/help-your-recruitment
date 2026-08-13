"""
最小闭环测试脚本

分两阶段验证：
- Stage A（无需 API Key）：PDF 解析 → 读取简历 → 写回 Word（用模拟优化文本）
- Stage B（LLM 链路）：岗位分析 → 简历优化。设 MOCK_LLM=1 时走模拟响应（无需 API Key），
  否则需要 DeepSeek API Key

用法：
    py test_pipeline.py                    # 只跑 Stage A
    py test_pipeline.py --with-llm         # 同时跑 Stage B（未配 Key 时需 MOCK_LLM=1）
    set MOCK_LLM=1 && py test_pipeline.py  # 全量走 MOCK 链路（CI 可用）
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# 确保能导入项目模块
sys.path.insert(0, str(Path(__file__).resolve().parent))


SAMPLE_RESUME_LINES = [
    "张三",
    "电话：138-0000-0000  邮箱：zhangsan@example.com",
    "求职目标：Python 后端开发工程师",
    "个人摘要：3 年 Python 开发经验，熟悉 Web 后端开发。",
    "核心技能：Python, Flask, MySQL, Git",
    "工作经历：",
    "某某科技公司 后端开发工程师 2022.07 - 至今",
    "负责公司内部管理系统后端开发，使用 Flask + MySQL。",
    "项目经历：",
    "在线商城系统：参与订单模块开发，完成支付接口对接。",
    "教育背景：",
    "某某大学 计算机科学与技术 本科 2018.09 - 2022.06",
]


def create_test_pdf(pdf_path: str) -> None:
    """用 PyMuPDF 生成一份简单的测试简历 PDF。"""
    import fitz  # PyMuPDF

    doc = fitz.open()
    page = doc.new_page()
    # 注册中文字体（使用内置 CJK 字体）
    fontname = "china-s"
    y = 60
    for line in SAMPLE_RESUME_LINES:
        page.insert_text(
            (60, y),
            line,
            fontname=fontname,
            fontsize=12,
        )
        y += 24
    doc.save(pdf_path)
    doc.close()
    print(f"[准备] 已生成测试简历 PDF: {pdf_path}")


def stage_a_document_pipeline() -> str:
    """Stage A：验证 PDF 解析 → 读取 → 写回（无需 API Key）。"""
    print("\n" + "=" * 60)
    print("Stage A：文档处理链路（无需 API Key）")
    print("=" * 60)

    from resume_reader import pdf_to_docx, read_resume
    from resume_writer import write_optimized_resume

    work_dir = Path(tempfile.mkdtemp(prefix="resume_test_"))
    pdf_path = str(work_dir / "测试简历.pdf")
    docx_path = str(work_dir / "测试简历.docx")
    output_docx = str(work_dir / "测试简历_优化版.docx")

    # 1. 生成测试 PDF
    create_test_pdf(pdf_path)

    # 2. PDF → Word
    pdf_to_docx(pdf_path, docx_path)
    assert Path(docx_path).exists(), "PDF 转 Word 失败"
    print("[A1] PDF → Word 转换成功")

    # 3. 读取简历内容
    data = read_resume(docx_path)
    assert data["full_text"].strip(), "简历全文为空"
    print(f"[A2] 读取简历成功：{len(data['paragraphs'])} 段落，全文 {len(data['full_text'])} 字")
    print("     全文预览：")
    for line in data["full_text"].splitlines()[:5]:
        print(f"       | {line}")

    # 4. 写回 Word（用模拟优化文本，验证格式保留链路）
    mock_optimized = "\n".join(
        [
            "张三",
            "电话：138-0000-0000  邮箱：zhangsan@example.com",
            "求职目标：Python 后端开发工程师",
            "个人摘要：3 年 Python 后端开发经验，专注高并发 Web 服务。",
            "核心技能：Python, Flask, MySQL, Redis, Git",
            "工作经历：",
            "某某科技公司 后端开发工程师 2022.07 - 至今",
            "主导内部管理系统后端架构，基于 Flask + MySQL 支撑日均万级请求。",
            "项目经历：",
            "在线商城系统：负责订单模块，完成支付接口对接，提升下单成功率。",
            "教育背景：",
            "某某大学 计算机科学与技术 本科 2018.09 - 2022.06",
        ]
    )
    write_optimized_resume(docx_path, mock_optimized, output_docx)
    assert Path(output_docx).exists(), "写回 Word 失败"
    print(f"[A3] 写回 Word 成功（格式保留）: {output_docx}")

    # 验证写回内容
    rewritten = read_resume(output_docx)
    assert "Redis" in rewritten["full_text"], "写回内容校验失败"
    print("[A4] 写回内容校验通过（检测到优化后的 Redis 技能）")

    print("\n[PASS] Stage A 通过：文档处理链路正常")
    return output_docx


def stage_b_llm_pipeline() -> None:
    """Stage B：验证 LLM 链路（岗位分析 + 简历优化，需 API Key 或 MOCK_LLM=1）。"""
    print("\n" + "=" * 60)
    print("Stage B：LLM 链路（需要 DeepSeek API Key，或 MOCK_LLM=1 走模拟响应）")
    print("=" * 60)

    from jd_analyzer import analyze_jd
    from content_optimizer import optimize_resume_content

    sample_jd = """岗位：Python 后端开发工程师
职责：负责核心业务系统后端设计与开发；参与系统性能优化。
要求：3 年以上 Python 开发经验；精通 Django/Flask；
熟悉 MySQL、Redis；了解微服务架构；有 Docker 使用经验优先。"""

    # 1. 岗位分析
    print("[B1] 调用 DeepSeek 分析岗位...")
    analysis = analyze_jd(sample_jd)
    print(f"     核心技能：{analysis['required_skills']}")
    print(f"     加分技能：{analysis['preferred_skills']}")
    print(f"     经验要求：{analysis['experience_years']}")

    # 2. 简历优化
    resume_text = "\n".join(SAMPLE_RESUME_LINES)
    print("[B2] 调用 DeepSeek 优化简历...")
    optimized = optimize_resume_content(resume_text, analysis)
    print("     优化后简历预览：")
    for line in optimized.splitlines()[:8]:
        print(f"       | {line}")

    print("\n[PASS] Stage B 通过：LLM 链路正常")


def main() -> None:
    with_llm = "--with-llm" in sys.argv

    # Stage A 始终运行
    stage_a_document_pipeline()

    # Stage B：--with-llm 显式开启，或 MOCK_LLM=1 时自动开启（走模拟响应，无需 Key）
    import os

    mock_mode = os.getenv("MOCK_LLM", "").strip().lower() in ("1", "true", "yes")
    if with_llm or mock_mode:
        try:
            stage_b_llm_pipeline()
        except ValueError as e:
            print(f"\n[SKIP] Stage B 跳过：{e}")
    else:
        print("\n提示：加 --with-llm 参数可测试 LLM 链路（需配置 DeepSeek API Key，"
              "或设 MOCK_LLM=1 走模拟响应）")


if __name__ == "__main__":
    main()
