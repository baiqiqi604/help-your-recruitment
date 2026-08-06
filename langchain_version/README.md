# 简历优化 Agent（LangChain 版）

一个基于 **LangChain Tool-calling Agent** 的智能求职助手：聚合多平台岗位数据、语义检索岗位、分析 JD、一键优化简历，并生成「简历-JD 匹配关系表」。

> 对应项目目录：`langchain_version/`，多 Provider（DeepSeek / OpenAI / 通义千问 / 智谱）统一走 OpenAI 兼容接口。

---

## 特性

- 🤖 **Tool-calling Agent**：LangChain Agent 自动规划调用「岗位检索 / 优质岗位 / JD 分析 / 简历优化」四个工具
- 🧠 **多 Provider LLM**：`LLM_PROVIDER` 一键切换 deepseek / openai / dashscope / zhipu
- 🔎 **语义检索**：ChromaDB + BGE（`bge-large-zh-v1.5`）中文向量检索岗位
- 📄 **多格式简历**：支持 `.pdf` / `.docx` / `.txt` 读取，优化结果输出结构化 `.docx`（可选 `.pdf`）
- 🕷️ **多平台爬虫骨架**：boss / lagou / liepin / zhilian，失败降级不崩溃
- ⏰ **定时采集**：APScheduler 每天自动爬取岗位并写入知识库
- 💬 **会话记忆**：按 session_id 隔离多轮对话记忆（`ConversationBufferMemory`）
- 🌐 **Web 界面**：FastAPI + 原生前端单页（无外部 CDN），CLI 也可用

## 目录结构

```
langchain_version/
├── config.py               # 全局配置（多 Provider / 路径 / 向量库 / 爬虫 / 调度）
├── llm_client.py           # LLM 客户端（chat / chat_json / chat_json_array）
├── jd_analyzer.py          # JD 分析（提取技能 / 职责 / 经验要求）
├── content_optimizer.py    # 简历内容优化 + 匹配关系表
├── resume_reader.py        # 简历读取（pdf_to_docx / read_resume）
├── resume_writer.py        # 优化结果写 docx / docx_to_pdf
├── jd_knowledge_base.py    # 岗位知识库（ChromaDB + BGE Embedding）
├── jd_crawler.py           # 多平台岗位爬虫（httpx + bs4 骨架）
├── scheduler.py            # APScheduler 定时爬取
├── agent.py                # LangChain Tool-calling Agent（核心）
├── web_app.py              # FastAPI Web 服务
├── main.py                 # 命令行入口
├── templates/index.html    # 单页前端
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
