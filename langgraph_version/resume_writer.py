"""
格式保留与输出模块

职责：
1. 将优化后的文本写回 Word 文件（保留原格式）
2. 可选：将 Word 导出为 PDF

替换策略：按行顺序替换 + 保留首 run 格式（最稳妥方案）

依赖：python-docx, docx2pdf
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def write_optimized_resume(
    original_docx: str, optimized_text: str, output_docx: str
) -> None:
    """把优化后的内容写回 Word，保留原有格式。

    策略：
    - 按段落顺序逐行替换文本
    - 保留每个段落首个 run 的字体格式
    - 行数不一致时：原简历行数多则截断，优化文本多则追加

    Args:
        original_docx: 原始 Word 文件路径（提供格式模板）
        optimized_text: 优化后的简历全文
        output_docx: 输出 Word 文件路径

    Raises:
        FileNotFoundError: 原始 Word 文件不存在
    """
    if not Path(original_docx).exists():
        raise FileNotFoundError(f"原始 Word 文件不存在: {original_docx}")

    try:
        from docx import Document
    except ImportError as e:
        raise ImportError("缺少依赖 python-docx，请执行: pip install python-docx") from e

    # 确保输出目录存在
    Path(output_docx).parent.mkdir(parents=True, exist_ok=True)

    document = Document(original_docx)

    # 将优化后文本按行拆分（过滤纯空行但保留顺序）
    new_lines = [line.rstrip() for line in optimized_text.splitlines()]
    # 去掉首尾空行
    while new_lines and not new_lines[0].strip():
        new_lines.pop(0)
    while new_lines and not new_lines[-1].strip():
        new_lines.pop()

    paragraphs = document.paragraphs
    logger.info(
        "写回简历：原段落 %d 个，优化后行数 %d",
        len(paragraphs),
        len(new_lines),
    )

    # 按行顺序替换：保留首 run 格式
    for i, para in enumerate(paragraphs):
        if i < len(new_lines):
            _replace_paragraph_text(para, new_lines[i])
        else:
            # 原简历段落多于优化文本：清空多余段落
            _replace_paragraph_text(para, "")

    # 优化文本行数多于原段落：在末尾追加新段落
    if len(new_lines) > len(paragraphs):
        for extra_line in new_lines[len(paragraphs):]:
            document.add_paragraph(extra_line)

    document.save(output_docx)
    logger.info("优化后简历已保存: %s", output_docx)


def _replace_paragraph_text(paragraph, new_text: str) -> None:
    """替换段落文本，保留首个 run 的格式。

    策略：将新文本写入首个 run，清空其余 run 的内容。
    这样能保留首 run 的字体/字号/加粗等格式属性。
    """
    runs = paragraph.runs

    # 段落没有任何 run：直接新增一个
    if not runs:
        if new_text:
            paragraph.add_run(new_text)
        return

    # 首 run 写入新文本
    runs[0].text = new_text
    # 清空其余 run（保留 run 对象但置空文本，避免破坏 XML 结构）
    for run in runs[1:]:
        run.text = ""


def docx_to_pdf(docx_path: str, pdf_path: str) -> None:
    """Word 转 PDF（可选功能）。

    注意：docx2pdf 在 Windows 上依赖 Microsoft Word，
    在 macOS 上依赖 Microsoft Word，Linux 不支持。

    Args:
        docx_path: 输入 Word 文件路径
        pdf_path: 输出 PDF 文件路径
    """
    if not Path(docx_path).exists():
        raise FileNotFoundError(f"Word 文件不存在: {docx_path}")

    # 确保输出目录存在
    Path(pdf_path).parent.mkdir(parents=True, exist_ok=True)

    try:
        from docx2pdf import convert
    except ImportError as e:
        raise ImportError(
            "缺少依赖 docx2pdf，请执行: pip install docx2pdf"
            "（需本地安装 Microsoft Word）"
        ) from e

    logger.info("开始转换 Word -> PDF: %s", docx_path)
    convert(docx_path, pdf_path)

    if not Path(pdf_path).exists():
        raise ValueError("PDF 导出失败，请确认本地已安装 Microsoft Word")
    logger.info("PDF 导出完成: %s", pdf_path)


if __name__ == "__main__":
    print("resume_writer 模块自测：需要传入实际文件路径")
