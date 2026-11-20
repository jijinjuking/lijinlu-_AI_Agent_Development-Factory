# 前端补全开发计划

> 版本：v1.0
> 日期：2026-06-06
> 背景：后端已完成 Phase 1-4（1418 测试全量通过），前端需与后端所有新功能打通

---

## 一、差距分析

### 1.1 后端 API vs 前端页面对照表

| 后端路由 | 前端页面 | 状态 | 说明 |
|---|---|---|---|
| `/dashboard` | `DashboardPage.tsx` | ✅ | 已有 |
| `/agents` | `AgentsPage.tsx` | ✅ | 已有 |
| `/traces` | `TracesPage.tsx` | ✅ | 已有 |
| `/pipelines` | `PipelinesPage.tsx` | ✅ | 已有 |
| `/skills` | `SkillsPage.tsx` | ✅ | 已有 |
| `/memory` | `MemoryPage.tsx` | ✅ | 已有 |
| `/costs` | `CostsPage.tsx` | ✅ | 已有 |
| `/settings` | `SettingsPage.tsx` | ✅ | 已有 |
| `/state` | `StateManagerPage.tsx` | ✅ | 已有 |
| `/artifacts` | `ArtifactsPage.tsx` | ✅ | 已有 |
| `/tools` | `ToolsPage.tsx` | ✅ | 已有 |
| `/context` | `ContextPage.tsx` | ✅ | 已有 |
| `/event-replay` | `EventReplayPage.tsx` | ✅ | 已有 |
| `/state-replay` | `StateReplayPage.tsx` | ✅ | 已有 |
| **`/tasks`** | ❌ 无 | **缺失** | Task 管理 |
| **`/events`** | ❌ 无 | **缺失** | 事件流监控 |
| **`/runtime`** | ❌ 无 | **缺失** | Runtime 运维（Phase 3 新功能） |
| **`/evaluation`** | ❌ 无 | **缺失** | 评估系统 |
| **`/k8s`** | ❌ 无 | **缺失** | K8s Job Scheduler（Phase 4） |
| **`/multi-node`** | ❌ 无 | **缺失** | Multi-Node Scheduling（Phase 4） |
| **`/marketplace`** | ❌ 无 | **缺失** | AI Marketplace（Phase 4） |
| **`/federation`** | ❌ 无 | **缺失** | Runtime Federation（Phase 4） |
| **`/tenant`** | ❌ 无 | **缺失** | Multi-Tenant System（Phase 4） |
| **`/performance`** | ❌ 无 | **缺失** | 性能监控 |
| **`/projects`** | ❌ 无 | **缺失** | 项目管理 |
| **`/issues`** | ❌ 无 | **缺失** | 问题跟踪 |

### 1.2 前端 API 层差距

| 缺失的 API 文件 | 对应后端路由 |
|---|---|
| `api/tasks.ts` | `/tasks` |
| `api/events.ts` | `/events` |
| `api/runtime_ops.ts` | `/runtime` |
| `api/evaluation.ts` | `/evaluation` |
| `api/k8s.ts` | `/k8s` |
| `api/multi_node.ts` | `/multi-node` |
| `api/marketplace.ts` | `/marketplace` |
| `api/federation.ts` | `/federation` |
| `api/tenant.ts` | `/tenant` |
| `api/performance.ts` | `/performance` |
| `api/projects.ts` | `/projects` |
| `api/issues.ts` | `/issues` |

### 1.3 前端 Stores 差距

| 缺失的 Store 文件 | 对应功能 |
|---|---|
| `stores/tasksStore.ts` | Task 管理 |
| `stores/eventsStore.ts` | 事件流 |
| `stores/runtimeOpsStore.ts` | Runtime 运维 |
| `stores/evaluationStore.ts` | 评估系统 |
| `stores/k8sStore.ts` | K8s Scheduler |
| `stores/multiNodeStore.ts` | Multi-Node |
| `stores/marketplaceStore.ts` | AI Marketplace |
| `stores/federationStore.ts` | Runtime Federation |
| `stores/tenantStore.ts` | Multi-Tenant |
| `stores/performanceStore.ts` | 性能监控 |
| `stores/projectsStore.ts` | 项目管理 |
| `stores/issuesStore.ts` | 问题跟踪 |

### 1.4 LangGraph 高级功能前端打通差距

Phase 3 实现的 7 项高级功能，前端需要对应支持：

| 功能 | 后端 | 前端需求 |
|---|---|---|
| `Command(update={...})` | ✅ `langgraph_adapter.py` | Workflow 编辑器：节点可返回 `Command` 更新部分状态 |
| `then=` 条件边 | ✅ `_add_conditional_edges_for_source()` | Workflow 编辑器：可视化编辑 `then=` 中间节点 |
| `checkpointer_adapter` | ✅ `checkpointer_adapter.py` | StateManager 页面：查看 checkpoint 历史、恢复状态 |
| `MessagesState/add_messages` | ✅ `workflow_schema.py` | Workflow 编辑器：消息字段可视化 |
| `store_adapter` | ✅ `store_adapter.py` | Context 页面：对接 LangGraph BaseStore |
| `ToolNode` | ✅ `_make_tool_node_handler()` | Workflow 编辑器：可视化配置 ToolNode |
| `ainvoke()/aget_state()/aupdate_state()` | ✅ `langgraph_adapter.py` | 所有页面：同步执行 graph、查看/更新状态 |

---

## 二、分阶段开发计划

### Phase A：补齐缺失页面（优先级：最高）

**目标**：让所有后端 API 都有前端入口

#### A1. 基础打通（4 个核心页面）

| 任务 | 文件 | 说明 |
|---|---|---|
| TasksPage | `pages/TasksPage.tsx` | Task 列表/详情/创建/取消 |
| EventsPage | `pages/EventsPage.tsx` | 事件流实时监控（SSE） |
| RuntimeOpsPage | `pages/RuntimeOpsPage.tsx` | Runtime 运维控制台 |
| EvaluationPage | `pages/EvaluationPage.tsx` | 评估指标查看 |

#### A2. Phase 4 分布式 Runtime（5 个页面）

| 任务 | 文件 | 说明 |
|---|---|---|
| K8sPage | `pages/K8sPage.tsx` | K8s Job 管理 |
| MultiNodePage | `pages/MultiNodePage.tsx` | 多节点调度监控 |
| MarketplacePage | `pages/MarketplacePage.tsx` | AI 能力包市场 |
| FederationPage | `pages/FederationPage.tsx` | Runtime 联邦管理 |
| TenantPage | `pages/TenantPage.tsx` | 多租户管理 |

#### A3. 辅助页面（3 个页面）

| 任务 | 文件 | 说明 |
|---|---|---|
| PerformancePage | `pages/PerformancePage.tsx` | 性能监控仪表盘 |
| ProjectsPage | `pages/ProjectsPage.tsx` | 项目管理 |
| IssuesPage | `pages/IssuesPage.tsx` | 问题跟踪 |

#### A4. API 层 + Store 补齐

- 新建 12 个 `api/*.ts` 文件
- 新建 12 个 `stores/*Store.ts` 文件
- 更新 `routes.tsx` 添加所有新路由
- 更新 `components/layout/AppLayout.tsx` 添加侧边栏入口

---

### Phase B：LangGraph 高级功能打通

**目标**：Phase 3 的 7 项功能在前端可用

#### B1. StateManager 升级（Checkpointer 支持）

- 查看 checkpoint 历史列表
- 可视化 checkpoint 状态快照
- 恢复指定 checkpoint
- 删除 checkpoint

#### B2. Context 页面升级（Store 支持）

- 对接 LangGraph BaseStore
- 支持 namespace/key-value 操作
- 支持 SearchOp 搜索

#### B3. ToolNode 配置支持

- Workflow 编辑器：节点可配置为 ToolNode
- 工具选择下拉（从 `/tools` API 加载）
- `handle_tool_errors` / `messages_key` 配置

#### B4. `ainvoke` 执行支持

- 所有页面：一键 `ainvoke` 执行 graph
- 实时显示执行进度（SSE）
- 执行完成后查看最终状态

---

### Phase C：Workflow 编辑器升级

**目标**：可视化编辑 LangGraph Workflow，支持 Phase 3 高级功能

#### C1. `then=` 边可视化

- 条件边可配置 `then=` 中间节点
- 画布上显示 `A --(condition)--> X --then--> Y` 的两段边
- 属性面板可编辑 `then=` 字段

#### C2. ToolNode 节点类型

- 节点类型新增 `ToolNode`
- 拖拽工具到画布自动创建 ToolNode
- 属性面板配置 `tools` / `handle_tool_errors` / `messages_key`

#### C3. Checkpointer 配置

- Workflow 级别配置：是否启用 checkpointer
- 选择 checkpointer 类型（MemorySaver / SqliteSaver / 自定义）
- 配置 checkpointer 参数

#### C4. Store 配置

- Workflow 级别配置：是否启用 store
- 选择 store 类型（InMemoryStore / 自定义）
- 配置 store 参数

#### C5. Command 节点支持

- 节点返回类型可选择 `Command(goto=...)` / `Command(update=...)`
- 可视化编辑 `Command` 参数

---

### Phase D：前后端联调

**目标**：所有功能真正跑起来

#### D1. 后端启动 + 前端 dev server 联调

- 启动后端：`cd backend && uvicorn app.main:app --reload --port 8002`
- 启动前端：`cd frontend && npm run dev`
- 验证所有 API 端点连通性

#### D2. SSE 实时推送打通

- 前端 SSE 连接 `/api/v1/events/stream`
- 实时更新 Task 状态、Agent 状态、Trace 节点
- 自动重连机制

#### D3. WebSocket 审批流打通

- 前端 WebSocket 连接 `/ws/approval`
- 收到 `approval_needed` 事件时弹出审批对话框
- 支持批准/拒绝/修改后批准

---

### Phase E：打磨和测试

**目标**：生产级质量

#### E1. 响应式适配

- 小屏幕（平板/手机）布局优化
- 侧边栏可折叠

#### E2. 错误处理

- API 请求失败提示
- 网络断开重连提示
- 后端返回错误码的友好提示

#### E3. 性能优化

- 大列表虚拟滚动（TanStack Virtual）
- SSE 消息节流（避免频繁 re-render）
- 图片/Artifact 懒加载

#### E4. E2E 测试

- Playwright 覆盖核心流程
- 每个页面至少有 1 个冒烟测试

---

## 三、执行顺序建议

```
Week 1: Phase A1-A4（补齐缺失页面，让所有 API 有入口）
Week 2: Phase B1-B4（LangGraph 高级功能打通）
Week 3: Phase C1-C5（Workflow 编辑器升级）
Week 4: Phase D1-D3 + Phase E1-E4（联调 + 打磨）
```

---

## 四、立即开始的任务（Phase A1）

1. 创建 `api/tasks.ts` + `stores/tasksStore.ts` + `pages/TasksPage.tsx`
2. 创建 `api/events.ts` + `stores/eventsStore.ts` + `pages/EventsPage.tsx`
3. 创建 `api/runtime_ops.ts` + `stores/runtimeOpsStore.ts` + `pages/RuntimeOpsPage.tsx`
4. 创建 `api/evaluation.ts` + `stores/evaluationStore.ts` + `pages/EvaluationPage.tsx`
5. 更新 `routes.tsx` 添加路由
6. 更新 `components/layout/AppLayout.tsx` 添加侧边栏入口

---

*文档版本：v1.0*
*更新时间：2026-06-06*
*作者：Rigel*
