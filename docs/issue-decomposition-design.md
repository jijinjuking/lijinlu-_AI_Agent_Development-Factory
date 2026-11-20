# AI Agent OS — "议题 → 分解 → 派发 → 看板联动" 完整设计方案

> 版本：v1.0  
> 日期：2026-06-05  
> 目标：让用户在系统的"议题板"上提出需求，系统自动/由架构师 Agent 将需求分解为子任务，派发给对应角色 Agent，并实时联动 Kanban 看板。

---

## 一、背景与现状

### 1.1 现有能力

| 能力 | 状态 | 说明 |
|------|------|------|
| Kanban 看板 | ✅ 已实现 | 5 列，拖拽，SSE 实时推送 |
| Pipeline 工作流 | ✅ 已实现 | 预定义模板串行执行，按 role 匹配 Agent |
| Agent 角色体系 | ✅ 已实现 | architect / developer / reviewer / tester / deployer |
| Planner Agent (W17) | ✅ 已实现 | 动态 Workflow 生成，支持 4 种策略 |
| Agent 提示词体系 | ✅ 已实现 | 自定义 > 角色默认，写入 system message |
| Task 模型 | ✅ 已实现 | 扁平结构，无父子关系 |

### 1.2 缺失环节

1. **无"议题/需求"入口** — 用户没有一个地方"扔议题"
2. **Task 无层级** — 无法表达"父需求 → 子任务"的关系
3. **Pipeline 是预定义模板** — 不是架构师看完需求后**动态分解**
4. **无"议题看板"视图** — 缺少需求级别的整体进度视图

---

## 二、整体架构设计

### 2.1 核心流程

```
用户提出需求（议题板）
  ↓
Issue 创建（状态：open）
  ↓
架构师 Agent 接收 Issue
  ↓
Planner 分解（LLM 生成子任务树）
  ↓
自动创建子 Task（parent_task_id = Issue 的主任务 ID）
  ↓
按角色自动分配 Agent（developer → 前端/后端 Agent）
  ↓
子 Task 推送到 Kanban 看板（todo 列）
  ↓
各 Agent 执行，SSE 实时推送状态
  ↓
所有子 Task 完成 → Issue 自动关闭
```

### 2.2 页面体系

```
/ issues            → Issue 列表（议题板）
/ issues/:id        → Issue 详情（需求描述 + 子任务树 + 进度）
/ agents            → Kanban 看板（已有，子任务自动出现）
/ projects          → Project 列表（ optional，需求的组织容器）
/ projects/:id     → Project 详情（关联的 Issue 列表 + 整体进度）
```

---

## 三、数据模型设计

### 3.1 新增模型

#### **Project（项目/需求容器）**

```python
class Project(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(
        String(32), default="active",
        comment="active | archived"
    )
    created_by: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
        comment="创建者（用户 or Agent name）"
    )
    tags: Mapped[str | None] = mapped_column(
        String(512), nullable=True,
        comment="逗号分隔的标签"
    )
```

#### **Issue（议题/需求）**

```python
class Issue(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "issues"

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="open", index=True,
        comment="open | in_progress | blocked | resolved | closed"
    )
    priority: Mapped[str] = mapped_column(
        String(16), default="medium",
        comment="low | medium | high | critical"
    )
    created_by: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
        comment="提出者（用户 name or Agent name）"
    )
    assigned_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="主要负责的 Agent（通常是架构师）"
    )
    # 分解结果（JSON 存储，避免额外表）
    decomposition_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="Planner 分解结果：子任务树结构"
    )
    decomposed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="分解完成时间"
    )
    tags: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    # 冗余统计字段（性能优化）
    total_sub_tasks: Mapped[int] = mapped_column(
        Integer, default=0,
        comment="子任务总数（含主任务）"
    )
    completed_sub_tasks: Mapped[int] = mapped_column(
        Integer, default=0,
        comment="已完成子任务数"
    )
```

#### **Task 扩展（新增父子关系字段）**

在现有 `Task` 模型追加：

```python
class Task(Base, UUIDPrimaryKey, TimestampMixin):
    # ... 现有字段保持不变 ...

    # === 新增：层级关系 ===
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=True, index=True,
        comment="父任务 ID。若为空则为顶层任务（对应一个 Issue）"
    )
    issue_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"),
        nullable=True, index=True,
        comment="关联的 Issue。顶层任务的 issue_id 指向所属 Issue"
    )
    # 子任务顺序（架构师分解时的排序）
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0
    )
    # 该任务在分解树中的角色（用于前端图标区分）
    task_role: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="architecture | frontend | backend | test | review | deploy | docs"
    )
```

### 3.2 分解结果 JSON 结构（`Issue.decomposition_json`）

```json
{
  "version": "1.0",
  "issue_id": "uuid-string",
  "decomposed_by": "Architect-01",
  "decomposed_at": "2026-06-05T10:30:00Z",
  "strategy": "llm_generated",
  "root_task_id": "uuid-string",
  "sub_tasks": [
    {
      "id": "uuid-1",
      "title": "设计数据库 Schema",
      "description": "设计用户表、订单表及关联关系",
      "task_role": "architecture",
      "assigned_role": "architect",
      "estimated_tokens": 2000,
      "dependencies": [],
      "children": []
    },
    {
      "id": "uuid-2",
      "title": "实现后端 API",
      "description": "基于 Schema 实现 RESTful API",
      "task_role": "backend",
      "assigned_role": "developer",
      "estimated_tokens": 5000,
      "dependencies": ["uuid-1"],
      "children": []
    },
    {
      "id": "uuid-3",
      "title": "实现前端页面",
      "task_role": "frontend",
      "assigned_role": "developer",
      "dependencies": ["uuid-1"],
      "children": []
    },
    {
      "id": "uuid-4",
      "title": "端到端测试",
      "task_role": "test",
      "assigned_role": "tester",
      "dependencies": ["uuid-2", "uuid-3"],
      "children": []
    }
  ]
}
```

### 3.3 数据关系图

```
Project 1───* Issue
                │
                │ 1───1 Task (顶层，issue_id)
                │
                │ 1───* Task (子任务，parent_task_id)
                │
                │ *───1 Agent (assigned_agent_id)
                │
                │ *───* Artifact (task_id)
                │
                │ *───* TaskCheckpoint (task_id)
```

---

## 四、后端 API 设计

### 4.1 Issue API（`/api/v1/issues`）

| 方法 | 路径 | 说明 | 请求体 / 参数 |
|------|------|------|------------------|
| `POST` | `/api/v1/issues` | 创建 Issue | `{project_id?, title, description, priority?, tags?}` |
| `GET` | `/api/v1/issues` | Issue 列表 | `?project_id= &status= &priority= &assigned_agent_id= &skip= &limit=` |
| `GET` | `/api/v1/issues/{issue_id}` | 获取单个 Issue（含子任务树） | — |
| `PUT` | `/api/v1/issues/{issue_id}` | 更新 Issue | `{title?, description?, status?, priority?, assigned_agent_id?, tags?}` |
| `DELETE` | `/api/v1/issues/{issue_id}` | 删除 Issue（级联删除子 Task） | — |
| `POST` | `/api/v1/issues/{issue_id}/decompose` | **触发分解**（核心端点） | `{strategy?: "template_match" \| "llm_generate" \| "hybrid" \| "query_expansion", model?: string}` |
| `GET` | `/api/v1/issues/{issue_id}/sub-tasks` | 获取子任务树（层级结构） | — |
| `POST` | `/api/v1/issues/{issue_id}/dispatch` | **派发所有子任务到 Kanban**（核心端点） | — |

### 4.2 Project API（`/api/v1/projects`）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/projects` | 创建项目 |
| `GET` | `/api/v1/projects` | 项目列表 |
| `GET` | `/api/v1/projects/{project_id}` | 项目详情（含 Issue 统计） |
| `PUT` | `/api/v1/projects/{project_id}` | 更新项目 |
| `DELETE` | `/api/v1/projects/{project_id}` | 删除项目 |

### 4.3 Task API 扩展

现有端点保持不变，新增：

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/tasks/{task_id}/children` | 获取子任务列表 |
| `PUT` | `/api/v1/tasks/{task_id}/order` | 更新子任务排序（`{parent_task_id, ordered_child_ids[]}`） |

### 4.4 分解端点详细说明

**`POST /api/v1/issues/{issue_id}/decompose`**

后台执行流程：

```
1. 校验 Issue 存在且 status == "open"
2. 找到 assigned_agent（必须是 architect 角色，若无则报错）
3. 异步执行分解（立即返回 202 + {decompose_run_id}）
4. 分解步骤：
   a. 构建 PlannerGoal：
      - raw_text = issue.description
      - complexity = 根据描述长度/关键词估算（1~10）
      - 尝试从 description 提取关键词
   b. 调用 PlannerAgent.plan(goal, strategy)
   c. 将 WorkflowSpec 转换为 sub_tasks 树结构
   d. 为每个 sub_task 建议 assigned_role（根据 task_role 映射）
   e. 写入 Issue.decomposition_json
   f. 更新 Issue.status = "in_progress"，decomposed_at = now()
   g. SSE 推送 "issue_decomposed" 事件
5. 返回 decomposition_json 的摘要
```

**SSE 事件**（分解过程中推送）：

| 事件类型 | 数据 | 说明 |
|-----------|------|------|
| `decompose_started` | `{issue_id, assigned_agent}` | 分解开始 |
| `decompose_progress` | `{issue_id, step_name, step_index, total_steps}` | 分解进度（Planner 各阶段） |
| `decompose_completed` | `{issue_id, sub_task_count, decomposition}` | 分解完成 |
| `decompose_failed` | `{issue_id, error}` | 分解失败 |

### 4.5 派发端点详细说明

**`POST /api/v1/issues/{issue_id}/dispatch`**

```
前提：Issue.decomposition_json 不为空

1. 读取 decomposition_json.sub_tasks[]
2. 遍历每个 sub_task：
   a. 根据 assigned_role 查找可用的 idle Agent
   b. 创建 Task 记录：
      - name = sub_task.title
      - goal_description = sub_task.description
      - parent_task_id = 顶层任务 ID（若有）
      - issue_id = issue.id
      - task_role = sub_task.task_role
      - agent_id = 匹配到的 Agent.id
      - kanban_column = "todo"
      - priority = issue.priority（继承）
      - tags = issue.tags + [sub_task.task_role]
   c. 若找不到匹配 Agent，设为 agent_id = None（待人工分配）
   d. SSE 推送 "task_dispatched" 事件
3. 返回派发结果：
   {
     "dispatched": 3,
     "pending_assignment": 1,
     "tasks": [...]
   }
4. SSE 推送 "issue_dispatched" 事件（前端刷新 Issue 详情页）
```

---

## 五、前端设计

### 5.1 Issue 列表页（`/issues`）

**布局**：类 GitHub Issues 的列表 + 筛选栏

```
┌──────────────────────────────────────────────────────┐
│  Issues                          [+ 新建 Issue]    │
├──────────────────────────────────────────────────────┤
│  筛选：[全部] [Open 3] [进行中 1] [已关闭 0]     │
│  搜索框：__________    按优先级：[全部 v]           │
├──────────────────────────────────────────────────────┤
│  🔴 高  Implement user auth system  │ open    │ 3d │
│  🟡 中  Optimize query performance │ in_prog │ 1d │
│  🟢 低  Update documentation       │ resolved│ 5h │
└──────────────────────────────────────────────────────┘
```

**交互**：
- 点击 Issue → 进入详情页
- 点击"新建 Issue" → 弹窗（选 Project、填标题/描述、选优先级）
- 每行显示：优先级色块、标题、状态 Tag、创建时间、分配给谁

### 5.2 Issue 详情页（`/issues/:id`）

**布局**：左右分栏

```
┌──────────────────────────────────────────────────────────┐
│  [← 返回]  Implement user auth system     🔴 high    │
├────────────────────────────┬─────────────────────────────┤
│  描述                       │  子任务树（可勾选完成）      │
│  ┌──────────────────────┐  │  ✅ 设计数据库 Schema      │
│  │ As a user, I want... │  │  ⬜ 实现后端 API          │
│  │ (Markdown 渲染)       │  │  ⬜ 实现前端登录页        │
│  └──────────────────────┘  │  ⬜ 编写单元测试          │
│                            │  ⬜ 代码审查              │
│  元数据                    │  ⬜ 部署到 staging        │
│  Project: MyApp           │                             │
│  Status: in_progress      │  进度条：███████░░░ 70%   │
│  Priority: high           │                             │
│  Assignee: Architect-01  │  [🚀 触发分解] [📤 派发] │
│  Tags: auth, security     │                             │
│  Created: 2026-06-03    │                             │
└────────────────────────────┴─────────────────────────────┘
│  Activity Log                                      ▼ │
│  [10:30] Architect-01 完成了分解，生成 5 个子任务      │
│  [10:35] Dev-01 认领了"实现后端 API"                   │
└──────────────────────────────────────────────────────────┘
```

**关键交互**：

1. **"触发分解"按钮**：
   - 点击后弹出策略选择（模板匹配 / LLM 生成 / 混合 / 多目标拆解）
   - 确认后调用 `POST /api/v1/issues/:id/decompose`
   - 显示分解进度条（SSE 实时更新）
   - 分解完成后，右侧子任务树刷新

2. **"派发"按钮**（分解完成后可点击）：
   - 调用 `POST /api/v1/issues/:id/dispatch`
   - 显示派发结果（已分配 X 个，待分配 Y 个）
   - 派发后自动跳转到 `/agents`（Kanban 看板），子任务已出现在 todo 列

3. **子任务树**：
   - 可展开/折叠
   - 每个子任务显示：角色图标（🏗️架构 / 💻开发 / 🧪测试 / 👀审查 / 🚀部署）
   - 点击子任务 → 弹出 Task 详情（或跳转到 Kanban 对应卡片）

### 5.3 Kanban 看板扩展（`/agents` 页面，已有）

**扩展内容**：

1. **TaskCard 增加层级标识**：
   - 顶层任务（parent_task_id is None）：显示 Issue 链接图标
   - 子任务：显示缩进 + 连接线（表示父子关系）
   - 悬停显示父任务标题

2. **按 Issue 筛选**：
   - 看板顶部增加下拉："全部" / "Issue #12: Auth" / "Issue #15: Performance"
   - 选中后只显示该 Issue 的子任务

3. **进度同步**：
   - Issue 的所有子任务完成后，后端自动将 Issue.status 设为 `resolved`
   - SSE 推送 `issue_completed` 事件

### 5.4 Project 列表页（`/projects`，可选）

如果实现 Project 概念，提供一个轻量项目导航页：

```
┌──────────────────────────────────┐
│  Projects            [+ 新建]    │
├──────────────────────────────────┤
│  📁 MyApp                      │
│    3 Open Issues, 2 In Progress │
│    Created: 2026-05-01         │
│                                │
│  📁 DataPlatform                │
│    1 Open Issue, 5 Resolved     │
└──────────────────────────────────┘
```

---

## 六、与现有系统集成

### 6.1 复用 Planner Agent (W17)

**不重复造轮子**：`PlannerAgent.plan()` 已经能把目标文本转化为 `WorkflowSpec`（节点 + 边）。

适配方式：

```python
# backend/app/api/issues.py 伪代码

async def decompose_issue(issue_id: str, strategy: str):
    issue = await get_issue(issue_id)
    
    # 1. 构建 PlannerGoal
    goal = PlannerGoal(
        raw_text=issue.description,
        complexity=estimate_complexity(issue.description),
        keywords=extract_keywords(issue.description),
    )
    
    # 2. 调用已有 PlannerAgent
    planner = get_default_planner()
    result: PlanningResult = await planner.plan(
        goal_text=issue.description,
        strategy=strategy,  # "hybrid" 是推荐默认值
        model="deepseek-chat",
    )
    
    # 3. 将 WorkflowSpec 转换为 sub_tasks 树
    sub_tasks = _workflow_spec_to_sub_tasks(result.workflow_spec, issue_id)
    
    # 4. 持久化到 Issue
    issue.decomposition_json = {
            "version": "1.0",
            "issue_id": issue_id,
            "decomposed_by": "Architect-01",
            "strategy": strategy,
            "sub_tasks": sub_tasks,
        }
    issue.status = "in_progress"
    await db.commit()
    
    # 5. SSE 通知
    await sse_manager.publish("issue_decomposed", {
        "issue_id": issue_id,
        "sub_task_count": len(sub_tasks),
    })
    
    return {"status": "decomposed", "sub_tasks": sub_tasks}
```

### 6.2 复用 Agent 角色能力映射

已有的 `ROLE_CAPABILITY_MAP`（在 `agent_executor.py` 中）可以扩展为**任务角色 → Agent 角色**的映射：

```python
# backend/app/services/task_dispatcher.py

TASK_ROLE_TO_AGENT_ROLE: dict[str, str] = {
    "architecture": "architect",
    "frontend":    "developer",    # 前端开发者也是 developer 角色
    "backend":      "developer",
    "test":         "tester",
    "review":       "reviewer",
    "deploy":       "deployer",
    "docs":         "custom",       # 文档任务暂时用 custom
}

def dispatch_sub_tasks(issue: Issue, sub_tasks: list[dict]) -> DispatchResult:
    """将子任务分配到对应角色的 Agent。"""
    assigned = []
    unassigned = []
    
    for sub in sub_tasks:
        agent_role = TASK_ROLE_TO_AGENT_ROLE.get(sub["task_role"], "developer")
        
        # 查找同角色的 idle Agent
        agent = await find_idle_agent_by_role(agent_role)
        
        if agent:
            task = await create_task_from_sub_task(sub, issue, agent)
            assigned.append(task)
        else:
            # 放入待分配池（Kanban 上显示"未分配"）
            task = await create_task_from_sub_task(sub, issue, agent=None)
            unassigned.append(task)
    
    return DispatchResult(assigned=assigned, unassigned=unassigned)
```

### 6.3 Kanban 联动

子任务创建时 `kanban_column="todo"`，自动出现在 Kanban 的"待办"列。

SSE 事件链：

```
子任务创建 → kanban_update 事件 → 前端 KanbanStore 更新 → 卡片出现在 todo 列
     ↓
Agent 认领 → task_started 事件 → 卡片移到 in_progress 列
     ↓
Agent 完成 → task_completed 事件 → 卡片移到 done 列
     ↓
所有子任务 done → issue_completed 事件 → Issue 详情页进度条 100%
```

### 6.4 Artifact 关联

架构师分解时生成的文档（需求分析、技术方案）可以作为 Artifact 保存：

```python
# 分解完成后，自动创建 Artifact
if issue.decomposition_json:
    artifact = Artifact(
        task_id=root_task.id,
        artifact_type="architecture_doc",
        file_path=save_to_file(decomposition_text),
        created_by_agent="Architect-01",
        metadata_json={"issue_id": issue.id},
    )
    db.add(artifact)
```

---

## 七、SSE 事件设计

新增事件类型（在现有基础上扩展）：

| 事件类型 | 触发时机 | 数据负载 |
|-----------|-----------|----------|
| `issue_created` | Issue 创建 | `{issue_id, title, priority}` |
| `issue_updated` | Issue 更新 | `{issue_id, changes}` |
| `issue_decompose_started` | 分解开始 | `{issue_id, strategy}` |
| `issue_decompose_progress` | 分解进度 | `{issue_id, step, progress: 0.0~1.0}` |
| `issue_decomposed` | 分解完成 | `{issue_id, sub_task_count, sub_tasks[]}` |
| `issue_dispatched` | 派发完成 | `{issue_id, dispatched: int, pending: int}` |
| `issue_completed` | 所有子任务完成 | `{issue_id, completed_at}` |
| `task_dispatched` | 单个子任务派发 | `{task_id, issue_id, assigned_agent}` |

**SSE 订阅方式扩展**：

- 全局订阅：接收所有 `issue_*` 事件
- Issue 专属订阅：`GET /api/v1/events/stream?issue_id=xxx`（前端 Issue 详情页使用）

---

## 八、数据库迁移方案

### 8.1 新增表

```sql
-- projects 表
CREATE TABLE projects (
    id UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT DEFAULT '',
    status VARCHAR(32) DEFAULT 'active',
    created_by VARCHAR(128),
    tags VARCHAR(512),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- issues 表
CREATE TABLE issues (
    id UUID PRIMARY KEY,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    status VARCHAR(32) DEFAULT 'open',
    priority VARCHAR(16) DEFAULT 'medium',
    created_by VARCHAR(128),
    assigned_agent_id UUID REFERENCES agents(id) ON DELETE SET NULL,
    decomposition_json JSON,
    decomposed_at TIMESTAMP WITH TIME ZONE,
    tags VARCHAR(512),
    total_sub_tasks INTEGER DEFAULT 0,
    completed_sub_tasks INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- tasks 表新增字段
ALTER TABLE tasks ADD COLUMN parent_task_id UUID REFERENCES tasks(id) ON DELETE CASCADE;
ALTER TABLE tasks ADD COLUMN issue_id UUID REFERENCES issues(id) ON DELETE CASCADE;
ALTER TABLE tasks ADD COLUMN sort_order INTEGER DEFAULT 0;
ALTER TABLE tasks ADD COLUMN task_role VARCHAR(32);
```

### 8.2 迁移脚本

在 `backend/app/database.py` 的 `_migrate_db()` 中追加：

```python
# v2 迁移：Issue 体系
if "issues" not in table_names:
    async with conn.begin():
        await conn.run_sync(lambda: Base.metadata.create_all(engine))
```

---

## 九、前端路由与文件结构

### 9.1 路由配置（`frontend/src/router.tsx`）

```typescript
const router = createBrowserRouter([
  { path: "/", element: <DashboardPage /> },
  { path: "/issues", element: <IssuesPage /> },          // 新增
  { path: "/issues/:id", element: <IssueDetailPage /> },  // 新增
  { path: "/projects", element: <ProjectsPage /> },       // 新增（可选）
  { path: "/projects/:id", element: <ProjectDetailPage /> },
  { path: "/agents", element: <AgentsPage /> },           // 已有，扩展
  // ... 其他已有路由
]);
```

### 9.2 新增文件清单

```
frontend/src/
├── pages/
│   ├── IssuesPage.tsx          # Issue 列表
│   ├── IssueDetailPage.tsx     # Issue 详情（分解 + 子任务树）
│   ├── ProjectsPage.tsx        # Project 列表（可选）
│   └── ProjectDetailPage.tsx   # Project 详情（可选）
├── components/
│   ├── issues/
│   │   ├── IssueList.tsx          # Issue 列表组件
│   │   ├── IssueCard.tsx          # Issue 卡片（列表用）
│   │   ├── IssueFormModal.tsx    # 新建/编辑 Issue 弹窗
│   │   ├── SubTaskTree.tsx       # 子任务树组件
│   │   ├── DecomposeProgress.tsx  # 分解进度条
│   │   └── DispatchButton.tsx    # 派发按钮（含结果反馈）
│   └── kanban/
│       └── TaskCard.tsx          # 已有，扩展：增加父任务标识
├── stores/
│   ├── issueStore.ts            # Issue 状态管理（Zustand）
│   └── projectStore.ts         # Project 状态管理（可选）
├── api/
│   ├── issues.ts               # Issue API 调用
│   └── projects.ts             # Project API 调用（可选）
├── types/
│   ├── issue.ts                # Issue / SubTask 类型定义
│   └── project.ts              # Project 类型定义（可选）
└── hooks/
    └── useSSEIssue.ts          # Issue 专属 SSE 订阅 Hook
```

---

## 十、实施优先级

### Phase 1：数据层 + 基础 API（后端核心）

- [ ] 新增 `Project`、`Issue` 模型 + 迁移脚本
- [ ] `Task` 模型扩展（`parent_task_id`、`issue_id`、`task_role`）
- [ ] Issue CRUD API（`/api/v1/issues`）
- [ ] Project CRUD API（`/api/v1/projects`，可选）
- [ ] 单元测试（模型 + API）

### Phase 2：分解引擎（后端核心）

- [ ] `POST /issues/:id/decompose` 端点
- [ ] 复用 PlannerAgent 实现分解逻辑
- [ ] `decomposition_json` 写入与验证
- [ ] SSE 事件推送（分解进度）
- [ ] 分解结果单元测试

### Phase 3：派发引擎（后端核心）

- [ ] `POST /issues/:id/dispatch` 端点
- [ ] 基于角色的 Agent 自动匹配
- [ ] 子任务 Task 批量创建
- [ ] Kanban 联动（自动入 todo 列）
- [ ] 派发结果 SSE 推送

### Phase 4：前端 Issue 列表 + 详情页

- [ ] `IssuesPage`（列表 + 筛选）
- [ ] `IssueDetailPage`（描述 + 子任务树）
- [ ] `IssueFormModal`（新建/编辑）
- [ ] `SubTaskTree` 组件
- [ ] 前端 SSE 订阅（`useSSEIssue` Hook）

### Phase 5：分解进度 + 派发交互（前端）

- [ ] 分解策略选择弹窗
- [ ] `DecomposeProgress` 组件（SSE 驱动）
- [ ] "触发分解"按钮交互
- [ ] "派发"按钮 + 结果反馈弹窗
- [ ] 派发后跳转到 Kanban 看板

### Phase 6：Kanban 扩展

- [ ] TaskCard 增加父子关系标识
- [ ] 按 Issue 筛选下拉
- [ ] Issue 全部完成后自动关闭（SSE 驱动）
- [ ] 进度同步到 Issue 详情页

### Phase 7：Project 层（可选，优先级较低）

- [ ] `ProjectsPage`
- [ ] `ProjectDetailPage`
- [ ] Issue 关联 Project

---

## 十一、边界情况与风险控制

### 11.1 分解失败

- Planner 返回结果验证失败 → 保留错误信息到 `Issue.metadata_json.error_log`
- 前端展示错误 + "重试"按钮
- 最多重试 3 次，每次自动降低复杂度（切换策略：hybrid → template_match）

### 11.2 Agent 全部繁忙

- 派发时找不到 idle Agent → 子任务 `agent_id = None`
- Kanban 上显示"待分配"标签
- 前端增加"人工分配 Agent"操作（已有 TaskCard 下拉框）

### 11.3 子任务依赖顺序

- `decomposition_json` 中的 `dependencies: ["uuid-1", ...]`
- 派发时按依赖顺序创建，但**不阻塞**（所有子任务都进 todo 列）
- 前端子任务树中，未完成依赖的项显示灰色（不可开始）

### 11.4 Issue 中途变更需求

- 允许重新分解（覆盖 `decomposition_json`）
- 已创建的子 Task：未开始的可以删除重新创建；已开始的提醒用户确认
- SSE 推送 `issue_redecomposed` 事件

### 11.5 权限控制

- 谁可以创建 Issue：所有用户（或配置）
- 谁可以触发分解：只有 `assigned_agent`（架构师）或用户手动触发
- 谁可以派发：系统自动（分解完成后）或用户手动

---

## 十二、验收标准

### 12.1 功能验收

- [ ] 用户能在 Issue 列表页创建新需求
- [ ] 点击"触发分解"后，架构师 Agent 能在 30 秒内完成分解
- [ ] 分解结果在前端子任务树中正确展示（角色图标、依赖关系）
- [ ] 点击"派发"后，子任务正确出现在 Kanban 的 todo 列
- [ ] Agent 执行子任务时，Issue 详情页进度条实时更新
- [ ] 所有子任务完成后，Issue 状态自动变为 `resolved`
- [ ] SSE 事件在分解、派发、完成各阶段正确推送

### 12.2 性能验收

- [ ] 分解 10 个子任务以内：< 30 秒
- [ ] 派发 10 个子任务：< 3 秒
- [ ] Kanban 看板 50 张卡片：滚动流畅（虚拟滚动）
- [ ] SSE 事件延迟：< 500ms

### 12.3 测试覆盖

- [ ] 模型层单元测试：> 90%
- [ ] API 层集成测试：> 80%
- [ ] 分解引擎测试：覆盖 4 种策略
- [ ] 前端组件测试：覆盖核心交互

---

## 十三、附录：角色图标映射

```typescript
// frontend/src/constants/issue.ts

export const TASK_ROLE_ICONS: Record<string, { icon: string; color: string }> = {
  architecture: { icon: "🏗️", color: "#722ed1" },  // 紫
  frontend:    { icon: "🎨", color: "#1890ff" },  // 蓝
  backend:     { icon: "⚙️",  color: "#52c41a" },  // 绿
  test:        { icon: "🧪", color: "#faad14" },  // 黄
  review:      { icon: "👀", color: "#eb2f96" },  // 粉
  deploy:      { icon: "🚀", color: "#13c2c2" },  // 青
  docs:        { icon: "📝", color: "#8c8c8c" },  // 灰
};
```

---

*本设计文档覆盖了从数据模型、API、前端页面、到与现有系统集成的所有关键环节。实施时建议严格按照 Phase 1~7 的顺序推进，每阶段完成后再进入下一阶段。*
