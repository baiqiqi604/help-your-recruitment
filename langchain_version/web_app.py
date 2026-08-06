"""
Web 服务模块（FastAPI）

接口一览：
- GET  /                  返回前端页面 templates/index.html
- POST /api/chat          智能对话（body: {messages, session_id}）
- POST /api/optimize      简历优化（body: {resume_text, jd_text | job_id}）
- GET  /api/jobs/search   岗位语义检索（q, top_k）
- GET  /api/jobs/premium  优质岗位列表（limit）

依赖：fastapi、uvicorn
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import agent
import content_optimizer
import jd_analyzer
import jd_knowledge_base
from config import PATH_CONFIG

logger = logging.getLogger(__name__)

app = FastAPI(title="简历优化 Agent（LangChain 版）", version="1.0.0")

# 挂载静态资源目录（可选，存在才挂载）
_templates_dir = Path(PATH_CONFIG["templates_dir"])
_static_dir = _templates_dir / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# ──────────────────────────────────────────────
# 请求 / 响应模型
# ──────────────────────────────────────────────
class ChatRequest(BaseModel):
    """智能对话请求。"""

    messages: list[dict[str, str]] = Field(
        default_factory=list, description="消息列表（取最后一条用户消息作为输入）"
    )
    session_id: str = Field(default="default", description="会话标识，共享记忆")


class ChatResponse(BaseModel):
    reply: str


class OptimizeRequest(BaseModel):
    """简历优化请求。jd_text 与 job_id 至少提供其一。"""

    resume_text: str = ""
    jd_text: str = ""
    job_id: str = ""


class OptimizeResponse(BaseModel):
    optimized: str
    matching_table: list[dict[str, Any]]
    jd_analysis: dict[str, Any]


# ──────────────────────────────────────────────
# 页面
# ──────────────────────────────────────────────
@app.get("/", response_class=FileResponse)
def index() -> FileResponse:
    """返回前端单页应用。"""
    html = _templates_dir / "index.html"
    if not html.exists():
        raise HTTPException(status_code=404, detail="index.html 不存在")
    return FileResponse(str(html))


# ──────────────────────────────────────────────
# 智能对话
# ──────────────────────────────────────────────
@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """调用 LangChain Agent 对话（会话级记忆）。"""
    if not req.messages:
        return ChatResponse(reply="请先输入内容。")
    last = req.messages[-1]
    user_input = last.get("content") or last.get("text") or ""
    reply = agent.chat_with_agent(user_input, req.session_id)
    return ChatResponse(reply=reply)


# ──────────────────────────────────────────────
# 简历优化
# ──────────────────────────────────────────────
@app.post("/api/optimize", response_model=OptimizeResponse)
def optimize(req: OptimizeRequest) -> OptimizeResponse:
    """一键简历优化：JD 分析 → 内容优化 → 匹配关系表。"""
    resume_text = req.resume_text.strip()
    if not resume_text:
        raise HTTPException(status_code=400, detail="resume_text 不能为空")

    # 解析 JD 文本：直接提供，或通过 job_id 从知识库取
    jd_text = req.jd_text.strip()
    if not jd_text and req.job_id:
        job = jd_knowledge_base.get_job_by_id(req.job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"未找到岗位 id={req.job_id}")
        jd_text = (job.get("jd_text") or "").strip()
    if not jd_text:
        raise HTTPException(
            status_code=400, detail="jd_text 与 job_id 至少提供其一"
        )

    logger.info("开始简历优化流程（resume=%d 字, jd=%d 字）", len(resume_text), len(jd_text))
    jd_analysis = jd_analyzer.analyze_jd(jd_text)
    optimized = content_optimizer.optimize_resume_content(resume_text, jd_analysis)
    matching_table = content_optimizer.build_matching_table(resume_text, jd_analysis)
    return OptimizeResponse(
        optimized=optimized,
        matching_table=matching_table,
        jd_analysis=jd_analysis,
    )


# ──────────────────────────────────────────────
# 岗位检索
# ──────────────────────────────────────────────
@app.get("/api/jobs/search")
def search_jobs(q: str = "", top_k: int = 5) -> dict[str, Any]:
    """按语义相似度检索岗位。"""
    jobs = jd_knowledge_base.search_jds(q, top_k=top_k) if q.strip() else []
    return {"count": len(jobs), "jobs": jobs}


@app.get("/api/jobs/premium")
def premium_jobs(limit: int = 20) -> dict[str, Any]:
    """获取优质岗位列表（大厂 + 高频）。"""
    jobs = jd_knowledge_base.get_premium_jobs(limit=limit)
    return {"count": len(jobs), "jobs": jobs}


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    from config import WEB_CONFIG

    uvicorn.run("web_app:app", host=WEB_CONFIG["host"], port=WEB_CONFIG["port"])
