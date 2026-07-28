"""
简历优化 Agent — 主程序入口

完整流程：
    PDF 简历 → pdf2docx → 简历文本
    岗位选择 → 从知识库检索 / 手动输入 → 岗位分析
                    ↓
              大模型优化简历内容
                    ↓
              写回 Word + 导出 PDF

使用示例：
    from main import optimize_resume

    result = optimize_resume(
        pdf_path="./input/我的简历.pdf",
        jd_source={"type": "manual", "text": "岗位：Python 后端..."},
    )
    print(result["message"])
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from config import PATH_CONFIG

logger = logging.getLogger(__name__)


def optimize_resume(
    pdf_path: str,
    jd_source: dict[str, Any],
    output_dir: str | None = None,
) -> dict[str, Any]:
    """完整流程：PDF → 解析 → 分析 JD → 优化 → 输出。

    Args:
        pdf_path: 原始简历 PDF 路径
        jd_source: 岗位来源，两种形式：
            - {"type": "manual", "text": "JD文本"}        # 手动输入
            - {"type": "kb", "job_id": "xxx"}             # 从知识库选择
        output_dir: 输出目录，默认 ./output

    Returns:
        {
            "success": True/False,
            "output_docx": "路径",
            "output_pdf": "路径",
            "message": "处理结果说明"
        }
    """
    if output_dir is None:
        output_dir = PATH_CONFIG["output_dir"]
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    try:
        # ── Step 1: PDF 转 Word ──
        from resume_reader import pdf_to_docx, read_resume

        pdf_name = Path(pdf_path).stem
        temp_docx = str(Path(tempfile.gettempdir()) / f"{pdf_name}_temp.docx")
        pdf_to_docx(pdf_path, temp_docx)
        logger.info("Step 1 完成：PDF 已转为 Word")

        # ── Step 2: 读取简历内容 ──
        resume_data = read_resume(temp_docx)
        resume_text = resume_data["full_text"]
        logger.info("Step 2 完成：读取到 %d 个段落", len(resume_data["paragraphs"]))

        # ── Step 3: 获取并分析岗位需求 ──
        from jd_analyzer import analyze_jd

        jd_text = _resolve_jd_text(jd_source)
        jd_analysis = analyze_jd(jd_text)
        logger.info("Step 3 完成：岗位分析成功")

        # ── Step 4: 大模型优化简历内容 ──
        from content_optimizer import optimize_resume_content

        optimized_text = optimize_resume_content(resume_text, jd_analysis)
        logger.info("Step 4 完成：简历内容已优化")

        # ── Step 5: 写回 Word（保留格式）──
        from resume_writer import write_optimized_resume, docx_to_pdf

        output_docx = str(Path(output_dir) / f"{pdf_name}_优化版.docx")
        write_optimized_resume(temp_docx, optimized_text, output_docx)
        logger.info("Step 5 完成：已输出 Word")

        # ── Step 6: 导出 PDF（可选）──
        output_pdf = str(Path(output_dir) / f"{pdf_name}_优化版.pdf")
        try:
            docx_to_pdf(output_docx, output_pdf)
            logger.info("Step 6 完成：已导出 PDF")
        except Exception as e:  # noqa: BLE001
            output_pdf = ""
            logger.warning("PDF 导出失败（可选功能）: %s", e)

        # ── 清理临时文件 ──
        _cleanup_temp(temp_docx)

        return {
            "success": True,
            "output_docx": output_docx,
            "output_pdf": output_pdf,
            "message": f"优化完成！输出文件：{output_docx}",
        }

    except Exception as e:  # noqa: BLE001
        logger.exception("简历优化流程失败")
        return {
            "success": False,
            "output_docx": "",
            "output_pdf": "",
            "message": f"处理失败：{e}",
        }


def _resolve_jd_text(jd_source: dict[str, Any]) -> str:
    """根据岗位来源解析出 JD 文本。

    支持：
    - manual: 直接使用 text 字段
    - kb: 从知识库按 job_id 检索
    """
    source_type = jd_source.get("type")

    if source_type == "manual":
        text = jd_source.get("text", "")
        if not text.strip():
            raise ValueError("手动输入的 JD 文本不能为空")
        return text

    if source_type == "kb":
        # 从知识库按 job_id 检索岗位全文
        from jd_knowledge_base import get_job_by_id

        job_id = jd_source.get("job_id", "")
        if not job_id:
            raise ValueError("知识库岗位来源缺少 job_id")
        job = get_job_by_id(job_id)
        if not job or not job.get("jd_text"):
            raise ValueError(f"知识库中未找到岗位: {job_id}")
        return job["jd_text"]

    raise ValueError(f"未知的岗位来源类型: {source_type}")


def _cleanup_temp(temp_path: str) -> None:
    """清理临时文件。"""
    try:
        p = Path(temp_path)
        if p.exists():
            p.unlink()
    except Exception as e:  # noqa: BLE001
        logger.warning("清理临时文件失败: %s", e)


def main() -> None:
    """命令行交互入口。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print("=" * 50)
    print("简历优化 Agent")
    print("=" * 50)

    # 1. 输入简历 PDF 路径
    pdf_path = input("请输入简历 PDF 路径（默认从 input/ 目录选择）：").strip()
    if not pdf_path:
        pdf_path = _pick_resume_from_input()
        if not pdf_path:
            print("未找到简历文件，退出。")
            return

    if not Path(pdf_path).exists():
        print(f"文件不存在: {pdf_path}")
        return

    # 2. 选择岗位来源
    jd_source = _choose_jd_source()
    if jd_source is None:
        print("未选择岗位，退出。")
        return

    # 3. 执行优化
    print("\n开始优化简历...")
    result = optimize_resume(pdf_path=pdf_path, jd_source=jd_source)

    # 4. 展示结果
    print("\n" + "=" * 50)
    if result["success"]:
        print("✅ " + result["message"])
        print(f"   Word: {result['output_docx']}")
        if result["output_pdf"]:
            print(f"   PDF : {result['output_pdf']}")
    else:
        print("❌ " + result["message"])
    print("=" * 50)


def _pick_resume_from_input() -> str:
    """从 input/ 目录列出 PDF 文件供用户选择。"""
    input_dir = Path(PATH_CONFIG["input_dir"])
    if not input_dir.exists():
        return ""

    pdfs = sorted(input_dir.glob("*.pdf"))
    if not pdfs:
        print(f"input/ 目录下没有 PDF 文件: {input_dir}")
        return ""

    print("\n检测到以下简历：")
    for i, pdf in enumerate(pdfs, 1):
        print(f"  {i}. {pdf.name}")

    choice = input("请选择序号（或直接输入路径）：").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(pdfs):
        return str(pdfs[int(choice) - 1])
    return choice


def _choose_jd_source() -> dict[str, Any] | None:
    """选择岗位来源：知识库检索 或 手动粘贴。"""
    print("\n岗位来源：")
    print("  1. 从岗位知识库检索")
    print("  2. 手动粘贴 JD 文本")
    choice = input("请选择（1/2，默认 2）：").strip() or "2"

    if choice == "1":
        return _jd_from_knowledge_base()

    # 手动粘贴
    print("\n请粘贴岗位描述 JD（输入单独一行 END 结束）：")
    lines: list[str] = []
    while True:
        line = input()
        if line.strip() == "END":
            break
        lines.append(line)
    text = "\n".join(lines).strip()
    if not text:
        return None
    return {"type": "manual", "text": text}


def _jd_from_knowledge_base() -> dict[str, Any] | None:
    """从知识库检索岗位并选择。"""
    try:
        from jd_knowledge_base import search_jds, get_premium_jobs
    except Exception as e:  # noqa: BLE001
        print(f"知识库不可用: {e}")
        return None

    print("\n大厂/高频岗位推荐：")
    try:
        premium = get_premium_jobs(limit=10)
    except Exception as e:  # noqa: BLE001
        logger.warning("获取推荐岗位失败: %s", e)
        premium = []

    candidates: list[dict[str, Any]] = []
    if premium:
        for i, job in enumerate(premium, 1):
            print(f"  {i}. [{job.get('company', '')}] {job.get('title', '')}"
                  f" - {job.get('city', '')}")
        candidates = premium

    query = input("\n输入关键词检索（或直接输入上方序号）：").strip()
    if not query:
        return None

    if query.isdigit() and candidates and 1 <= int(query) <= len(candidates):
        chosen = candidates[int(query) - 1]
        return {"type": "manual", "text": chosen.get("jd_text", "")}

    # 关键词检索
    try:
        results = search_jds(query, top_k=10)
    except Exception as e:  # noqa: BLE001
        print(f"检索失败: {e}")
        return None

    if not results:
        print("未检索到匹配岗位，请改用手动粘贴。")
        return None

    print("\n检索结果：")
    for i, job in enumerate(results, 1):
        print(f"  {i}. [{job.get('company', '')}] {job.get('title', '')}"
              f" - {job.get('city', '')}")

    choice = input("选择序号：").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(results):
        chosen = results[int(choice) - 1]
        return {"type": "manual", "text": chosen.get("jd_text", "")}

    return None


if __name__ == "__main__":
    main()
