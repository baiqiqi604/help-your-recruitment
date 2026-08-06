# 简历优化 Agent（LangGraph 版）

基于 **LangGraph** 图编排框架的简历优化 Agent：针对目标岗位 JD 自动优化简历，
并内置一个带多轮记忆的对话 Agent 与 RAG 岗位知识库。

> 对应项目：`langchain_version`（LangChain 版）、`resume_optimizer`（原始版）。
> 本版本在流程编排上引入 LangGraph StateGraph，并通过 LangGraph Checkpoint 实现对话记忆。

## 功能特性

| 模块 | 说明 |
|------|------|
| 简历优化流水线 | LangGraph StateGraph 编排：加载简历 → 分析 JD → 优化 → LLM 审核 → 重试/输出 |
| 对话 Agent | `create_react_agent` + `MemorySaver`，按 session（thread_id）多轮记忆 |
| 简历读取 | PDF → Word（pdf2docx）+ python-docx 提取段落/表格/全文 |
| 格式输出 | 优化结果写回 Word 保留格式，可选导出 PDF（docx2pdf） |
| 岗位知识库 | ChromaDB + BGE 中文 Embedding（`BGEEmbeddingFunction`），语义检索/优质岗位 |
| 岗位爬虫 | httpx + BeautifulSoup 骨架，`crawl_jobs` / `save_jobs` 单点失败不崩溃 |
| 定时任务 | APScheduler 每日定时爬取 + 知识库增量更新 |

## 项目结构

```
langgraph_version/
├── config.py                 # 全局配置（LLM / 向量库 / 路径 / 爬虫 / 调度）
├── llm_client.py             # 多 Provider LLM 客户端（DeepSeek/OpenAI/通义/智谱）
├── jd_analyzer.py            # 岗位分析（大模型提取结构化需求）
├── content_optimizer.py      # 简历优化 + 匹配关系表
├── resume_reader.py          # PDF→Word→文本
├── resume_writer.py          # 写回 Word + 导出 PDF
├── jd_knowledge_base.py      # ChromaDB + BGE 知识库（init_kb / add_jobs / search_jds / get_job_by_id / get_premium_jobs）
├── jd_crawler.py             # 爬虫骨架（crawl_jobs / save_jobs 等）
├── scheduler.py              # APScheduler 定时任务（start_scheduler）
├── graph.py                  # ★ LangGraph StateGraph 优化流水线
├── agent.py                  # ★ LangGraph ReAct 对话 Agent（MemorySaver 记忆）
├── web_app.py                # FastAPI 服务
├── main.py                   # CLI 入口（web / chat / optimize）
├── templates/index.html      # 单页前端（聊天 + 优化，原生 JS/CSS，无 CDN）
├── requirements.txt
├── .env.example
└── docs/
    ├── PRD.md
    └── 技术开发文档.md
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

```bash
# 复制 .env.example 为 .env 并填入 API Key
cp .env.example .env
# LLM_PROVIDER=deepseek
# DEEPSEEK_API_KEY=sk-xxx
```

### 3. 启动 Web 服务

```bash
python main.py web
# 或
uvicorn web_app:app --reload
```

打开 http://127.0.0.1:8000 ，使用「聊天」或「简历优化」两个 Tab。

### 4. 命令行对话

```bash
python main.py chat
# 可选指定会话实现多轮记忆
python main.py chat --session my-session-001
```

### 5. 命令行一次性优化

```bash
# 使用 JD 文本文件
python main.py optimize --resume input/我的简历.pdf --jd input/jd.txt

# 使用岗位知识库中的岗位
python main.py optimize --resume input/我的简历.docx --job-id boss_xxxx

# 简历支持 .pdf / .docx / .txt
```

### 6. API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/` | 返回前端页面 |
| POST | `/api/chat` | `{messages, session_id}` → `{reply, session_id}` |
| POST | `/api/optimize` | `{resume_text, jd_text 或 job_id}` → `{optimized, matching_table, jd_analysis}` |
| GET  | `/api/jobs/search?q=&top_k=` | 岗位知识库语义检索 |
| GET  | `/api/jobs/premium` | 大厂/高频优质岗位 |
| GET  | `/api/health` | 健康检查 |

## 核心模块

### graph.py — LangGraph 优化流水线

State（TypedDict）：`resume_text / jd_text / jd_analysis / optimized_text / matching_table / error / attempts`。

节点：`load_resume → analyze_jd → optimize → review → write_output`；
条件边：`review` 通过 → `write_output → END`；不通过且 `attempts < 3` 回到 `optimize`（attempts+1）；超限 → `END`。

```python
from graph import build_graph, run_optimize

result = run_optimize(resume_text, jd_text)
print(result["optimized_text"])
```

### agent.py — 对话 Agent

```python
from agent import chat_with_agent

reply = chat_with_agent("帮我分析这段 JD", session_id="s1")
reply2 = chat_with_agent("它需要哪些技能？", session_id="s1")  # 记得上文
```

## 设计文档

- [产品需求文档 PRD](docs/PRD.md)
- [技术开发文档（含 StateGraph 设计图 / 记忆机制）](docs/技术开发文档.md)
