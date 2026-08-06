# 简历优化 Agent（双框架版本）

一个基于大模型的**简历优化 Agent** 项目：读取简历 → 分析目标岗位 JD → 按岗位定制优化简历内容 → 输出 ATS 友好简历，并提供对话式求职建议、岗位知识库检索、多平台 JD 爬虫与定时更新能力。

本仓库包含**两个独立版本**，核心流程相同，仅 Agent 编排层采用不同框架：

| 版本 | 目录 | Agent 编排框架 | 特色 |
|------|------|----------------|------|
| LangChain 版 | `langchain_version/` | LangChain Tool-calling Agent + AgentExecutor | 工具调用式 Agent，ConversationBufferMemory 会话记忆，LCEL 思想，依赖轻 |
| LangGraph 版 | `langgraph_version/` | LangGraph StateGraph + create_react_agent | 图状态工作流（含 LLM 质量审核节点与失败重试回路），MemorySaver + thread_id 持久记忆 |

## 功能特性（两版一致）

- **核心优化流水线**：读简历 → 分析 JD → 简历-JD 匹配分析 → 按九大定制原则优化 → 输出 docx/pdf
- **岗位知识库**：ChromaDB + BGE 中文 Embedding，语义检索 JD，标记大厂/高频岗位
- **JD 爬虫**：boss / lagou / liepin / zhilian 多平台骨架（httpx + BeautifulSoup）
- **定时任务**：APScheduler 每日自动增量爬取
- **对话式求职建议**：Web 聊天界面，Agent 自主调用工具（查岗位 / 分析 JD / 优化简历）
- **多 Provider**：DeepSeek / OpenAI / 通义千问 / 智谱 GLM，OpenAI 兼容接口一键切换
- **Web 界面**：FastAPI + 单页前端（聊天 + 简历优化两个 Tab）

## 快速开始

```bash
# 1. 进入任一版本目录
cd langchain_version          # 或 langgraph_version

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置 API Key
cp .env.example .env          # 填写 LLM_PROVIDER 与对应 API Key

# 4. 启动 Web 服务（浏览器访问 http://127.0.0.1:8000）
python main.py web

# 其他入口
python main.py chat           # CLI 对话
python main.py optimize --resume input/简历.pdf --jd "岗位描述文本文件路径或--job-id ID"
```

## 目录结构（两版一致，langgraph 版额外含 graph.py）

```
<version>/
├── config.py              # 全局配置（多 Provider / 路径 / 向量库 / 爬虫 / 调度）
├── llm_client.py          # OpenAI 兼容多 Provider LLM 客户端
├── resume_reader.py       # PDF/Word/TXT 简历读取
├── resume_writer.py       # docx 写出 + 转 PDF
├── jd_analyzer.py         # JD 结构化分析（技能/职责/经验）
├── content_optimizer.py   # 简历优化 + 匹配关系表
├── jd_knowledge_base.py   # ChromaDB + BGE 岗位知识库
├── jd_crawler.py          # 多平台 JD 爬虫骨架
├── scheduler.py           # APScheduler 定时任务
├── agent.py               # 对话 Agent（LangChain AgentExecutor / LangGraph ReAct）
├── graph.py               # [仅 LangGraph 版] StateGraph 工作流
├── web_app.py             # FastAPI 应用
├── main.py                # 入口（web / chat / optimize）
├── templates/index.html   # 单页前端
├── docs/                  # 各版本独立 PRD + 技术开发文档
└── data/ input/ output/   # 运行数据目录
```

## 版本差异速览

| 维度 | LangChain 版 | LangGraph 版 |
|------|--------------|--------------|
| Agent 构建 | `create_tool_calling_agent` + `AgentExecutor` | `create_react_agent` + `MemorySaver` |
| 工作流 | 线性函数调用 + 工具路由 | `StateGraph`：load → analyze → optimize → review → write，带条件边与重试 |
| 记忆 | `ConversationBufferMemory` | `MemorySaver` + thread_id（checkpoint 机制） |
| 质量保障 | 无内置审核 | `review` 节点 LLM 审核，不合格自动重试（最多 3 次） |
| 新增依赖 | 无 | `langgraph`、`langgraph-checkpoint` |

详细设计与接口说明见各版本目录下 `docs/PRD.md` 与 `docs/技术开发文档.md`。

> 历史初版位于 `resume_optimizer/`（LangChain 0.3 线性流水线），仅作参考保留。
