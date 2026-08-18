# DeepSeek 缓存命中率优化方案

> 日期：2026-08-18 ｜ 适用：langgraph_version / langchain_version 两版
> 结论速览：你总结的 3 个方向全部**可行且正确**，是本方案的骨架；但结合本项目代码，有一个
> 前置问题必须先回答——**web 对话路径目前根本不产生可命中缓存的多轮前缀**。先度量、再对齐
> 架构，方向 1/2/3 才能落地生效。

---

## 一、缓存机制回顾（优化依据）

DeepSeek 上下文缓存是**自动、按输入前缀（prefix）匹配**的：

- 请求的输入（system + tools + 历史消息）从头开始与历史请求做最长前缀匹配，命中的部分按缓存价计费（约未命中的 1/10），未命中部分按正常价。
- 缓存**不保证永久有效**：热门前缀保留更久，冷门前缀数小时量级失效；官方不承诺命中。
- 缓存空间按模型隔离：换 model / base_url 即换缓存空间。
- 命中情况可直接度量：响应 `usage` 含 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`。
- 命中率 = hit / (hit + miss)。它对成本是**非线性**的：前缀越长、复用越多，收益越大。

由此推出唯一铁律：**让"越靠前的输入"越稳定**。前缀中任何一字节变化，都会使其之后的所有内容无法命中。

---

## 二、现状分析（基于代码事实）

### 2.1 两条实际存在的 LLM 调用路径

| 路径 | 触发方 | 输入结构 | 缓存潜力 |
|------|--------|----------|----------|
| A：`llm_client.chat(user_input)`（无 system） | web 未命中 RAG 时 | `[HumanMessage(问题)]`，全部动态 | **趋近 0**：前缀第一字节就是每次不同的问题 |
| B：`_summarize_kb_answer` | web RAG 命中时 | `[SystemMessage(固定), HumanMessage(问题+题库内容)]` | 低：system 段稳定可命中，但占比小 |
| C：agent（`chat_with_agent`/`astream_chat`） | CLI、测试 | `[SystemMessage, tools, checkpoint 历史, 新问题]` | **高**：第 2 轮起历史前缀逐轮复用 |

### 2.2 关键结论

1. **web 对话没走 agent**（`web_app.py` 仅 `import agent` 保留入口；文档《LangChain_1_3_15迁移评估报告》也写明"对话走确定性分流"）。所以：
   - 若"命中率低"的观测来自 web 对话 → 大部分请求是路径 A，**结构上就不存在可命中的前缀**，优化 prompt 结构也救不回来；
   - 方向 2 的"Agent History append-only"对 web 路径**目前没有作用对象**。
2. **没有任何 usage 埋点** → 当前无法量化命中率，也无法验证任何优化效果。
3. 两版差异点（不影响缓存，但注意行为不一致）：langgraph 版 `answer_from_kb` 用 `top_k=5, max_distance=0.6`；langchain 版 `top_k=8, max_distance=0.45` 且截断参考答案 600 字。web 路径（不走 agent）统一用 `search_questions(top_k=8, max_distance=0.45)`。

---

## 三、你的 3 个方向：可行性评估

### 方向 1：Prompt 结构（固定前置、动态后置）—— ✅ 可行，是基础

完全符合前缀缓存机制。细化要求：

- **System → Tools → Stable Context → Dynamic Context → User Query** 的顺序正确，LangChain 序列化时就是 system 在前、tools 在后、历史再后。
- **动态内容绝不能放进 system 头部**：一旦 system 开头出现会变的内容（日期、会话号、每次不同的统计），整个前缀（包括 tools 和历史）全部失效——这是最常见的"静默杀手"。
- 本项目 `SYSTEM_PROMPT` 是纯静态常量，✅ 已符合；`_summarize_kb_answer` 的 system 也是静态，✅。
- 注意：**tools 的 docstring 就是工具描述，是前缀的一部分**；改 docstring / 调 TOOLS 顺序 = 全部前缀变化（一次性成本，发布节奏上注意）。

### 方向 2：Agent History Append-only—— ✅ 可行（对 agent 路径），但需先明确优化对象

- 多轮对话历史**只追加、不改写**，则第 N 轮输入 = 第 N-1 轮输入 + 少量新 token，前缀天然复用，第 2 轮起命中率显著上升。
- **两个陷阱**：
  1. 重新生成 Summary 替换历史、或把摘要插到历史**前面** → 前缀字节全变 → 全部 miss。若必须压缩历史，正确姿势是"**从尾部整体截断/丢弃**"，而不是"重新生成替换前缀内容"；
  2. `MemorySaver` 是进程内存，重启即失；跨会话不共享历史（这是特性不是 bug）。
- **对本项目**：先决定 web 对话是否接入 agent（见方向 5）。若保持单轮分流，方向 2 只对 CLI 场景有意义。

### 方向 3：Tools / RAG 稳定—— ✅ 可行

- **Tool Schema**：LangChain 按 `TOOLS` 列表顺序序列化，稳定即保持：不改 docstring、不改参数注解、不调顺序。
- **JSON 序列化**：同一进程内每次请求的序列化字节一致（LangChain 保证）；跨版本升级（如已发生的 1.x 迁移）会一次性改变序列化格式 → 全量缓存失效一次，属正常成本。
- **RAG 结果放动态区**：✅ 正确——放工具结果 / 用户消息尾部，不进 system。`_summarize_kb_answer` 已把题库内容放在 HumanMessage 尾部，✅。
- **排序/格式稳定**：⚠️ 补充要求——检索结果需**确定性排序**（score 相同按 id 稳定排序）。否则同一问题两次检索返回顺序不同 → 文本不同 → 前缀不同。当前 `search_questions` 若存在并列分随机序，需加 tie-breaker。

---

## 四、补充方向

### 方向 4（⭐ 最重要，优先级最高）：度量先行

没有数据就没有优化。当前 `llm_client.chat/stream_chat/chat_json/chat_structured` 全部丢弃 usage。

**落点**：在 `llm_client.py` 各调用处统一采集并记录（日志或独立指标）：

```python
# 以 chat() 为例：取 LangChain 响应里的 usage
usage = getattr(response, "usage_metadata", None) or {}
# DeepSeek 原始字段：prompt_cache_hit_tokens / prompt_cache_miss_tokens
hit = usage.get("input_token_details", {}).get("cache_read", 0)
miss = usage.get("input_tokens", 0) - hit
logger.info("LLM usage: hit=%s miss=%s hit_rate=%.1f%%", hit, miss,
            100 * hit / (hit + miss) if (hit + miss) else 0)
```

先跑几天拿基线，再谈优化目标（例如：单轮路径命中率可从 ~0 提到 30-50%，多轮 agent 路径第 2 轮起可达 60-90%）。

### 方向 5（本项目特有，架构对齐）：决定 web 对话是否接入 agent

- **方案 5a（推荐，改动大但收益大）**：web `/api/chat`、`/api/chat/stream` 改为调用 `chat_with_agent` / `astream_chat`，让多轮历史真正存在 → 方向 1/2/3 全部生效。注意前端 `index.html` 已把完整 `chatHistory` 发给后端，但后端目前只取最后一条 user 消息——接入 agent 后仍应以 `thread_id`（session_id）为准，**不要**把前端传来的历史重新拼进 prompt（会引入与 checkpoint 不一致的前缀）。
- **方案 5b（保守）**：维持单轮分流，接受命中率低，只做方向 4（度量）+ 方向 6（system 加长）。成本最低，收益有限。

### 方向 6：把"稳定内容"做大、把"易变内容"赶出 system

- system 稳定 → **跨会话共享**：所有会话的 system + tools 前缀相同，天然可命中。因此：静态指令、few-shot 示例、通用知识尽量留在 system；会话信息、时间、个性化内容一律放动态区。
- 反面教材：在 system 里拼 `今天是 {date}` 或知识库条数 → 所有会话全部 miss。

### 方向 7：缓存保活（低频场景可选）

- 缓存 TTL 不保证。对低频调用（CLI、测试），可考虑定时发一个"相同前缀"的最小请求保活缓存；高频 web 场景不需要。权衡：保活本身消耗一次未命中成本。

### 方向 8：请求参数稳定

- temperature / max_tokens 不进输入前缀，**不需要**为缓存特意固定；但 base_url、model、`extra_body`（如 qwen3 的 `enable_thinking`）保持稳定总没错（换模型=换缓存空间）。

---

## 五、落地实施步骤

| 阶段 | 动作 | 涉及文件 | 验收 |
|------|------|----------|------|
| 0（先行） | usage 埋点：采集 hit/miss，输出命中率日志 | 两版 `llm_client.py` | 每次调用日志出现 hit_rate |
| 1 | 跑 1-3 天拿基线；统计 web 两路径 + agent 路径各自的命中率分布 | 无（仅观测） | 明确"低"到底低在哪条路径 |
| 2 | 按方向 1/6 审查：确认 system 全静态、动态内容全部后置 | 两版 `agent.py`、`web_app.py` | 无任何动态内容在 system/前缀 |
| 3 | 按方向 3：检索结果确定性排序（score+id tie-break） | `interview_knowledge_base.py`、`retrievers.py` | 同问题两次检索字节一致 |
| 4 | 按方向 2：确认历史只追加；若引入压缩，用尾部截断而非重写前缀 | `agent.py`（若 web 接入） | 多轮第 2 轮起命中率上升 |
| 5（可选） | 按方向 5a：web 对话接入 agent，多轮历史生效 | 两版 `web_app.py`、`index.html` | web 多轮命中率达标 |
| 6 | 复测命中率，对比基线；固化发布纪律（改 system/tool docstring 需知会） | 文档 | 命中率提升有数据支撑 |

---

## 六、验收目标（建议）

- **路径 A（web 未命中 RAG）**：命中率 0% → 接入 agent 后首轮 ~10-20%（system+tools 段），第 2 轮起 50%+。
- **路径 B（web RAG 命中）**：system 段稳定命中，总体 30-50%（取决于题库内容长度占比）。
- **路径 C（agent 多轮）**：第 2 轮起 60-90%。
- 成本上：缓存价约为未命中 1/10，命中率提升直接线性降低成本；延迟方面命中段免 prefill，TTFT 下降。

> 一句话总结：**方向 1/2/3 全对，但先用方向 4 拿到数据，再决定方向 5（web 是否接入 agent）——否则你优化的可能是一个不存在的前缀。**
