"""
graph 模块适配层（LangChain 版）。

背景：langchain_version/web_app.py 与 langgraph 版共用同一套 Web 接口，
其中 /api/optimize 以 `from graph import run_optimize` 懒加载流水线入口，
但本目录没有 LangGraph 实现（graph.py 缺失曾导致该接口 ModuleNotFoundError）。

此适配层将调用转发到本目录的 LCEL 管道 chain.run_optimize，
保持 Web 层接口与 langgraph 版一致（返回字段对齐）。

如需切换为真正的 LangGraph 图，可整体替换此文件为 langgraph_version/graph.py。
"""

from __future__ import annotations

from typing import Any


def run_optimize(
    resume_text: str,
    jd_text: str,
    target_company: str = "",
    photo_base64: str = "",
) -> dict[str, Any]:
    """转发到 chain.run_optimize（LCEL 管道）。

    Args:
        resume_text: 简历纯文本
        jd_text: 岗位描述全文
        target_company: 目标公司名称
        photo_base64: 可选，用户上传的照片（data URI / 纯 base64）

    Returns:
        dict，包含 optimized_text / jd_analysis / company_research /
        matching_table / interview_questions / interview_advice /
        resume_docx_path / resume_html_path / resume_yaml_path /
        resume_check_report / advice_docx_path / error 等字段
        （与 langgraph 版 graph.run_optimize 对齐）。
    """
    from chain import run_optimize as _lc_run_optimize

    return _lc_run_optimize(
        resume_text, jd_text, target_company=target_company, photo_base64=photo_base64
    )


__all__ = ["run_optimize"]
