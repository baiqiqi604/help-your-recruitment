"""
Web 服务模块（FastAPI）— 定制化简历大师（LangChain 版）

接口一览：
- GET  /                  返回前端页面 templates/index.html
- POST /api/chat          智能对话（RAG 优先答疑，多轮记忆 session_id）
- POST /api/optimize      定制化简历优化（简历 + JD + 目标公司 → 双 Word 文档）
- POST /api/upload        上传简历文件（.pdf/.docx/.txt）解析为文本
- GET  /api/download      下载生成的 Word 文档
- GET  /api/exp/search    面试题库语义检索（top_k=0 全量 + 阈值过滤）
- GET  /api/exp/company   按公司获取面试题
- GET  /api/exp/algorithm 笔试算法题
- POST /api/exp/upload    手动面经入库
- GET  /api/exp/count     题库题目总数
- GET  /api/jobs/search   岗位检索（已降级）
- GET  /api/jobs/premium  优质岗位（已降级）
- GET  /api/health        健康检查

依赖：fastapi、uvicorn
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import agent
import content_optimizer
import jd_analyzer
from config import PATH_CONFIG

logger = logging.getLogger(__name__)

app = FastAPI(
    title="简历优化 Agent（LangChain 版）— 定制化简历大师",
    version="1.0.0",
)


# ──────────────────────────────────────────────
# 请求 / 响应模型
# ──────────────────────────────────────────────
class ChatRequest(BaseModel):
    """智能对话请求。"""

    messages: list[dict[str, Any]] = Field(
        default_factory=list, description="消息列表（取最后一条用户消息作为输入）"
    )
    session_id: str = Field(default="default", description="会话标识，共享记忆")


class OptimizeRequest(BaseModel):
    """定制化简历优化请求。jd_text 与 job_id 至少提供其一。"""

    resume_text: str = Field(default="", description="简历纯文本")
    jd_text: str = Field(default="", description="岗位描述全文")
    job_id: str = Field(default="", description="知识库岗位 ID（与 jd_text 二选一）")
    target_company: str = Field(default="", description="目标公司名称（必填）")


class ExpUploadRequest(BaseModel):
    """手动粘贴面经入库请求。"""

    text: str = Field(default="", description="面经/笔试经验原文（必填）")
    company: str = Field(default="", description="公司名（可选）")
    role: str = Field(default="", description="岗位名（可选）")
    stage: str = Field(default="", description="面试轮次（可选）")
    source_url: str = Field(default="", description="来源链接（可选）")


# ──────────────────────────────────────────────
# 页面
# ──────────────────────────────────────────────
@app.get("/", response_class=FileResponse)
def index() -> FileResponse:
    """返回前端单页应用。"""
    html = Path(PATH_CONFIG["templates_dir"]) / "index.html"
    if not html.exists():
        raise HTTPException(status_code=404, detail="index.html 不存在")
    return FileResponse(str(html))


# ──────────────────────────────────────────────
# 智能对话（RAG 优先答疑）
# ──────────────────────────────────────────────
@app.post("/api/chat")
def chat(req: ChatRequest) -> dict[str, Any]:
    """调用 LangChain Agent 对话（会话级记忆）。"""
    if not req.messages:
        return {"reply": "请先输入内容。"}
    last = req.messages[-1]
    user_input = last.get("content") or last.get("text") or ""
    reply = agent.chat_with_agent(user_input, req.session_id)
    return {"reply": reply, "session_id": req.session_id}


# ──────────────────────────────────────────────
# 定制化简历优化
# ──────────────────────────────────────────────
def _sanitize_filename(name: str) -> str:
    """清洗文件名中的非法字符。"""
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "未知"


@app.post("/api/optimize")
def optimize(req: OptimizeRequest) -> dict[str, Any]:
    """定制化简历优化：拆解岗位 → 公司分析 → 优化 → 面试建议 → 双 Word 文档。"""
    resume_text = req.resume_text.strip()
    if not resume_text:
        raise HTTPException(status_code=400, detail="resume_text 不能为空")

    target_company = (req.target_company or "").strip()
    if not target_company:
        raise HTTPException(status_code=400, detail="请填写目标公司名称")

    # 解析 JD 文本：直接提供，或通过 job_id 从知识库取
    jd_text = req.jd_text.strip()
    if not jd_text and req.job_id:
        from jd_knowledge_base import get_job_by_id

        job = get_job_by_id(req.job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"未找到岗位 id={req.job_id}")
        jd_text = (job.get("jd_text") or "").strip()
    if not jd_text:
        raise HTTPException(status_code=400, detail="jd_text 与 job_id 至少提供其一")

    logger.info("定制优化开始（resume=%d 字, jd=%d 字, 公司=%s）", len(resume_text), len(jd_text), target_company)

    try:
        # 1. 拆解岗位（含分级/类型/隐含目标/风险项）
        jd_analysis = jd_analyzer.analyze_jd(jd_text, resume_text=resume_text)

        # 2. 公司分析与求职判断
        from company_researcher import research_company

        company_research = research_company(target_company, jd_analysis, resume_text)

        # 3. 定制化简历优化 + 四级匹配表
        optimized = content_optimizer.optimize_resume_content(resume_text, jd_analysis)
        matching_table = content_optimizer.build_matching_table(resume_text, jd_analysis)

        # 4. 面试问题 + 面试建议
        from interview_advisor import build_interview_advice, generate_interview_questions

        role_type = jd_analysis.get("role_type", "tech")
        questions = generate_interview_questions(role_type, jd_analysis, resume_text)
        advice = build_interview_advice(
            target_company, jd_analysis, resume_text, company_research, questions
        )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("/api/optimize failed")
        raise HTTPException(status_code=500, detail=f"定制优化失败: {e}") from e

    # 5. 生成双 Word 文档
    from resume_writer import write_customized_resume, write_interview_advice_docx

    out_dir = Path(PATH_CONFIG["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    company_tag = _sanitize_filename(target_company)
    role_tag = _sanitize_filename(jd_analysis.get("role_position", "") or "目标岗位")

    resume_docx = ""
    advice_docx = ""
    try:
        resume_docx = write_customized_resume(optimized, str(out_dir / f"定制化简历_{company_tag}_{role_tag}.docx"))
    except Exception as e:  # noqa: BLE001
        logger.warning("定制化简历文档生成失败: %s", e)
    try:
        advice_docx = write_interview_advice_docx(advice, str(out_dir / f"面试建议_{company_tag}_{role_tag}.docx"))
    except Exception as e:  # noqa: BLE001
        logger.warning("面试建议文档生成失败: %s", e)

    return {
        "optimized": optimized,
        "matching_table": matching_table,
        "jd_analysis": jd_analysis,
        "company_research": company_research,
        "interview_questions": questions,
        "interview_advice": advice,
        "resume_docx": Path(resume_docx).name if resume_docx else "",
        "advice_docx": Path(advice_docx).name if advice_docx else "",
    }


# ──────────────────────────────────────────────
# 文档下载（仅限 output 目录内文件）
# ──────────────────────────────────────────────
@app.get("/api/download")
def download_file(filename: str) -> FileResponse:
    """下载生成的 Word 文档（定制化简历 / 面试建议）。"""
    if not filename or not filename.strip():
        raise HTTPException(status_code=400, detail="缺少文件名")

    base = Path(PATH_CONFIG["output_dir"]).resolve()
    target = (base / Path(filename).name).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=400, detail="非法文件路径")
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {filename}")
    return FileResponse(str(target), filename=target.name)


# ──────────────────────────────────────────────
# 简历文件上传（.pdf / .docx / .txt）
# ──────────────────────────────────────────────
def _parse_resume_file(path: str, suffix: str) -> str:
    """按扩展名解析简历文件为纯文本。"""
    if suffix == ".txt":
        return Path(path).read_text(encoding="utf-8", errors="replace")

    from resume_reader import pdf_to_docx, read_resume

    docx_path = path
    if suffix == ".pdf":
        docx_path = str(Path(path).with_suffix(".docx"))
        pdf_to_docx(path, docx_path)
    try:
        data = read_resume(docx_path)
    finally:
        if suffix == ".pdf" and Path(docx_path).exists():
            Path(docx_path).unlink(missing_ok=True)
    return data["full_text"]


@app.post("/api/upload")
async def upload_resume(file: UploadFile = File(...)) -> dict[str, Any]:
    """上传简历文件（.pdf/.docx/.txt），解析为纯文本返回。"""
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in (".pdf", ".docx", ".txt"):
        raise HTTPException(status_code=400, detail=f"仅支持 .pdf/.docx/.txt，收到: {filename or '未知'}")

    import tempfile

    tmp_dir = Path(tempfile.gettempdir()) / f"resume_upload_{uuid.uuid4().hex[:8]}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    src_path = tmp_dir / f"resume{suffix}"
    try:
        content = await file.read()
        src_path.write_bytes(content)
        text = _parse_resume_file(str(src_path), suffix)
        if not (text or "").strip():
            raise HTTPException(status_code=422, detail="未能提取到文本（可能是扫描件/加密 PDF，请改传 DOCX）")
        return {"text": text, "filename": filename}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"简历解析失败: {e}") from e
    finally:
        for p in tmp_dir.iterdir():
            p.unlink(missing_ok=True)
        tmp_dir.rmdir()


# ──────────────────────────────────────────────
# 面试/笔试经验知识库接口
# ──────────────────────────────────────────────
@app.post("/api/exp/upload")
def exp_upload(req: ExpUploadRequest) -> dict[str, Any]:
    """手动粘贴面经/笔试经验入库：保存素材 → LLM 结构化 → 写入 interview_kb。"""
    from experience_crawler import save_manual_experience
    from experience_processor import process_raw_item
    from interview_knowledge_base import add_experiences

    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="面经文本不能为空")

    try:
        item = save_manual_experience(
            text=text, company=req.company, role=req.role,
            stage=req.stage, source_url=req.source_url,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"素材保存失败: {e}") from e

    questions = []
    try:
        questions = process_raw_item(item)
    except Exception as e:  # noqa: BLE001
        logger.warning("/api/exp/upload 结构化失败（素材已保留）: %s", e)

    added = 0
    if questions:
        try:
            added = add_experiences(questions)
        except Exception as e:  # noqa: BLE001
            logger.warning("/api/exp/upload 入库失败: %s", e)

    return {"saved": added, "questions": questions}


@app.get("/api/exp/search")
def exp_search(
    q: str = "",
    company: str = "",
    role: str = "",
    stage: str = "",
    top_k: int = 10,
    max_distance: float = 0.6,
) -> dict[str, Any]:
    """语义检索面试/笔试题目。

    top_k=0 表示取回全部匹配结果；max_distance 为相似度阈值。
    """
    from interview_knowledge_base import count_questions, search_questions

    query = (q or "").strip()
    if not query:
        return {"questions": [], "total": 0}
    if top_k <= 0:
        top_k = count_questions() or 100
    questions = search_questions(
        query, company=company, role=role, stage=stage,
        top_k=top_k, max_distance=max_distance,
    )
    return {"questions": questions, "total": len(questions)}


@app.get("/api/exp/company")
def exp_company(company: str = "", top_k: int = 20) -> dict[str, Any]:
    """按公司名获取面试题。"""
    from interview_knowledge_base import get_questions_by_company

    if not company or not company.strip():
        return {"questions": []}
    questions = get_questions_by_company(company.strip(), top_k=top_k)
    return {"questions": questions}


@app.get("/api/exp/algorithm")
def exp_algorithm(role: str = "", top_k: int = 20) -> dict[str, Any]:
    """获取笔试算法题（可选按岗位过滤）。"""
    from interview_knowledge_base import get_algorithm_questions

    questions = get_algorithm_questions(role=role, top_k=top_k)
    return {"questions": questions}


@app.get("/api/exp/count")
def exp_count() -> dict[str, Any]:
    """题库题目总数。"""
    from interview_knowledge_base import count_questions

    return {"count": count_questions()}


# ──────────────────────────────────────────────
# 岗位检索（已降级）
# ──────────────────────────────────────────────
@app.get("/api/jobs/search")
def search_jobs(q: str = "", top_k: int = 5) -> dict[str, Any]:
    """按语义相似度检索岗位（岗位库已降级，数据有限）。"""
    from jd_knowledge_base import search_jds

    jobs = search_jds(q, top_k=top_k) if q.strip() else []
    return {"count": len(jobs), "jobs": jobs, "degraded": True, "note": "岗位知识库已降级，数据有限"}


@app.get("/api/jobs/premium")
def premium_jobs(limit: int = 20) -> dict[str, Any]:
    """获取优质岗位列表（岗位库已降级，数据有限）。"""
    from jd_knowledge_base import get_premium_jobs

    jobs = get_premium_jobs(limit=limit)
    return {"count": len(jobs), "jobs": jobs, "degraded": True, "note": "岗位知识库已降级，数据有限"}


# ──────────────────────────────────────────────
# 健康检查
# ──────────────────────────────────────────────
@app.get("/api/health")
def health() -> dict[str, Any]:
    """健康检查。"""
    import importlib.util

    missing = [
        label for module, label in {
            "langchain": "langchain", "chromadb": "chromadb",
            "sentence_transformers": "sentence-transformers",
        }.items() if importlib.util.find_spec(module) is None
    ]
    return {"status": "ok" if not missing else "degraded", "missing_dependencies": missing}


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    from config import WEB_CONFIG

    uvicorn.run("web_app:app", host=WEB_CONFIG["host"], port=WEB_CONFIG["port"])
