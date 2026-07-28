"""
PDF 解析模块

职责：
1. 将 PDF 简历转换为 Word 文件（保留格式）
2. 从 Word 中提取段落文本和表格文本
3. 记录每个段落的样式信息（字体、字号、加粗等）

依赖：pdf2docx, python-docx
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def pdf_to_docx(pdf_path: str, docx_path: str) -> None:
    """PDF 转 Word，保留原始排版。

    Args:
        pdf_path: 输入 PDF 文件路径
        docx_path: 输出 Word 文件路径

    Raises:
        FileNotFoundError: PDF 文件不存在
        ValueError: PDF 为空或无法解析（如扫描件、加密件）
    """
    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")

    # TODO: 使用 pdf2docx 的 Converter 进行转换
    # from pdf2docx import Converter
    # cv = Converter(pdf_path)
    # cv.convert(docx_path)
    # cv.close()
    raise NotImplementedError("pdf_to_docx 待实现")


def read_resume(docx_path: str) -> dict[str, Any]:
    """读取 Word 简历内容。

    Args:
        docx_path: Word 文件路径

    Returns:
        {
            "paragraphs": [
                {"index": int, "text": str, "style": str, "font": {...}},
                ...
            ],
            "tables": [[["cell1", "cell2"], ...], ...],
            "full_text": str  # 纯文本拼接
        }

    Raises:
        FileNotFoundError: Word 文件不存在
    """
    docx_file = Path(docx_path)
    if not docx_file.exists():
        raise FileNotFoundError(f"Word 文件不存在: {docx_path}")

    # TODO: 使用 python-docx 读取段落和表格
    # 1. 遍历 document.paragraphs，记录 index/text/style/font
    # 2. 遍历 document.tables，按行/列读取单元格
    # 3. 拼接 full_text
    raise NotImplementedError("read_resume 待实现")


def _extract_font_info(run) -> dict[str, Any]:
    """从 python-docx 的 run 对象提取字体信息。

    Returns:
        {"name": str, "size": float, "bold": bool, "italic": bool}
    """
    # TODO: 提取 run.font 的 name/size/bold/italic 属性
    raise NotImplementedError("_extract_font_info 待实现")


if __name__ == "__main__":
    # 简单自测
    import sys

    if len(sys.argv) > 1:
        result = read_resume(sys.argv[1])
        print(result["full_text"][:500])
