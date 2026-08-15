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

import importlib.util
import logging
import os
import re
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import agent  # noqa: F401  # 保留 LangChain 版入口，chat 现走确定性分流
import content_optimizer
import jd_analyzer
from config import LLM_CONFIG, PATH_CONFIG

logger = logging.getLogger(__name__)


def _warmup() -> None:
    """启动预热：预加载 embedding 模型 + 完成一次 LLM 冷启动调用（与 langgraph 版对齐）。

    冷启动成本实测：embedding 模型约 25s（一次性），LLM 首次调用 24-46s
    （连接复用后降至 ~0.6s）。预热把这些开销移到服务启动阶段，
    避免用户首次检索/对话/简历优化被冷启动拖慢。
    """
    t0 = time.time()
    # 1) embedding 模型：预加载，之后检索不再等加载
    try:
        from jd_knowledge_base import _get_embedding_function

        _get_embedding_function()
        logger.info("预热：embedding 模型加载完成（%.1fs）", time.time() - t0)
    except Exception as e:  # noqa: BLE001
        logger.warning("预热：embedding 模型加载失败（将按需加载）: %s", e)

    # 2) LLM：首次调用建立连接（MOCK 模式跳过）
    try:
        import llm_client

        if not llm_client.mock_enabled():
            llm_client.chat("请只回复两个字：就绪", max_tokens=10)
            logger.info("预热：LLM 首次调用完成（累计 %.1fs）", time.time() - t0)
    except Exception as e:  # noqa: BLE001
        logger.warning("预热：LLM 首次调用失败（将按需重试）: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时后台预热，退出时无需特殊清理。"""
    threading.Thread(target=_warmup, name="warmup", daemon=True).start()
    yield


app = FastAPI(
    title="简历优化 Agent（LangChain 版）— 定制化简历大师",
    version="1.0.0",
    lifespan=lifespan,
)

# 静态资源（Tabler Icons 等本地化文件），目录不存在时跳过挂载
_STATIC_DIR = Path(PATH_CONFIG["templates_dir"]).parent / "static"
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

RUNTIME_DEPENDENCIES = {
    "langchain": "langchain",
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
    """面经咨询接口：RAG 优先答疑（聊天式，后端确定性分流）。

    流程：
        1. 先检索面经题库（interview_kb）；
        2. 命中（非空）→ 大模型基于命中的面经内容总结成连贯答案，source=rag；
        3. 未命中 → 调用大模型直接回答，source=llm，标注「本题库暂无收录」。
    Returns:
        {"reply": 回答文本, "source": "rag"|"llm", "questions": 命中的题目列表, "session_id": ...}
    """
    session_id = req.session_id.strip() or f"session-{uuid.uuid4().hex[:12]}"

    # 取最后一条用户消息
    user_input = ""
    for msg in reversed(req.messages):
        if msg.get("role") == "user" and (msg.get("content") or "").strip():
            user_input = msg["content"]
            break

    if not user_input:
        raise HTTPException(status_code=400, detail="缺少用户消息内容")

    logger.info("/api/chat：session=%s 收到输入 %d 字", session_id, len(user_input))

    from interview_knowledge_base import search_questions

    try:
        # 命中判定阈值 0.45（cosine 距离）：相关题目 top1 一般 ≤0.31，无关问题 ≥0.5；
        # top_k 提到 8，配合 interview_knowledge_base 的关键词兜底，提高召回
        hits = search_questions(user_input, top_k=8, max_distance=0.45)
    except Exception as e:  # noqa: BLE001
        logger.exception("面经检索失败，回退到模型回答")
        hits = []

    if hits:
        # ── RAG 命中：LLM 基于面经内容总结回答 + 附相关面试题 ──
        reply = _summarize_kb_answer(user_input, hits)
        return {"reply": reply, "source": "rag", "questions": hits, "session_id": session_id}

    # ── 未命中：大模型直接回答并标注 ──
    import llm_client

    try:
        model_answer = llm_client.chat(user_input)
    except Exception as e:  # noqa: BLE001
        logger.exception("大模型回答失败")
        raise HTTPException(status_code=503, detail="对话服务暂时不可用") from e

    answer = "【本题库暂无收录，以下为模型回答】\n\n" + str(model_answer).strip()
    return {"reply": answer, "source": "llm", "questions": [], "session_id": session_id}


# ──────────────────────────────────────────────
# 智能对话（SSE 流式，与 langgraph 版对齐）
# ──────────────────────────────────────────────
@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE 流式对话接口（打字机效果，RAG 优先分流与 /api/chat 一致）。

    SSE 事件格式（text/event-stream）：
        data: {"event": "start", "source": "rag"|"llm"}
        data: {"event": "delta", "text": "..."}        （逐块文本）
        data: {"event": "questions", "questions": [...]}（RAG 命中时附题目）
        data: {"event": "done"}
    """
    import json as _json

    from fastapi.responses import StreamingResponse

    session_id = req.session_id.strip() or f"session-{uuid.uuid4().hex[:12]}"

    user_input = ""
    for msg in reversed(req.messages):
        if msg.get("role") == "user" and (msg.get("content") or "").strip():
            user_input = msg["content"]
            break

    if not user_input:
        raise HTTPException(status_code=400, detail="缺少用户消息内容")

    logger.info("/api/chat/stream：session=%s 收到输入 %d 字", session_id, len(user_input))

    from interview_knowledge_base import search_questions

    try:
        hits = search_questions(user_input, top_k=8, max_distance=0.45)
    except Exception as e:  # noqa: BLE001
        logger.exception("面经检索失败，回退到模型回答")
        hits = []

    def sse(payload: dict) -> str:
        return "data: " + _json.dumps(payload, ensure_ascii=False) + "\n\n"

    async def gen():
        import llm_client

        yield sse({"event": "start", "source": "rag" if hits else "llm"})

        if hits:
            # ── RAG 命中：LLM 基于面经内容流式总结回答 ──
            kb_text = ""
            for i, q in enumerate(hits[:4], start=1):
                kb_text += f"{i}. 题目：{q.get('question', '')}\n"
                key_points = q.get("key_points") or []
                if key_points:
                    kb_text += f"   考察点：{'、'.join(key_points)}\n"
                if q.get("reference_answer"):
                    ans = str(q["reference_answer"])
                    if len(ans) > 600:
                        ans = ans[:600] + "…（已截断）"
                    kb_text += f"   参考答案：{ans}\n"

            system = (
                "你是求职面试答疑助手。请基于下方提供的「面经题库内容」，用通俗清晰的语言"
                "总结回答用户的问题，输出一段连贯的答案：不要逐条罗列题目，不要提“题库”字样，"
                "也不要输出面试题列表。内容必须来源于题库材料，不要编造；材料未覆盖的部分明确说明。"
            )
            prompt = f"用户问题：{user_input}\n\n【面经题库内容】\n{kb_text}"
            try:
                for delta in llm_client.stream_chat(prompt, system, max_tokens=1500):
                    if delta:
                        yield sse({"event": "delta", "text": delta})
            except Exception as e:  # noqa: BLE001
                logger.warning("流式总结失败，回退直接整理: %s", e)
                yield sse({"event": "delta", "text": _format_kb_reply(user_input, hits)})
            yield sse({"event": "questions", "questions": hits})
        else:
            # ── 未命中：大模型直接流式回答并标注 ──
            try:
                first = True
                for delta in llm_client.stream_chat(user_input):
                    if not delta:
                        continue
                    if first:
                        yield sse({"event": "delta", "text": "【本题库暂无收录，以下为模型回答】\n\n"})
                        first = False
                    yield sse({"event": "delta", "text": delta})
                if first:  # 一个字符都没产出
                    yield sse({"event": "delta", "text": "（模型无输出）"})
            except Exception as e:  # noqa: BLE001
                logger.warning("流式回答失败: %s", e)
                yield sse({"event": "delta", "text": f"（回答失败：{e}）"})

        yield sse({"event": "done"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _summarize_kb_answer(user_input: str, questions: list[dict[str, Any]]) -> str:
    """让 LLM 基于命中的面经内容总结成连贯答案（相关面试题由前端渲染可点击列表）。

    LLM 调用失败时回退为逐条整理（_format_kb_reply）。
    """
    import llm_client

    kb_text = ""
    # 只取前 4 道用于总结（完整列表由前端渲染），控制 prompt 长度以加快响应
    for i, q in enumerate(questions[:4], start=1):
        kb_text += f"{i}. 题目：{q.get('question', '')}\n"
        key_points = q.get("key_points") or []
        if key_points:
            kb_text += f"   考察点：{'、'.join(key_points)}\n"
        if q.get("reference_answer"):
            ans = str(q["reference_answer"])
            if len(ans) > 600:
                ans = ans[:600] + "…（已截断）"
            kb_text += f"   参考答案：{ans}\n"

    system = (
        "你是求职面试答疑助手。请基于下方提供的「面经题库内容」，用通俗清晰的语言"
        "总结回答用户的问题，输出一段连贯的答案：不要逐条罗列题目，不要提“题库”字样，"
        "也不要输出面试题列表。内容必须来源于题库材料，不要编造；材料未覆盖的部分明确说明。"
    )
    prompt = f"用户问题：{user_input}\n\n【面经题库内容】\n{kb_text}"
    try:
        # 总结类短回答：max_tokens=1500 即可，显著加快响应
        summary = llm_client.chat(prompt, system, max_tokens=1500)
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM 总结失败，回退为直接整理: %s", e)
        return _format_kb_reply(user_input, questions)
    return str(summary).strip()


def _format_kb_reply(user_input: str, questions: list[dict[str, Any]]) -> str:
    """将 RAG 命中的题目整理为面向用户的咨询回答文本。"""
    parts = ["【来自面经题库】为你找到 " + str(len(questions)) + " 道相关面试题，供参考：", ""]
    for i, q in enumerate(questions, start=1):
        parts.append(f"{i}. {q.get('question', '')}")
        tags = " / ".join(
            str(q.get(k, "") or "") for k in ("stage", "question_type")
            if q.get(k)
        )
        if tags:
            parts.append(f"   （{tags}）")
        key_points = q.get("key_points") or []
        if key_points:
            parts.append("   考察点：" + "、".join(key_points))
        if q.get("reference_answer"):
            parts.append("   参考答案：" + str(q["reference_answer"]))
        parts.append("")
    return "\n".join(parts)


# ──────────────────────────────────────────────
# 定制化简历优化
# ──────────────────────────────────────────────
def _sanitize_filename(name: str) -> str:
    """清洗文件名中的非法字符。"""
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "未知"


@app.post("/api/optimize")
def optimize(req: OptimizeRequest) -> dict[str, Any]:
    """定制化简历优化：LCEL 管道（拆解岗位 → 公司分析 → 优化 → 匹配表 → 审核 → 面试建议 → 双 Word 文档）。"""
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
        # LCEL 管道：load → analyze → research → optimize → matching → review → interview → write
        from chain import run_optimize

        result = run_optimize(resume_text, jd_text, target_company=target_company)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("/api/optimize failed")
        raise HTTPException(status_code=500, detail=f"定制优化失败: {e}") from e

    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])

    return {
        "optimized": result.get("optimized_text", ""),
        "matching_table": result.get("matching_table", []),
        "jd_analysis": result.get("jd_analysis", {}),
        "company_research": result.get("company_research", {}),
        "interview_questions": result.get("interview_questions", []),
        "interview_advice": result.get("interview_advice", ""),
        "resume_docx": Path(result.get("resume_docx_path", "")).name if result.get("resume_docx_path") else "",
        "advice_docx": Path(result.get("advice_docx_path", "")).name if result.get("advice_docx_path") else "",
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
    """按扩展名解析简历文件为纯文本（统一走 resume_reader.read_resume_text）。"""
    from resume_reader import read_resume_text

    return read_resume_text(path)


MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 上传简历大小上限：10MB
MAX_TOP_K = 200  # 检索接口 top_k / limit 上限，防止异常大值拖慢检索


def _clamp_top_k(top_k: int, default: int = 10) -> int:
    """把 top_k 钳制到 [1, MAX_TOP_K]；非正数用 default（exp_search 的 0=全量语义由调用方保留）。"""
    if top_k <= 0:
        return default
    return min(top_k, MAX_TOP_K)


@app.post("/api/upload")
async def upload_resume(file: UploadFile = File(...)) -> dict[str, Any]:
    """上传简历文件（.pdf/.docx/.txt），解析为纯文本返回。"""
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in (".pdf", ".docx", ".txt"):
        raise HTTPException(status_code=400, detail=f"仅支持 .pdf/.docx/.txt，收到: {filename or '未知'}")

    tmp_dir = Path(tempfile.gettempdir()) / f"resume_upload_{uuid.uuid4().hex[:8]}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    src_path = tmp_dir / f"resume{suffix}"
    try:
        # 分块读取并限制大小，防止超大文件一次性读入内存拖垮服务
        content = bytearray()
        while chunk := await file.read(1024 * 1024):
            content.extend(chunk)
            if len(content) > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="文件过大（上限 10MB）")
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

    warnings: list[str] = []
    questions = []
    try:
        questions = process_raw_item(item)
    except Exception as e:  # noqa: BLE001
        logger.warning("/api/exp/upload 结构化失败（素材已保留）: %s", e)
        warnings.append(f"LLM 结构化失败（素材已保留）: {e}")

    added = 0
    if questions:
        try:
            added = add_experiences(questions)
        except Exception as e:  # noqa: BLE001
            logger.warning("/api/exp/upload 入库失败: %s", e)
            warnings.append(f"入库失败: {e}")
    elif not warnings:
        warnings.append("LLM 未提取到题目（素材已保留，可检查内容格式后重试）")

    return {"saved": added, "questions": questions, "warning": "；".join(warnings) or ""}


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
        top_k = count_questions() or 100  # 0=全量语义
    else:
        top_k = min(top_k, MAX_TOP_K)
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
    top_k = _clamp_top_k(top_k, default=20)
    questions = get_questions_by_company(company.strip(), top_k=top_k)
    return {"questions": questions}


@app.get("/api/exp/algorithm")
def exp_algorithm(role: str = "", top_k: int = 20) -> dict[str, Any]:
    """获取笔试算法题（可选按岗位过滤）。"""
    from interview_knowledge_base import get_algorithm_questions

    top_k = _clamp_top_k(top_k, default=20)
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

    top_k = _clamp_top_k(top_k, default=5)
    jobs = search_jds(q, top_k=top_k) if q.strip() else []
    return {"count": len(jobs), "jobs": jobs, "degraded": True, "note": "岗位知识库已降级，数据有限"}


@app.get("/api/jobs/premium")
def premium_jobs(limit: int = 20) -> dict[str, Any]:
    """获取优质岗位列表（岗位库已降级，数据有限）。"""
    from jd_knowledge_base import get_premium_jobs

    limit = _clamp_top_k(limit, default=20)
    jobs = get_premium_jobs(limit=limit)
    return {"count": len(jobs), "jobs": jobs, "degraded": True, "note": "岗位知识库已降级，数据有限"}


# ──────────────────────────────────────────────
# 健康检查
# ──────────────────────────────────────────────
@app.get("/api/health")
def health() -> dict[str, Any]:
    """健康检查：依赖完整性 + LLM 配置状态。"""
    return _runtime_status()


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    from config import WEB_CONFIG

    uvicorn.run("web_app:app", host=WEB_CONFIG["host"], port=WEB_CONFIG["port"])
