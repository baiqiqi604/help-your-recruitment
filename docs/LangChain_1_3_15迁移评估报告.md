# LangChain 0.3.29 → 1.3.15 迁移评估报告

> 日期：2026-08-13
> 范围：langchain_version / langgraph_version 两套代码
> 状态：评估完成，待执行迁移

## 一、背景

- 当前实际安装：langchain 0.3.29（0.3.x 最终版本，已停止维护）
- 目标版本：langchain 1.3.15（最新稳定版）+ langgraph 1.x
- 0.3 → 1.0 是官方唯一一次破坏性重构，中间无过渡版本
- 历史教训：全局环境曾被 pip 装成 1.3.14，导致 `ImportError: cannot import name 'AgentExecutor'`，当时退回 0.3.29 解决；本次迁移需在隔离 venv 中进行

## 二、当前 API 使用盘点

### 1. `langchain_version/`（老版，直接命中 1.x 移除项）

| 文件 | 使用的 API | 1.x 状态 |
|---|---|---|
| `agent.py` | `AgentExecutor`、`create_tool_calling_agent`（langchain.agents） | ❌ **已移除** |
| `agent.py` | `ConversationBufferMemory`（langchain.memory） | ❌ **已移除**（移入 langchain-classic） |
| `agent.py` | `ChatPromptTemplate`、`MessagesPlaceholder`（langchain.prompts） | ⚠️ 变更为 `system_prompt` 字符串 + 中间件 |
| `agent.py` | `@tool`（langchain.tools） | ✅ 保留（re-export from core） |
| `llm_client.py` | `ChatOpenAI`（langchain-openai 0.3.35） | ✅ 保留（升级到 1.4.x） |
| `llm_client.py` | `HumanMessage`/`SystemMessage`（langchain_core.messages） | ✅ 保留 |

### 2. `langgraph_version/`（新版，影响较小）

| 文件 | 使用的 API | 1.x 状态 |
|---|---|---|
| `agent.py` | `create_react_agent`（langgraph.prebuilt） | ❌ **已废弃** → `langchain.agents.create_agent` |
| `agent.py` | `MemorySaver`（langgraph.checkpoint.memory） | ✅ 保留 |
| `agent.py` | `@tool`（langchain_core.tools） | ✅ 保留 |
| `graph.py` | `StateGraph`/`END`（langgraph.graph） | ✅ 保留（懒加载导入不受影响） |
| `llm_client.py` | 与 langchain_version 基本一致 | ✅ 保留 |

### 3. 好消息

- **知识库层不依赖 langchain**：`interview_knowledge_base.py`、`jd_knowledge_base.py` 直接用 chromadb + sentence-transformers，无需改动。
- **web_app.py 不直接调 agent API**：只 `import agent` 保留入口，对话走确定性分流，agent 接口只需保持 `chat_with_agent(user_input, session_id)` 签名不变。

## 三、逐文件改动清单

### A. `langchain_version/agent.py`（核心改造，工作量最大）

```python
# 0.3 现在
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain.memory import ConversationBufferMemory
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

agent = create_tool_calling_agent(llm, TOOLS, prompt)
executor = AgentExecutor(agent=agent, tools=TOOLS, memory=memory, max_iterations=6)
```

```python
# 1.3.15 迁移后
from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver  # 或 SQLiteSaver/PostgresSaver

agent = create_agent(
    model=llm,                      # 传模型实例
    tools=TOOLS,
    system_prompt=SYSTEM_PROMPT,    # prompt 参数改名 + 接受字符串
    checkpointer=checkpointer,      # 记忆改为 checkpoint 机制
)
result = agent.invoke(
    {"messages": [{"role": "user", "content": user_input}]},
    config={"configurable": {"thread_id": session_id}},
)
```

关键差异点：

1. **记忆机制重构**：`ConversationBufferMemory`（内存 dict）→ LangGraph checkpoint（`MemorySaver`/`SqliteSaver`），会话隔离从"dict 缓存"改为 `thread_id`。好处：重启后会话不丢（可持久化到 SQLite）；坏处：逻辑变了。
2. **`max_iterations=6` 等价物**：1.x 中通过 `recursion_limit`（LangGraph 继承）或 `ToolCallLimitMiddleware` 控制，需另行配置。
3. **`handle_parsing_errors=True`** → 1.x 用 `ToolStrategy`/中间件的错误处理替代。
4. **`agent_scratchpad` 占位符**：1.x `create_agent` 自动管理，无需手写。
5. `_sessions` dict 缓存可删除，改由 checkpoint 管理。

### B. `langgraph_version/agent.py`（小改）

```python
# 0.3 现在
from langgraph.prebuilt import create_react_agent
agent = create_react_agent(model=model, tools=TOOLS, prompt=SYSTEM_PROMPT, checkpointer=MemorySaver())

# 1.3.15 迁移后
from langchain.agents import create_agent
agent = create_agent(model=model, tools=TOOLS, system_prompt=SYSTEM_PROMPT, checkpointer=MemorySaver())
```

仅两处变化：导入路径 `langgraph.prebuilt` → `langchain.agents`、参数 `prompt` → `system_prompt`。函数名、调用方式、`thread_id` 用法不变。约 5 分钟工作量。

### C. `llm_client.py`（两版，基本不动）

- `ChatOpenAI(model=..., api_key=..., base_url=..., temperature=..., max_tokens=..., timeout=...)` 在 langchain-openai 1.x **参数全部兼容**，无需改动。
- 可选优化：换用 `init_chat_model` 统一入口，但非必需。

### D. `graph.py`（不动）

`StateGraph`/`END`/`compile()` 在 langgraph 1.x 保留，懒加载 try/except 兼容模式也不需要改。

### E. `requirements.txt`（两个目录都要改）

```
langchain>=1.3.0,<2.0.0
langchain-core>=1.5.0
langchain-openai>=1.4.0
langchain-community>=1.0.0      # 1.x 仍需（知识库等）？评估后决定
langgraph>=1.0.0,<2.0.0        # langgraph_version 需要
langgraph-checkpoint>=2.0.0
```

## 四、工作量估算

| 项 | 工作量 | 说明 |
|---|---|---|
| `langgraph_version/agent.py` | **0.5 小时** | 两行改动 |
| `langchain_version/agent.py` | **2–4 小时** | 记忆机制重写是主要成本 |
| 两个 `requirements.txt` + 虚拟环境重装 | 1 小时 | 建议新建独立 venv 验证 |
| 回归测试（对话/RAG/简历优化全流程） | 2–3 小时 | 用 `test_core_pipeline.py`/`validate_runtime.py` |
| 文档同步（README/docs 升级总结） | 1 小时 | 提及 0.3→1.x 变更 |

**总计约 1 天（6–9 小时）**。若只升 langgraph_version 一套，半天内可完成。

## 五、风险清单

| 风险 | 等级 | 说明与对策 |
|---|---|---|
| 记忆行为变化 | 🟠 高 | 内存 dict → checkpoint 是机制级变化，需重点回归多轮对话 |
| `max_iterations`/错误处理语义变化 | 🟠 中 | 需显式配置 `recursion_limit` 或中间件，防止 agent 死循环/静默失败 |
| 提供商兼容 | 🟡 中 | 多 Provider（DeepSeek/OpenAI/通义/智谱）走 OpenAI 兼容接口，1.x 的 content_blocks 对非官方 OpenAI 提供商支持有限——但本项目只取 `response.content` 文本，不受影响 |
| langchain-community 在 1.x 的定位 | 🟡 中 | 1.x 里 community 包仍存在但很多能力移入 langchain-classic；本项目未直接用 community API（grep 确认），可考虑直接去掉该依赖 |
| 依赖联动 | 🟡 中 | langgraph 1.x 要求配 langchain 1.x，两套必须**同时升级**，不能只升一套 |
| 生产中断 | 🟢 低 | 建议先在 git 分支上迁移，用新 venv 验证后再切换 |

## 六、建议迁移顺序

1. **建分支 + 新建 venv**（隔离，避免重蹈全局装 1.3.14 的覆辙）
2. **先改简单的**：`langgraph_version/agent.py` 两行替换 → 跑通验证
3. **再改核心**：`langchain_version/agent.py` 记忆机制重写
4. **统一升级**：两个 requirements.txt + 同时装 langchain 1.3.15 + langgraph 1.x
5. **全量回归**：对话、RAG 检索、JD 分析、简历优化、Word 输出、定时任务
6. **文档同步** + 更新 requirements.txt 顶部的"请勿升级到 1.x"警告注释

## 结论

迁移可行且收益明确（脱离 EOL 的 0.3、获得中间件/checkpoint 持久化/跨提供商 content_blocks），核心成本集中在 `langchain_version/agent.py` 的记忆机制重写。两套都升预算 1 天；只升一套建议先升 langgraph_version（半小时级改动）。
