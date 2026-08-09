# LangChain 版升级总结（定制化简历大师）

> 日期：2026-08-09
> 目标：将 langgraph 版（主力版）的全部能力按相同标准同步到 langchain 版，RAG 复用同一套知识库

## 一、升级内容总览

| 类别 | 模块 | 说明 |
|------|------|------|
| 岗位拆解 | `jd_analyzer.py` | 岗位拆解分级（必须/强相关/加分/风险项）+ 岗位类型 + 隐含目标 + 风险项识别 |
| 简历优化 | `content_optimizer.py` | 匹配表升级为四级强度（强/部分/弱/缺失）+ 放入位置 + 需确认标记；Prompt 融入要求分级 |
| 公司分析 | `company_researcher.py` | **新增**：目标公司信息分析与求职判断（推荐程度/机会/风险/投递策略/反向确认问题） |
| 面试建议 | `interview_advisor.py` | **新增**：按 7 类岗位生成针对性面试问题 + 完整面试建议（Markdown） |
| 文档输出 | `resume_writer.py` | 新增 `write_customized_resume`（定制化简历）、`write_interview_advice_docx`（面试建议 Word） |
| 面试题库 RAG | `interview_knowledge_base.py` | **新增**：ChromaDB `interview_kb` 集合（入库/检索/阈值过滤/按公司/算法题） |
| 面经抓取 | `experience_crawler.py` | **新增**：CSDN/掘金浏览器渲染抓取 + 手动素材保存 |
| 面经加工 | `experience_processor.py` | **新增**：LLM 去噪/归并/结构化加工 |
| 批量入库 | `_ingest_experiences.py` / `_ingest_ai_pm_bank.py` | **新增**：.json/.txt/.md/.docx 批量导入 + 结构化题库解析 |
| 答疑 Agent | `agent.py` | 改为 **RAG 优先答疑**：先检索题库 → 命中整理答案+推荐 5 题 → 未命中走大模型；移除岗位工具，新增 `answer_from_kb` |
| Web 服务 | `web_app.py` | 接口扩展至 12 个（/api/exp\*、/api/upload、/api/download、扩展 optimize 支持目标公司） |
| 前端 | `templates/index.html` | 三 Tab 美化界面（聊天/简历优化/面试题库）+ 检索分页 + 阈值过滤 |
| CLI | `main.py` | `optimize` 支持 `--company`（必填）+ 双 Word 文档输出 |
| LLM 客户端 | `llm_client.py` | mock 补齐全部新模块响应 |
| 启动脚本 | `start_web_offline.py` | **新增**：HF 离线启动（避免模型加载联网卡死） |

## 二、RAG 共享策略

- **同一向量库**：`config.py` 的 `CHROMA_CONFIG["persist_directory"]` 优先指向 langgraph 版 `data/chroma_db`（不存在时回退本地目录），两版共享 `interview_kb` 集合（973 题），避免重复建库
- **模型配置修复**：`.env` 的 `EMBEDDING_MODEL` 由 `bge-large-zh-v1.5`（本地缓存不完整）改为 `bge-small-zh-v1.5`（已缓存），保证 Embedding 可加载
- 检索使用相同实现：`search_questions`（top_k=0 全量 + `max_distance=0.6` 相似度阈值过滤）

## 三、验证结果

| 验证项 | 结果 |
|------|------|
| 全模块导入（16 个） | ✅ |
| CLI 端到端（mock 模式） | ✅ 双 Word 文档生成（定制化简历 + 面试建议） |
| 题库共享 | ✅ `exp/count` = 973（与 langgraph 版一致） |
| 题库检索 | ✅ RAG 检索命中（含参考答案） |
| Web 接口 | ✅ health / exp/count / exp/search / 首页均正常 |
| `--company` 参数 | ✅ 解析正常 |

## 四、与 langgraph 版的差异（有意保留）

| 维度 | langchain 版 | langgraph 版 |
|------|--------------|--------------|
| Agent 构建 | `create_tool_calling_agent` + AgentExecutor + ConversationBufferMemory | `create_react_agent` + MemorySaver |
| 优化编排 | 线性函数调用（analyze → optimize → 面试建议） | LangGraph StateGraph 7 节点（含 LLM 审核重试回路） |
| 质量保障 | 无内置审核 | `review` 节点审核，不合格自动重试（≤3 次） |

两版功能能力对等，编排框架不同；**面试题库 RAG 完全共用**。
