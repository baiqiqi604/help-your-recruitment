# 📄 AI 简历优化 Agent — 定制化简历大师

> 一个基于大模型的**求职助手**：针对目标公司与岗位 JD，生成定制化简历与面试建议，并提供**面试/笔试题库答疑**（RAG）与对话式求职咨询。

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![LangGraph](https://img.shields.io/badge/LangGraph-0.2-orange) ![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green) ![ChromaDB](https://img.shields.io/badge/ChromaDB-1.5-purple)

---

## ✨ 核心能力

| 模块 | 说明 |
|------|------|
| 📝 **定制化简历** | 围绕目标公司 + 岗位 JD，按「定制简历原则」生成 ATS 友好简历（不虚构经历），输出 Word 文档 |
| 🏢 **公司分析** | 分析目标公司公开信息（正负面/网络评价/招聘观察），给出求职判断与投递策略 |
| 🎯 **面试建议** | 结合公司情况 + JD + 用户履历，生成针对性面试问题与 STAR 案例建议（Word 文档） |
| 📚 **面试题库（RAG）** | ChromaDB 面试/笔试经验知识库，支持语义检索、按公司/岗位/轮次筛选、相关题目推荐 |
| 💬 **答疑助手** | 聊天先检索题库 → 命中整理答案 + 推荐 5 道相关题；未命中由大模型回答 |
| 🧠 **多 Provider** | DeepSeek / OpenAI / 通义千问 / 智谱 GLM，OpenAI 兼容接口一键切换 |
| 🧬 **LangGraph 工作流** | 图状态编排：拆解岗位 → 公司分析 → 优化 → LLM 审核（自动重试）→ 面试建议 → 双文档输出 |

## 🌿 分支结构

| 分支 | 内容 | 状态 |
|------|------|------|
| `master` | 完整归档（根文档 + 三个版本目录） | 归档 |
| `langgraph` | **LangGraph 版（主力）**：图编排 + 面试题库 + 答疑 | ✅ 推荐 |
| `langchain` | LangChain 版：Tool-calling Agent + 线性流水线 | 可选 |
| `resume-optimizer` | 历史初版（LangChain 0.3 线性流水线） | 参考保留 |

> 本 README 以 `langgraph` 分支为准。

## 🚀 快速开始

### 环境要求
- Python 3.10+
- 一个 LLM API Key（DeepSeek 等，OpenAI 兼容接口）

### 安装与启动

```bash
# 1. 进入主力版本
cd langgraph_version

# 2. 安装依赖（建议使用虚拟环境）
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. 配置 API Key
cp .env.example .env               # 填写 LLM_PROVIDER 与对应 API Key

# 4. 启动 Web 服务（浏览器访问 http://127.0.0.1:8000）
python main.py web
```

> 💡 **网络受限环境**：Embedding 模型加载会联网检查 HuggingFace，可用离线脚本启动避免卡死：
> ```bash
> python start_web_offline.py 8000
> ```

### CLI 用法

```bash
# 一次性定制：简历 + JD + 目标公司 → 生成定制化简历与面试建议 Word 文档
python main.py optimize --resume input/sample_resume.txt --jd input/sample_jd.txt --company "字节跳动"

# 对话答疑
python main.py chat

# 环境自检
python main.py doctor
```

### 面试题库导入（可选）

```bash
# 导入整理好的面经文件（支持 .docx / .txt / .md / .json）
python _ingest_experiences.py 面经1.docx 面经2.md

# 导入《AI产品经理1000题面试题库（带参考答案）.docx》类结构化题库
python _ingest_ai_pm_bank.py "AI产品经理1000题面试题库.docx"
```

## 🔌 API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | Web 前端页面 |
| POST | `/api/chat` | 对话答疑（RAG 优先，多轮记忆 session_id） |
| POST | `/api/optimize` | 定制化简历优化（简历 + JD + 目标公司） |
| POST | `/api/upload` | 上传简历文件（.pdf/.docx/.txt）解析为文本 |
| GET | `/api/download?filename=` | 下载生成的 Word 文档 |
| GET | `/api/exp/search` | 面试题库语义检索（`top_k=0` 全量 + 阈值过滤） |
| GET | `/api/exp/company` | 按公司获取面试题 |
| GET | `/api/exp/algorithm` | 笔试算法题 |
| POST | `/api/exp/upload` | 手动面经入库 |
| GET | `/api/exp/count` | 题库题目总数 |
| GET | `/api/jobs/search` | 岗位检索（已降级，数据有限） |
| GET | `/api/health` | 健康检查 |

## 🗂️ 项目结构（langgraph_version）

```
langgraph_version/
├── graph.py                    # LangGraph 7 节点工作流（核心编排）
├── agent.py                    # RAG 优先答疑 Agent（ReAct + MemorySaver）
├── jd_analyzer.py              # 岗位拆解（分级/岗位类型/隐含目标/风险项）
├── content_optimizer.py        # 简历优化 + 四级匹配关系表
├── company_researcher.py       # 公司信息分析与求职判断
├── interview_advisor.py        # 面试问题生成 + 面试建议
├── resume_reader.py            # PDF/Word/TXT 简历读取
├── resume_writer.py            # 定制化简历/面试建议 Word 文档输出
├── experience_crawler.py       # 面经抓取（CSDN/掘金浏览器渲染）
├── experience_processor.py     # 面经 LLM 结构化加工
├── interview_knowledge_base.py # 面试题库检索层（ChromaDB interview_kb）
├── jd_knowledge_base.py        # 岗位库（已降级，可选）
├── llm_client.py               # 多 Provider LLM 客户端
├── config.py                   # 全局配置
├── web_app.py                  # FastAPI 应用
├── templates/index.html        # 单页前端（聊天/简历优化/面试题库）
├── main.py                     # 入口（web / chat / optimize / doctor）
├── docs/                       # PRD / 技术文档 / 题库设计文档
└── data/ input/ output/        # 运行数据目录
```

## ⚙️ 配置说明（.env）

```ini
# LLM Provider（deepseek / openai / dashscope / zhipu）
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-xxx

# Embedding 模型（BGE 中文，本地运行）
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5

# Web 服务
WEB_HOST=127.0.0.1
WEB_PORT=8000
```

## 🛠️ 技术栈

- **编排**：LangGraph（StateGraph + ReAct Agent + MemorySaver）
- **Web**：FastAPI + 原生单页前端（HTML/CSS/JS）
- **RAG**：ChromaDB + BGE 中文 Embedding（sentence-transformers）
- **文档**：python-docx / pdf2docx
- **抓取**：DrissionPage（浏览器渲染）+ BeautifulSoup

## 📄 文档

- [PRD（产品需求）](langgraph_version/docs/PRD.md)
- [技术开发文档](langgraph_version/docs/技术开发文档.md)
- [面试笔试经验知识库设计](langgraph_version/docs/面试笔试经验知识库设计.md)

## ⚠️ 声明

- 简历优化只基于用户真实经历，不虚构内容；AI 生成的参考思路仅供求职参考
- 面试题库来自公开面经与用户整理，仅供参考，不构成录用保证
- 公司分析基于公开信息与模型知识，需以官方披露为准

## 📝 License

MIT
