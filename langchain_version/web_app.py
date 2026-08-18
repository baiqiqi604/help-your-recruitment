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
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import LLM_CONFIG, PATH_CONFIG

# 说明：轻量的标准库与 fastapi 导入统一放模块级；重型依赖
# （langgraph / chromadb / sentence-transformers / graph / agent /
# interview_knowledge_base / jd_knowledge_base / resume_reader 等）保持
# 函数内懒加载，避免健康检查等轻量路径在启动时加载整条依赖链。

logger = logging.getLogger(__name__)


def _plain_advice(text: str) -> str:
    """将面试建议 Markdown 转成纯净纯文本（前端展示用）。

    懒加载 resume_writer（避免重型依赖进入轻量路径）；
    Word 导出由 resume_writer.write_interview_advice_docx 保留标题层级与表格。
    """
    if not text or not text.strip():
        return text
    from resume_writer import markdown_to_plain_text

    return markdown_to_plain_text(text)


def _warmup() -> None:
    """启动预热：预加载 embedding 模型 + 完成一次 LLM 冷启动调用。

    冷启动成本实测：embedding 模型约 25s（一次性），LLM 首次调用 24-46s
    （连接复用后降至 ~0.6s）。预热把这些开销移到服务启动阶段，
    避免用户首次检索/对话/简历优化被冷启动拖慢。

    预热在后台线程执行，失败仅记日志，不影响服务启动；
    调用方（检索/对话）本身都有按需加载与降级逻辑。
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
    title="简历优化 Agent（LangGraph 版）",
    description="基于 LangGraph 的简历优化 Agent：Chat 对话 + 简历优化 + 岗位知识库检索",
    version="1.0.0",
    lifespan=lifespan,
)

# 静态资源（Tabler Icons 等本地化文件），目录不存在时跳过挂载；
# 跟随 PATH_CONFIG 的 BASE_DIR（打包后为 exe 目录，由启动器补齐）
_STATIC_DIR = Path(PATH_CONFIG["templates_dir"]).parent / "static"
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

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
    photo_base64: str = Field(default="", description="证件照（data URI 或纯 base64，可选，≤2MB）")


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
# 未命中题库时使用的静态 system（固定前缀，保证跨会话/跨请求缓存命中；
# 动态内容（用户问题）只出现在其后，不进入前缀）
_FALLBACK_SYSTEM = (
    "你是求职面试答疑助手。请用通俗清晰的语言直接回答用户的问题；"
    "回答准确、克制、结构化，必要时用列表分点；不确定的内容明确说明。"
)


# ──────────────────────────────────────────────
# 会话历史（服务端 append-only，缓存友好）
# 设计要点（配合 DeepSeek 前缀缓存）：
#   1. 历史只追加、绝不改写/重排：第 N 轮输入 = 第 N-1 轮输入 + 少量新 token，
#      前缀字节稳定 → 第 2 轮起命中率显著上升；
#   2. 超限策略 = 整体重置：超过轮次上限时清空历史、只保留当前轮。
#      绝不"截断头部保留最近"——那会让历史段不再是任何历史请求的前缀，
#      整段 miss；整体重置后新请求回退到 system+tools 共享前缀，反而仍可命中；
#   3. 历史以 session_id（thread_id）为键，与 agent checkpoint 的隔离粒度一致。
# ──────────────────────────────────────────────
_SESSION_HISTORY: dict[str, list[dict[str, str]]] = {}
_SESSION_HISTORY_LOCK = threading.Lock()
_SESSION_MAX_MESSAGES = 40  # 20 轮（user+assistant 各一条）；超限整体重置


def _get_session_history(session_id: str) -> list[dict[str, str]]:
    """返回会话历史消息列表（不存在则初始化为空）。"""
    with _SESSION_HISTORY_LOCK:
        return _SESSION_HISTORY.setdefault(session_id, [])


def _append_session_message(session_id: str, role: str, content: str) -> None:
    """向会话历史追加一条消息；超限时整体重置（仅保留当前轮）。"""
    with _SESSION_HISTORY_LOCK:
        history = _SESSION_HISTORY.setdefault(session_id, [])
        history.append({"role": role, "content": content})
        if len(history) > _SESSION_MAX_MESSAGES:
            logger.info(
                "会话 %s 历史超限（%d 条），整体重置以保持缓存前缀稳定",
                session_id,
                len(history),
            )
            _SESSION_HISTORY[session_id] = history[-2:]  # 保留当前轮 user+assistant


@app.post("/api/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    """面经咨询接口：RAG 优先答疑（聊天式）。

    流程：
        1. 先检索面经题库（interview_kb）；
        2. 命中（非空）→ 大模型基于命中的面经内容总结成连贯答案，末尾附相关面试题，source=rag；
        3. 未命中 → 调用大模型直接回答，source=llm，回复中标注「本题库暂无收录，以下为模型回答」。
    Returns:
        {"reply": 回答文本, "source": "rag"|"llm", "questions": 命中的题目列表, "session_id": ...}
    """
    session_id = request.session_id.strip() or f"session-{uuid.uuid4().hex[:12]}"

    # 取最后一条用户消息
    user_input = ""
    for msg in reversed(request.messages):
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
    except Exception:  # noqa: BLE001
        logger.exception("面经检索失败，回退到模型回答")
        hits = []

    # 服务端会话历史（append-only）：取历史 → 追加本轮 user → LLM 调用带上历史，
    # 保证第 2 轮起输入前缀逐轮复用（DeepSeek 前缀缓存命中）
    history = _get_session_history(session_id)
    _append_session_message(session_id, "user", user_input)

    if hits:
        # ── RAG 命中：LLM 基于面经内容总结回答 + 附相关面试题 ──
        reply = _summarize_kb_answer(user_input, hits, history=history)
        _append_session_message(session_id, "assistant", reply)
        return {"reply": reply, "source": "rag", "questions": hits, "session_id": session_id}

    # ── 未命中：大模型直接回答并标注 ──
    import llm_client

    try:
        model_answer = llm_client.chat(
            user_input, system=_FALLBACK_SYSTEM, history=history
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("大模型回答失败")
        raise HTTPException(status_code=503, detail="对话服务暂时不可用") from e

    answer = "【本题库暂无收录，以下为模型回答】\n\n" + str(model_answer).strip()
    _append_session_message(session_id, "assistant", answer)
    return {"reply": answer, "source": "llm", "questions": [], "session_id": session_id}


# ──────────────────────────────────────────────
# 对话接口（SSE 流式）
# ──────────────────────────────────────────────
@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """SSE 流式对话接口（打字机效果，RAG 优先分流与 /api/chat 一致）。

    SSE 事件格式（text/event-stream）：
        data: {"event": "start", "source": "rag"|"llm"}
        data: {"event": "delta", "text": "..."}        （逐块文本）
        data: {"event": "questions", "questions": [...]}（RAG 命中时附题目）
        data: {"event": "done"}

    流程：
        1. 先检索面经题库（interview_kb，命中判定与 /api/chat 一致）；
        2. 命中 → LLM 基于命中的面经内容流式总结回答（source=rag）；
        3. 未命中 → 大模型直接流式回答（source=llm）。
    """
    import json as _json

    from fastapi.responses import StreamingResponse

    session_id = request.session_id.strip() or f"session-{uuid.uuid4().hex[:12]}"

    user_input = ""
    for msg in reversed(request.messages):
        if msg.get("role") == "user" and (msg.get("content") or "").strip():
            user_input = msg["content"]
            break

    if not user_input:
        raise HTTPException(status_code=400, detail="缺少用户消息内容")

    logger.info("/api/chat/stream：session=%s 收到输入 %d 字", session_id, len(user_input))

    from interview_knowledge_base import search_questions

    try:
        hits = search_questions(user_input, top_k=8, max_distance=0.45)
    except Exception:  # noqa: BLE001
        logger.exception("面经检索失败，回退到模型回答")
        hits = []

    def sse(payload: dict) -> str:
        return "data: " + _json.dumps(payload, ensure_ascii=False) + "\n\n"

    async def gen():
        import llm_client

        yield sse({"event": "start", "source": "rag" if hits else "llm"})

        # 服务端会话历史（append-only）：与 /api/chat 一致，LLM 调用带上历史
        history = _get_session_history(session_id)
        _append_session_message(session_id, "user", user_input)

        reply_parts: list[str] = []
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
                for delta in llm_client.stream_chat(
                    prompt, system, max_tokens=1500, history=history
                ):
                    if delta:
                        reply_parts.append(delta)
                        yield sse({"event": "delta", "text": delta})
            except Exception as e:  # noqa: BLE001
                logger.warning("流式总结失败，回退直接整理: %s", e)
                fallback = _format_kb_reply(user_input, hits)
                reply_parts.append(fallback)
                yield sse({"event": "delta", "text": fallback})
            yield sse({"event": "questions", "questions": hits})
        else:
            # ── 未命中：大模型直接流式回答并标注 ──
            try:
                first = True
                for delta in llm_client.stream_chat(
                    user_input, system=_FALLBACK_SYSTEM, history=history
                ):
                    if not delta:
                        continue
                    if first:
                        prefix = "【本题库暂无收录，以下为模型回答】\n\n"
                        reply_parts.append(prefix)
                        yield sse({"event": "delta", "text": prefix})
                        first = False
                    reply_parts.append(delta)
                    yield sse({"event": "delta", "text": delta})
                if first:  # 一个字符都没产出
                    fallback = "（模型无输出）"
                    reply_parts.append(fallback)
                    yield sse({"event": "delta", "text": fallback})
            except Exception as e:  # noqa: BLE001
                logger.warning("流式回答失败: %s", e)
                fallback = f"（回答失败：{e}）"
                reply_parts.append(fallback)
                yield sse({"event": "delta", "text": fallback})

        _append_session_message(session_id, "assistant", "".join(reply_parts))
        yield sse({"event": "done"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _summarize_kb_answer(
    user_input: str,
    questions: list[dict[str, Any]],
    history: list[dict[str, str]] | None = None,
) -> str:
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
        summary = llm_client.chat(prompt, system, max_tokens=1500, history=history)
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
    return "\n".join(parts).rstrip()


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
    # 证件照校验：可选；格式须为 jpeg/png 的 data URI 或纯 base64，解码后 ≤ 2MB
    photo_base64 = (request.photo_base64 or "").strip()
    if photo_base64:
        _raw = photo_base64
        if _raw.startswith("data:"):
            if "image/" not in _raw.split(";", 1)[0]:
                raise HTTPException(status_code=400, detail="照片格式不支持，仅支持 jpeg / png")
            _raw = _raw.split(",", 1)[1] if "," in _raw else ""
        try:
            import base64 as _b64

            photo_bytes = _b64.b64decode(_raw, validate=True)
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="照片 base64 数据非法") from None
        if not photo_bytes:
            raise HTTPException(status_code=400, detail="照片数据为空")
        if len(photo_bytes) > 2 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="照片过大（上限 2MB）")
    try:
        result = run_optimize(
            resume_text, jd_text, target_company=target_company, photo_base64=photo_base64
        )
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
        # 前端展示用纯净纯文本（去 markdown 符号）；Word 导出保留标题层级与表格
        "interview_advice": _plain_advice(result.get("interview_advice", "")),
        # 文档下载（Word 版）
        "resume_docx": Path(result.get("resume_docx_path", "")).name,
        "advice_docx": Path(result.get("advice_docx_path", "")).name,
        # 《resume-formatter》Skill 新增产出
        "resume_html": Path(result.get("resume_html_path", "")).name,      # 精美 HTML 简历（浏览器→打印→导出PDF）
        "resume_yaml": Path(result.get("resume_yaml_path", "")).name,      # 结构化 YAML 数据（便于迭代）
        "resume_check_report": result.get("resume_check_report", ""),      # 简历质量检查报告（Markdown）
        "pdf_export_guide": (
            "💡 PDF导出方法：用 Chrome/Edge 打开下载的 HTML 简历 → 按 Ctrl+P → "
            "打印机选择「另存为PDF」 → 纸张尺寸A4 → 边距选「无」或默认 → 勾选「背景图形」 → 保存。"
        ),
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
    if not filename or not filename.strip():
        raise HTTPException(status_code=400, detail="缺少文件名")

    base = Path(PATH_CONFIG["output_dir"]).resolve()
    target = (base / Path(filename).name).resolve()
    # 防路径穿越：只允许 output 目录内的文件
    if not target.is_relative_to(base):
        raise HTTPException(status_code=400, detail="非法文件路径")
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {filename}")
    # HTML 文件直接内嵌展示（浏览器内渲染），其他文件走下载
    if target.suffix.lower() == ".html":
        return FileResponse(target, media_type="text/html", filename=None)
    return FileResponse(target, filename=target.name)


# ──────────────────────────────────────────────
# 简历文件上传接口（.pdf / .docx / .txt）
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

    top_k = _clamp_top_k(top_k)
    logger.info("/api/jobs/search：q=%s top_k=%d", query, top_k)
    jobs = search_jds(query, top_k=top_k)
    return {"jobs": jobs, "degraded": True, "note": "岗位知识库已降级，数据有限"}


@app.get("/api/jobs/premium")
def premium_jobs(limit: int = 50) -> dict[str, Any]:
    """获取大厂/高频优质岗位接口（岗位库已降级，数据有限，仅供参考）。"""
    from jd_knowledge_base import get_premium_jobs

    limit = _clamp_top_k(limit, default=50)
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
    warnings: list[str] = []
    try:
        questions = process_raw_item(item)
    except Exception as e:  # noqa: BLE001
        logger.warning("/api/exp/upload 结构化失败（素材已保留）: %s", e)
        questions = []
        warnings.append(f"LLM 结构化失败（素材已保留）: {e}")

    # 3. 写入知识库
    added = 0
    if questions:
        try:
            added = add_experiences(questions)
        except Exception as e:  # noqa: BLE001
            logger.warning("/api/exp/upload 入库失败: %s", e)
            warnings.append(f"入库失败: {e}")
    elif not warnings:
        warnings.append("LLM 未提取到题目（素材已保留，可检查内容格式后重试）")

    logger.info("/api/exp/upload：素材已存，结构化 %d 条，入库 %d 条", len(questions), added)
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
        top_k = count_questions() or 100  # 0=全量语义
    else:
        top_k = min(top_k, MAX_TOP_K)
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
    top_k = _clamp_top_k(top_k, default=20)
    logger.info("/api/exp/company：company=%s top_k=%d", company, top_k)
    questions = get_questions_by_company(company.strip(), top_k=top_k)
    return {"questions": questions}


@app.get("/api/exp/algorithm")
def exp_algorithm(role: str = "", top_k: int = 20) -> dict[str, Any]:
    """获取笔试算法题（可选按岗位过滤）。"""
    from interview_knowledge_base import get_algorithm_questions

    top_k = _clamp_top_k(top_k, default=20)
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
