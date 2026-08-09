"""
简历优化 Agent（LangGraph 版）— 主程序入口

用法：
    python main.py web                      启动 FastAPI Web 服务（uvicorn）
    python main.py chat                     命令行多轮对话（带 session 记忆）
    python main.py optimize --resume PATH --jd PATH
    python main.py optimize --resume PATH --job-id ID

说明：
    --resume 支持 .pdf / .docx / .txt（PDF 自动转 Word 提取文本）
    --jd 为 JD 文本文件路径；--job-id 为岗位知识库中的岗位 ID（二选一）
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from config import PATH_CONFIG, WEB_CONFIG

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    """统一日志格式。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _load_resume_text(resume_path: str) -> str:
    """按文件类型读取简历文本：.pdf/.docx/.txt。"""
    path = Path(resume_path)
    if not path.exists():
        raise FileNotFoundError(f"简历文件不存在: {resume_path}")

    suffix = path.suffix.lower()

    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="replace")

    # PDF / DOCX 统一走 resume_reader（pdf 先转 docx）
    from resume_reader import pdf_to_docx, read_resume

    temp_docx = path
    if suffix == ".pdf":
        temp_docx = Path(tempfile.gettempdir()) / f"{path.stem}_graph_temp.docx"
        pdf_to_docx(str(path), str(temp_docx))

    try:
        data = read_resume(str(temp_docx))
    finally:
        if suffix == ".pdf" and temp_docx.exists():
            temp_docx.unlink(missing_ok=True)

    return data["full_text"]


def _load_jd_text(jd_path: str, job_id: str) -> str:
    """读取 JD 文本：--jd 文件路径 或 --job-id 知识库岗位。"""
    if jd_path:
        jd_file = Path(jd_path)
        if not jd_file.exists():
            raise FileNotFoundError(f"JD 文件不存在: {jd_path}")
        return jd_file.read_text(encoding="utf-8", errors="replace")

    if job_id:
        from jd_knowledge_base import get_job_by_id

        job = get_job_by_id(job_id)
        if not job or not job.get("jd_text"):
            raise ValueError(f"知识库中未找到岗位: {job_id}")
        return job["jd_text"]

    raise ValueError("请提供 --jd PATH 或 --job-id ID（至少其一）")


# ──────────────────────────────────────────────
# 子命令实现
# ──────────────────────────────────────────────
def cmd_web(_args: argparse.Namespace) -> None:
    """启动 Web 服务。"""
    import uvicorn

    logger.info("启动 Web 服务: http://%s:%d", WEB_CONFIG["host"], WEB_CONFIG["port"])
    uvicorn.run(
        "web_app:app",
        host=WEB_CONFIG["host"],
        port=WEB_CONFIG["port"],
        reload=False,
    )


def cmd_chat(args: argparse.Namespace) -> None:
    """命令行多轮对话（带 session 记忆）。"""
    from agent import chat_with_agent

    session_id = args.session or f"cli-{uuid.uuid4().hex[:12]}"
    print("=" * 60)
    print("简历优化 Agent（LangGraph 版）— 命令行对话")
    print(f"会话 ID: {session_id}  （退出请输入 exit / quit）")
    print("=" * 60)

    while True:
        try:
            user_input = input("\n你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit", "退出"}:
            print("再见！")
            break

        try:
            reply = chat_with_agent(user_input, session_id)
        except Exception as e:  # noqa: BLE001
            logger.exception("对话失败")
            reply = f"（出错了: {e}）"

        print(f"Agent: {reply}")


def cmd_optimize(args: argparse.Namespace) -> None:
    """命令行一次性简历定制优化（依据《定制化简历大师》Skill）。"""
    from graph import run_optimize

    print("读取简历中...")
    resume_text = _load_resume_text(args.resume)
    print(f"  简历文本 {len(resume_text)} 字")

    print("读取岗位描述中...")
    jd_text = _load_jd_text(args.jd, args.job_id)
    print(f"  JD 文本 {len(jd_text)} 字")

    target_company = (args.company or "").strip()
    if not target_company:
        print("❌ 请提供 --company 目标公司名称")
        sys.exit(1)

    print("执行 LangGraph 定制流水线（拆解岗位 → 公司分析 → 优化 → 审核 → 面试建议）...")
    result = run_optimize(resume_text, jd_text, target_company=target_company)

    if result.get("error"):
        print(f"❌ 定制失败: {result['error']}")
        sys.exit(1)

    optimized = result.get("optimized_text", "")
    matching_table = result.get("matching_table", [])
    interview_questions = result.get("interview_questions", [])
    resume_docx = result.get("resume_docx_path", "")
    advice_docx = result.get("advice_docx_path", "")

    print("\n" + "=" * 60)
    print("✅ 定制完成")
    print("=" * 60)
    print(optimized)

    if matching_table:
        print("\n【简历-JD 匹配关系表】")
        for row in matching_table:
            if isinstance(row, dict):
                print(
                    f"- {row.get('jd_requirement', '')} "
                    f"[{row.get('match_strength', '')}] "
                    f"→ {row.get('resume_position', '')}"
                )

    if interview_questions:
        print("\n【面试问题清单】")
        for q in interview_questions:
            if isinstance(q, dict):
                print(f"- [{q.get('stage', '')}] {q.get('question', '')}")

    if resume_docx:
        print(f"\n📄 定制化简历（Word）: {resume_docx}")
    if advice_docx:
        print(f"🎯 面试建议（Word）: {advice_docx}")

    # 存档优化结果（纯文本兜底）
    out_dir = Path(PATH_CONFIG["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"optimized_{ts}.txt"
    out_path.write_text(optimized, encoding="utf-8")
    print(f"\n已保存: {out_path}")


def cmd_doctor(_args: argparse.Namespace) -> None:
    """Check dependencies, LLM configuration, and persisted crawl data."""
    from validate_runtime import collect_diagnostics

    report = collect_diagnostics()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ready"]:
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="简历优化 Agent（LangGraph 版）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # web
    subparsers.add_parser("web", help="启动 Web 服务（uvicorn）")

    # chat
    chat_parser = subparsers.add_parser("chat", help="命令行多轮对话")
    chat_parser.add_argument(
        "--session", type=str, default="", help="会话 ID（缺省自动生成，实现多轮记忆）"
    )

    subparsers.add_parser("doctor", help="检查运行依赖、LLM 配置与岗位数据")

    # optimize
    opt_parser = subparsers.add_parser("optimize", help="一次性简历定制优化")
    opt_parser.add_argument("--resume", type=str, required=True, help="简历文件路径（.pdf/.docx/.txt）")
    opt_parser.add_argument("--jd", type=str, default="", help="JD 文本文件路径")
    opt_parser.add_argument("--job-id", type=str, default="", help="岗位知识库中的岗位 ID（与 --jd 二选一）")
    opt_parser.add_argument("--company", type=str, default="", help="目标公司名称（必填，用于公司分析/求职判断/面试建议）")

    return parser


def main() -> None:
    """入口分发。"""
    _setup_logging()
    parser = build_parser()
    args = parser.parse_args()

    handlers = {
        "web": cmd_web,
        "chat": cmd_chat,
        "optimize": cmd_optimize,
        "doctor": cmd_doctor,
    }
    try:
        handlers[args.command](args)
    except KeyboardInterrupt:
        print("\n已退出。")
    except Exception as e:  # noqa: BLE001
        logger.exception("命令执行失败")
        print(f"❌ {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
