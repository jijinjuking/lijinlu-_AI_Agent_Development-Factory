# 前端 → 后端 API 接口映射表

> 版本：v1.0  
> 日期：2026-05-29  
> 用途：确保所有前端 mock 数据字段都有对应的后端 API，防止页面成死页面

---

## 综述

当前 8 个前端页面共使用 **10 组 mock 数据源**，对应 **28+ 个 API 端点**。

后端将分两阶段对接：
- **Phase 1 后端**：提供 RESTful API，返回静态/内存数据（先让前端活起来）
- **Phase 2 后端**：对接真实 PostgreSQL/Redis，动态数据

---

## 1. DashboardPage — 总览仪表盘

| 前端数据字段 | mock 文件 | API 端点 | 方法 | 说明 |
|---|---|---|---|---|
| 统计卡片（6项） | `mock/dashboard.ts > mockStats` | `/api/v1/dashboard/stats` | GET | 活跃Agent数、流程执行次数、完成任务数、Token消耗、累计费用、成功率 |
| 最近活动列表 | `mock/dashboard.ts > mockActivities` | `/api/v1/dashboard/activities` | GET | 最近 N 条活动，支持分页 |

**Dashboard stats 返回结构**：
```json
{
  "activeAgents": 8,
  "pipelineRuns": 47,
  "completedTasks": 156,
  "totalTokens": 2400000,
  "totalCost": 48.50,
  "successRate": 94.2,
  "trends": {
    "agents": 14, "pipelines": 23, "tasks": -5,
    "tokens": 31, "cost": 18, "successRate": 2.1
  }
}
```

**Dashboard activities 返回结构**：
```json
[{
  "id": "act-1",
  "type": "agent_complete | pipeline_run | error | review | agent_start",
  "title": "任务完成",
  "description": "...",
  "agentName": "Dev-01",
  "timestamp": "2026-05-29T08:02:05Z",
  "status": "success | running | failed"
}]
```

---

## 2. AgentsPage — Agent 管理

| 前端数据字段 | mock 文件 | API 端点 | 方法 | 说明 |
|---|---|---|---|---|
| Agent 列表 | `mock/dashboard.ts > mockAgents` | `/api/v1/agents` | GET | 支持 ?status=running&role=developer 过滤 |
| 单个 Agent 详情 | 同上 | `/api/v1/agents/:name` | GET | 含任务统计 |
| 注册 Agent | — | `/api/v1/agents` | POST | Capability-based 注册 |
| 更新 Agent | — | `/api/v1/agents/:name` | PATCH | 更新配置、启用/禁用 |
| Agent 心跳 | — | `/api/v1/agents/:name/heartbeat` | GET | |

**Agent 对象结构**：
```json
{
  "id": "agent-1",
  "name": "Architect-01",
  "role": "architect | developer | tester | reviewer | deployer",
  "status": "running | idle | error | offline",
  "model": "gpt-4o",
  "description": "...",
  "createdAt": "2026-05-20T08:00:00Z",
  "lastActiveAt": "2026-05-29T09:15:00Z",
  "totalTasks": 24,
  "completedTasks": 22,
  "failedTasks": 1,
  "avgDuration": 180000,
  "totalTokens": 125000,
  "totalCost": 2.50
}
```

---

## 3. TracesPage — Trace 执行追踪

| 前端数据字段 | mock 文件 | API 端点 | 方法 | 说明 |
|---|---|---|---|---|
| Trace 列表 | `mock/trace.ts > mockTraceList` | `/api/v1/traces` | GET | 支持 ?status=running&agent=Dev-01 |
| Trace 详情 | `mock/trace.ts > mockTraceDetail` | `/api/v1/traces/:id` | GET | 含统计信息 |
| Trace 节点树 | `mock/trace.ts > mockTraceNodes` | `/api/v1/traces/:id/nodes` | GET | 节点树形结构，用于可视化 |
| 创建 Trace | — | 内部自动 | — | 由 Runtime Kernel 自动创建 |

**Trace 节点结构**：
```json
{
  "id": "n-1-1",
  "parentId": null,
  "type": "chain | agent_action | llm_call | tool_call | error",
  "name": "...",
  "status": "success | running | failed",
  "startTime": "...",
  "endTime": "...",
  "duration": 125000,
  "model": "gpt-4o",           // llm_call 节点专用
  "inputTokens": 1200,          // llm_call 节点专用
  "outputTokens": 800,          // llm_call 节点专用
  "cost": 0.02,                 // llm_call 节点专用
  "toolName": "read_file",      // tool_call 节点专用
  "error": "...",               // error 节点专用
  "input": "...",
  "output": "...",
  "children": ["n-1-2", "n-1-3"]
}
```

---

## 4. PipelinesPage — 流程编排

| 前端数据字段 | mock 文件 | API 端点 | 方法 | 说明 |
|---|---|---|---|---|
| Pipeline 模板列表 | `mock/pipeline.ts > mockPipelineTemplates` | `/api/v1/pipelines/templates` | GET | 支持 ?category=dev 过滤 |
| 单个模板详情 | 同上 | `/api/v1/pipelines/templates/:id` | GET | 含步骤定义 |
| 运行记录列表 | `mock/pipeline.ts > mockPipelineRuns` | `/api/v1/pipelines/runs` | GET | 支持 ?status=running |
| 启动 Pipeline | — | `/api/v1/pipelines/run` | POST | 选择模板 + 传入参数 |
| 暂停/恢复/取消 | — | `/api/v1/pipelines/runs/:id/pause` | POST | |
| 运行详情 | — | `/api/v1/pipelines/runs/:id` | GET | |

**Pipeline 模板结构**：
```json
{
  "id": "tpl-1",
  "name": "新功能开发全流程",
  "description": "...",
  "icon": "CodeOutlined",
  "category": "dev | ops | review | data | custom",
  "tags": ["开发", "全流程"],
  "steps": [{
    "id": "s1",
    "name": "需求分析",
    "type": "agent | condition | parallel | review | deploy | notify",
    "agentRole": "architect",
    "description": "...",
    "nextSteps": ["s2"]
  }],
  "avgDuration": 720000,
  "successRate": 94.5
}
```

---

## 5. SkillsPage — Skill 市场

| 前端数据字段 | mock 文件 | API 端点 | 方法 | 说明 |
|---|---|---|---|---|
| Skill 列表 | `mock/skills.ts > mockSkills` | `/api/v1/skills` | GET | 支持 ?category=code&installed=true&q=搜索词 |
| Skill 详情 | 同上 | `/api/v1/skills/:id` | GET | |
| 安装 Skill | — | `/api/v1/skills/:id/install` | POST | |
| 卸载 Skill | — | `/api/v1/skills/:id/uninstall` | POST | |
| 配置 Skill | — | `/api/v1/skills/:id/config` | PATCH | |

**Skill 对象结构**：
```json
{
  "id": "sk-1",
  "name": "Code Review Expert",
  "description": "...",
  "category": "code | data | ops | communication | security | media",
  "icon": "CodeOutlined",
  "author": "AI-OS Team",
  "version": "2.3.1",
  "downloads": 12400,
  "rating": 4.8,
  "installed": true,
  "size": "2.4 MB",
  "tags": ["审查", "安全"],
  "updatedAt": "2026-05-28",
  "requiresConfig": true,
  "configFields": ["review_rules", "severity_threshold"]
}
```

---

## 6. MemoryPage — 三层记忆管理

| 前端数据字段 | mock 文件 | API 端点 | 方法 | 说明 |
|---|---|---|---|---|
| 记忆条目列表 | `mock/memory.ts > mockMemories` | `/api/v1/memory` | GET | 支持 ?layer=cloud|user|project&q=搜索&importance=high |
| 记忆统计 | 同上（需汇总） | `/api/v1/memory/stats` | GET | 各层级条目数、总 Token 估算 |
| 创建记忆 | — | `/api/v1/memory` | POST | |
| 更新记忆 | — | `/api/v1/memory/:id` | PATCH | |
| 删除记忆 | — | `/api/v1/memory/:id` | DELETE | |

**Memory 对象结构**：
```json
{
  "id": "mem-c1",
  "layer": "cloud | user | project",
  "title": "技术栈偏好",
  "content": "...",
  "tags": ["技术栈", "偏好"],
  "createdAt": "2026-05-20",
  "updatedAt": "2026-05-28",
  "source": "自动学习 | 手动设置 | 工作日志",
  "importance": "high | medium | low",
  "tokenEstimate": 120
}
```

---

## 7. CostsPage — 成本分析

| 前端数据字段 | mock 文件 | API 端点 | 方法 | 说明 |
|---|---|---|---|---|
| 费用概览 | `mock/costs.ts > mockCostSummary` | `/api/v1/costs/summary` | GET | ?period=today|week|month |
| 费用明细列表 | `mock/costs.ts > mockCostRecords` | `/api/v1/costs/records` | GET | 支持分页、日期范围、agent/model 过滤 |
| 按模型汇总 | `mock/costs.ts > mockModelCostSummary` | `/api/v1/costs/by-model` | GET | ?period=month |
| 按 Agent 汇总 | `mock/costs.ts > mockAgentCostSummary` | `/api/v1/costs/by-agent` | GET | ?period=month |
| 每日趋势 | `mock/costs.ts > mockDailyCostTrend` | `/api/v1/costs/trend` | GET | ?days=7 |
| 模型定价表 | `mock/costs.ts > mockModelPricing` | `/api/v1/costs/pricing` | GET | |

---

## 8. SettingsPage — 系统设置

| 前端数据字段 | mock 文件 | API 端点 | 方法 | 说明 |
|---|---|---|---|---|
| LLM 模型配置 | `mock/settings.ts > mockModelConfigs` | `/api/v1/settings/models` | GET | |
| 更新模型配置 | — | `/api/v1/settings/models/:id` | PATCH | 启用/禁用、修改温度 |
| API Key 列表 | `mock/settings.ts > mockApiKeys` | `/api/v1/settings/api-keys` | GET | maskedKey 已脱敏 |
| 添加 API Key | — | `/api/v1/settings/api-keys` | POST | |
| 删除 API Key | — | `/api/v1/settings/api-keys/:id` | DELETE | |
| Agent 权限列表 | `mock/settings.ts > mockAgentPermissions` | `/api/v1/settings/permissions` | GET | |
| 更新权限 | — | `/api/v1/settings/permissions/:roleId` | PATCH | |

---

## 9. 实时推送（WebSocket）

当前 mock 不涉及，但开发计划要求的实时功能：

| 连接 | 端点 | 方向 | 说明 |
|---|---|---|---|
| 任务事件流 | `ws://host/api/v1/ws/tasks/:tid` | 服务端→客户端 | task_started, node_entered, llm_call_complete, artifact_created, approval_needed, task_completed |
| 审批响应 | 同上 | 客户端→服务端 | submit_approval |

---

## 对接策略

```
Phase 1 后端：所有 API 返回 mock 等效数据（内存/SQLite），让前端先"活"起来
Phase 2 后端：切换到 PostgreSQL + Redis，数据变成真实的 Agent 执行结果
Phase 3 后端：WebSocket 实时推送接入
```

---

## 附录：数据模型汇总

从 mock 数据中提取的核心实体：

| 实体 | 主要字段 | 对应 DB 表 |
|---|---|---|
| Agent | id, name, role, status, model, stats | `agents` |
| Task | id, title, agentId, status, priority, stats | `tasks` |
| Trace | id, pipelineId, agentId, status, nodes | `events` + 计算 |
| TraceNode | id, parentId, type, status, duration, model/cost | 同上 |
| PipelineTemplate | id, name, category, steps[] | `pipeline_templates` |
| PipelineRun | id, templateId, status, progress | `pipeline_runs` |
| Skill | id, name, category, installed, rating | `skills` |
| Memory | id, layer, title, content, tags | `project_memories` (Qdrant) + `user_memories` |
| CostRecord | id, agentId, model, tokens, cost | `llm_calls` |
| ModelConfig | id, name, provider, enabled | `model_configs` |
| ApiKey | id, provider, maskedKey | `api_keys` |
| AgentPermission | roleId, permissions | `agent_permissions` |
