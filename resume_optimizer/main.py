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
        # TODO: 从知识库按 job_id 检索岗位全文
        # from jd_knowledge_base import get_job_by_id
        # job = get_job_by_id(jd_source["job_id"])
        # return job["jd_text"]
        raise NotImplementedError("知识库岗位检索待实现")

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
    """命令行入口（Phase 4 完善交互流程）。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # TODO: Phase 4 实现命令行交互
    # 1. 提示用户输入简历 PDF 路径
    # 2. 选择岗位来源（知识库浏览 / 手动粘贴）
    # 3. 调用 optimize_resume
    # 4. 展示结果
    print("=" * 50)
    print("简历优化 Agent")
    print("=" * 50)
    print("命令行交互流程待 Phase 4 实现。")
    print("当前可通过 optimize_resume() 函数直接调用。")


if __name__ == "__main__":
    main()
