"""
简历读取模块

职责：
1. 将 PDF 简历转为 docx（pdf2docx）
2. 读取 .pdf / .docx / .txt 格式简历为纯文本

依赖：pdf2docx、python-docx
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def pdf_to_docx(pdf_path: str | Path, docx_path: str | Path) -> str:
    """将 PDF 文件转换为 docx 文件。

    Args:
        pdf_path: 源 PDF 路径
        docx_path: 输出 docx 路径

    Returns:
        输出 docx 的绝对路径

    Raises:
        ValueError: 源文件不存在或不是 PDF
    """
    from pdf2docx import Converter

    pdf = Path(pdf_path)
    out = Path(docx_path)
    if not pdf.exists():
        raise ValueError(f"PDF 文件不存在: {pdf}")

    out.parent.mkdir(parents=True, exist_ok=True)
    logger.info("转换 PDF → DOCX: %s", pdf)
    cv = Converter(str(pdf))
    cv.convert(str(out))
    cv.close()
    logger.info("PDF 转换完成: %s", out)
    return str(out)


def _iter_block_items(doc):
    """按文档顺序迭代段落（Paragraph）与表格（Table）。"""
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    body = doc.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


def _read_docx(path: Path) -> str:
    """读取 docx：段落 + 表格（按文档原始顺序）。"""
    from docx import Document

    doc = Document(str(path))
    parts: list[str] = []

    for block in _iter_block_items(doc):
        if block.__class__.__name__ == "Paragraph":
            text = block.text.strip()
            if text:
                parts.append(text)
        else:  # Table
            for row in block.rows:
                cells = [cell.text.strip() for cell in row.cells]
                line = " | ".join(c for c in cells if c)
                if line:
                    parts.append(line)

    text = "\n".join(parts).strip()
    if not text:
        logger.warning("docx 内容为空: %s", path)
    return text


def _read_txt(path: Path) -> str:
    """读取文本文件，自动尝试 UTF-8 / GBK / GB18030 编码。"""
    for encoding in ("utf-8", "gbk", "gb18030"):
        try:
            return path.read_text(encoding=encoding).strip()
        except (UnicodeDecodeError, LookupError):
            continue
    logger.warning("文本编码识别失败，按 utf-8 忽略错误读取: %s", path)
    return path.read_text(encoding="utf-8", errors="ignore").strip()


def read_resume(path: str | Path) -> str:
    """读取简历文件为纯文本。

    支持格式：
    - .pdf  ：经 pdf2docx 转为 docx 后读取（临时文件自动清理）
    - .docx ：python-docx 读取段落 + 表格
    - .txt  ：直接读取（自动识别常见中文编码）

    Args:
        path: 简历文件路径

    Returns:
        简历纯文本

    Raises:
        ValueError: 文件不存在或格式不支持
    """
    file = Path(path)
    if not file.exists():
        raise ValueError(f"文件不存在: {file}")

    suffix = file.suffix.lower()
    if suffix == ".pdf":
        temp_docx = file.with_name(file.stem + "_temp.docx")
        try:
            pdf_to_docx(file, temp_docx)
            return _read_docx(temp_docx)
        finally:
            if temp_docx.exists():
                temp_docx.unlink(missing_ok=True)
    elif suffix == ".docx":
        return _read_docx(file)
    elif suffix == ".txt":
        return _read_txt(file)
    else:
        raise ValueError(
            f"不支持的简历格式: {suffix}，仅支持 .pdf / .docx / .txt"
        )


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2:
        print("用法: python resume_reader.py <简历文件路径>")
        sys.exit(1)
    print(read_resume(sys.argv[1]))
