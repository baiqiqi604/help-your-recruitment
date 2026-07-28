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

    # TODO: 实现写回逻辑
    # 1. 用 python-docx 打开原始 Word
    # 2. 将 optimized_text 按行拆分
    # 3. 遍历段落，保留首 run 格式，替换文本
    # 4. 处理表格内单元格
    # 5. 保存到 output_docx
    raise NotImplementedError("write_optimized_resume 待实现")


def _replace_paragraph_text(paragraph, new_text: str) -> None:
    """替换段落文本，保留首个 run 的格式。"""
    # TODO: 清空除首 run 外的所有 run，将新文本写入首 run
    raise NotImplementedError("_replace_paragraph_text 待实现")


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

    # TODO: 使用 docx2pdf 转换
    # from docx2pdf import convert
    # convert(docx_path, pdf_path)
    raise NotImplementedError("docx_to_pdf 待实现")


if __name__ == "__main__":
    print("resume_writer 模块自测：需要传入实际文件路径")
