# AI Runtime OS v2 — 开发实施计划

> 版本：v1.0  
> 日期：2026-05-29  
> 定位：AI Runtime OS（AI Agent 操作系统平台）  
> 核心理念：Runtime Engineering，不是 Prompt + LLM

---

## 目录

1. [项目总览](#1-项目总览)
2. [架构总览与设计哲学](#2-架构总览与设计哲学)
3. [技术栈选型](#3-技术栈选型)
4. [数据库设计](#4-数据库设计)
5. [Runtime Kernel 详细设计](#5-runtime-kernel-详细设计)
6. [Event Bus 详细设计](#6-event-bus-详细设计)
7. [State System 详细设计](#7-state-system-详细设计)
8. [Artifact System 详细设计](#8-artifact-system-详细设计)
9. [Context Engine 详细设计](#9-context-engine-详细设计)
10. [Tool Runtime 详细设计](#10-tool-runtime-详细设计)
11. [Sandbox System 详细设计](#11-sandbox-system-详细设计)
12. [Multi-Agent System 详细设计](#12-multi-agent-system-详细设计)
13. [Governance Layer 详细设计](#13-governance-layer-详细设计)
14. [Observability 详细设计](#14-observability-详细设计)
15. [前端设计](#15-前端设计)
16. [后端 API 设计](#16-后端-api-设计)
17. [开发路线图](#17-开发路线图)
18. [部署方案](#18-部署方案)
19. [核心原则检查清单](#19-核心原则检查清单)

---

## 1. 项目总览

### 1.1 产品定位

**AI Runtime OS** 是一个 AI Agent 操作系统平台，不是普通 ChatBot。

```
AI Runtime OS
=
State（状态管理）
+
Event（事件驱动）
+
Artifact（产物外置）
+
Context（上下文工程）
+
Policy（治理策略）
+
Scheduler（资源调度）
+
Evaluation（自我评估）
```

### 1.2 支持的业务场景

- AI 自动开发
- AI 量化分析
- AI 企业管理
- AI 法律助手
- AI 自动运维
- AI Workflow 自动化
- 多 Agent 协同系统
- AI Skill Marketplace
- AI Tool Runtime
- AI Browser Runtime
- AI Sandbox Runtime

### 1.3 核心目标

```
可长期运行的 AI 基础设施平台
```

具体指标：

| 指标 | 目标值 |
|------|--------|
| 稳定运行任务数 | 1,000,000+ |
| 多 Agent 并发 | 100+ |
| 系统可用性 | 99.9% |
| 故障恢复时间 | < 30s |
| Context 命中率 | > 85% |

---

## 2. 架构总览与设计哲学

### 2.1 系统分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend Layer                       │
│              Web / Desktop App (Tauri)                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐             │
│  │ Runtime   │ │ Multi-   │ │ Artifact │             │
│  │ Dashboard │ │ Agent     │ │ Viewer   │             │
│  └──────────┘ └──────────┘ └──────────┘             │
├─────────────────────────────────────────────────────────────┤
│                    API Gateway Layer                      │
│              FastAPI + WebSocket + gRPC                 │
├─────────────────────────────────────────────────────────────┤
│                    Runtime Kernel                        │
│  ┌──────────────────────────────────────────────┐     │
│  │  Scheduler │ Event Bus │ FSM Engine       │     │
│  │  Checkpoint │ Recovery  │ Worker Manager   │     │
│  └──────────────────────────────────────────────┘     │
├─────────────────────────────────────────────────────────────┤
│                  Core Engine Layer                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ Context    │ │ Policy    │ │Evaluation│           │
│  │ Engine     │ │ Engine    │ │ Engine   │           │
│  └──────────┘ └──────────┘ └──────────┘           │
├─────────────────────────────────────────────────────────────┤
│                  Multi-Agent Layer                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ Capability │ │ Agent     │ │ Workflow  │           │
│  │ Registry   │ │ Runtime   │ │ Generator │           │
│  └──────────┘ └──────────┘ └──────────┘           │
├─────────────────────────────────────────────────────────────┤
│                  Tool & Sandbox Layer                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ Tool      │ │ Sandbox   │ │ Artifact  │           │
│  │ Runtime   │ │ Manager   │ │ Store     │           │
│  └──────────┘ └──────────┘ └──────────┘           │
├─────────────────────────────────────────────────────────────┤
│                    Data Layer                             │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐│
│  │  PostgreSQL   │ │    Redis     │ │   Qdrant    ││
│  │  (主数据库)   │ │  (实时状态)  │ │  (向量检索)  ││
│  └──────────────┘ └──────────────┘ └──────────────┘│
│  ┌──────────────┐ ┌──────────────┐                   │
│  │    MinIO      │ │   Kafka      │                   │
│  │  (文件存储)   │ │  (事件总线)  │                   │
│  └──────────────┘ └──────────────┘                   │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 八大核心原则（严格执行）

```
原则1：Agent 无状态化
  → 状态归 Runtime 管，Agent 节点本身不持有状态

原则2：Workflow 不写死
  → 禁止 graph.add_edge() 写死业务流程
  → Workflow 由 Planner 动态生成

原则3：Tool 必须 Runtime 化
  → 禁止业务代码直接 import tool
  → 所有 Tool 调用经过 ToolRuntime

原则4：State 必须轻量化
  → State 只存 artifact_refs，不存完整内容
  → 真正内容全部进入 Artifact Store

原则5：Event First
  → 系统以 Event 驱动，所有行为都发 Event

原则6：Capability First
  → 调度 Capability，不是调度 Agent Name

原则7：Context Engineering First
  → 真正核心竞争力是 Context，不是模型大小

原则8：Runtime Stability First
  → 目标：AI 系统稳定运行 100 万次任务
```

---

## 3. 技术栈选型

### 3.1 后端技术栈

| 组件 | 技术选型 | 理由 |
|------|----------|------|
| **Web 框架** | FastAPI | 异步高性能，原生 WebSocket 支持 |
| **gRPC** | grpcio + protobuf | Worker 间高性能通信 |
| **流程编排** | LangGraph | StateGraph 动态编排，支持 interrupt/recovery |
| **LLM 接入** | LangChain | 统一接口，动态模型路由 |
| **主数据库** | PostgreSQL 16+ | JSONB 支持、向量扩展 |
| **向量数据库** | Qdrant | 专用向量数据库，性能优于 pgvector |
| **缓存/实时** | Redis 7+ | 状态缓存、Event Bus（Redis Streams） |
| **事件总线** | Redis Streams（阶段1）→ Kafka（阶段3） | 高吞吐事件流 |
| **文件存储** | MinIO（S3 兼容） | 私有部署，Artifact 存储 |
| **任务队列** | Redis Streams / Celery | Agent 异步调度 |
| **认证** | JWT + PBKDF2 | 无状态认证 |
| **可观测性** | OpenTelemetry + 自研 UI | 替代 LangSmith，数据本地 |
| **容器隔离** | Docker + Firecracker（阶段4） | Sandbox 隔离 |

### 3.2 前端技术栈

| 组件 | 技术选型 | 理由 |
|------|----------|------|
| **框架** | React 18 + TypeScript | 类型安全，生态成熟 |
| **桌面端** | Tauri（Rust） | 比 Electron 更轻量，适合 OS 级工具 |
| **状态管理** | Zustand | 轻量，适合实时数据 |
| **流程图** | React Flow | 渲染动态 Workflow，支持拖拽编辑 |
| **看板** | dnd-kit + React Kanban | Agent 协作看板 |
| **图表** | ECharts + D3.js | 成本/质量/性能报表 |
| **代码编辑器** | Monaco Editor | 查看/编辑 Artifact |
| **实时通信** | WebSocket + EventSource | Runtime 事件推送 |
| **UI 组件** | Ant Design 5 | 企业级组件 |
| **构建** | Vite | 快速热更新 |

### 3.3 部署技术栈

| 组件 | 技术选型 |
|------|----------|
| **单机** | Docker + Docker Compose |
| **集群** | Kubernetes + Helm |
| **反向代理** | Nginx / Caddy |
| **服务发现** | Consul（阶段3） |
| **日志** | Loki + Promtail |
| **监控** | Prometheus + Grafana |
| **追踪** | OpenTelemetry Collector |

---

## 4. 数据库设计

### 4.1 PostgreSQL 核心表

#### `users`

```sql
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username        VARCHAR(64)  NOT NULL UNIQUE,
    email           VARCHAR(255) NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    role            VARCHAR(32)  NOT NULL DEFAULT 'developer',
    -- admin / pm / developer / viewer / agent_operator
    preferences_json JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### `tenants`（多租户，阶段4）

```sql
CREATE TABLE tenants (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          VARCHAR(255) NOT NULL,
    slug          VARCHAR(64)  NOT NULL UNIQUE,
    config_json   JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### `projects`

```sql
CREATE TABLE projects (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID REFERENCES tenants(id),
    name          VARCHAR(255) NOT NULL,
    description   TEXT,
    owner_id      UUID NOT NULL REFERENCES users(id),
    config_json   JSONB,       -- 使用的模型、Agent 配置、Policy 配置
    status        VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### `tasks`（Runtime Kernel 核心）

```sql
CREATE TABLE tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID        NOT NULL REFERENCES projects(id),
    name            VARCHAR(255) NOT NULL,
    goal_description TEXT,       -- 用户目标描述（用于动态 Workflow 生成）

    -- 状态机：pending → running → paused → completed / failed / cancelled
    status          VARCHAR(32) NOT NULL DEFAULT 'pending',

    -- 轻量 State（只存引用，不存内容）
    state_json      JSONB NOT NULL DEFAULT '{}',
    -- 格式：{ "current_node": "...", "artifact_refs": [...], "context_refs": [...] }

    workflow_graph_json JSONB,  -- 动态生成的 LangGraph StateGraph 定义

    priority        INTEGER NOT NULL DEFAULT 5,  -- 1~10
    assigned_worker VARCHAR(128),
    created_by      UUID NOT NULL REFERENCES users(id),

    -- 时间戳
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    paused_at       TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,

    -- Checkpoint（用于 Recovery）
    last_checkpoint_id UUID REFERENCES task_checkpoints(id)
);
```

#### `task_checkpoints`（故障恢复）

```sql
CREATE TABLE task_checkpoints (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id       UUID        NOT NULL REFERENCES tasks(id),
    state_snapshot JSONB       NOT NULL,  -- 完整 State 快照
    event_seq_num BIGINT,                -- Event 序号（用于 Replay）
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### `agents`（Agent 注册表，Capability-Based）

```sql
CREATE TABLE agents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(128) NOT NULL UNIQUE,
    capability_tags  TEXT[]        NOT NULL,  -- {'code_generation', 'browser_control', ...}
    model_preference VARCHAR(128),          -- 偏好模型（可动态路由覆盖）
    max_retries     INTEGER DEFAULT 3,
    timeout_sec     INTEGER DEFAULT 300,
    is_active       BOOLEAN DEFAULT TRUE,
    config_json     JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### `artifacts`（产物系统核心）

```sql
CREATE TABLE artifacts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id         UUID        NOT NULL REFERENCES tasks(id),
    task_step_id    UUID,
    artifact_type   VARCHAR(64) NOT NULL,  -- 'requirement_doc' / 'code_file' / 'test_result' / ...
    file_path       VARCHAR(512) NOT NULL,  -- MinIO 路径
    version         INTEGER NOT NULL DEFAULT 1,
    parent_artifact_id UUID REFERENCES artifacts(id),  -- 版本溯源
    metadata_json   JSONB,
    created_by_agent VARCHAR(128),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 快照表（用于 Rollback）
CREATE TABLE artifact_snapshots (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id   UUID NOT NULL REFERENCES artifacts(id),
    version       INTEGER NOT NULL,
    file_path     VARCHAR(512) NOT NULL,
    snapshot_diff TEXT,        -- 与上版本的 diff（可选）
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### `events`（Event Store，支持 Replay）

```sql
CREATE TABLE events (
    id            BIGSERIAL PRIMARY KEY,
    task_id       UUID REFERENCES tasks(id),
    event_type    VARCHAR(64) NOT NULL,  -- TASK_CREATED / AGENT_STARTED / TOOL_EXECUTED / ...
    event_payload JSONB        NOT NULL,
    produced_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    produced_by   VARCHAR(128) -- agent_name / system / user
);

CREATE INDEX idx_events_task_id ON events(task_id);
CREATE INDEX idx_events_type ON events(event_type);
```

#### `llm_calls`（成本追踪）

```sql
CREATE TABLE llm_calls (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id         UUID REFERENCES tasks(id),
    agent_name      VARCHAR(128),
    model_name      VARCHAR(128) NOT NULL,
    prompt_tokens   INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens    INTEGER NOT NULL DEFAULT 0,
    estimated_cost  DECIMAL(12,8),    -- USD
    latency_ms      INTEGER,
    input_text      TEXT,               -- 可脱敏
    output_text     TEXT,               -- 可脱敏
    quality_score   DECIMAL(3,2),     -- 0~5
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### `governance_records`（治理层记录）

```sql
CREATE TABLE governance_records (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id       UUID REFERENCES tasks(id),
    rule_type     VARCHAR(64) NOT NULL,  -- 'quota' / 'budget' / 'loop' / 'permission'
    rule_name     VARCHAR(128) NOT NULL,
    action_taken  VARCHAR(64) NOT NULL,  -- 'blocked' / 'warned' / 'auto_fixed'
    detail_json   JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 4.2 Qdrant 集合设计

```
Collection: project_memories
  Vector size: 1536 (text-embedding-ada-002) 或 384 (FastEmbed)
  Payload: { project_id, memory_type, title, content, created_by, created_at }

Collection: codebase_index
  Vector size: 768 (code embedding)
  Payload: { project_id, file_path, language, chunk_type, start_line, end_line }

Collection: skill_index
  Vector size: 384
  Payload: { skill_name, version, tags, description }
```

### 4.3 Redis 数据结构

```
# Runtime 状态（轻量，TTL 1h）
runtime:task:{task_id}        → Hash { status, current_node, progress_pct }
runtime:agent:{agent_name}    → Hash { status, task_id, current_node, heartbeat_at }
runtime:worker:{worker_id}    → Hash { status, capacity, capabilities, heartbeat_at }

# Event Stream（Redis Streams）
events:task:{task_id}         → Stream（FIFO，保留 7 天）

# 语义缓存（Context Engineering）
ctx:semantic_cache:{hash}     → String（TTL 1h）→ 缓存的 Context 拼接结果

# 分布式锁
lock:task:{task_id}           → String（TTL 30s）

# 限流
rate:{user_id}:{endpoint}     → String（滑动窗口）
```

---

## 5. Runtime Kernel 详细设计

### 5.1 目录结构

```
runtime/
├── __init__.py
├── kernel.py                  # RuntimeKernel 主类
├── scheduler/
│   ├── __init__.py
│   ├── capability_scheduler.py  # Capability-Based 调度器
│   ├── resource_scheduler.py    # Resource-Aware 调度
│   └── priority_queue.py
├── event_bus/
│   ├── __init__.py
│   ├── redis_event_bus.py       # Redis Streams 实现
│   ├── event_dispatcher.py
│   └── event_replay.py         # Event Replay 引擎
├── state_manager/
│   ├── __init__.py
│   ├── lightweight_state.py     # 轻量 State 管理
│   └── state_validator.py
├── checkpoint_manager/
│   ├── __init__.py
│   ├── checkpoint_writer.py
│   └── checkpoint_loader.py
├── recovery_manager/
│   ├── __init__.py
│   ├── failure_detector.py
│   ├── auto_recovery.py
│   └── state_rollback.py
├── task_dispatcher/
│   ├── __init__.py
│   ├── dispatcher.py
│   └── retry_policy.py
├── worker_manager/
│   ├── __init__.py
│   ├── worker_registry.py
│   ├── heartbeat_monitor.py
│   └── worker_scaler.py        # 自动扩缩容
├── runtime_monitor/
│   ├── __init__.py
│   ├── metrics_collector.py
│   └── health_checker.py
└── execution_engine/
    ├── __init__.py
    ├── langgraph_adapter.py    # LangGraph 适配器（动态图）
    ├── node_executor.py
    └── interrupt_handler.py
```

### 5.2 RuntimeKernel 主类设计

```python
# runtime/kernel.py

class RuntimeKernel:
    """
    AI Runtime OS 的核心大脑。
    负责：Task 生命周期、Workflow 调度、Event 分发、
          State 管理、Recovery、Checkpoint、Retry、
          Resource 调度、Agent 调度。
    """

    def __init__(
        self,
        event_bus: EventBus,
        state_manager: StateManager,
        scheduler: CapabilityScheduler,
        checkpoint_mgr: CheckpointManager,
        recovery_mgr: RecoveryManager,
        tool_runtime: ToolRuntime,
        context_engine: ContextEngine,
        policy_engine: PolicyEngine,
    ):
        self.event_bus = event_bus
        self.state_mgr = state_manager
        self.scheduler = scheduler
        self.checkpoint_mgr = checkpoint_mgr
        self.recovery_mgr = recovery_mgr
        self.tool_rt = tool_runtime
        self.ctx_engine = context_engine
        self.policy_engine = policy_engine

    async def submit_task(self, task_request: TaskRequest) -> str:
        """
        提交任务。
        1. 创建 Task 记录（DB）
        2. 发布 TASK_CREATED 事件
        3. 触发动态 Workflow 生成
        4. 进入调度队列
        """
        task_id = await self._create_task_record(task_request)
        await self.event_bus.publish(Event(
            type=EventType.TASK_CREATED,
            task_id=task_id,
            payload={"goal": task_request.goal_description}
        ))
        # 触发 Planner 生成 Workflow
        workflow = await self._generate_workflow(task_request)
        await self._save_workflow(task_id, workflow)
        await self.scheduler.enqueue(task_id, task_request.priority)
        return task_id

    async def _generate_workflow(self, task_request: TaskRequest) -> StateGraph:
        """
        动态 Workflow 生成。
        禁止：在代码里写死 graph.add_edge()。
        正确：由 Planner Agent 根据 goal 动态生成 StateGraph。
        """
        planner_agent = await self.scheduler.get_agent_by_capability("planning")
        workflow_spec = await planner_agent.plan(task_request.goal_description)
        # workflow_spec 是 JSON 描述的 Graph 结构
        # 转换为 LangGraph StateGraph
        return build_graph_from_spec(workflow_spec)

    async def execute_task(self, task_id: str):
        """执行任务主循环"""
        # 1. 加载 State（轻量）
        state = await self.state_mgr.load(task_id)

        # 2. 加载 Workflow Graph（动态）
        graph = await self._load_workflow(task_id)

        # 3. 注册 Callback（自研追踪，替代 LangSmith）
        callbacks = [LocalTracingCallback(task_id, self.db)]

        # 4. 执行（支持 interrupt 和恢复）
        async for event in graph.astream(state, config={"callbacks": callbacks}):
            await self._handle_graph_event(task_id, event)
            # 5. 每个节点执行完写 Checkpoint
            await self.checkpoint_mgr.write(task_id, state)

        # 6. 完成
        await self.event_bus.publish(Event(
            type=EventType.TASK_COMPLETED,
            task_id=task_id
        ))

    async def pause_task(self, task_id: str, reason: str):
        """暂停任务（人工干预 / 策略触发）"""
        await self.state_mgr.update_status(task_id, "paused")
        await self.checkpoint_mgr.write(task_id, await self.state_mgr.load(task_id))
        await self.event_bus.publish(Event(
            type=EventType.TASK_PAUSED,
            task_id=task_id,
            payload={"reason": reason}
        ))

    async def resume_task(self, task_id: str, approval_data: dict = None):
        """恢复任务"""
        state = await self.state_mgr.load(task_id)
        if approval_data:
            state["approval_result"] = approval_data
        await self.execute_task(task_id)

    async def recover_task(self, task_id: str):
        """
        故障恢复。
        1. 读取最新 Checkpoint
        2. Replay Checkpoint 之后的 Event
        3. 恢复 State
        4. 重新执行
        """
        checkpoint = await self.checkpoint_mgr.load_latest(task_id)
        events = await self.event_bus.replay(
            task_id, after_seq_num=checkpoint.event_seq_num
        )
        state = checkpoint.state_snapshot
        for event in events:
            state = apply_event(state, event)
        await self.state_mgr.save(task_id, state)
        await self.execute_task(task_id)
```

### 5.3 Capability Scheduler 设计

```python
# runtime/scheduler/capability_scheduler.py

class CapabilityScheduler:
    """
    Capability-Based 调度器。
    调度 Capability，不是调度 Agent Name。
    """

    def __init__(self, agent_registry, worker_manager, policy_engine):
        self.agents = agent_registry
        self.workers = worker_manager
        self.policy = policy_engine
        self.queue = PriorityQueue()

    async def enqueue(self, task_id: str, priority: int):
        """入队（按优先级）"""
        self.queue.put((priority, time.time(), task_id))

    async def schedule(self) -> ScheduleDecision:
        """
        调度决策。
        返回：{ agent_name, worker_id, model_name, tool_permissions }
        """
        task_id = self.queue.get()[2]
        task = await self._load_task(task_id)
        required_caps = task.required_capabilities

        # 1. 找出拥有所需 Capability 的 Agent
        candidate_agents = self.agents.find_by_capabilities(required_caps)

        # 2. Policy Engine 过滤（预算、配额、权限）
        allowed_agents = self.policy.filter_agents(candidate_agents, task)

        # 3. 动态模型路由（Resource-Aware）
        model = self._select_model(task, allowed_agents)

        # 4. Worker 分配（Resource-Aware）
        worker = await self.workers.select_worker(
            capabilities=required_caps,
            resource_req=task.resource_requirements
        )

        agent = allowed_agents[0]  # 取评分最高的
        return ScheduleDecision(
            agent_name=agent.name,
            worker_id=worker.id,
            model_name=model,
            tool_permissions=agent.allowed_tools
        )

    def _select_model(self, task, agents) -> str:
        """
        动态模型路由。
        禁止：model = "claude" 写死。
        """
        # 简单任务 → 小模型
        if task.estimated_complexity <= 3:
            return self.policy.route_to_small_model(task)
        # 代码任务 → Claude（代码能力强）
        if "code_generation" in task.required_capabilities:
            return "claude-3-5-sonnet"
        # 架构设计 → GPT-4o
        if "architecture_design" in task.required_capabilities:
            return "gpt-4o"
        # 默认
        return self.policy.default_model(task)
```

---

## 6. Event Bus 详细设计

### 6.1 设计原则

```
所有行为 → 转为 Event → 发布到 Event Bus → 消费者处理
```

### 6.2 事件类型定义

```python
# events/event_types.py

class EventType:
    # Task 生命周期
    TASK_CREATED    = "TASK_CREATED"
    TASK_STARTED    = "TASK_STARTED"
    TASK_PAUSED     = "TASK_PAUSED"
    TASK_RESUMED    = "TASK_RESUMED"
    TASK_COMPLETED  = "TASK_COMPLETED"
    TASK_FAILED     = "TASK_FAILED"
    TASK_CANCELLED  = "TASK_CANCELLED"

    # Agent 执行
    AGENT_STARTED   = "AGENT_STARTED"
    AGENT_COMPLETED = "AGENT_COMPLETED"
    AGENT_FAILED    = "AGENT_FAILED"

    # Tool 调用
    TOOL_EXECUTION_STARTED = "TOOL_EXECUTION_STARTED"
    TOOL_EXECUTION_COMPLETED = "TOOL_EXECUTION_COMPLETED"
    TOOL_EXECUTION_FAILED   = "TOOL_EXECUTION_FAILED"

    # Artifact
    ARTIFACT_CREATED = "ARTIFACT_CREATED"
    ARTIFACT_UPDATED = "ARTIFACT_UPDATED"
    ARTIFACT_ROLLED_BACK = "ARTIFACT_ROLLED_BACK"

    # Workflow
    WORKFLOW_GENERATED = "WORKFLOW_GENERATED"
    WORKFLOW_NODE_ENTERED = "WORKFLOW_NODE_ENTERED"
    WORKFLOW_NODE_EXITED  = "WORKFLOW_NODE_EXITED"

    # Governance
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    QUOTA_EXCEEDED  = "QUOTA_EXCEEDED"
    LOOP_DETECTED   = "LOOP_DETECTED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
```

### 6.3 Event Bus 实现（Redis Streams）

```python
# events/redis_event_bus.py

class RedisEventBus:
    """基于 Redis Streams 的 Event Bus"""

    def __init__(self, redis_client):
        self.redis = redis_client

    async def publish(self, event: Event):
        """发布事件"""
        stream_key = f"events:task:{event.task_id}"
        await self.redis.xadd(stream_key, {
            "type": event.type,
            "payload": json.dumps(event.payload),
            "produced_by": event.produced_by,
            "produced_at": event.produced_at.isoformat()
        })
        # 同时写入 PostgreSQL（持久化 + Replay）
        await self._persist_to_db(event)

    async def subscribe(self, task_id: str, consumer_group: str):
        """订阅事件（消费者组）"""
        stream_key = f"events:task:{task_id}"
        # 创建消费者组（如不存在）
        try:
            await self.redis.xgroup_create(stream_key, consumer_group, id="0")
        except redis.ResponseError:
            pass  # 已存在
        # 读取新事件
        while True:
            messages = await self.redis.xreadgroup(
                stream_key, consumer_group,
                count=10, block=5000
            )
            for msg_id, fields in messages:
                yield Event.from_dict(fields)
                await self.redis.xack(stream_key, consumer_group, msg_id)

    async def replay(self, task_id: str, after_seq_num: int = 0):
        """Replay 事件（用于故障恢复）"""
        async for event in self._iter_persisted_events(task_id, after_seq_num):
            yield event
```

### 6.4 Event Replay 引擎

```python
# events/event_replay.py

async def replay_events(task_id: str, checkpoint_seq_num: int,
                       state: dict) -> dict:
    """
    Event Replay：从 Checkpoint 之后的事件重新应用，恢复 State。
    核心公式：
      recovered_state = apply_events(checkpoint.state, events_after_checkpoint)
    """
    events = await event_bus.replay(task_id, after_seq_num=checkpoint_seq_num)
    for event in events:
        state = apply_event(state, event)
    return state

def apply_event(state: dict, event: Event) -> dict:
    """将单个 Event 应用到 State"""
    if event.type == EventType.ARTIFACT_CREATED:
        state["artifact_refs"].append(event.payload["artifact_id"])
    elif event.type == EventType.AGENT_COMPLETED:
        state["current_node"] = event.payload["next_node"]
    # ... 其他事件类型
    return state
```

---

## 7. State System 详细设计

### 7.1 核心原则：轻量 State

```
❌ 错误方式（禁止）：
state = {
  "full_document": "...10000字...",
  "entire_codebase": "..."
}

✅ 正确方式：
state = {
  "task_id": "xxx",
  "current_node": "coding",
  "artifact_refs": ["artifact_id_1", "artifact_id_2"],
  "context_refs": ["ctx_id_1"],
  "status": "running",
  "error_count": 0,
  "metadata": {...}
}
```

真正内容（需求文档、架构设计、代码文件）全部进入 **Artifact Store**。

### 7.2 State 数据结构

```python
# runtime/state_manager/lightweight_state.py

class LightweightState(TypedDict):
    """
    LangGraph 全局共享 State。
    只存引用，不存内容。
    """

    # 任务标识
    task_id: str
    project_id: str

    # 流程控制
    current_node: str
    workflow_status: str  # running / paused / waiting_approval
    error_count: int
    max_retries: int

    # 引用（关键！内容不在这里）
    artifact_refs: list[str]   # Artifact ID 列表
    context_refs: list[str]    # Context ID 列表
    checkpoint_id: str | None

    # 人工干预
    approval_needed: bool
    approval_result: bool | None

    # 运行时上下文（小量）
    messages: Annotated[list[BaseMessage], operator.add]  # 只保留最近 N 条
    current_goal: str

    # 元数据
    metadata: dict  # { elapsed_time_sec, token_usage, cost_usd }
```

### 7.3 State Manager 实现

```python
class StateManager:
    """轻量 State 管理（只存引用）"""

    async def load(self, task_id: str) -> LightweightState:
        """从 Redis 加载热 State，miss 则从 PostgreSQL 加载"""
        cached = await redis.get(f"state:{task_id}")
        if cached:
            return json.loads(cached)
        # 从 DB 加载
        task = await db.fetch_task(task_id)
        state = task.state_json
        await redis.setex(f"state:{task_id}", 3600, json.dumps(state))
        return state

    async def save(self, task_id: str, state: LightweightState):
        """保存 State（只存引用，内容走 Artifact Store）"""
        # 验证 State 大小（防止膨胀）
        state_size = len(json.dumps(state))
        if state_size > 100_000:  # 100KB 阈值
            raise StateTooLargeError(
                "State 过大，请将内容移到 Artifact Store"
            )
        await db.update_task_state(task_id, state)
        await redis.setex(f"state:{task_id}", 3600, json.dumps(state))

    async def get_artifact_content(self, artifact_id: str) -> str:
        """按需加载 Artifact 内容（不在 State 里）"""
        return await artifact_store.load(artifact_id)
```

---

## 8. Artifact System 详细设计

### 8.1 核心原则

```
系统核心不是 Message。
系统核心是：Artifact。
```

### 8.2 Artifact 类型

| 类型 | 说明 | 示例 |
|------|------|------|
| `requirement_doc` | 需求文档 | PRD、用户故事 |
| `architecture_doc` | 架构设计文档 | 系统架构图、技术选型 |
| `code_file` | 代码文件 | `.py`, `.tsx`, `.go` 等 |
| `code_patch` | 代码补丁 | diff 格式 |
| `test_result` | 测试结果 | 覆盖率、失败用例 |
| `review_report` | 审查报告 | 代码审查意见 |
| `deploy_log` | 部署日志 | 部署过程输出 |
| `browser_screenshot` | 浏览器截图 | UI 测试截图 |
| `runtime_trace` | 运行时追踪 | LangGraph 执行链路 |
| `context_snapshot` | 上下文快照 | 某时刻的 Context 拼接结果 |

### 8.3 Artifact Store 实现

```python
# artifacts/store.py

class ArtifactStore:
    """Artifact 存储（MinIO + PostgreSQL 元数据）"""

    def __init__(self, minio_client, db):
        self.minio = minio_client
        self.db = db

    async def save(self, task_id: str, artifact_type: str,
                  content: str, metadata: dict = None) -> str:
        """保存 Artifact，返回 artifact_id"""
        artifact_id = str(uuid4())

        # 1. 写入 MinIO
        file_path = f"artifacts/{task_id}/{artifact_type}/{artifact_id}"
        await self.minio.put_object(
            bucket="ai-runtime-os",
            object_name=file_path,
            data=content.encode(),
            length=len(content)
        )

        # 2. 写入 PostgreSQL 元数据
        await self.db.create_artifact({
            "id": artifact_id,
            "task_id": task_id,
            "artifact_type": artifact_type,
            "file_path": file_path,
            "version": 1,
            "metadata_json": metadata or {},
            "created_by_agent": metadata.get("agent_name") if metadata else None
        })

        # 3. 发布 Event
        await event_bus.publish(Event(
            type=EventType.ARTIFACT_CREATED,
            task_id=task_id,
            payload={"artifact_id": artifact_id, "type": artifact_type}
        ))

        return artifact_id

    async def load(self, artifact_id: str) -> str:
        """加载 Artifact 内容"""
        meta = await self.db.get_artifact(artifact_id)
        data = await self.minio.get_object(
            bucket="ai-runtime-os",
            object_name=meta.file_path
        )
        return data.decode()

    async def diff(self, artifact_id_v1: str, artifact_id_v2: str) -> str:
        """两个版本之间的 diff"""
        content_v1 = await self.load(artifact_id_v1)
        content_v2 = await self.load(artifact_id_v2)
        return difflib.unified_diff(
            content_v1.splitlines(),
            content_v2.splitlines()
        )

    async def rollback(self, artifact_id: str, target_version: int):
        """回滚到指定版本"""
        snapshot = await self.db.get_artifact_snapshot(artifact_id, target_version)
        # 恢复文件
        await self.minio.put_object(...)  # 覆盖为快照版本
        await event_bus.publish(Event(
            type=EventType.ARTIFACT_ROLLED_BACK,
            task_id=snapshot.task_id,
            payload={"artifact_id": artifact_id, "version": target_version}
        ))
```

---

## 9. Context Engine 详细设计

### 9.1 设计哲学

```
未来 AI Runtime 核心竞争力 = Context Engineering
不是模型大小。
```

### 9.2 目录结构

```
context_engine/
├── __init__.py
├── retrieval/
│   ├── vector_retriever.py      # 向量检索
│   └── keyword_retriever.py    # 关键词检索
├── rerank/
│   └── cross_encoder_reranker.py  # 重排序
├── compression/
│   ├── llm_compressor.py       # LLM 压缩（摘要）
│   └── extractive_compressor.py # 抽取式压缩
├── summarization/
│   └── recursive_summarizer.py # 递归摘要
├── chunking/
│   ├── code_splitter.py        # 代码分块（语法感知）
│   └── text_splitter.py        # 文本分块
├── relevance/
│   └── relevance_scorer.py     # 相关性评分
├── semantic_cache/
│   └── semantic_cache.py       # 语义缓存（避免重复拼接）
└── context_builder/
    └── context_assembler.py     # 最终 Context 拼接
```

### 9.3 Context Builder 核心流程

```python
# context_engine/context_builder/context_assembler.py

class ContextAssembler:
    """
    Context 拼接器。
    核心竞争力：把最相关的 Context 拼出来，控制在 Token Budget 内。
    """

    def __init__(self, retrieval_engine, reranker, compressor, semantic_cache):
        self.retrieval = retrieval_engine
        self.reranker = reranker
        self.compressor = compressor
        self.cache = semantic_cache

    async def build_context(
        self,
        query: str,
        token_budget: int = 8000,
        project_id: str = None
    ) -> str:
        """
        Context 拼接主流程：
        1. 语义缓存查找（命中则直接返回）
        2. 向量检索 + 关键词检索（混合）
        3. 重排序
        4. 相关性过滤
        5. Token Budget 控制（压缩/截断）
        6. 写入语义缓存
        """
        # 1. 语义缓存
        cache_key = self.cache.hash(query, project_id)
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        # 2. 混合检索
        vector_results = await self.retrieval.vector_search(query, project_id, top_k=20)
        keyword_results = await self.retrieval.keyword_search(query, project_id, top_k=10)
        merged = self._merge_results(vector_results, keyword_results)

        # 3. 重排序
        reranked = await self.reranker.rerank(query, merged, top_k=10)

        # 4. 拼接 + Token Budget 控制
        context_parts = []
        used_tokens = 0
        for doc in reranked:
            doc_tokens = self._estimate_tokens(doc.content)
            if used_tokens + doc_tokens > token_budget:
                # 压缩
                compressed = await self.compressor.compress(
                    doc.content, max_tokens=token_budget - used_tokens
                )
                context_parts.append(compressed)
                break
            context_parts.append(doc.content)
            used_tokens += doc_tokens

        final_context = "\n\n---\n\n".join(context_parts)

        # 5. 写入缓存
        await self.cache.set(cache_key, final_context, ttl_sec=3600)

        return final_context
```

---

## 10. Tool Runtime 详细设计

### 10.1 核心原则

```
Tool 必须 Runtime 化。
禁止：from tools import shell_tool
正确：tool_runtime.execute("shell_tool", args, permission_context)
```

### 10.2 Tool Runtime 架构

```
tool_runtime/
├── registry/
│   └── tool_registry.py        # Tool 注册表（名称 → 实现）
├── sandbox/
│   ├── docker_sandbox.py       # Docker 隔离
│   ├── python_sandbox.py       # Python 代码沙箱（restrictedpython）
│   └── browser_sandbox.py      # 浏览器沙箱（Playwright）
├── permission/
│   ├── permission_engine.py    # 权限检查
│   └── audit_logger.py        # 审计日志
├── execution/
│   ├── executor.py             # 执行器（统一入口）
│   └── timeout_handler.py     # 超时处理
├── trace/
│   └── tool_tracer.py         # Tool 调用追踪（写入 DB）
├── rollback/
│   └── rollback_manager.py     # 回滚管理（文件变更回滚）
└── adapters/
    ├── shell_adapter.py
    ├── git_adapter.py
    ├── docker_adapter.py
    ├── browser_adapter.py
    ├── database_adapter.py
    ├── python_adapter.py
    ├── deployment_adapter.py
    └── blockchain_adapter.py
```

### 10.3 ToolRuntime 主类

```python
# tool_runtime/execution/executor.py

class ToolRuntimeExecutor:
    """
    Tool 执行器（统一入口）。
    所有 Tool 调用必须经过此处，不允许绕过。
    """

    def __init__(self, registry, permission_engine, sandbox_mgr, tracer, rollback_mgr):
        self.registry = registry
        self.permission = permission_engine
        self.sandbox = sandbox_mgr
        self.tracer = tracer
        self.rollback = rollback_mgr

    async def execute(self, tool_name: str, args: dict,
                     permission_context: PermissionContext) -> ToolResult:
        """
        Tool 执行（带完整 Runtime 管控）：
        1. 权限检查
        2. 写 Trace（开始）
        3. 创建回滚点（文件变更类 Tool）
        4. 在 Sandbox 中执行
        5. 超时控制
        6. 写 Trace（结束）
        7. 返回结果
        """
        # 1. 权限检查
        if not await self.permission.check(tool_name, args, permission_context):
            await self.tracer.log_denied(tool_name, args, permission_context)
            raise PermissionDeniedError(f"Tool {tool_name} 权限不足")

        # 2. Trace
        trace_id = await self.tracer.start(tool_name, args)

        # 3. 回滚点（文件变更类）
        if self._is_file_mutating(tool_name):
            rollback_id = await self.rollback.create_checkpoint(args.get("target_path"))

        try:
            # 4. 获取 Tool 实现
            tool_impl = self.registry.get(tool_name)

            # 5. 在 Sandbox 中执行
            sandbox = await self.sandbox.get_sandbox_for_tool(tool_name)
            result = await asyncio.wait_for(
                sandbox.execute(tool_impl, args),
                timeout=permission_context.timeout_sec or 300
            )

            # 6. Trace（成功）
            await self.tracer.success(trace_id, result)
            return result

        except asyncio.TimeoutError:
            await self.tracer.timeout(trace_id)
            raise ToolTimeoutError(f"Tool {tool_name} 超时")
        except Exception as e:
            await self.tracer.failure(trace_id, e)
            # 文件变更类 Tool 失败时自动回滚
            if self._is_file_mutating(tool_name):
                await self.rollback.restore(rollback_id)
            raise
```

---

## 11. Sandbox System 详细设计

### 11.1 设计原则

```
Agent 必须隔离运行。
禁止：共享全局环境。
必须：Runtime Isolation。
```

### 11.2 Sandbox 类型

| 类型 | 技术实现 | 适用场景 |
|------|-----------|----------|
| Docker Sandbox | Docker Container（每次新建） | Shell 命令、Git 操作、部署 |
| Python Sandbox | RestrictedPython + 资源限制 | Python 代码执行 |
| Browser Sandbox | Playwright + 无头 Chrome（容器化） | 网页浏览、UI 测试 |
| Tool Sandbox | 同 Docker Sandbox | Tool 执行隔离 |
| Skill Sandbox | Docker Sandbox + 网络隔离 | Skill 插件执行 |

### 11.3 Sandbox Manager 实现

```python
# sandbox/sandbox_manager.py

class SandboxManager:
    """Sandbox 生命周期管理"""

    async def create_sandbox(self, sandbox_type: str, task_id: str) -> Sandbox:
        """创建隔离沙箱"""
        if sandbox_type == "docker":
            return await self._create_docker_sandbox(task_id)
        elif sandbox_type == "python":
            return await self._create_python_sandbox(task_id)
        elif sandbox_type == "browser":
            return await self._create_browser_sandbox(task_id)

    async def _create_docker_sandbox(self, task_id: str) -> DockerSandbox:
        container = await docker_client.containers.create(
            image="ai-runtime-sandbox:latest",
            name=f"sandbox-{task_id}",
            detach=True,
            # 资源限制
            mem_limit="512m",
            cpu_quota=50000,  # 50% 单核
            # 网络隔离
            network_mode="none",  # 默认无网络，需要时再开
            # 文件系统隔离
            volumes={
                f"/tmp/sandbox/{task_id}": {"bind": "/workspace", "mode": "rw"}
            },
            # 安全选项
            security_opt=["no-new-privileges"],
            cap_drop=["ALL"],
            cap_add=["CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID"]
        )
        await container.start()
        return DockerSandbox(container)

    async def destroy_sandbox(self, sandbox: Sandbox):
        """销毁沙箱（必须调用）"""
        await sandbox.cleanup()
        # Docker 容器停止 + 删除
        # 临时文件清理
```

---

## 12. Multi-Agent System 详细设计

### 12.1 设计原则

```
Capability-Based Multi-Agent Architecture。
不是：写死角色。
调度：Capability，不是 Agent Name。
```

### 12.2 Agent 能力标签体系

```python
CAPABILITY_TAXONOMY = {
    # 开发类
    "code_generation": ["python", "javascript", "go", "rust"],
    "code_review": ["static_analysis", "security_audit", "style_check"],
    "debug": ["stack_trace_analysis", "log_analysis"],
    "refactor": ["performance", "readability"],

    # 设计类
    "architecture_design": ["microservice", "monolith", "serverless"],
    "api_design": ["rest", "graphql", "grpc"],
    "database_design": ["relational", "nosql", "vector"],

    # 测试类
    "test_generation": ["unit", "integration", "e2e"],
    "test_execution": ["pytest", "jest", "go_test"],

    # 运维类
    "deployment": ["docker", "kubernetes", "ci_cd"],
    "monitoring": ["log_analysis", "metric_analysis"],

    # 浏览器类
    "browser_control": ["navigation", "form_filling", "screenshot", "scraping"],

    # 量化类
    "quant_analysis": ["backtest", "risk_model", "portfolio_optimization"],

    # 法律类
    "legal_analysis": ["contract_review", "compliance_check"],

    # 规划类
    "planning": ["workflow_generation", "task_decomposition"],

    # 上下文类
    "context_retrieval": ["vector_search", "keyword_search", "codebase_indexing"],
}
```

### 12.3 动态 Agent 调度流程

```python
# agents/dynamic_agent_runner.py

class DynamicAgentRunner:
    """
    动态 Agent 执行器。
    根据当前 Node 需要的 Capability，动态选择合适的 Agent + 模型。
    """

    async def run_node(self, node_spec: dict, state: LightweightState):
        required_caps = node_spec.get("required_capabilities", [])
        preferred_model = node_spec.get("preferred_model")

        # 1. 动态选择 Agent（按 Capability）
        agent = await self.scheduler.select_agent(
            capabilities=required_caps,
            policy_constraints=state.get("policy_constraints")
        )

        # 2. 动态路由模型（Resource-Aware）
        model = await self.model_router.route(
            agent=agent,
            task_complexity=state.get("estimated_complexity"),
            budget_remaining=state.get("budget_remaining"),
            preferred=preferred_model
        )

        # 3. 构建 Context（Context Engineering）
        context = await self.ctx_engine.build_context(
            query=node_spec.get("prompt_template"),
            project_id=state["project_id"],
            token_budget=model.context_window * 0.6  # 留余量
        )

        # 4. 执行（带 Tool Runtime 管控）
        result = await agent.run(
            prompt=context,
            model=model,
            tools=agent.allowed_tools,
            tool_runtime=self.tool_runtime,  # 统一管控
            callbacks=[LocalTracingCallback(state["task_id"])]
        )

        # 5. 保存结果到 Artifact Store（State 只存引用）
        artifact_id = await self.artifact_store.save(
            task_id=state["task_id"],
            artifact_type=node_spec.get("output_artifact_type"),
            content=result.content
        )
        state["artifact_refs"].append(artifact_id)

        return state
```

---

## 13. Governance Layer 详细设计

### 13.1 治理维度

```
Governance =
  Token Budget
+ Cost Control
+ Infinite Loop Detection
+ Agent Governance
+ Tool Governance
+ Security Governance
```

### 13.2 目录结构

```
governance/
├── quota/
│   ├── token_quota.py          # Token 配额管理
│   └── cost_quota.py           # 费用配额管理
├── budget/
│   ├── budget_tracker.py       # 预算追踪
│   └── budget_enforcer.py      # 预算强制执行
├── retry_policy/
│   └── retry_policy_engine.py  # 重试策略
├── timeout_policy/
│   └── timeout_policy_engine.py # 超时策略
├── audit/
│   └── audit_logger.py         # 审计日志
├── loop_detector/
│   └── infinite_loop_detector.py # 无限循环检测
├── permission/
│   └── permission_engine.py    # 权限引擎
└── compliance/
    └── compliance_checker.py   # 合规检查
```

### 13.3 无限循环检测

```python
# governance/loop_detector/infinite_loop_detector.py

class InfiniteLoopDetector:
    """
    无限循环检测。
    LangGraph 的图如果条件边写错，可能无限循环。
    """

    def __init__(self, max_iterations: int = 50):
        self.max_iter = max_iterations
        self.node_visit_counts = {}  # task_id → { node_name: count }

    async def check(self, task_id: str, current_node: str) -> LoopDecision:
        """
        检测是否可能无限循环。
        策略：
        1. 单节点访问次数超限 → 判定为循环
        2. 最近 N 个节点序列重复 → 判定为循环
        3. 总迭代次数超限 → 判定为循环
        """
        # 策略 1：单节点访问次数
        key = f"{task_id}:{current_node}"
        self.node_visit_counts[key] = self.node_visit_counts.get(key, 0) + 1
        if self.node_visit_counts[key] > self.max_iter:
            return LoopDecision(
                is_loop=True,
                reason=f"节点 {current_node} 访问次数超过 {self.max_iter}",
                action="pause_task"
            )

        # 策略 2：最近访问序列检测
        recent_nodes = await self._get_recent_node_sequence(task_id, window=10)
        if self._is_cyclic(recent_nodes):
            return LoopDecision(
                is_loop=True,
                reason=f"检测到循环序列：{recent_nodes}",
                action="pause_task"
            )

        return LoopDecision(is_loop=False)
```

---

## 14. Observability 详细设计

### 14.1 设计原则

```
系统必须支持：
- Runtime Trace
- Agent Timeline
- Tool Timeline
- Token Trace
- Cost Trace
- Event Replay
- State Replay
```

### 14.2 自研追踪层（替代 LangSmith）

```python
# observability/local_tracing.py

class LocalTracingCallback(BaseCallbackHandler):
    """
    自研 LLM 调用追踪 Callback。
    数据本地，完全可控，替代 LangSmith。
    """

    def __init__(self, task_id: str, db, event_bus):
        super().__init__()
        self.task_id = task_id
        self.db = db
        self.event_bus = event_bus
        self.step_id = None
        self.start_time = None

    async def on_llm_start(self, serialized, prompts, **kwargs):
        self.start_time = time.time()
        self.step_id = str(uuid4())
        await self.db.create_task_step({
            "id": self.step_id,
            "task_id": self.task_id,
            "node_name": kwargs.get("run_name", "unknown"),
            "status": "running",
            "input_json": {"prompts": prompts},
            "started_at": datetime.utcnow()
        })
        await self.event_bus.publish(Event(
            type=EventType.TOOL_EXECUTION_STARTED,
            task_id=self.task_id,
            payload={"step_id": self.step_id, "type": "llm_call"}
        ))

    async def on_llm_end(self, response, **kwargs):
        latency_ms = int((time.time() - self.start_time) * 1000)
        token_usage = response.llm_output.get("token_usage", {})

        # 写入 llm_calls 表（成本追踪）
        estimated_cost = self._calc_cost(
            model=response.llm_output.get("model_name"),
            prompt_tokens=token_usage.get("prompt_tokens", 0),
            completion_tokens=token_usage.get("completion_tokens", 0)
        )
        await self.db.create_llm_call({
            "task_id": self.task_id,
            "task_step_id": self.step_id,
            "model_name": response.llm_output.get("model_name"),
            "prompt_tokens": token_usage.get("prompt_tokens", 0),
            "completion_tokens": token_usage.get("completion_tokens", 0),
            "total_tokens": token_usage.get("total_tokens", 0),
            "estimated_cost": estimated_cost,
            "latency_ms": latency_ms,
        })

        # 更新 task_step 状态
        await self.db.update_task_step(self.step_id, {
            "status": "completed",
            "output_json": {"content": response.content},
            "completed_at": datetime.utcnow()
        })

    def _calc_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """计算费用（USD）"""
        price = MODEL_PRICE_TABLE.get(model, DEFAULT_PRICE)
        return (prompt_tokens / 1000 * price["prompt"] +
                completion_tokens / 1000 * price["completion"])
```

### 14.3 可视化数据结构（前端渲染用）

```json
{
  "trace_id": "trace-abc-123",
  "task_id": "task-456",
  "spans": [
    {
      "span_id": "s1",
      "parent_span_id": null,
      "node_name": "requirement_agent",
      "agent_name": "requirement_agent",
      "start_time": "2026-05-29T14:32:01Z",
      "end_time": "2026-05-29T14:32:15Z",
      "status": "completed",
      "llm_calls": [
        {
          "model": "gpt-4o",
          "prompt_tokens": 1200,
          "completion_tokens": 800,
          "cost_usd": 0.0045,
          "latency_ms": 3200
        }
      ],
      "tool_calls": [],
      "children": ["s2"]
    }
  ]
}
```

---

## 15. 前端设计

### 15.1 页面结构

```
路由结构：

/Login                   → 登录页
/Dashboard               → Runtime 总览仪表盘
/Project/:id             → 项目详情
/Project/:id/Task/:tid  → 任务执行页（Workflow 可视化）
/Project/:id/Board       → 多 Agent 协作看板（Kanban）
/Project/:id/Memory      → Context 管理（三层记忆 UI）
/Project/:id/Artifacts   → Artifact 浏览器
/Project/:id/Cost        → 成本/质量报表
/Project/:id/Events      → Event Stream 浏览器（可 Replay）
/Admin/Agents            → Agent 管理（Capability 配置）
/Admin/Tools             → Tool 管理（权限配置）
/Admin/Policies          → 治理策略配置
/Admin/System            → 系统配置
```

### 15.2 Runtime Dashboard（总览）

```
┌─────────────────────────────────────────────────────────────┐
│  AI Runtime OS  Dashboard        [🔍 搜索任务]  [⚙ 设置]  │
├──────────┬──────────────────────────────────────────────────┤
│ 侧边栏   │  核心指标卡片                                         │
│           ├───────┬───────┬───────┬───────┬─────────────┤
│ ● Dashboard│ 运行中 │ 今日   │ Token  │ 费用   │ Agent      │
│ ● 项目    │ 任务   │ 完成   │ 消耗   │ 今日   │ 在线      │
│ ● 看板    │ 12     │ 45     │ 2.3M  │ $18.50 │ 8/12      │
│ ● Artifact │        │        │        │        │             │
│ ● 成本    │        │        │        │        │             │
│ ● Event    │        │        │        │        │             │
│           ├───────┴───────┴───────┴───────┴─────────────┤
│           │  Workflow 执行状态（实时）                         │
│           │  ┌─────────────────────────────────────────┐   │
│           │  │ [需求] → [架构] → 🔵[编码] → [审查]     │   │
│           │  │                  ↑ 当前节点（脉动动画）    │   │
│           │  └─────────────────────────────────────────┘   │
│           │                                                  │
│           │  Agent 状态栏                                    │
│           │  🤖 req_agent [工作中]  🤖 code_agent [空闲]    │
│           │  🤖 rev_agent [工作中]  🤖 test_agent [空闲]   │
│           └──────────────────────────────────────────────────┘
└──────────┴──────────────────────────────────────────────────┘
```

### 15.3 Workflow 可视化页（核心）

```
┌─────────────────────────────────────────────────────────────┐
│  任务：XX项目需求开发    状态：运行中      [⏸ 暂停]  [⏹ 停止] │
├─────────────────────────────────────────────────────────────┤
│           │
│  ┌─ Workflow 流程图（React Flow）─────────────────────┐   │
│  │   [需求分析] → [架构设计] → [代码开发]              │   │
│  │         ↑                ↓                      │   │
│  │   [修复代码] ← [代码审查] ← [人工审批]              │   │
│  │                                                  │   │
│  │   ● 当前节点高亮（蓝色脉动）                        │   │
│  │   ● 已完成节点绿色 ✓  失败节点红色 ✗                │   │
│  │   ● 点击节点 → 右侧展开详情                        │   │
│  └───────────────────────────────────────────────────────┘   │
│           │
│  ┌─ 节点详情（右侧面板）────────────────────────────┐      │
│  │  Agent：code_dev_agent                          │      │
│  │  状态：completed ✅                             │      │
│  │  耗时：12.3s                                     │      │
│  │  Token：prompt=1200, completion=800             │      │
│  │  费用：$0.0045                                   │      │
│  │                                                  │      │
│  │  ▼ 输入（折叠）                                   │      │
│  │  ▼ 输出（折叠）→ 点击查看 Artifact               │      │
│  │  ▼ LLM 调用记录（展开）                          │      │
│  │     [1] gpt-4o  3.2s   $0.002                 │      │
│  │     [2] gpt-4o  1.8s   $0.001                 │      │
│  └───────────────────────────────────────────────────────┘   │
│           │
│  ┌─ 实时 Event Stream（底部）─────────────────────┐         │
│  │  [14:32:01] TASK_STARTED       → task-456            │         │
│  │  [14:32:03] AGENT_STARTED     → code_dev_agent      │         │
│  │  [14:32:05] LLM_CALL_COMPLETE → gpt-4o, 3200ms    │         │
│  │  [14:32:15] ARTIFACT_CREATED  → code_file, v1       │         │
│  │  [14:32:16] AGENT_COMPLETED  → code_dev_agent ✓    │         │
│  └───────────────────────────────────────────────────────┘         │
└─────────────────────────────────────────────────────────────┘
```

### 15.4 多 Agent 协作看板（Kanban）

```
┌─────────────────────────────────────────────────────────────┐
│  多 Agent 协作看板    [⚙ 配置 Agent]  [＋ 新任务]          │
├────────┬────────┬────────┬────────┬────────┬────────────┤
│ 待办     │ 进行中  │ 审查中  │ 测试中  │ 已完成  │ 已打回   │
├────────┼────────┼────────┼────────┼────────┼────────────┤
│         │ 🤖     │ 🤖     │         │ ✅      │ ❌ 审查    │
│ [＋ 新  │ code_  │review_ │         │需求    │ 未通过    │
│  任务]  │ dev    │agent   │         │分析 ✅  │ 原因：... │
│         │ Agent  │ 在干活 │         │        │ [🔍 查看] │
│         │ 在干活 │        │         │架构    │ [🔄 重做] │
│         │        │        │         │设计 ✅  │            │
│         │        │        │         │        │            │
├────────┴────────┴────────┴────────┴────────┴────────────┤
│  Agent 状态栏（底部常驻）                                 │
│  🤖 req_agent [空闲]   🤖 code_agent [工作中]            │
│  🤖 rev_agent [工作中]  🤖 test_agent [空闲]             │
│  📊 今日：任务 12 个，Token 45K，费用 $2.30             │
└─────────────────────────────────────────────────────────────┘
```

---

## 16. 后端 API 设计

### 16.1 RESTful API 端点

#### 项目管理

```
GET    /api/v1/projects              # 项目列表
POST   /api/v1/projects              # 创建项目
GET    /api/v1/projects/:id         # 项目详情
PATCH  /api/v1/projects/:id         # 更新项目
DELETE /api/v1/projects/:id         # 删除项目
```

#### 任务管理

```
GET    /api/v1/projects/:pid/tasks                  # 任务列表
POST   /api/v1/projects/:pid/tasks                  # 创建任务（触发动态 Workflow）
GET    /api/v1/projects/:pid/tasks/:tid             # 任务详情
PATCH  /api/v1/projects/:pid/tasks/:tid             # 更新任务
POST   /api/v1/projects/:pid/tasks/:tid/pause       # 暂停任务
POST   /api/v1/projects/:pid/tasks/:tid/resume      # 恢复任务
POST   /api/v1/projects/:pid/tasks/:tid/cancel      # 取消任务
GET    /api/v1/projects/:pid/tasks/:tid/trace       # 获取执行 Trace
GET    /api/v1/projects/:pid/tasks/:tid/events      # 获取 Event 列表
POST   /api/v1/projects/:pid/tasks/:tid/approval   # 提交人工审批结果
```

#### Artifact 管理

```
GET    /api/v1/projects/:pid/artifacts              # Artifact 列表
GET    /api/v1/projects/:pid/artifacts/:aid         # Artifact 详情
GET    /api/v1/projects/:pid/artifacts/:aid/content  # 获取 Artifact 内容
GET    /api/v1/projects/:pid/artifacts/:aid/diff    # 版本 Diff
POST   /api/v1/projects/:pid/artifacts/:aid/rollback # 回滚版本
```

#### Agent 管理

```
GET    /api/v1/agents                  # Agent 列表（按 Capability 可过滤）
POST   /api/v1/agents                  # 注册 Agent
PATCH  /api/v1/agents/:name           # 更新 Agent
GET    /api/v1/agents/:name/heartbeat # 获取 Agent 心跳
```

#### 成本报表

```
GET    /api/v1/projects/:pid/cost/report        # 成本报表
GET    /api/v1/projects/:pid/cost/by_agent     # 按 Agent 汇总
GET    /api/v1/projects/:pid/cost/by_model     # 按模型汇总
GET    /api/v1/projects/:pid/cost/by_task     # 按任务汇总
```

### 16.2 WebSocket API

```
连接：ws://host/api/v1/ws/tasks/:tid

# 服务端 → 客户端（推送）
{
  "type": "task_started",
  "task_id": "task-456",
  "timestamp": "2026-05-29T14:32:01Z"
}

{
  "type": "node_entered",
  "task_id": "task-456",
  "node_name": "code_dev_agent",
  "agent_name": "code_dev_agent"
}

{
  "type": "llm_call_complete",
  "task_id": "task-456",
  "model": "gpt-4o",
  "prompt_tokens": 1200,
  "completion_tokens": 800,
  "cost_usd": 0.0045
}

{
  "type": "artifact_created",
  "task_id": "task-456",
  "artifact_id": "art-789",
  "artifact_type": "code_file"
}

{
  "type": "approval_needed",
  "task_id": "task-456",
  "node_name": "human_approval",
  "prompt": "架构方案已生成，是否批准？",
  "artifact_urls": ["/api/v1/artifacts/art-789/content"]
}

{
  "type": "task_completed",
  "task_id": "task-456",
  "total_cost_usd": 0.087,
  "total_tokens": 42000
}

# 客户端 → 服务端（审批响应）
{
  "type": "submit_approval",
  "task_id": "task-456",
  "approved": true,
  "comment": "方案批准，进入开发"
}
```

---

## 17. 开发路线图

### Phase 1：Runtime Kernel v1（当前阶段）

**目标**：跑通 Event Bus + Scheduler + State Manager + Artifact Store + Context Engine + Tool Runtime

| 周次 | 任务 | 交付物 |
|------|------|--------|
| W1 | 项目脚手架（FastAPI + PostgreSQL + Redis + MinIO） | 可运行的空框架 |
| W2 | Event Bus（Redis Streams）+ 事件类型定义 | Event 发布/订阅可运行 |
| W3 | State Manager（轻量 State）+ Checkpoint Manager | State 读写 + Checkpoint 写入 |
| W4 | Artifact Store（MinIO + PG 元数据）| 保存/加载 Artifact |
| W5 | Tool Runtime（基础：Shell + Git + Python）| Tool 通过 Runtime 执行 |
| W6 | Context Engine（向量检索 + 基础拼接）| Context 可检索并拼接 |
| W7 | LangGraph 适配器（动态图基础）| 可加载动态 Workflow |
| W8 | Recovery Manager（Checkpoint + Event Replay）| 故障可恢复 |

**Phase 1 结束可验收标准**：
- 提交一个任务 → 动态生成 Workflow → 执行 → 完成
- 过程中 Event 可追踪
- Artifact 可存储和查看
- 进程崩溃后能从 Checkpoint 恢复

---

### Phase 2：Multi-Agent Runtime

**目标**：Worker System + Sandbox + Dynamic Routing + Policy Engine + Capability Layer

| 周次 | 任务 | 交付物 |
|------|------|--------|
| W9 | Worker Manager（注册 + 心跳 + 监控）| 多 Worker 可并行执行任务 |
| W10 | Capability Scheduler（Capability-Based 调度）| 按能力调度 Agent |
| W11 | Model Router（动态模型路由）| 简单任务用小模型，复杂任务用大模型 |
| W12 | Sandbox System（Docker + Python）| Agent 隔离执行 |
| W13 | Policy Engine（预算 + 配额 + 权限）| 有治理管控 |
| W14 | 无限循环检测 + 自动恢复 | 稳定跑大量任务 |
| W15~W16 | 前端 MVP（Dashboard + Workflow 可视化）| 能看到执行过程 |

**Phase 2 结束可验收标准**：
- 多 Agent 真正并行执行
- 有完整的前端看板
- 治理策略生效（超预算自动暂停）

---

### Phase 3：Autonomous Runtime

**目标**：Dynamic Workflow + Self Evaluation + Auto Recovery + Event Replay + 前端完整版

| 周次 | 任务 | 交付物 |
|------|------|--------|
| W17 | Planner Agent（动态 Workflow 生成）| 不需要写死 graph.add_edge() |
| W18 | Self Evaluation（自动质量评分）| 每次 Agent 输出自动评估 |
| W19 | Event Replay UI（前端）| 可回放执行过程 |
| W20 | State Replay（从 Checkpoint 恢复并 Replay）| 调试体验完整 |
| W21~W22 | 成本/质量报表（前端 + 后端）| 完整的成本追踪 |
| W23~W24 | Artifact 版本管理 + Diff + Rollback UI | Artifact 完整生命周期 |

**Phase 3 结束可验收标准**：
- Workflow 完全动态生成
- 有完整的可观测性（替代 LangSmith）
- 系统稳定运行 10,000 次任务

---

### Phase 4：AI Operating System

**目标**：Distributed Runtime + Multi-Node Scheduling + AI Marketplace + Runtime Federation + Multi-Tenant

| 周次 | 任务 | 交付物 |
|------|------|--------|
| W25~W26 | 分布式 Runtime（Kubernetes）| 多节点部署 |
| W27~W28 | Multi-Node Scheduling（跨节点调度）| Worker 可跨机器调度 |
| W29~W30 | AI Marketplace（Skill + Agent + Workflow 模板）| 能力市场上线 |
| W31~W32 | Runtime Federation（多 Runtime 实例互联）| 企业多实例部署 |
| W33~W34 | Multi-Tenant（租户隔离）| SaaS 化 |
| W35~W36 | 性能优化（目标 100 并发任务）| 稳定可扩展 |

**Phase 4 结束可验收标准**：
- 分布式部署，支持水平扩展
- Skill Marketplace 上线
- 系统稳定运行 100,000+ 次任务

---

## 18. 部署方案

### 18.1 单机部署（Docker Compose）

适合：小团队（5~20 人）、内网环境、开发测试

```yaml
# docker-compose.yml
version: "3.8"

services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: ai_runtime_os
      POSTGRES_USER: admin
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U admin"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redisdata:/data
    ports:
      - "6379:6379"

  qdrant:
    image: qdrant/qdrant:latest
    volumes:
      - qdrantdata:/qdrant/storage
    ports:
      - "6333:6333"
      - "6334:6334"

  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_PASSWORD}
    volumes:
      - miniodata:/data
    ports:
      - "9000:9000"
      - "9001:9001"

  backend-api:
    build: ./backend
    environment:
      DATABASE_URL: postgresql+asyncpg://admin:${DB_PASSWORD}@postgres:5432/ai_runtime_os
      REDIS_URL: redis://redis:6379/0
      QDRANT_URL: http://qdrant:6333
      MINIO_ENDPOINT: minio:9000
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
    ports:
      - "8000:8000"
    deploy:
      resources:
        limits:
          memory: 2G

  backend-worker:
    build: ./backend
    command: python -m app.workers.langgraph_worker
    environment:
      # 同 backend-api
      WORKER_ID: "worker-1"
    depends_on:
      - redis
      - postgres
    deploy:
      replicas: 2  # 2 个 Worker 并行

  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    depends_on:
      - backend-api

  nginx:
    image: nginx:alpine
    volumes:
      - ./deployments/nginx.conf:/etc/nginx/nginx.conf
    ports:
      - "80:80"
      - "443:443"
    depends_on:
      - backend-api
      - frontend

volumes:
  pgdata:
  redisdata:
  qdrantdata:
  miniodata:
```

### 18.2 集群部署（Kubernetes）

适合：中大型团队（20+ 人）、需要高可用

```yaml
# k8s/backend-worker-deployment.yaml

apiVersion: apps/v1
kind: Deployment
metadata:
  name: ai-runtime-worker
  namespace: ai-runtime-os
spec:
  replicas: 3  # 3 个 Worker 并行
  selector:
    matchLabels:
      app: ai-runtime-worker
  template:
    metadata:
      labels:
        app: ai-runtime-worker
    spec:
      containers:
      - name: worker
        image: ai-runtime-os/backend:latest
        command: ["python", "-m", "app.workers.langgraph_worker"]
        env:
        - name: WORKER_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: ai-runtime-secrets
              key: database-url
        resources:
          requests:
            memory: "1Gi"
            cpu: "500m"
          limits:
            memory: "4Gi"
            cpu: "2000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8001
          initialDelaySeconds: 30
          periodSeconds: 10
```

**K8s 部署架构**：

```
Namespace: ai-runtime-os
├── Deployment: backend-api       （2+ 副本，无状态）
├── Deployment: backend-worker   （3+ 副本，可执行 LangGraph 任务）
├── StatefulSet: postgres       （主从复制，使用 Cloud SQL 更佳）
├── StatefulSet: qdrant        （向量数据库，PersistentVolume）
├── Deployment: redis           （哨兵模式，或使用 ElastiCache）
├── Deployment: minio           （分布式模式）
├── Deployment: frontend         （2+ 副本）
└── Ingress: nginx              （统一入口，HTTPS 终止）
```

---

## 19. 核心原则检查清单

**每次 Code Review 必须核对以下清单**：

```
□ Agent 是否有状态？
  → 如果有：❌ 违反原则1，状态必须归 Runtime 管

□ 是否有 graph.add_edge() 写死了业务流程？
  → 如果有：❌ 违反原则2，Workflow 必须动态生成

□ 是否有业务代码直接 import tool？
  → 如果有：❌ 违反原则3，必须通过 ToolRuntime 执行

□ State 里是否有完整文档/代码内容？
  → 如果有：❌ 违反原则4，必须改为 artifact_refs

□ 是否有非 Event 驱动的操作？
  → 如果有：❌ 违反原则5，所有操作必须发 Event

□ 调度是否写了 Agent Name 的硬编码？
  → 如果有：❌ 违反原则6，必须按 Capability 调度

□ Context 是否只是简单拼接？
  → 如果是：❌ 违反原则7，必须使用 Context Engine

□ 是否只关注 AI 多聪明，而不关注系统稳定性？
  → 如果是：❌ 违反原则8，稳定性优先
```

---

## 附录 A：与 LangSmith 的功能对照（自研实现）

| LangSmith 功能 | 自研实现方案 | 状态 |
|----------------|--------------|------|
| Traces（链路追踪） | LocalTracingCallback → PostgreSQL → React Flow 渲染 | Phase 1 |
| Hub（Prompt 管理） | prompt_templates 表 + API 拉取 + 前端编辑 | Phase 2 |
| Playground（调试） | 前端 Prompt 编辑 + 单步执行界面 | Phase 2 |
| Evaluation（评估） | evaluation/ 模块 + 自动评分 + 人工评分 | Phase 3 |
| Datasets（测试集） | evaluation_datasets 表 + 前端管理 UI | Phase 3 |
| Cost Tracking | llm_calls 表 + 报表 API + 前端图表 | Phase 2 |
| Dashboard | Runtime Dashboard（自研，比 LangSmith 更针对软件开发场景）| Phase 2 |

---

## 附录 B：目录结构总览（最终）

```
ai-runtime-os/
├── runtime/                          # Runtime Kernel（核心）
│   ├── kernel.py
│   ├── scheduler/
│   ├── event_bus/
│   ├── state_manager/
│   ├── checkpoint_manager/
│   ├── recovery_manager/
│   ├── task_dispatcher/
│   ├── worker_manager/
│   ├── runtime_monitor/
│   └── execution_engine/
├── events/                           # Event Bus
│   ├── event_bus.py
│   ├── event_types.py
│   ├── consumers/
│   ├── producers/
│   └── replay/
├── agents/                           # Multi-Agent Layer
│   ├── dynamic_agent_runner.py
│   ├── capability_registry.py
│   ├── planner_agent.py
│   ├── requirement_agent.py
│   ├── architecture_agent.py
│   ├── code_dev_agent.py
│   ├── review_agent.py
│   ├── test_agent.py
│   └── deploy_agent.py
├── context_engine/                    # Context Engine（核心竞争力）
│   ├── retrieval/
│   ├── rerank/
│   ├── compression/
│   ├── summarization/
│   ├── chunking/
│   ├── relevance/
│   ├── semantic_cache/
│   └── context_builder/
├── memory/                           # Memory Layer
│   ├── short_term.py                # Redis
│   ├── long_term.py                 # PostgreSQL + Qdrant
│   └── embedding_client.py
├── tool_runtime/                     # Tool Runtime（必须隔离）
│   ├── registry/
│   ├── sandbox/
│   ├── permission/
│   ├── execution/
│   ├── trace/
│   ├── rollback/
│   └── adapters/
├── sandbox/                          # Sandbox System
│   ├── sandbox_manager.py
│   ├── docker_sandbox.py
│   ├── python_sandbox.py
│   └── browser_sandbox.py
├── artifacts/                        # Artifact System
│   ├── store.py
│   ├── versioning.py
│   ├── snapshots.py
│   └── diff_engine.py
├── governance/                       # Governance Layer
│   ├── quota/
│   ├── budget/
│   ├── retry_policy/
│   ├── timeout_policy/
│   ├── audit/
│   ├── loop_detector/
│   ├── permission/
│   └── compliance/
├── resources/                        # Resource Management
│   ├── resource_scheduler.py
│   └── quota_manager.py
├── evaluation/                       # Evaluation System
│   ├── scoring/
│   ├── benchmark/
│   ├── hallucination/
│   ├── regression/
│   ├── code_quality/
│   └── tool_metrics/
├── model_router/                     # Dynamic Model Routing
│   └── model_router.py
├── observability/                    # Observability（替代 LangSmith）
│   ├── local_tracing.py
│   ├── metrics.py
│   └── replay_ui.py
├── api/                              # API 层
│   ├── main.py                       # FastAPI 入口
│   ├── config.py
│   ├── auth/
│   ├── routes/
│   │   ├── projects.py
│   │   ├── tasks.py
│   │   ├── agents.py
│   │   ├── artifacts.py
│   │   ├── costs.py
│   │   └── websocket.py
│   └── middleware/
├── frontend/                         # 前端（React + Tauri）
│   ├── src/
│   │   ├── components/               # 看板、流程图、报表
│   │   ├── pages/
│   │   ├── store/                   # Zustand
│   │   ├── api/                     # API 请求封装
│   │   └── utils/
│   ├── package.json
│   └── tauri.conf.json
├── skill_packages/                    # Skill Marketplace
│   ├── code_review_expert/
│   ├── api_designer/
│   └── ...
├── deployments/                      # 部署配置
│   ├── docker-compose.yml
│   ├── k8s/
│   └── nginx.conf
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── docs/
│   ├── ARCHITECTURE.md
│   ├── API.md
│   └── DEPLOY.md
├── alembic/                          # 数据库迁移
└── README.md
```

---

*本文档版本 v1.0，根据 ai_runtime_os_v2_architecture.md 编写。*
*后续根据开发进展持续更新。*
*核心原则：Runtime Engineering，不是 Prompt + LLM。*
