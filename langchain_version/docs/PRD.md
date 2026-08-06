# 简历优化 Agent 产品需求文档（PRD）

| 项目 | 说明 |
| --- | --- |
| 版本 | v1.0 |
| 模块 | langchain_version（LangChain 版） |
| 文档状态 | 已评审 |

---

## 1. 背景

求职者在投递不同岗位时，往往需要针对每个岗位微调简历，突出与岗位最相关的能力与经历。传统做法是手动修改，效率低且容易遗漏关键匹配点；同时，招聘平台岗位分散、信息碎片化，难以集中分析目标岗位的核心要求。

本项目构建一个「简历优化 Agent」：自动采集与检索岗位、用大模型解析 JD 核心要求、按定制简历原则优化简历，并输出「简历-JD 匹配关系表」，帮助求职者快速产出高匹配度的定制简历。

## 2. 目标用户

- **应届毕业生 / 社招求职者**：需要批量定制简历投递不同岗位
- **简历服务从业者**：作为工具提升简历优化的效率与专业性
- **个人开发者 / 学生**：学习 LangChain Agent、RAG、向量检索与 Web 应用集成

## 3. 功能需求

### 3.1 岗位数据采集（爬虫）

- FR-1 支持多平台（boss / lagou / liepin / zhilian）按关键词与城市爬取岗位
- FR-2 单个平台失败不阻塞整体流程，返回空结果并记录 warning
- FR-3 岗位数据按日期 JSON 存档（`data/crawled_jobs/`）
- FR-4 支持定时自动采集（每天指定时刻）

### 3.2 岗位知识库（RAG）

- FR-5 岗位写入 ChromaDB，按 id 去重
- FR-6 公司命中大厂名单或同一岗位高频出现时标记为「优质岗位（premium）」
- FR-7 支持语义检索岗位（top_k）与按 id 查询岗位详情

### 3.3 简历处理

- FR-8 支持读取 `.pdf` / `.docx` / `.txt` 简历（PDF 经 pdf2docx 转换）
- FR-9 优化结果按标准小节（姓名/求职目标/个人摘要/核心技能/工作经历/项目经历/教育背景/证书）写入 `.docx`
- FR-10 支持 docx → PDF 转换（依赖本机 Word，失败降级不中断）

### 3.4 JD 分析与简历优化（LLM）

- FR-11 解析 JD，输出：核心技能、加分技能、岗位职责、经验要求、关键词
- FR-12 基于「定制简历九大原则」优化简历：不虚构经历、匹配项前置、技能按 JD 重排、行动化表达、缺失内容标【待确认】
- FR-13 生成「简历-JD 匹配关系表」（jd_requirement / user_evidence / match_strength / suggested_expression）

### 3.5 Agent 智能对话

- FR-14 基于 LangChain Tool-calling Agent，提供 4 个工具：岗位检索、优质岗位、JD 分析、简历优化
- FR-15 支持多轮会话记忆，按 session_id 隔离

### 3.6 人机界面

- FR-16 Web 单页：两个页签（智能对话 / 简历优化），简历优化页展示优化结果与匹配关系表
- FR-17 命令行：`web`（启动服务）、`chat`（对话）、`optimize`（一键优化输出 docx/pdf/匹配表）

## 4. 非功能需求

| 类别 | 要求 |
| --- | --- |
| 可用性 | 单平台爬虫/单次 LLM 调用失败不导致进程崩溃 |
| 性能 | 语义检索 top_k ≤ 50；对话响应在 LLM 超时（120s）内返回 |
| 可靠性 | 数据按日期落盘；知识库幂等可重复写入；临时文件自动清理 |
| 安全性 | API Key 仅从 .env / 环境变量读取，不写入代码与日志 |
| 可维护性 | 中文注释 + 类型注解 + logging；模块同目录直接 import |
| 合规 | 爬虫遵守目标站点 robots 协议与相关法律法规 |
| 兼容性 | LLM 走 OpenAI 兼容接口，可切换 4 家 provider |

## 5. 验收标准

1. `python main.py web` 可启动服务，访问 `/` 返回前端页面；两个页签可用
2. `POST /api/chat` 返回 `{reply}`，同一 session_id 多轮可引用上文
3. `POST /api/optimize`（jd_text 与 job_id 两种方式）返回 `{optimized, matching_table, jd_analysis}`；JD 分析字段完整；匹配表包含 4 个字段
4. `GET /api/jobs/search?q=Python&top_k=5` 返回岗位列表；`GET /api/jobs/premium` 返回优质岗位
5. `read_resume` 对 `.pdf` / `.docx` / `.txt` 均可提取文本
6. `write_optimized_resume` 生成的 docx 可打开，包含全部标准小节
7. `add_jobs` 重复调用同 id 岗位不重复入库；大厂岗位 premium=True
8. `crawl_jobs` 在目标站点不可达时返回空列表，不抛异常
9. `main.py optimize` 成功输出 `_optimized.docx` / `_optimized.pdf` / `_matching_table.json`
10. 全部新建 `.py` 通过 `python -m py_compile`
