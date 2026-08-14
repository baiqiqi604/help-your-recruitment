# Changelog

> 项目 git 提交日志：按时间倒序记录每次提交所做的更改；**每次 git 提交后请同步更新本文件**
> （规则见文末「记录未来的提交」）。
>
> 格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)；
> 类型标签（feat / fix / perf / refactor / docs / chore / test）与 git commit 前缀一致。

## [Unreleased]

（暂无新变更。未来提交按文末「记录未来的提交」规则在此记录。）

---

## 2026-08-14 — RAG 检索增强（标题索引 + Rerank 精排）

### 新增
- **feat (6c0fbc2)** `langgraph_version` 增强 RAG 检索（标题索引 + Rerank）：
  - 新增标题/短文本索引集合 `jd_title` / `interview_kb_title`：只存「题目+考察点」/「岗位名+公司+技能」短文本，短查询的向量距离显著降低，召回提升（"LRU" 等简写不再只靠关键词兜底）；
  - 新增 `reranker.py`：`bge-reranker-v2-m3` 跨编码器精排——粗召回 `top_k×5`（上限 50）后按 (query, 全文) 逐对打分取 top_k；懒加载 + 优雅降级（模型不可用时按向量原序返回）；numpy 分数转原生 float，修复 pydantic/JSON 序列化 500；
  - `config.py` 新增 `RERANK_CONFIG`（enabled / model_name / device / candidate_multiplier / max_candidates）与 `jd_title` 集合；本地模型自动探测（`models/bge-reranker-v2-m3` 存在即用，否则回退 HuggingFace id）；
  - 检索流水线：标题索引 → 相似度阈值过滤（≤0.6）→ 关键词 `$contains` 兜底 → 标题索引为空时回退全文集合（兼容旧库）→ Rerank 精排；
  - `tests/conftest.py` 以 `RERANK_ENABLED=0` 保证测试确定性；`.gitignore` 排除 `models/` 与 `web_verify.*`。
- **feat (07296fc)** `langchain_version` 同步 RAG 检索增强：与主力版一致的检索层（reranker / config / 两个 knowledge_base），两版共享同一 ChromaDB，标题索引与 Rerank 集合共用。

### 文档
- **docs (9a8b1aa)** 重写三份 README：根 README 新增「RAG 检索策略」章节、Rerank 本地模型下载方式（hf-mirror）、`RERANK_*` 配置说明与项目结构（reranker / 双集合 / models/）；两版 README 同步检索与配置说明。

---

## 2026-08-13 — 测试体系与安全加固

### 修复
- **fix (0d9c181)** 安全加固、Mock LLM 重构、新增 pytest 套件（36 文件 +1357/−531）：统一 `MOCK_LLM` 测试模式、以轻量桩替代重型依赖（chromadb / sentence-transformers）、补 Web API / LLM JSON 解析等用例。

### 测试
- **test (bba34a4)** 扩展测试套件至 **114 个用例**并修复 CI 覆盖率（23 文件 +1222/−111）：覆盖图流程 / Web API / 知识库真实检索（确定性 embedding）/ 简历 IO 等。

### 重构
- **refactor (6f8964b)** LangChain 0.3 → 1.3 迁移（langchain 1.x + langgraph 1.x，`create_agent` 替代 `create_react_agent`），并新增迁移评估报告（`docs/LangChain_1_3_15迁移评估报告.md`，6 文件 +193/−72）。

---

## 2026-08-11 — 工具脚本与版本同步

### 新增
- **chore (d865a9c)** 新增面经导入脚本（`_ingest_*.py`）、桌面 exe 打包（PyInstaller `desktop/`）、启动脚本与文档（11 文件 +1152）。

### 变更
- **feat (bc467b2)** `langchain` 版同步 langgraph 版的前端与后端改动（11 文件 +465/−83）。

### 性能
- **perf (322fa1e)** `langgraph` 版提升 RAG 命中率与 DeepSeek 回答速度（10 文件 +406/−67）。

---

## 2026-08-09 — 面试题库体系与 langchain 版同步

### 新增
- **feat (3c54472)** 新增面试/笔试经验知识库（RAG）体系：`interview_knowledge_base.py` 检索层 + 加工/抓取链路（experience_processor / experience_crawler）+ 设计文档（7 文件 +1424）。
- **feat (5d20f50)** 定制化简历流程增强：公司分析（company_researcher）、面试建议（interview_advisor）、岗位拆解分级（jd_analyzer）、四级匹配关系表（9 文件 +1212）。
- **feat (29e5b79)** Web 前端美化与聊天 RAG 优先答疑改造（3 文件 +784/−135）。
- **feat (d26cd3c)** `langchain` 版同步核心模块：岗位拆解 / 四级匹配 / 公司分析 / 面试建议（7 文件 +1099/−186）。
- **feat (63e6c31)** `langchain` 版接入面试题库 RAG，与 langgraph 版共享向量库（8 文件 +1613/−249）。
- **feat (567fdac)** `langchain` 版 Web/CLI 升级与总结文档（5 文件 +1162/−419）。

### 文档
- **docs (38a005d)** 重写 GitHub 版 README（定制化简历大师，1 文件 +138/−51）。

### 重构
- **refactor (830912e)** 移除岗位爬虫体系，岗位库降级为可选（优雅降级：缺依赖返回空而非 500，9 文件 +66/−1290）。

---

## 2026-08-08 — PDF 导出与仓库治理

### 新增
- **feat (91bc043)** 补齐 PDF 导出（docx2pdf）、同步知识库兼容、新增智联浏览器爬虫（21 文件 +1199/−117）。

### 文档
- **docs (f74e300)** 记录 PRD 待确认项决策，增强 PDF 降级提示（2 文件 +10/−6）。

### 变更
- **chore (dacd5bf)** 移除 `output/` 运行产物并补充 `.gitignore` 规则（5 文件 +4/−114）。

---

## 2026-07-28 ~ 08-06 — 初始搭建与框架比较

- **1a05aa2** 开发文档（3 文件 +1102）
- **24f46e8** agent 框架搭建（25 文件 +1048/−164）
- **c0c320b** 代码搭建（19 文件 +1404/−184）
- **a5482a8** 两版框架（langchain / langgraph）demo 比较（10 文件）
- **a027ada** 两版代码 demo 落地（49 文件 +7728）

---

## 记录未来的提交

每次 git 提交时，请同步执行以下步骤（CHANGELOG.md 与代码一起提交）：

1. 若本次提交对使用者/开发者可见（功能、修复、性能、配置、文档、测试），在顶部 `## [Unreleased]` 区块的对应类型分组下追加一行：
   `**<type> (<短哈希>) <提交主题>**：<一句话影响说明>`（可附 1–3 条要点）；
2. 类型标签与 commit 前缀一致：`feat`（新功能）/ `fix`（修复）/ `perf`（性能）/ `refactor`（重构）/ `docs`（文档）/ `chore`（杂项）/ `test`（测试）；
3. 纯内部改动（如格式化、重命名、注释）可在条目后注明 `（内部）`，避免日志膨胀；
4. 发布或打 tag 时，将 `[Unreleased]` 内容更名为版本号或日期标题（如 `## 2026-08-14 — …`）；
5. 提交命令示例：

   ```bash
   git add CHANGELOG.md <改动文件>
   git commit -m "<type>: <subject>"
   ```
