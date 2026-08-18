"""
命令行入口 — 定制化简历大师（LangChain 版）

用法：
    python main.py web                      启动 Web 服务（uvicorn）
    python main.py chat                     启动 CLI 对话
    python main.py optimize --resume PATH --jd PATH --company 公司名
    python main.py optimize --resume PATH --job-id ID --company 公司名

说明：
- web 的 host / port 取自 config.WEB_CONFIG，可用 --host / --port 覆盖
- optimize 输出：定制化简历 + 面试建议 Word 文档（需提供目标公司名称）
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
    p_chat = sub.add_parser("chat", help="启动 CLI 对话")
    p_chat.add_argument(
        "--session", default="", help="会话 ID（缺省用固定 cli，实现多轮记忆）"
    )

    # doctor
    sub.add_parser("doctor", help="检查运行依赖、LLM 配置与岗位数据")

    # optimize
    p_opt = sub.add_parser("optimize", help="定制化简历优化，输出双 Word 文档")
    p_opt.add_argument("--resume", required=True, help="简历文件路径（.pdf/.docx/.txt）")
    src = p_opt.add_mutually_exclusive_group(required=True)
    src.add_argument("--jd", help="岗位描述文本文件路径")
    src.add_argument("--job-id", help="知识库中的岗位 id")
    p_opt.add_argument("--company", required=True, help="目标公司名称（必填）")
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


def run_chat(session_id: str = "") -> int:
    """启动 CLI 对话（复用 Agent 会话记忆）。"""
    import agent

    print("=" * 56)
    print("简历优化 Agent 命令行对话（输入 exit / quit / 退出 结束）")
    print("=" * 56)
    session_id = session_id or "cli"
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


def run_doctor() -> int:
    """检查运行依赖、LLM 配置与岗位数据（与 langgraph 版对齐）。"""
    from validate_runtime import collect_diagnostics

    report = collect_diagnostics()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready"] else 1


def _read_resume_text(resume_path: str) -> str:
    """按扩展名读取简历文本（.pdf/.docx/.txt，统一走 resume_reader.read_resume_text）。"""
    from resume_reader import read_resume_text

    return read_resume_text(resume_path).strip()


def run_optimize(
    resume_path: str,
    jd_path: str | None,
    job_id: str | None,
    company: str,
    out_dir: str | None,
) -> int:
    """执行定制化简历优化：拆解岗位 → 公司分析 → 优化 → 面试建议 → 双 Word 文档。"""
    import content_optimizer
    import jd_analyzer
    import jd_knowledge_base

    # 1. 读取简历
    resume_text = _read_resume_text(resume_path)
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

    # 3. 拆解岗位（含分级/类型/隐含目标/风险项）
    logger.info("开始岗位拆解...")
    jd_analysis = jd_analyzer.analyze_jd(jd_text, resume_text=resume_text)

    # 4. 公司分析与求职判断
    from company_researcher import research_company

    logger.info("开始公司分析：%s", company)
    company_research = research_company(company, jd_analysis, resume_text)

    # 5. 定制化简历优化 + 四级匹配表
    logger.info("开始简历内容优化...")
    optimized = content_optimizer.optimize_resume_content(resume_text, jd_analysis)
    logger.info("构建匹配关系表...")
    matching_table = content_optimizer.build_matching_table(resume_text, jd_analysis)

    # 6. 面试问题 + 面试建议
    from interview_advisor import build_interview_advice, generate_interview_questions

    questions = generate_interview_questions(
        jd_analysis.get("role_type", "tech"), jd_analysis, resume_text
    )
    advice = build_interview_advice(company, jd_analysis, resume_text, company_research, questions)

    # 7. 输出双 Word 文档
    import re

    from resume_writer import write_customized_resume, write_interview_advice_docx

    def _clean(name: str) -> str:
        return re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "未知"

    out_dir_path = Path(out_dir or cfg.PATH_CONFIG["output_dir"])
    out_dir_path.mkdir(parents=True, exist_ok=True)
    company_tag = _clean(company)
    role_tag = _clean(jd_analysis.get("role_position", "") or "目标岗位")

    out_docx = out_dir_path / f"定制化简历_{company_tag}_{role_tag}.docx"
    out_advice = out_dir_path / f"面试建议_{company_tag}_{role_tag}.docx"
    out_table = out_dir_path / "matching_table.json"

    write_customized_resume(optimized, str(out_docx))
    write_interview_advice_docx(advice, str(out_advice), questions=questions)
    out_table.write_text(
        json.dumps(matching_table, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("✅ 定制化简历完成：")
    print(f"   定制化简历: {out_docx}")
    print(f"   面试建议  : {out_advice}")
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
        return run_chat(args.session)
    if args.command == "doctor":
        return run_doctor()
    if args.command == "optimize":
        return run_optimize(args.resume, args.jd, args.job_id, args.company, args.out)
    return 1


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    sys.exit(main())
