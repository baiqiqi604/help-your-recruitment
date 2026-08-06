"""
命令行入口

用法：
    python main.py web                      启动 Web 服务（uvicorn）
    python main.py chat                     启动 CLI 对话
    python main.py optimize --resume PATH --jd PATH [--out DIR]
    python main.py optimize --resume PATH --job-id ID [--out DIR]

说明：
- web 的 host / port 取自 config.WEB_CONFIG，可用 --host / --port 覆盖
- optimize 输出：optimized.docx / optimized.pdf / matching_table.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import config as cfg

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 命令行解析
# ──────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="简历优化 Agent（LangChain 版）命令行入口"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # web
    p_web = sub.add_parser("web", help="启动 Web 服务（uvicorn）")
    p_web.add_argument("--host", default=cfg.WEB_CONFIG["host"], help="监听地址")
    p_web.add_argument("--port", type=int, default=cfg.WEB_CONFIG["port"], help="监听端口")

    # chat
    sub.add_parser("chat", help="启动 CLI 对话")

    # optimize
    p_opt = sub.add_parser("optimize", help="优化简历并输出 docx/pdf/匹配表")
    p_opt.add_argument("--resume", required=True, help="简历文件路径（.pdf/.docx/.txt）")
    src = p_opt.add_mutually_exclusive_group(required=True)
    src.add_argument("--jd", help="岗位描述文本文件路径")
    src.add_argument("--job-id", help="知识库中的岗位 id")
    p_opt.add_argument("--out", help="输出目录（默认 config.PATH_CONFIG['output_dir']）")

    return parser


# ──────────────────────────────────────────────
# 子命令实现
# ──────────────────────────────────────────────
def run_web(host: str, port: int) -> int:
    """启动 FastAPI Web 服务。"""
    import uvicorn

    logger.info("启动 Web 服务: http://%s:%d", host, port)
    uvicorn.run("web_app:app", host=host, port=port, reload=False)
    return 0


def run_chat() -> int:
    """启动 CLI 对话（复用 Agent 会话记忆）。"""
    import agent

    print("=" * 56)
    print("简历优化 Agent 命令行对话（输入 exit / quit / 退出 结束）")
    print("=" * 56)
    session_id = "cli"
    while True:
        try:
            user_input = input("\n你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break
        if user_input.lower() in ("exit", "quit", "退出"):
            print("再见！")
            break
        if not user_input:
            continue
        try:
            reply = agent.chat_with_agent(user_input, session_id)
        except Exception as e:  # noqa: BLE001
            logger.exception("对话出错")
            reply = f"出错：{e}"
        print(f"\nAgent: {reply}")
    return 0


def run_optimize(
    resume_path: str,
    jd_path: str | None,
    job_id: str | None,
    out_dir: str | None,
) -> int:
    """执行完整简历优化流程并输出结果文件。"""
    import content_optimizer
    import jd_analyzer
    import jd_knowledge_base
    import resume_reader
    import resume_writer

    # 1. 读取简历
    resume_text = resume_reader.read_resume(resume_path).strip()
    if not resume_text:
        logger.error("简历内容为空: %s", resume_path)
        return 1
    logger.info("已读取简历：%s（%d 字）", resume_path, len(resume_text))

    # 2. 获取 JD 文本
    if jd_path:
        try:
            jd_text = Path(jd_path).read_text(encoding="utf-8").strip()
        except OSError as e:
            logger.error("读取 JD 文件失败: %s", e)
            return 1
    elif job_id:
        job = jd_knowledge_base.get_job_by_id(job_id)
        if not job:
            logger.error("未找到岗位 id=%s", job_id)
            return 1
        jd_text = (job.get("jd_text") or "").strip()
    else:  # 理论上不可达（argparse 已约束）
        logger.error("请提供 --jd 或 --job-id")
        return 1

    if not jd_text:
        logger.error("JD 内容为空")
        return 1
    logger.info("已获取 JD 文本：%d 字", len(jd_text))

    # 3. 分析与优化
    logger.info("开始岗位分析...")
    jd_analysis = jd_analyzer.analyze_jd(jd_text)
    logger.info("开始简历内容优化...")
    optimized = content_optimizer.optimize_resume_content(resume_text, jd_analysis)
    logger.info("构建匹配关系表...")
    matching_table = content_optimizer.build_matching_table(resume_text, jd_analysis)

    # 4. 输出文件
    out_dir_path = Path(out_dir or cfg.PATH_CONFIG["output_dir"])
    out_dir_path.mkdir(parents=True, exist_ok=True)
    stem = Path(resume_path).stem
    out_docx = out_dir_path / f"{stem}_optimized.docx"
    out_pdf = out_dir_path / f"{stem}_optimized.pdf"
    out_table = out_dir_path / f"{stem}_matching_table.json"

    resume_writer.write_optimized_resume(optimized, out_docx)
    resume_writer.docx_to_pdf(out_docx, out_pdf)
    out_table.write_text(
        json.dumps(matching_table, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("✅ 简历优化完成：")
    print(f"   DOCX     : {out_docx}")
    print(f"   PDF      : {out_pdf}")
    print(f"   匹配关系表: {out_table}")
    return 0


# ──────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────
def main() -> int:
    args = build_parser().parse_args()

    if args.command == "web":
        return run_web(args.host, args.port)
    if args.command == "chat":
        return run_chat()
    if args.command == "optimize":
        return run_optimize(args.resume, args.jd, args.job_id, args.out)
    return 1


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    sys.exit(main())
