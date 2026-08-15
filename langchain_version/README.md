# 简历优化 Agent（LangChain 版）

> ✅ **并行开发版（ACTIVE）**：自 2026-08-15 起与 `langgraph_version`（主力版）同步开发。
> 工作流约定：改动先在 langgraph 版落地，随后同步到本版。本版与主力版的
> 差异仅在框架选型：**LangChain（Tool-calling Agent + LCEL 管道）** vs
> **LangGraph（StateGraph 图编排）**；两版共享同一 ChromaDB 向量库、检索层
> （`jd_knowledge_base.py` / `interview_knowledge_base.py` / `reranker.py`）、
> 结构化输出（`schemas.py` + PydanticOutputParser）、Retriever 抽象
> （`retrievers.py`）与 SSE 流式对话。

一个基于 **LangChain** 的智能求职助手：聚合多平台岗位数据、语义检索岗位、分析 JD、
一键优化简历，并生成「简历-JD 匹配关系表」；简历优化流程走 **LCEL 管道**
（`chain.py`：load → analyze → research → optimize → matching → review → interview → write）。

> 对应项目目录：`langchain_version/`，多 Provider（DeepSeek / OpenAI / 通义千问 / 智谱）统一走 OpenAI 兼容接口。

---

## 特性

- 🤖 **Tool-calling Agent**：LangChain Agent 自动规划调用「答疑检索 / JD 分析 / 简历优化」工具
- 🧠 **多 Provider LLM**：`LLM_PROVIDER` 一键切换 deepseek / openai / dashscope / zhipu
- 🔎 **语义检索**：ChromaDB + BGE（`bge-small-zh-v1.5`）中文向量检索岗位；岗位/面试题库
  采用「标题索引 + 关键词兜底 + Rerank 精排」（`bge-reranker-v2-m3`，与主力版一致）
- 🔗 **Retriever 抽象**：`retrievers.py` 把检索链路包成 LangChain `BaseRetriever`，Agent 工具走 `retriever.invoke()`
- 🧩 **结构化输出**：`schemas.py` + `llm_client.chat_structured`（PydanticOutputParser，解析失败自动降级手写解析）
- ⚡ **SSE 流式对话**：`/api/chat/stream` 打字机输出（`llm_client.stream_chat` / `agent.astream_chat`）
- ⛓️ **LCEL 简历优化管道**：`chain.py` 用 `RunnableSequence`（`|` 组合）编排 load→analyze→research→optimize→matching→review（LLM 审核重试≤3）→interview→write
- 📄 **多格式简历**：支持 `.pdf` / `.docx` / `.txt` 读取，优化结果输出结构化 `.docx`（可选 `.pdf`）
- 🕷️ **多平台爬虫骨架**：boss / lagou / liepin / zhilian，失败降级不崩溃
- ⏰ **定时采集**：APScheduler 每天自动爬取岗位并写入知识库
- 💬 **会话记忆**：按 session_id 隔离多轮对话记忆（LangGraph MemorySaver checkpoint）
- 🌐 **Web 界面**：FastAPI + 原生前端单页（无外部 CDN），CLI 也可用

## 目录结构

```
langchain_version/
├── config.py               # 全局配置（多 Provider / 路径 / 向量库 / 爬虫 / 调度）
├── llm_client.py           # LLM 客户端（chat / stream_chat / chat_json / chat_structured）
├── schemas.py              # 结构化输出 Pydantic 模型（JDAnalysis / MatchingRow）
├── retrievers.py           # LangChain Retriever 抽象（InterviewKB / JDKB）
├── jd_analyzer.py          # JD 分析（提取技能 / 职责 / 经验要求）
├── content_optimizer.py    # 简历内容优化 + 匹配关系表
├── chain.py                # ★ LCEL 简历优化管道（RunnableSequence）
├── resume_reader.py        # 简历读取（pdf_to_docx / read_resume）
├── resume_writer.py        # 优化结果写 docx / docx_to_pdf
├── jd_knowledge_base.py    # 岗位知识库（ChromaDB + BGE Embedding，jd_title 标题索引）
├── interview_knowledge_base.py # 面试题库检索（标题索引 + 关键词兜底 + Rerank）
├── reranker.py             # Rerank 精排（bge-reranker-v2-m3，懒加载 + 优雅降级）
├── jd_crawler.py           # 多平台岗位爬虫（httpx + bs4 骨架）
├── scheduler.py            # APScheduler 定时爬取
├── agent.py                # LangChain Tool-calling Agent（核心，含 astream_chat）
├── web_app.py              # FastAPI Web 服务（含 /api/chat/stream SSE 流式）
├── main.py                 # 命令行入口（web / chat / doctor / optimize）
├── validate_runtime.py     # 运行环境依赖校验（main.py doctor）
├── tests/                  # pytest 套件（与主力版对齐）
├── templates/index.html    # 单页前端（聊天打字机 + 优化）
├── requirements.txt
├── .env.example
├── docs/
│   ├── PRD.md              # 产品需求文档
│   └── 技术开发文档.md       # 技术设计文档
├── input/                  # 原始简历（可选）
├── output/                 # 优化结果输出
└── data/                   # 爬取存档与 Chroma 向量库
```

## 安装

```bash
# 1. 创建虚拟环境（可选）
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env             # Windows: copy .env.example .env
# 编辑 .env，填入 LLM_PROVIDER 与对应 API Key
```

> 说明：BGE Embedding 模型（`bge-large-zh-v1.5`）首次使用会自动下载；`docx2pdf` 转 PDF 需要本机安装 MS Word。

## 配置（.env）

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `LLM_PROVIDER` | `deepseek` / `openai` / `dashscope` / `zhipu` | `deepseek` |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | - |
| `OPENAI_API_KEY` | OpenAI API Key | - |
| `DASHSCOPE_API_KEY` | 通义千问 API Key | - |
| `ZHIPU_API_KEY` | 智谱 API Key | - |
| `LLM_MODEL` | 覆盖默认模型名 | 随 provider |
| `LLM_TEMPERATURE` | 采样温度 | `0.3` |
| `LLM_MAX_TOKENS` | 最大输出 token | `4096` |
| `EMBEDDING_MODEL` | BGE 向量模型 | `BAAI/bge-large-zh-v1.5` |
| `EMBEDDING_DEVICE` | `cpu` / `cuda` | `cpu` |
| `RERANK_ENABLED` | 是否启用 Rerank 精排 | `1`（测试环境 `0`） |
| `RERANK_MODEL` | Rerank 模型（默认自动探测本地 `models/bge-reranker-v2-m3`，否则回退 HF id） | `BAAI/bge-reranker-v2-m3` |
| `RERANK_DEVICE` | Rerank 设备 | 同 `EMBEDDING_DEVICE` |
| `RERANK_CANDIDATE_MULTIPLIER` / `RERANK_MAX_CANDIDATES` | 粗召回倍数 / 候选上限 | `5` / `50` |
| `WEB_HOST` / `WEB_PORT` | Web 服务监听 | `127.0.0.1` / `8000` |

更多配置项见 `config.py`（爬虫平台、定时调度、大厂名单、路径等）。

## 运行

```bash
# ① Web 服务（浏览器访问 http://127.0.0.1:8000）
python main.py web

# ② 命令行对话
python main.py chat

# ③ 一键优化简历（指定 JD 文本文件）
python main.py optimize --resume input/我的简历.pdf --jd input/岗位JD.txt

# ③' 或从知识库岗位优化
python main.py optimize --resume input/我的简历.docx --job-id <job_id>

# ④ 先爬取岗位入库，再使用上述能力
python -m jd_crawler "Python"          # 手动爬取并存档
python -m jd_knowledge_base            # 将岗位写入知识库（示例）
```

Web 服务启动后，前端提供两个页签：**智能对话**（调 `/api/chat`）与 **简历优化**（调 `/api/optimize`，展示优化结果与匹配关系表）。

## API 一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 返回前端页面 |
| POST | `/api/chat` | 智能对话 `{messages, session_id}` → `{reply}` |
| POST | `/api/optimize` | 简历优化 `{resume_text, jd_text \| job_id}` → `{optimized, matching_table, jd_analysis}` |
| GET | `/api/jobs/search?q=&top_k=` | 岗位语义检索 |
| GET | `/api/jobs/premium?limit=` | 优质岗位列表 |

## 典型流程

1. 爬虫（手动或定时）采集岗位 → `data/crawled_jobs/*.json`
2. `jd_knowledge_base.add_jobs` 写入 ChromaDB（大厂 / 高频自动标记 premium）
3. 用户提供简历 → `read_resume` 读取 → `analyze_jd` 分析 JD → `optimize_resume_content` 优化 → `resume_writer` 输出 docx
4. Agent 对话中按需调用检索 / 分析 / 优化工具，辅助求职决策

## License

仅供学习交流使用。爬虫请遵守目标站点 robots 协议与当地法律法规。
