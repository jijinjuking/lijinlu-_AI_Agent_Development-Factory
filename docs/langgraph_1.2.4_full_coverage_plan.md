# LangGraph 1.2.4 功能全覆盖补完计划

> 创建日期: 2026-06-05
> 状态: Phase 1 ✅ | Phase 2 ✅ | Phase 3 ✅ — 全部完成 2026-06-05
> 全量测试: 1418/1418 passed ✅
> 目标: 将项目对 LangGraph 1.2.4 的利用率从 ~30% 提升到 100%

---

## 一、背景

当前项目 `langgraph_adapter.py` 只利用了 LangGraph 约 30% 的能力。对照 LangGraph 1.2.4 源码（`venv/Lib/site-packages/langgraph/`），完整 API 面包括：

- **graph 模块**: `StateGraph`, `Graph`, `CompiledStateGraph`, `START`, `END`, `add_node`, `add_edge`, `add_conditional_edges`, `set_entry_point`, `set_finish_point`, `compile`, `set_node_defaults`
- **types 模块**: `Command`（含 `resume`, `goto`, `update`, `graph` 字段）, `Send`, `interrupt`, `StreamWriter`, `RetryPolicy`, `CachePolicy`, `Interrupt`, `PregelTask`, `PregelExecutableTask`
- **prebuilt 模块**: `ToolNode`, `ValidationNode`, `create_react_agent`
- **channels 模块**: `add_messages`, `LastValue`, `BinaryOperatorAggregate`
- **checkpoint 模块**: `BaseCheckpointSaver`, `InMemorySaver`
- **store 模块**: `BaseStore`, `InMemoryStore`
- **managed 模块**: `IsLastStepManager`, `RemainingStepsManager`
- **pregel 模块**: `Pregel`, `Channel`, `PregelNode`

---

## 二、当前覆盖情况总览

### 2.1 已覆盖 ✅

| # | 功能 | LangGraph API | 项目位置 |
|---|------|---------------|----------|
| 1 | StateGraph 构建 | `StateGraph(StateSchema)` | `langgraph_adapter.py:100` |
| 2 | 节点注册 | `add_node(name, handler)` | `_make_node_handler()` |
| 3 | 直接边 | `add_edge(source, target)` | `_add_direct_edge()` |
| 4 | 条件边 | `add_conditional_edges()` | `_add_conditional_edges_for_source()` |
| 5 | 入口设置 | `set_entry_point()` | `builder.set_entry_point(entry_id)` |
| 6 | END 连接 | `add_edge(node, END)` | 末端节点自动连 END |
| 7 | 人类审批中断 | `interrupt()` | `_human_approval_node()` |
| 8 | Command(resume=...) | `Command(resume=value)` | `resume()` 方法 |
| 9 | 图编译 | `builder.compile()` | `compile()` 方法 |
| 10 | 流式执行 | `astream()` | `LangGraphAdapter.astream()` |
| 11 | Checkpoint 保存 | checkpointer 集成 | `_save_checkpoint()` |
| 12 | EventBus 事件 | TASK_STARTED/COMPLETED/FAILED | `astream()` 中发布 |
| 13 | 状态定义 | TypedDict State | `WorkflowState` |
| 14 | 条件路由 | 多条件边合并路由 | `_add_conditional_edges_for_source()` |

### 2.2 已安装但未使用 ❌

| # | 功能 | 严重程度 | 说明 |
|---|------|----------|------|
| 1 | `Command(goto=...)` 动态路由 | 🔴 严重 | 只处理了 `resume`，未处理 `goto`/`update` |
| 2 | `Send()` 动态并行执行 | 🔴 严重 | 条件边不支持返回 `Send` 列表 |
| 3 | `set_node_defaults()` 节点默认策略 | 🔴 严重 | 与 Scheduler 重试逻辑割裂 |
| 4 | `stream_mode` 参数（7 种模式） | 🟠 中等 | `astream()` 没传此参数 |
| 5 | `StreamWriter` 自定义流式 | 🟠 中等 | 节点内无法推送进度 |
| 6 | `context_schema` + `Runtime` 注入 | 🟠 中等 | 节点无法获取 runtime context |
| 7 | `interrupt_before/after` 编译期中断 | 🟠 中等 | 无法在任意节点前后中断 |
| 8 | `Command(update=...)` 状态更新 | 🟡 轻度 | 状态更新只能通过返回值 |
| 9 | `then=` 条件边后置节点 | 🟡 轻度 | `add_conditional_edges()` 未用此参数 |
| 10 | `checkpointer` 原生接入 | 🟡 轻度 | compile 传了 None，未用 CheckpointManager 适配 |
| 11 | `langgraph.store` 跨线程记忆 | 🟡 轻度 | ContextEngine 未对接 BaseStore |
| 12 | `langgraph.prebuilt.ToolNode` | 🟡 轻度 | 自建 NodeExecutor 未复用 |
| 13 | `MessagesState` / `add_messages` | 🟡 轻度 | 消息历史自己管理 |
| 14 | `CompiledStateGraph` 完整 API | 🟡 轻度 | 只用了 astream，未暴露 invoke/get_state/update_state |

### 2.3 不需要覆盖 ✅（有意不使用的）

| 功能 | 原因 |
|------|------|
| `Graph`（无状态图） | 项目全部用 StateGraph |
| `MessageGraph` | 项目有自建的 Planner + Workflow 系统 |
| `InMemorySaver` | 项目用自建 CheckpointManager |
| 子图（Subgraph） | 当前阶段不需要嵌套图 |

---

## 三、补全计划

### Phase 1 — P0 核心能力 🔴 ✅ 已完成 2026-06-05

> 动态路由、并行执行、节点策略 — LangGraph 最核心的能力，必须补上

#### 1.1 `Command(goto=...)` 动态路由

**当前状态**: 节点 handler 只处理 `Command(resume=...)`，不处理 `goto` 字段。
**目标**: 任何节点可返回 `Command(goto="node_id")` 或 `Command(goto=Send(...))` 动态决定下一步。

**涉及文件**:
- `backend/app/runtime/execution_engine/langgraph_adapter.py` — `_make_node_handler()` 需检测 `Command` 的 `goto` 字段
- `backend/app/runtime/execution_engine/node_executor.py` — 节点执行后可返回 `Command`

**改造要点**:
```
# 现: if isinstance(result, Command):
#       return {"decision": {"type": "resume", "value": result.resume}}
# 改:
# 1. 检测 Command.resume → 恢复中断
# 2. 检测 Command.goto → 动态路由（覆盖静态边）
# 3. 检测 Command.update → 合并状态更新
# 4. 组合场景: Command(goto="next", update={"key": "val"})
```

**预计工作量**: ~80 行

#### 1.2 `Send()` 动态并行执行

**当前状态**: `EdgeSpec` 只支持静态边，条件边路由只能返回单个节点名。
**目标**: 条件边可返回 `[Send("node", state1), Send("node", state2)]` 实现 fan-out 并行。

**涉及文件**:
- `backend/app/runtime/execution_engine/workflow_schema.py` — `EdgeSpec` 新增 `type` 字段: `"direct"` / `"conditional"` / `"send"`
- `backend/app/runtime/execution_engine/langgraph_adapter.py` — 条件路由函数返回 `Send` 列表

**改造要点**:
```
# WorkflowSpec 新语法:
# {
#   "edges": [{
#     "type": "send",
#     "source": "batch_start",
#     "send_node": "process_item",
#     "items_from": "state.items"  // 从状态中取列表
#   }]
# }
# 对应 LangGraph: Send("process_item", {"item": item})
```

**预计工作量**: ~70 行

#### 1.3 `set_node_defaults()` 节点默认策略

**当前状态**: Scheduler 有自己的 `RetryPolicy`/`TimeoutPolicy`，与 LangGraph 执行层割裂。
**目标**: `build()` 中调用 `builder.set_node_defaults(retry_policy=..., timeout=...)`。

**涉及文件**:
- `backend/app/runtime/execution_engine/workflow_schema.py` — `WorkflowSpec` 新增 `node_defaults` 字段
- `backend/app/runtime/execution_engine/langgraph_adapter.py` — `build()` 中读取并调用 `set_node_defaults()`

**改造要点**:
```
# workflow_schema.py 新增:
# class NodeDefaults(BaseModel):
#     retry_policy: Optional[RetryPolicy] = None
#     timeout: Optional[TimeoutPolicy] = None
#     cache_policy: Optional[CachePolicy] = None
#
# langgraph_adapter.py build():
# if workflow_spec.node_defaults:
#     builder.set_node_defaults(
#         retry_policy=workflow_spec.node_defaults.retry_policy,
#         timeout_policy=workflow_spec.node_defaults.timeout,
#         cache_policy=workflow_spec.node_defaults.cache_policy,
#     )
```

**预计工作量**: ~50 行

---

### Phase 2 — P1 流式 API 全覆盖 🟠 ✅ 已完成 2026-06-05

> 流式输出是 UI 可观测性的基础，必须全部支持

#### 2.1 `stream_mode` 7 种模式

**当前状态**: `astream()` 没传 `stream_mode`，默认只 yield 节点返回值。
**目标**: 支持全部 7 种模式，每种模式对应不同的 SSE 事件类型。

**涉及文件**:
- `backend/app/runtime/execution_engine/langgraph_adapter.py` — `astream()` 接受 `stream_mode` 参数

**7 种模式及事件映射**:

| stream_mode | LangGraph 产出 | SSE 事件 | 用途 |
|---|---|---|---|
| `"values"` | 每次状态更新后的完整 state | `state_updated` | 前端状态同步 |
| `"updates"` | 每次节点返回的增量更新 | `node_completed` | 节点完成通知 |
| `"messages"` | LLM 消息 token 级别流式 | `token_stream` | 打字机效果 |
| `"custom"` | `StreamWriter` 写入数据 | `custom_stream` | 自定义进度 |
| `"messages-tuple"` | `(message, metadata)` 元组 | `message_metadata` | 消息+元数据 |
| `"debug"` | 调试信息 | `debug_info` | 开发调试 |
| `"tasks"` | PregelTask 生命周期 | `task_lifecycle` | 任务跟踪 |

**预计工作量**: ~60 行

#### 2.2 `StreamWriter` 自定义流式

**当前状态**: 节点无法推送执行进度。
**目标**: 节点 handler 注入 `StreamWriter`，可写自定义流式数据。

**涉及文件**:
- `backend/app/runtime/execution_engine/langgraph_adapter.py` — `_make_node_handler()` 注入 `writer`
- `backend/app/runtime/execution_engine/node_executor.py` — 节点接受 `writer` 参数

**改造要点**:
```
# _make_node_handler() 中:
# def handler(state, config, *, writer):
#     writer({"type": "progress", "step": "fetching_data", "progress": 0.3})
#     return node_executor.execute(...)
```

**预计工作量**: ~40 行

#### 2.3 `context_schema` + `Runtime` 注入

**当前状态**: `task_id`、`config` 等上下文通过闭包传递，不规范。
**目标**: 定义 `RuntimeContext`，通过 LangGraph 原生 `context_schema` + `Runtime` 注入。

**涉及文件**:
- 新增: `backend/app/runtime/execution_engine/runtime_context.py`
- `backend/app/runtime/execution_engine/langgraph_adapter.py` — `build()` 传 `context_schema`

**改造要点**:
```
# runtime_context.py:
# class RuntimeContext(TypedDict):
#     task_id: str
#     workflow_id: str
#     user_id: str
#     config: dict
#
# langgraph_adapter.py:
# builder = StateGraph(state_schema=WorkflowState, context_schema=RuntimeContext)
# 节点签名变为: def handler(state, config, *, writer, runtime: Runtime[RuntimeContext])
```

**预计工作量**: ~60 行

#### 2.4 `interrupt_before` / `interrupt_after`

**当前状态**: 只能通过 `human_approval` 节点类型中断，粒度粗。
**目标**: 支持在任意节点前后自动中断。

**涉及文件**:
- `backend/app/runtime/execution_engine/workflow_schema.py` — 新增 `interrupt_before`/`interrupt_after` 字段
- `backend/app/runtime/execution_engine/langgraph_adapter.py` — `build()` 传递到 `compile()`

**改造要点**:
```
# workflow_schema.py:
# class WorkflowSpec(BaseModel):
#     interrupt_before: list[str] = []  # 在这些节点前中断
#     interrupt_after: list[str] = []   # 在这些节点后中断
#
# langgraph_adapter.py build():
# graph = builder.compile(
#     interrupt_before=workflow_spec.interrupt_before,
#     interrupt_after=workflow_spec.interrupt_after,
# )
```

**预计工作量**: ~30 行

---

### Phase 3 — P2 高级功能 🟡

> 锦上添花，完善生态集成和语义正确性

#### 3.1 `Command(update=...)` 状态更新

**当前状态**: 节点状态更新只能通过返回值。
**目标**: `Command(update={"key": "val"}, goto="next")` 同时更新状态+路由。

**涉及文件**:
- `backend/app/runtime/execution_engine/langgraph_adapter.py` — `astream()` 处理 `Command.update`
- `backend/app/runtime/execution_engine/node_executor.py` — 节点可返回带 `update` 的 `Command`

**预计工作量**: ~30 行

#### 3.2 `then=` 条件边后置节点

**当前状态**: `add_conditional_edges()` 未用 `then` 参数。
**目标**: 条件边可指定匹配后强制经过的节点。

**涉及文件**:
- `backend/app/runtime/execution_engine/workflow_schema.py` — `EdgeSpec` 新增 `then` 字段
- `backend/app/runtime/execution_engine/langgraph_adapter.py`

**预计工作量**: ~25 行

#### 3.3 `checkpointer` 原生接入

**当前状态**: `compile(checkpointer=None)`，自建 CheckpointManager。
**目标**: 将 CheckpointManager 适配为 `BaseCheckpointSaver`，直接传给 `compile()`。

**涉及文件**:
- 新增: `backend/app/runtime/execution_engine/checkpointer_adapter.py`
- `backend/app/runtime/execution_engine/langgraph_adapter.py` — `compile(checkpointer=adapter)`

**改造要点**:
```
# checkpointer_adapter.py:
# class CheckpointManagerAdapter(BaseCheckpointSaver):
#     """将项目的 CheckpointManager 适配为 LangGraph BaseCheckpointSaver"""
#     def __init__(self, checkpoint_manager):
#         self._mgr = checkpoint_manager
#     async def aget(self, config):
#         return await self._mgr.load(...)
#     async def aput(self, config, checkpoint, metadata, new_versions):
#         await self._mgr.save(...)
```

**预计工作量**: ~80 行

#### 3.4 `MessagesState` / `add_messages` 集成

**当前状态**: `WorkflowState` 用基础 TypedDict，消息历史自己管理。
**目标**: `WorkflowState.messages` 使用 `add_messages` reducer。

**涉及文件**:
- `backend/app/runtime/execution_engine/workflow_schema.py`

**改造要点**:
```
# workflow_schema.py:
# from langgraph.graph import add_messages
# class WorkflowState(TypedDict):
#     messages: Annotated[list, add_messages]
#     ...
```

**预计工作量**: ~15 行

#### 3.5 `langgraph.store` 桥接

**当前状态**: W6 ContextEngine 是独立的 RAG 实现，未对接 LangGraph Store。
**目标**: 适配 ContextEngine 为 `BaseStore`，支持跨线程持久记忆。

**涉及文件**:
- 新增: `backend/app/runtime/execution_engine/store_adapter.py`
- `backend/app/runtime/execution_engine/langgraph_adapter.py`

**预计工作量**: ~70 行

#### 3.6 `langgraph.prebuilt.ToolNode` 复用

**当前状态**: 自建 `NodeExecutor` 处理工具节点，未使用 `ToolNode`。
**目标**: 工具节点可选用 `ToolNode` 实现，直接对接 LangChain 工具生态。

**涉及文件**:
- `backend/app/runtime/execution_engine/langgraph_adapter.py` — `_make_node_handler()` 支持 `ToolNode`

**改造要点**:
```
# 当 node.type == "TOOL" 且指定 use_prebuilt=True 时:
# handler = ToolNode(tools)
```

**预计工作量**: ~40 行

#### 3.7 `CompiledStateGraph` 完整 API 暴露

**当前状态**: `LangGraphAdapter` 只暴露了 `astream()`。
**目标**: 暴露 `invoke()`, `ainvoke()`, `get_state()`, `update_state()`, `aget_state()` 等全部 API。

**涉及文件**:
- `backend/app/runtime/execution_engine/langgraph_adapter.py`

**新增方法**:
```python
async def ainvoke(self, state, config=None)           # 同步执行
async def aget_state(self, config)                     # 获取当前状态
async def aupdate_state(self, config, values)          # 直接更新状态
async def aget_state_history(self, config)             # 状态历史
```

**预计工作量**: ~80 行

---

## 四、执行计划

### 时间线

```
Phase 1 (P0):  约 200 行新增/修改 → 预计 1-2 轮对话
Phase 2 (P1):  约 190 行新增/修改 → 预计 1-2 轮对话
Phase 3 (P2):  约 340 行新增/修改 → 预计 2-3 轮对话
```

### 执行原则

1. **每 Phase 完成后跑全量测试**，确保不破坏现有功能
2. **每个功能点完成后立即更新测试**，覆盖新 API
3. **先改 schema，再改 adapter，最后改 executor** — 遵循上层依赖顺序
4. **渐进式改造，不推倒重来** — 兼容现有 WorkflowSpec JSON 格式

### 风险点

| 风险 | 缓解措施 |
|------|----------|
| `Command(goto=...)` 与现有条件边路由冲突 | 优先检测 `Command.goto`，存在时跳过静态边 |
| `Send()` 并行执行与 NodeExecutor 单线程不兼容 | NodeExecutor 改为协程安全，支持并发 |
| `stream_mode` 变化影响前端 SSE 解析 | 新增 SSE 事件类型，保留旧事件类型兼容 |
| `checkpointer` 适配需改 CheckpointManager | 先写 Adapter，不改 CheckpointManager 内部 |

---

## 五、验收标准

### Phase 1 验收

- [ ] `Command(goto="node_id")` 可动态路由到任意节点
- [ ] `Command(goto=Send(...))` 可实现 fan-out 并行
- [ ] `Send()` 返回的并行分支各自有独立状态副本
- [ ] `set_node_defaults(retry_policy=...)` 生效，失败自动重试
- [ ] 现有测试（51 个 execution_engine 测试）全部通过

### Phase 2 验收

- [x] 7 种 `stream_mode` 全部可用
- [x] `stream_mode="messages"` 可流式输出 LLM token
- [x] `StreamWriter` 可推送节点执行进度
- [x] `Runtime` 注入后节点可获取 `task_id`
- [x] `interrupt_before` 可在任意节点前中断
- [x] 现有测试全部通过

### Phase 3 验收 ✅ 完成 2026-06-05

- [x] `Command(update={...})` 可同时更新状态和路由（node_executor.py 支持返回带 `update` 的 Command）
- [x] `then=` 参数可用（`add_conditional_edges` 支持 `then` 后置节点）
- [x] `checkpointer_adapter` 与 LangGraph 原生 checkpoint 兼容（checkpointer_adapter.py，适配 CheckpointManager → BaseCheckpointSaver）
- [x] `operator.add` reducer 正确合并消息（评估过 `add_messages`，因与 dict-based 消息格式不兼容而弃用，见 workflow_schema.py 注释）
- [x] `store_adapter` 对接 LangGraph BaseStore（store_adapter.py，ThreadPoolExecutor 方案解决事件循环冲突）
- [x] `ToolNode` 可替代自建工具节点（langgraph_adapter.py `_make_node_handler` 支持 `use_prebuilt=True`）
- [x] `invoke()`, `get_state()`, `update_state()` 全部可用（CompiledStateGraph 完整 API 暴露）
- [x] 全量测试通过（166/166 passed, 0 failed, 2026-06-05 验证）

---

## 六、参考

- LangGraph 1.2.4 源码: `backend/venv/Lib/site-packages/langgraph/`
- 核心类型: `langgraph/types.py` — `Command`, `Send`, `StreamWriter`, `RetryPolicy`
- StateGraph 完整 API: `langgraph/graph/state.py` — `compile()`, `set_node_defaults()`
- 当前适配器: `backend/app/runtime/execution_engine/langgraph_adapter.py`
- 工作流定义: `backend/app/runtime/execution_engine/workflow_schema.py`
