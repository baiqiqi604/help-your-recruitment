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

import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from config import PATH_CONFIG

logger = logging.getLogger(__name__)

app = FastAPI(
    title="简历优化 Agent（LangGraph 版）",
    description="基于 LangGraph 的简历优化 Agent：Chat 对话 + 简历优化 + 岗位知识库检索",
    version="1.0.0",
)


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
    reply = chat_with_agent(user_input, session_id)
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

    logger.info("/api/optimize：开始优化（简历 %d 字，JD %d 字）", len(resume_text), len(jd_text))
    result = run_optimize(resume_text, jd_text)

    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])

    return {
        "optimized": result.get("optimized_text", ""),
        "matching_table": result.get("matching_table", []),
        "jd_analysis": result.get("jd_analysis", {}),
    }


# ──────────────────────────────────────────────
# 岗位知识库接口
# ──────────────────────────────────────────────
@app.get("/api/jobs/search")
def search_jobs(q: str = "", top_k: int = 10) -> dict[str, Any]:
    """岗位语义检索接口。"""
    from jd_knowledge_base import search_jds

    query = (q or "").strip()
    if not query:
        return {"jobs": []}

    logger.info("/api/jobs/search：q=%s top_k=%d", query, top_k)
    jobs = search_jds(query, top_k=top_k)
    return {"jobs": jobs}


@app.get("/api/jobs/premium")
def premium_jobs(limit: int = 50) -> dict[str, Any]:
    """获取大厂/高频优质岗位接口。"""
    from jd_knowledge_base import get_premium_jobs

    logger.info("/api/jobs/premium：limit=%d", limit)
    jobs = get_premium_jobs(limit=limit)
    return {"jobs": jobs}


@app.get("/api/health")
def health() -> dict[str, str]:
    """健康检查。"""
    return {"status": "ok"}


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
