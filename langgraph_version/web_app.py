"""
FastAPI Web 服务

接口（同 LangChain 版）：
    GET  /                   返回前端页面 templates/index.html
    POST /api/chat           多轮对话（带 session_id 记忆）→ {reply}
    POST /api/optimize       简历优化（resume_text + jd_text 或 job_id）
                             → {optimized, matching_table, jd_analysis}
    GET  /api/jobs/search    岗位知识库检索 ?q=&top_k=
    GET  /api/jobs/premium   优质岗位列表

导出：app（FastAPI 实例），供 uvicorn 启动。
"""

from __future__ import annotations

import importlib.util
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from config import LLM_CONFIG, PATH_CONFIG

logger = logging.getLogger(__name__)

app = FastAPI(
    title="简历优化 Agent（LangGraph 版）",
    description="基于 LangGraph 的简历优化 Agent：Chat 对话 + 简历优化 + 岗位知识库检索",
    version="1.0.0",
)

RUNTIME_DEPENDENCIES = {
    "langgraph": "langgraph",
    "langchain_openai": "langchain-openai",
    "chromadb": "chromadb",
    "sentence_transformers": "sentence-transformers",
    "bs4": "beautifulsoup4",
    "httpx": "httpx",
}


def _runtime_status() -> dict[str, Any]:
    missing = [
        label for module, label in RUNTIME_DEPENDENCIES.items()
        if importlib.util.find_spec(module) is None
    ]
    mock_enabled = os.getenv("MOCK_LLM", "").lower() in {
        "1", "true", "yes"
    }
    llm_ready = mock_enabled or bool(LLM_CONFIG["api_key"])
    return {
        "status": "ok" if not missing and llm_ready else "degraded",
        "llm_mode": "mock" if mock_enabled else ("configured" if llm_ready else "missing_api_key"),
        "missing_dependencies": missing,
    }


# ──────────────────────────────────────────────
# 请求模型（Pydantic）
# ──────────────────────────────────────────────
class ChatRequest(BaseModel):
    """POST /api/chat 请求体。"""

    messages: list[dict[str, Any]] = Field(default_factory=list)
    session_id: str = Field(default="")


class OptimizeRequest(BaseModel):
    """POST /api/optimize 请求体。"""

    resume_text: str = Field(default="", description="简历纯文本")
    jd_text: str = Field(default="", description="岗位描述全文")
    job_id: str = Field(default="", description="知识库中的岗位 ID（与 jd_text 二选一）")
    target_company: str = Field(default="", description="目标公司名称（必填）")


# ──────────────────────────────────────────────
# 页面路由
# ──────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """返回单页前端。"""
    template_path = Path(PATH_CONFIG["templates_dir"]) / "index.html"
    if not template_path.exists():
        raise HTTPException(status_code=500, detail="前端模板缺失: templates/index.html")
    return template_path.read_text(encoding="utf-8")


# ──────────────────────────────────────────────
# 对话接口
# ──────────────────────────────────────────────
@app.post("/api/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    """多轮对话接口：调用 LangGraph ReAct Agent（带记忆）。"""
    from agent import chat_with_agent

    session_id = request.session_id.strip() or f"session-{uuid.uuid4().hex[:12]}"

    # 取最后一条用户消息
    user_input = ""
    for msg in reversed(request.messages):
        if msg.get("role") == "user" and (msg.get("content") or "").strip():
            user_input = msg["content"]
            break

    if not user_input:
        raise HTTPException(status_code=400, detail="缺少用户消息内容")

    logger.info("/api/chat：session=%s 开始对话", session_id)
    try:
        reply = chat_with_agent(user_input, session_id)
    except Exception as e:  # noqa: BLE001
        logger.exception("/api/chat failed")
        raise HTTPException(status_code=503, detail="对话服务暂时不可用") from e
    return {"reply": reply, "session_id": session_id}


# ──────────────────────────────────────────────
# 简历优化接口
# ──────────────────────────────────────────────
@app.post("/api/optimize")
def optimize(request: OptimizeRequest) -> dict[str, Any]:
    """简历优化接口：走 graph.run_optimize（LangGraph 流水线）。"""
    from graph import run_optimize

    resume_text = (request.resume_text or "").strip()
    if not resume_text:
        raise HTTPException(status_code=400, detail="resume_text 不能为空")

    target_company = (request.target_company or "").strip()
    if not target_company:
        raise HTTPException(status_code=400, detail="请填写目标公司名称")

    # JD 来源：job_id（知识库）或 jd_text（直接输入）
    jd_text = (request.jd_text or "").strip()
    if request.job_id:
        try:
            from jd_knowledge_base import get_job_by_id

            job = get_job_by_id(request.job_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("按 job_id 获取岗位失败: %s", e)
            job = None
        if not job or not job.get("jd_text"):
            raise HTTPException(status_code=400, detail=f"知识库中未找到岗位: {request.job_id}")
        jd_text = job["jd_text"]

    if not jd_text:
        raise HTTPException(status_code=400, detail="jd_text 与 job_id 至少提供其一")

    logger.info("/api/optimize：开始优化（简历 %d 字，JD %d 字，公司=%s）", len(resume_text), len(jd_text), target_company)
    try:
        result = run_optimize(resume_text, jd_text, target_company=target_company)
    except Exception as e:  # noqa: BLE001
        logger.exception("/api/optimize failed")
        raise HTTPException(status_code=503, detail="简历优化服务暂时不可用") from e

    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])

    return {
        "optimized": result.get("optimized_text", ""),
        "matching_table": result.get("matching_table", []),
        "jd_analysis": result.get("jd_analysis", {}),
        "company_research": result.get("company_research", {}),
        "interview_questions": result.get("interview_questions", []),
        "interview_advice": result.get("interview_advice", ""),
        "resume_docx": Path(result.get("resume_docx_path", "")).name,
        "advice_docx": Path(result.get("advice_docx_path", "")).name,
    }


# ──────────────────────────────────────────────
# 文档下载接口（仅限 output 目录内的文件）
# ──────────────────────────────────────────────
@app.get("/api/download")
def download_file(filename: str) -> Any:
    """下载生成的 Word 文档（定制化简历 / 面试建议）。

    Args:
        filename: 文件名（如 定制化简历_某公司_某岗位.docx）
    """
    from fastapi.responses import FileResponse

    if not filename or not filename.strip():
        raise HTTPException(status_code=400, detail="缺少文件名")

    base = Path(PATH_CONFIG["output_dir"]).resolve()
    target = (base / Path(filename).name).resolve()
    # 防路径穿越：只允许 output 目录内的文件
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=400, detail="非法文件路径")
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {filename}")
    return FileResponse(target, filename=target.name)


# ──────────────────────────────────────────────
# 简历文件上传接口（.pdf / .docx / .txt）
# ──────────────────────────────────────────────
def _parse_resume_file(path: str, suffix: str) -> str:
    """按扩展名解析简历文件为纯文本（.txt 直读，.pdf 先转 docx 再提取）。"""
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
    """上传简历文件（.pdf/.docx/.txt），解析为纯文本返回，供前端填入优化表单。

    Returns:
        {"text": 解析后的简历文本, "filename": 原始文件名}
    """
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in (".pdf", ".docx", ".txt"):
        raise HTTPException(
            status_code=400,
            detail=f"仅支持 .pdf / .docx / .txt 简历文件，收到: {filename or '未知文件'}",
        )

    import tempfile

    tmp_dir = Path(tempfile.gettempdir()) / f"resume_upload_{uuid.uuid4().hex[:8]}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    src_path = tmp_dir / f"resume{suffix}"
    try:
        content = await file.read()
        src_path.write_bytes(content)

        text = _parse_resume_file(str(src_path), suffix)
        if not (text or "").strip():
            raise HTTPException(
                status_code=422,
                detail="未能从简历中提取到文本（可能是扫描件/加密 PDF，请改传 DOCX）",
            )
        logger.info("/api/upload：解析成功 filename=%s（%d 字）", filename, len(text.strip()))
        return {"text": text, "filename": filename}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning("简历文件解析失败: %s", e)
        raise HTTPException(status_code=422, detail=f"简历解析失败: {e}") from e
    finally:
        # 清理临时文件
        for p in tmp_dir.iterdir():
            p.unlink(missing_ok=True)
        tmp_dir.rmdir()


# ──────────────────────────────────────────────
# 岗位知识库接口
# ──────────────────────────────────────────────
@app.get("/api/jobs/search")
def search_jobs(q: str = "", top_k: int = 10) -> dict[str, Any]:
    """岗位语义检索接口（岗位库已降级，数据有限，仅供参考）。"""
    from jd_knowledge_base import search_jds

    query = (q or "").strip()
    if not query:
        return {"jobs": [], "degraded": True, "note": "岗位知识库已降级，数据有限"}

    logger.info("/api/jobs/search：q=%s top_k=%d", query, top_k)
    jobs = search_jds(query, top_k=top_k)
    return {"jobs": jobs, "degraded": True, "note": "岗位知识库已降级，数据有限"}


@app.get("/api/jobs/premium")
def premium_jobs(limit: int = 50) -> dict[str, Any]:
    """获取大厂/高频优质岗位接口（岗位库已降级，数据有限，仅供参考）。"""
    from jd_knowledge_base import get_premium_jobs

    logger.info("/api/jobs/premium：limit=%d", limit)
    jobs = get_premium_jobs(limit=limit)
    return {"jobs": jobs, "degraded": True, "note": "岗位知识库已降级，数据有限"}


# ──────────────────────────────────────────────
# 面试/笔试经验知识库接口
# ──────────────────────────────────────────────
class ExpUploadRequest(BaseModel):
    """POST /api/exp/upload 请求体（手动粘贴面经入库）。"""

    text: str = Field(default="", description="面经/笔试经验原文（必填）")
    company: str = Field(default="", description="公司名（可选）")
    role: str = Field(default="", description="岗位名（可选）")
    stage: str = Field(default="", description="面试轮次（可选，HR面/业务面/专业面/主管面/终面/笔试）")
    source_url: str = Field(default="", description="来源链接（可选）")


@app.post("/api/exp/upload")
def exp_upload(request: ExpUploadRequest) -> dict[str, Any]:
    """手动粘贴面经/笔试经验入库：保存素材 → LLM 结构化 → 写入 interview_kb。

    Returns:
        {"saved": 入库题目数, "questions": 结构化题目列表}
    """
    from experience_crawler import save_manual_experience
    from experience_processor import process_raw_item
    from interview_knowledge_base import add_experiences

    text = (request.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="面经文本不能为空")

    # 1. 保存原始素材（source=manual）
    try:
        item = save_manual_experience(
            text=text,
            company=request.company,
            role=request.role,
            stage=request.stage,
            source_url=request.source_url,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("/api/exp/upload 保存素材失败")
        raise HTTPException(status_code=500, detail=f"素材保存失败: {e}") from e

    # 2. LLM 结构化
    try:
        questions = process_raw_item(item)
    except Exception as e:  # noqa: BLE001
        logger.warning("/api/exp/upload 结构化失败（素材已保留）: %s", e)
        questions = []

    # 3. 写入知识库
    added = 0
    if questions:
        try:
            added = add_experiences(questions)
        except Exception as e:  # noqa: BLE001
            logger.warning("/api/exp/upload 入库失败: %s", e)

    logger.info("/api/exp/upload：素材已存，结构化 %d 条，入库 %d 条", len(questions), added)
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

    top_k=0 表示取回全部匹配结果（不分页由前端处理）；
    max_distance 为相似度阈值（cosine 距离，越小越相关，超过则视为无关丢弃）。

    Returns:
        {"questions": 题目列表, "total": 匹配总数}
    """
    from interview_knowledge_base import count_questions, search_questions

    query = (q or "").strip()
    if not query:
        return {"questions": [], "total": 0}
    if top_k <= 0:
        top_k = count_questions() or 100
    logger.info("/api/exp/search：q=%s company=%s role=%s stage=%s top_k=%d max_distance=%.2f", query, company, role, stage, top_k, max_distance)
    questions = search_questions(
        query, company=company, role=role, stage=stage,
        top_k=top_k, max_distance=max_distance,
    )
    return {"questions": questions, "total": len(questions)}


@app.get("/api/exp/company")
def exp_company(company: str = "", top_k: int = 20) -> dict[str, Any]:
    """按公司名获取面试题（面试前查"这家公司面什么"）。"""
    from interview_knowledge_base import get_questions_by_company

    if not company or not company.strip():
        return {"questions": []}
    logger.info("/api/exp/company：company=%s top_k=%d", company, top_k)
    questions = get_questions_by_company(company.strip(), top_k=top_k)
    return {"questions": questions}


@app.get("/api/exp/algorithm")
def exp_algorithm(role: str = "", top_k: int = 20) -> dict[str, Any]:
    """获取笔试算法题（可选按岗位过滤）。"""
    from interview_knowledge_base import get_algorithm_questions

    logger.info("/api/exp/algorithm：role=%s top_k=%d", role, top_k)
    questions = get_algorithm_questions(role=role, top_k=top_k)
    return {"questions": questions}


@app.get("/api/exp/count")
def exp_count() -> dict[str, Any]:
    """题库题目总数。"""
    from interview_knowledge_base import count_questions

    return {"count": count_questions()}


@app.get("/api/health")
def health() -> dict[str, Any]:
    """健康检查。"""
    return _runtime_status()


if __name__ == "__main__":
    import uvicorn

    from config import WEB_CONFIG

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    uvicorn.run(
        "web_app:app",
        host=WEB_CONFIG["host"],
        port=WEB_CONFIG["port"],
        reload=False,
    )
