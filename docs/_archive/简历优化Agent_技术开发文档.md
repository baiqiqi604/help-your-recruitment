# 简历优化 Agent — 技术开发文档

> 版本：v1.1  
> 基于 RAG + LangChain 的智能简历优化系统  
> 新增：多平台岗位爬虫 + 岗位知识库 RAG 增强

---

## 目录

1. [项目背景与目标](#1-项目背景与目标)
2. [技术选型及理由](#2-技术选型及理由)
3. [系统架构设计](#3-系统架构设计)
4. [核心模块设计](#4-核心模块设计)
   - 4.1 PDF 解析模块
   - 4.2 岗位爬虫模块
   - 4.3 岗位分析模块
   - 4.4 简历优化模块
   - 4.5 岗位知识库（RAG）
   - 4.6 格式保留与输出模块
5. [数据流转流程](#5-数据流转流程)
6. [接口设计](#6-接口设计)
7. [开发计划与排期](#7-开发计划与排期)
8. [待解决问题与风险](#8-待解决问题与风险)
9. [附录：项目结构](#9-附录项目结构)

---

## 1. 项目背景与目标

### 1.1 背景

求职过程中，不同岗位对简历的侧重点各不相同。一份简历投递多个岗位，往往因为匹配度不够而无法通过初筛。传统做法是手动针对每个岗位修改简历，耗时且容易遗漏关键匹配点。

本项目旨在通过 **RAG（检索增强生成）** + **大模型** 技术，实现自动化简历优化，提升简历与岗位的匹配度，同时保留原始排版格式。

### 1.2 目标

构建一个简历优化 Agent，实现以下核心功能：

| 功能 | 说明 |
|------|------|
| **多平台岗位爬虫** | 每日自动从四大招聘网站爬取岗位信息，获取全文 JD |
| **岗位知识库（RAG）** | 将大厂和高频岗位存入向量数据库，支持检索匹配 |
| PDF 简历解析 | 读取 PDF 格式简历，提取文本内容并保留格式信息 |
| 岗位需求分析 | 解析岗位描述，提取核心技能、关键词、经验要求 |
| 简历内容优化 | 基于岗位需求，用大模型优化简历措辞，突出匹配度 |
| 格式保留输出 | 修改内容后保留原简历排版，输出 Word 和 PDF 格式 |

### 1.3 预期效果

- **输入**：一份 PDF 简历 + 一个目标岗位（或从岗位库中选择）
- **岗位来源**：四大招聘网站每日自动爬取 + 手动导入
- **输出**：优化后的简历（Word/PDF），内容更匹配岗位，格式与原版一致
- **核心原则**：保持真实性，不编造经历，只调整措辞和排序

---

## 2. 技术选型及理由

### 2.1 技术栈

| 技术 | 用途 | 版本 | 选型理由 |
|------|------|------|---------|
| **Python** | 开发语言 | 3.10+ | 生态最完善，NLP/LLM 工具链成熟 |
| **pdf2docx** | PDF → Word 转换 | 最新 | 保留原始排版能力最强，开源免费 |
| **python-docx** | 读写 Word 文件 | 最新 | 可精确控制段落、表格、字体、样式 |
| **LangChain** | RAG 链路编排 | 0.3+ | 社区最流行的 LLM 应用框架，文档丰富 |
| **ChromaDB** | 向量数据库 | 最新 | 轻量，无需单独部署，适合原型开发 |
| **BGE-large-zh-v1.5** | 中文 Embedding 模型 | 最新 | 中文语义理解效果领先，国产开源 |
| **通义千问 / DeepSeek** | 大语言模型 | - | 中文能力强，性价比高，有免费额度 |
| **DrissionPage** | 浏览器自动化（爬虫） | 最新 | 绕过反爬，真实浏览器监听 API，支持自动登录 |
| **Playwright** | 浏览器自动化（爬虫备选） | 最新 | 跨浏览器支持，多平台兼容 |
| **httpx** | HTTP 客户端（爬虫） | 最新 | 支持异步，性能好，用于 Cookie 直调 API |
| **APScheduler** | 定时任务调度 | 最新 | 支持每日定时爬取，持久化任务 |
| **docx2pdf**（可选） | Word → PDF 导出 | 最新 | 最终输出格式需要 |

### 2.2 关键设计决策

#### 决策一：为什么选 pdf2docx 而不是直接解析 PDF 文本？

| 方案 | 优点 | 缺点 |
|------|------|------|
| 直接解析 PDF（PyPDF2/pdfplumber） | 简单，纯文本提取 | **丢失所有格式信息**（字体、字号、表格结构） |
| pdf2docx 转换 | **保留排版**，后续可编辑 | 复杂排版可能有偏差 |

**结论**：选 pdf2docx。格式保留是核心需求，不可妥协。

#### 决策二：为什么用 LangChain 而不是直接调 API？

- 简历优化需要 RAG 能力（按 JD 关键词检索简历对应经历段）
- LangChain 提供标准化的 Prompt 管理、链式调用、向量检索集成
- 后续扩展（多轮对话、批量处理）更方便

#### 决策三：为什么不用 Fine-tuning？

| 方案 | 适用场景 | 成本 |
|------|---------|------|
| Fine-tuning | 需要模型学会特定风格/格式 | 高，需要标注数据 |
| Prompt Engineering | 通用任务，一次性指令 | 低，零成本 |

**结论**：简历优化是通用阅读理解 + 改写任务，Prompt Engineering 完全够用。

---

## 3. 系统架构设计

### 3.1 整体架构

```
┌──────────────────────────────────────────────────────────────┐
│                        数据来源层                              │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │ BOSS直聘 │  │   拉勾   │  │   猎聘   │  │ 智联招聘 │     │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘     │
│       │             │             │             │            │
│       └─────────────┴──────┬──────┴─────────────┘            │
│                            │                                  │
│                      ┌─────▼──────┐                          │
│                      │ 爬虫调度器  │  ← 每日定时触发            │
│                      │ (APScheduler)│                         │
│                      └─────┬──────┘                          │
│                            │                                  │
│                      ┌─────▼──────┐                          │
│                      │ 原始 JD 数据 │  (JSON 文件)              │
│                      └─────┬──────┘                          │
└────────────────────────────┼─────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────┐
│                      处理层                                    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │             岗位清洗与入库 Pipeline                      │    │
│  │                                                      │    │
│  │  原始 JD  → 去重 → 大厂/高频标记 → 向量化 → 存入 ChromaDB │    │
│  │                           │                          │    │
│  │                           ▼                          │    │
│  │                    岗位知识库（RAG）                    │    │
│  │              (按公司/技能/关键词检索)                   │    │
│  └──────────────────────────────────────────────────────┘    │
│                              │                                │
│  ┌───────────────────────────┴──────────────────────────┐    │
│  │                   简历优化主流程                        │    │
│  │                                                      │    │
│  │  PDF 简历 ──▶ pdf2docx ──▶ 简历文本                    │    │
│  │  岗位选择 ──▶ 从知识库检索 / 手动输入 ──▶ 岗位分析       │    │
│  │                        │                              │    │
│  │                  ┌─────▼──────┐                       │    │
│  │                  │ 大模型优化  │                       │    │
│  │                  └─────┬──────┘                       │    │
│  │                        │                              │    │
│  │                  ┌─────▼──────┐                       │    │
│  │                  │ 写回 Word   │                       │    │
│  │                  │ + 导出 PDF  │                       │    │
│  │                  └────────────┘                       │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 模块依赖关系

```
爬虫模块 ──▶ 岗位知识库（ChromaDB） ◀── 手动导入
                   │
                   ▼
             岗位分析模块 ◀── 用户选择岗位
                   │
                   ▼
PDF解析模块 ──▶ 简历优化模块
                   │
                   ▼
             格式保留与输出模块
```

---

## 4. 核心模块设计

### 4.1 PDF 解析模块

**文件**：`resume_reader.py`

**职责**：
1. 将 PDF 简历转换为 Word 文件（保留格式）
2. 从 Word 中提取段落文本和表格文本
3. 记录每个段落的样式信息（字体、字号、加粗等）

**核心函数**：

```python
def pdf_to_docx(pdf_path: str, docx_path: str) -> None
    """PDF 转 Word，保留原始排版"""

def read_resume(docx_path: str) -> dict
    """读取 Word 简历内容，返回：
    {
        "paragraphs": [{"text": str, "style": str, "font": {...}}, ...],
        "tables": [[["cell1", "cell2"], ...], ...],
        "full_text": str  # 纯文本拼接
    }
    """
```

**关键逻辑**：
- 段落按顺序读取，保留索引用于后续替换
- 表格按行/列读取，保留单元格结构
- `full_text` 用于传给大模型进行内容优化

**边界情况**：
- 空 PDF → 返回错误提示
- 扫描件 PDF（图片格式，无可提取文本）→ 需要 OCR，暂时不支持
- 加密 PDF → 需要密码，暂时不支持

### 4.2 岗位爬虫模块（AI 实现）

**文件**：`jd_crawler.py`（由 AI 自动生成，人工仅做配置和验证）

**说明**：该模块由 AI 根据本设计文档自动生成代码，人工负责配置爬虫参数、验证爬取结果、处理反爬异常。不涉及手写爬虫逻辑。

**职责**：
1. 每日定时从四大招聘网站爬取岗位信息
2. 获取岗位全文 JD（含公司、薪资、技能要求、职责描述等）
3. 数据去重、清洗、结构化存储
4. 标记大厂岗位和高频岗位

**支持平台**：

| 平台 | 爬取方案 | 原理 | 难度 |
|------|---------|------|------|
| **BOSS 直聘** | DrissionPage 浏览器监听 | 打开真实 Chrome，监听 API 返回的 JSON | ⭐⭐ |
| **拉勾** | requests + Cookie | 模拟浏览器请求，解析 HTML/JSON | ⭐⭐ |
| **猎聘** | requests + Cookie | 模拟浏览器请求，解析 HTML | ⭐⭐ |
| **智联招聘** | requests + Cookie | 模拟浏览器请求，解析 HTML | ⭐⭐ |

**爬虫策略**：

```python
# 四级降级策略（参考开源项目 JobOS）
def crawl_jobs(keyword: str, city: str):
    """
    1. DrissionPage 浏览器监听（最稳定，推荐）
    2. httpx + Cookie 直调 API（最快）
    3. requests + HTML 解析（兜底）
    4. 本地策展数据（离线兜底，永远能用）
    """
```

**核心函数**：

```python
def crawl_jobs(keyword: str, city: str, platforms: list = ["boss", "lagou", "liepin", "zhilian"]) -> list[dict]
    """爬取指定关键词和城市的岗位信息，返回结构化列表"""

def crawl_job_detail(job_url: str, platform: str) -> dict
    """爬取单个岗位详情页，获取完整 JD"""

def deduplicate_jobs(jobs: list[dict]) -> list[dict]
    """按岗位 ID 去重，同平台去重 + 跨平台去重"""

def mark_premium_jobs(jobs: list[dict]) -> list[dict]
    """标记大厂（BAT/字节/华为等）和高频匹配岗位"""
```

**数据字段定义**：

```python
{
    "job_id": "唯一标识（平台+原始ID）",
    "platform": "boss / lagou / liepin / zhilian",
    "title": "岗位名称",
    "company": "公司名称",
    "company_size": "公司规模",
    "salary": "薪资范围",
    "city": "工作城市",
    "experience": "经验要求",
    "education": "学历要求",
    "skills": ["技能1", "技能2"],
    "jd_text": "职位描述全文（核心字段）",
    "responsibilities": "岗位职责",
    "requirements": "任职要求",
    "is_big_tech": True/False,  # 是否大厂
    "match_count": 0,            # 被匹配次数
    "crawled_at": "2026-07-20",
    "url": "原始链接"
}
```

**定时调度**：

```python
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()
scheduler.add_job(
    func=daily_crawl_task,
    trigger="cron",
    hour=2,        # 凌晨 2 点执行
    minute=0,
    id="daily_jd_crawl"
)
scheduler.start()

def daily_crawl_task():
    """每日爬取任务：按预设关键词列表逐个爬取"""
    keywords = ["Python", "Java", "前端", "产品经理", "数据分析", ...]
    for keyword in keywords:
        crawl_jobs(keyword, "全国")
```

**边界情况**：
- 反爬拦截（滑块/验证码）→ DrissionPage 弹出浏览器，手动验证后自动恢复
- 单平台宕机 → 不影响其他三个平台
- 当日已爬取过 → 增量更新，按 job_id 去重

### 4.3 岗位分析模块

**文件**：`jd_analyzer.py`

**职责**：
1. 接收岗位描述文本
2. 调用大模型提取结构化信息
3. 输出技能清单、关键词、经验要求

**核心函数**：

```python
def analyze_jd(jd_text: str) -> dict
    """分析岗位描述，返回：
    {
        "required_skills": ["Python", "Django", ...],
        "preferred_skills": ["Docker", "Redis", ...],
        "responsibilities": ["负责后端开发", ...],
        "experience_years": "3-5年",
        "keywords": ["Python后端", "微服务", ...]
    }
    """
```

**Prompt 设计**：

```
你是一位招聘分析师。请分析以下岗位描述，提取关键信息。

岗位描述：
{jd_text}

请以 JSON 格式返回：核心技能、加分技能、岗位职责、经验要求、关键词。
只返回 JSON，不要其他内容。
```

**边界情况**：
- 岗位描述过长 → 截断到模型最大上下文长度
- 岗位描述语言非中文 → 保留原文，提取时按原文语言输出

### 4.4 简历优化模块（核心）

**文件**：`content_optimizer.py`

**职责**：
1. 接收简历文本和岗位分析结果
2. 按照 SKILL.md 定义的定制简历原则，用大模型优化简历内容
3. 突出与岗位匹配的经历，调整措辞，不虚构经历
4. 输出 ATS 友好的简历格式

**核心函数**：

```python
def optimize_resume_content(resume_text: str, jd_analysis: dict) -> str
    """根据岗位分析结果，优化简历内容，返回优化后的全文"""

def build_matching_table(resume_text: str, jd_analysis: dict) -> list[dict]
    """建立简历-JD匹配关系表：JD要求 → 用户证据 → 匹配强度 → 推荐表达"""
```

**定制简历原则**（来源：SKILL.md）：

| # | 原则 | 说明 |
|---|------|------|
| 1 | **真实性** | 只基于用户真实经历，不虚构工作经历、项目、学历、证书、数据、工具或结果 |
| 2 | **经历前置** | 将最匹配目标岗位的经历前置 |
| 3 | **摘要定制** | 个人摘要直接回应目标岗位最核心的能力要求 |
| 4 | **技能排序** | 技能清单按 JD 重要性重排，但不得添加用户不具备的技能 |
| 5 | **STAR 表达** | 工作经历使用"行动 + 场景/规模 + 方法 + 结果"的表达 |
| 6 | **项目突出** | 项目经历突出与目标岗位相关的业务、技术、协作、数据和结果 |
| 7 | **缺失标记** | 对缺失或不确定内容使用待确认标记，不要自行补全 |
| 8 | **语言克制** | 语言专业、具体、克制，避免夸大 |
| 9 | **ATS 友好** | 格式 ATS 友好，使用清晰标题和标准结构 |

**建议简历结构**：

```text
姓名 / 联系方式
求职目标
个人摘要
核心技能
工作经历
项目经历
教育背景
证书 / 奖项 / 其他
```

**Prompt 设计**：

```
你是一位专业的简历优化顾问，遵循以下定制简历原则：

1. 只基于用户真实经历，不虚构工作经历、项目、学历、证书、数据、工具或结果
2. 将最匹配目标岗位的经历前置
3. 个人摘要直接回应目标岗位最核心的能力要求
4. 技能清单按 JD 重要性重排，但不得添加用户不具备的技能
5. 工作经历使用"行动 + 场景/规模 + 方法 + 结果"的表达
6. 项目经历突出与目标岗位相关的业务、技术、协作、数据和结果
7. 对缺失或不确定内容使用【待确认】标记，不要自行补全
8. 语言专业、具体、克制，避免夸大
9. 格式 ATS 友好，使用清晰标题和标准结构

【简历-JD匹配分析】
- 核心技能要求：{', '.join(jd_analysis['required_skills'])}
- 加分技能：{', '.join(jd_analysis['preferred_skills'])}
- 岗位职责：{', '.join(jd_analysis['responsibilities'])}
- 经验要求：{jd_analysis['experience_years']}

【原始简历】
{resume_text}

请输出优化后的简历全文，按以下结构：
姓名 / 联系方式
求职目标
个人摘要
核心技能
工作经历
项目经历
教育背景
证书 / 奖项 / 其他
```

**RAG 增强**：

```
1. 将简历按项目经历/技能/教育切块，存入 ChromaDB
2. 用 JD 关键词检索最相关的经历块
3. 只优化匹配的经历块，不动的保留原文
4. 拼回完整简历
```

### 4.5 岗位知识库（RAG）

**文件**：`jd_knowledge_base.py`

**职责**：
1. 管理爬取到的岗位数据，存入向量数据库
2. 标记大厂岗位和高频匹配岗位，优先检索
3. 支持按关键词、技能、公司名检索岗位
4. 每日增量更新，避免重复

**核心函数**：

```python
def build_jd_knowledge_base():
    """从爬取的 JSON 数据构建岗位知识库"""
    # 1. 读取爬取的岗位数据
    # 2. 去重
    # 3. 标记大厂（BAT/字节/华为/美团/京东等）
    # 4. 向量化存入 ChromaDB（按 JD 全文 + 技能标签）
    # 5. 建立关键词索引（按岗位名称、公司名、技能）

def search_jds(query: str, top_k: int = 10, filter_big_tech: bool = False) -> list[dict]
    """检索岗位知识库，返回最匹配的岗位列表"""

def get_premium_jobs(limit: int = 50) -> list[dict]
    """获取大厂和高频匹配岗位"""

def increment_update(jobs: list[dict]):
    """增量更新知识库，按 job_id 去重"""
```

**知识库结构**：

ChromaDB 中创建两个 Collection：

| Collection | 存储内容 | 检索用途 |
|------------|---------|---------|
| `jd_fulltext` | 岗位全文 JD（去重后） | 按语义检索匹配岗位 |
| `jd_premium` | 大厂 + 高频岗位（子集） | 优先推荐给用户 |

**大厂名单**：

```python
BIG_TECH_COMPANIES = [
    "阿里巴巴", "腾讯", "百度", "字节跳动", "华为",
    "美团", "京东", "小米", "网易", "拼多多",
    "快手", "滴滴", "小红书", "B站", "蚂蚁集团",
    # 更多可按需扩展
]
```

**高频岗位标记逻辑**：

```python
def mark_premium_jobs(jobs: list[dict]) -> list[dict]:
    for job in jobs:
        # 大厂标记
        if any(company in job["company"] for company in BIG_TECH_COMPANIES):
            job["is_big_tech"] = True
        
        # 高频标记（被用户匹配次数多的岗位）
        if job.get("match_count", 0) >= 5:
            job["is_high_frequency"] = True
    
    return jobs
```

**用户选择岗位的流程**：

```
用户打开系统
  → 展示大厂岗位推荐（jd_premium）
  → 用户可搜索关键词/技能
  → 从 jd_fulltext 检索最匹配的岗位
  → 选择目标岗位
  → 进入简历优化流程
```

**边界情况**：
- 知识库为空（首次运行）→ 提示用户手动导入或等待爬虫完成
- 检索不到匹配岗位 → 允许用户手动粘贴 JD 文本
- 爬虫数据未更新 → 显示上次更新时间，提示用户

### 4.6 格式保留与输出模块

**文件**：`resume_writer.py`

**职责**：
1. 将优化后的文本写回 Word 文件（保留原格式）
2. 可选：将 Word 导出为 PDF

**核心函数**：

```python
def write_optimized_resume(original_docx: str, optimized_text: str, output_docx: str) -> None
    """把优化后的内容写回 Word，保留原有格式"""

def docx_to_pdf(docx_path: str, pdf_path: str) -> None
    """Word 转 PDF（可选）"""
```

**替换策略**：

| 策略 | 适用场景 | 优点 | 缺点 |
|------|---------|------|------|
| 按行顺序替换 | 段落结构简单 | 实现简单 | 行数不一致时错位 |
| 按内容匹配替换 | 有唯一标识的段落 | 精准匹配 | 复杂内容匹配不到 |
| 保留首个 run 格式 | 通用 | 保留字体/字号 | 多 run 段落需处理 |

**推荐策略**：按行顺序替换 + 保留首 run 格式，这是最稳妥的方案。

**边界情况**：
- 优化后文本行数与原简历不一致 → 按原简历行数截断或补充空行
- 表格内格式变化 → 单独处理每个单元格

---

## 5. 数据流转流程

### 5.1 完整流程

```
岗位数据采集（每日自动）
  │
  ├─ 四大招聘网站定时爬取（凌晨 2:00）
  │  ├─ BOSS直聘 → DrissionPage 浏览器监听
  │  ├─ 拉勾 → requests + Cookie
  │  ├─ 猎聘 → requests + Cookie
  │  └─ 智联招聘 → requests + Cookie
  │
  ▼
岗位数据清洗与入库
  │
  ├─ 去重 → 按 job_id 去重，跨平台合并
  ├─ 标记 → 大厂标记 + 高频匹配计数
  ├─ 向量化 → BGE 模型转为向量
  └─ 存入 → ChromaDB（jd_fulltext + jd_premium）
  │
  ▼
用户使用
  │
  ├─ 选择岗位来源：
  │  ├─ 从知识库浏览（大厂推荐 / 搜索关键词）
  │  └─ 手动粘贴 JD 文本
  │
  ▼
简历优化（与之前流程一致）
  │
  ├─ Step 1: PDF 转 Word
  ├─ Step 2: 读取简历内容
  ├─ Step 3: 分析岗位需求（从知识库中提取或手动输入）
  ├─ Step 4: 大模型优化简历内容
  ├─ Step 5: 写回 Word（保留格式）
  └─ Step 6: 导出 PDF（可选）
  │
  ▼
 清理临时文件
```

### 5.2 数据格式定义

**输入格式**：

| 数据 | 格式 | 来源 |
|------|------|------|
| PDF 简历 | `.pdf` 文件 | 用户上传/选择 |
| 岗位描述 | 纯文本（`.txt` 或粘贴） | 用户输入或从招聘网站复制 |
| 爬虫关键词 | 文本（关键词 + 城市） | 配置文件或用户输入 |

**中间格式**：

| 数据 | 格式 | 说明 |
|------|------|------|
| Word 简历 | `.docx` 文件 | PDF 转换后的临时文件 |
| 简历数据 | `dict`（段落+表格+全文） | 从 Word 提取的结构化数据 |
| 原始爬虫数据 | `list[dict]`（JSON 文件） | 四大平台爬取的原始岗位数据 |
| 清洗后岗位数据 | `list[dict]`（结构化） | 去重、标记后的岗位数据 |
| 岗位向量 | ChromaDB Collection | 岗位全文 JD 的向量化存储 |
| 岗位分析 | `dict`（技能+关键词+要求） | 大模型输出的结构化 JSON |

**输出格式**：

| 数据 | 格式 | 说明 |
|------|------|------|
| 优化后简历 Word | `.docx` 文件 | 保留原格式 |
| 优化后简历 PDF（可选） | `.pdf` 文件 | 从 Word 导出 |
| 爬虫结果 | `.json` 文件 | 每日爬取的原始数据存档 |

---

## 6. 接口设计

### 6.1 核心函数接口

```python
# ──── 主入口 ────

def optimize_resume(pdf_path: str, jd_source: dict, output_dir: str = "./output") -> dict
    """
    完整流程：PDF → 解析 → 分析JD → 优化 → 输出
    jd_source 可以是：
      - {"type": "manual", "text": "JD文本"}
      - {"type": "kb", "job_id": "xxx"}  # 从知识库选择
    返回：
    {
        "success": True/False,
        "output_docx": "路径",
        "output_pdf": "路径",
        "message": "处理结果说明"
    }
    """

# ──── PDF 解析模块 ────

def pdf_to_docx(pdf_path: str, docx_path: str) -> None
    """PDF 转 Word"""

def read_resume(docx_path: str) -> dict
    """读取简历内容"""

# ──── 岗位爬虫模块 ────

def crawl_jobs(keyword: str, city: str, platforms: list = None) -> list[dict]
    """爬取岗位信息，platforms 默认全平台"""

def crawl_job_detail(job_url: str, platform: str) -> dict
    """爬取单个岗位详情"""

def daily_crawl_task() -> dict
    """每日定时爬取任务，返回爬取统计"""

# ──── 岗位知识库模块 ────

def search_jds(query: str, top_k: int = 10, filter_big_tech: bool = False) -> list[dict]
    """检索岗位知识库"""

def get_premium_jobs(limit: int = 50) -> list[dict]
    """获取大厂/高频岗位"""

def build_jd_knowledge_base() -> None
    """构建/重建岗位知识库"""

# ──── 岗位分析模块 ────

def analyze_jd(jd_text: str) -> dict
    """分析岗位需求"""

# ──── 简历优化模块 ────

def optimize_resume_content(resume_text: str, jd_analysis: dict) -> str
    """优化简历内容"""

# ──── 格式输出模块 ────

def write_optimized_resume(original_docx: str, optimized_text: str, output_docx: str) -> None
    """写回 Word 并保留格式"""

def docx_to_pdf(docx_path: str, pdf_path: str) -> None
    """Word 转 PDF"""
```

### 6.2 调用示例

```python
from resume_optimizer import optimize_resume

result = optimize_resume(
    pdf_path="./input/我的简历.pdf",
    jd_text="""岗位：Python 后端开发工程师
要求：3年以上 Python 开发经验，熟悉 Django/Flask 框架，
熟悉 MySQL、Redis，了解微服务架构，有 Docker 使用经验优先。"""
)

print(result["message"])  # "优化完成！输出文件：./output/我的简历_优化版.docx"
```

### 6.3 Web 接口（后续扩展）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/optimize` | 上传简历 PDF + 岗位描述，返回优化结果 |
| POST | `/api/upload` | 上传简历文件 |
| GET | `/api/download/{filename}` | 下载优化后的文件 |

---

## 7. 开发计划与排期

### 7.1 阶段划分

| 阶段 | 内容 | 预估时间 |
|------|------|---------|
| **Phase 1：简历优化核心流程** | PDF 解析 + 岗位分析 + 内容优化 + 格式输出（手动导入 JD） | 4 天 |
| **Phase 2：岗位知识库** | ChromaDB 入库 + RAG 检索 + 大厂标记 + 手动导入接口 | 2 天 |
| **Phase 3：爬虫开发（AI 实现）** | 四大平台爬虫 + 数据清洗 + 定时调度，由 AI 自动生成代码 | 2 天（配置+验证） |
| **Phase 4：界面与完善** | 命令行交互 + 错误处理 + 文档 | 2 天 |

### 7.2 详细任务

**Phase 1（4 天）**：

| 天 | 任务 | 产出 |
|----|------|------|
| Day 1 | 搭环境 + PDF 转 Word + 简历内容读取 | `resume_reader.py` |
| Day 2 | 岗位分析 + 简历内容优化（SKILL.md 原则） | `jd_analyzer.py` + `content_optimizer.py` |
| Day 3 | 格式保留输出（Word + PDF） | `resume_writer.py` |
| Day 4 | 主程序串联 + 手动导入 JD 验证 | `main.py` |

**Phase 2（2 天）**：

| 天 | 任务 | 产出 |
|----|------|------|
| Day 5 | 岗位数据向量化 + 存入 ChromaDB | `jd_knowledge_base.py` |
| Day 6 | 检索接口 + 大厂优先推荐 + 关键词搜索 | `search_jds()` + `get_premium_jobs()` |

**Phase 3（2 天）—— AI 实现**：

| 天 | 任务 | 产出 |
|----|------|------|
| Day 7 | 向 AI 提供设计文档，由 AI 生成爬虫代码（四大平台），人工验证爬取结果 | `jd_crawler.py`（AI 生成） |
| Day 8 | 配置 APScheduler 定时调度 + 处理反爬异常 + 验证每日爬取稳定性 | `scheduler.py` + 调优 |

**Phase 4（2 天）**：

| 天 | 任务 | 产出 |
|----|------|------|
| Day 9 | 命令行交互 + 岗位选择流程 | CLI 交互 |
| Day 10 | 错误处理 + 日志 + README | 完善文档 |

---

## 8. 待解决问题与风险

### 8.1 已知风险

| 风险 | 等级 | 说明 | 应对方案 |
|------|------|------|---------|
| 招聘网站反爬升级 | 🔴 高 | 网站可能更新反爬策略，导致爬虫失效 | 多级降级策略（浏览器→API→HTML→策展数据）；失效时自动告警 |
| 爬虫被封 IP | 🔴 高 | 频繁请求可能被封 | 控制请求频率；使用代理池；浏览器模拟真人操作 |
| PDF 转 Word 格式错乱 | ⚠️ 中 | pdf2docx 对复杂排版（多栏、表格嵌套）支持有限 | 先测试目标简历格式；如格式太乱则改用方案二（输出修改建议） |
| 大模型改写改变原意 | ⚠️ 中 | 模型可能过度改写，导致信息失真 | Prompt 中强调"保持真实性"；输出前做事实校验 |
| 段落行数不一致导致错位 | ⚠️ 中 | 优化后文本行数可能与原简历不一致 | 使用按内容匹配替换策略兜底 |
| 扫描件 PDF 无法提取文本 | ⚠️ 低 | 纯图片 PDF 没有可提取的文本层 | 提示用户上传可编辑的 PDF；OCR 暂不纳入 v1 |
| 跨平台岗位去重冲突 | ⚠️ 低 | 同一岗位在不同平台被重复爬取 | 按岗位名称+公司名+地点组合去重 |

### 8.2 技术债

- **OCR 支持**：当前不支持扫描件 PDF，后续可接入 PaddleOCR 或 Tesseract
- **批量处理**：当前一次只处理一份简历，后续可支持批量投递场景
- **效果评估**：当前没有自动评估机制，后续可加入 AI 模拟 HR 打分
- **多语言**：当前只支持中文简历，后续可扩展英文简历
- **爬虫监控**：当前无爬虫状态监控面板，后续可加入运行状态看板
- **代理池**：当前未使用代理池，高频爬取时可能被封 IP
- **验证码自动识别**：当前遇到验证码需要手动处理，后续可接入打码平台

### 8.3 未定事项

- 大模型选型：通义千问 vs DeepSeek vs GPT-4o，需根据实际效果和成本决定
- 是否需要 Gradio 界面：v1 以命令行为主，界面看需求决定
- 输出格式优先级：Word 优先保证，PDF 导出作为可选功能

---

## 9. 附录：项目结构

```
resume_optimizer/
├── main.py                  # 主程序入口
├── resume_reader.py         # PDF 解析模块
├── jd_crawler.py            # 岗位爬虫模块（四大平台）
├── jd_knowledge_base.py     # 岗位知识库（RAG + ChromaDB）
├── jd_analyzer.py           # 岗位分析模块
├── content_optimizer.py     # 简历优化模块
├── resume_writer.py         # 格式保留与输出模块
├── scheduler.py             # 定时爬取调度器
├── config.py                # 配置（API Key、模型名、爬虫参数等）
├── requirements.txt         # 依赖
├── data/
│   ├── raw/                 # 爬虫原始 JSON 数据
│   ├── chroma_db/           # ChromaDB 持久化目录
│   └── crawled_jobs/        # 每日爬取存档
├── input/                   # 放原始简历 PDF
├── output/                  # 输出优化后的简历
└── README.md                # 项目说明
```

### requirements.txt

```
pdf2docx>=1.0.0
python-docx>=1.1.0
langchain>=0.3.0
langchain-community>=0.3.0
chromadb>=0.5.0
sentence-transformers>=3.0.0
dashscope>=1.0.0
docx2pdf>=0.1.0
DrissionPage>=4.0.0          # 浏览器自动化爬虫
playwright>=1.40.0            # 浏览器自动化（备选）
httpx>=0.25.0                 # HTTP 客户端（Cookie 直调 API）
APScheduler>=3.10.0           # 定时任务调度
beautifulsoup4>=4.12.0        # HTML 解析（兜底方案）
lxml>=5.0.0                   # HTML 解析加速
```

---

> 文档版本：v1.1  
> 最后更新：2026-07-20  
> 说明：本文档为技术开发文档，每次修改前需确认。