# AI Agent OS v1.0（工业级 AI 开发操作系统）

## 1. 系统定位

AI Agent OS 是一个“AI 自动软件工厂系统”，用于通过 DeepSeek + WorkBuddy 实现：

- 自动需求拆解
- 自动架构设计
- 自动代码生成
- 自动调度 Agent 执行
- 自动修复与迭代

核心目标：  
👉 从“聊天式 AI”升级为“可持续交付软件的 AI 操作系统”

---

## 2. 总体架构

```
User Request
     ↓
┌──────────────────────┐
│  Intent Router (DeepSeek) │
└──────────────────────┘
     ↓
┌──────────────────────┐
│ WorkBuddy Orchestrator │
└──────────────────────┘
     ↓
┌───────────────┬───────────────┬──────────────┐
│ Planner Agent │ Coder Agent   │ Debug Agent   │
└───────────────┴───────────────┴──────────────┘
     ↓
┌──────────────────────┐
│ Execution Layer (Runtime) │
└──────────────────────┘
     ↓
Frontend / Backend / DB
```

---

## 3. 核心模块设计

### 3.1 Intent Router（DeepSeek）

职责：
- 解析用户需求
- 分类任务类型

输出：

```json
{
  "type": "feature | bugfix | refactor | deploy",
  "complexity": "low | medium | high",
  "modules": ["frontend", "backend", "db"]
}
```

---

### 3.2 WorkBuddy Orchestrator

职责：
- 调度 Agent Node
- 管理执行顺序

标准 Node：

```json
{
  "name": "CoderAgent",
  "input": {},
  "process": "",
  "output": {}
}
```

---

### 3.3 Planner Agent

功能：
- 拆解任务
- 生成模块结构

输出：
- 文件结构树
- API设计
- 数据库设计

---

### 3.4 Coder Agent

功能：
- 生成可运行代码
- 按文件输出
- 严格遵守路径结构

---

### 3.5 Debug Agent

功能：
- 自动读取错误日志
- 修复代码
- 重新生成 patch

规则：
- 不允许只说“检查配置”
- 必须给修复代码

---

## 4. 系统执行循环（核心）

```
while (task not done):

1. Intent Router classify
2. Planner break down
3. WorkBuddy assign nodes
4. Coder generate files
5. Debug verify
6. Re-run if failure
```

---

## 5. 项目目录结构（标准）

```
ai-agent-os/
├── backend/
│   ├── app.py
│   ├── routes/
│   ├── services/
│   └── agents/
│
├── frontend/
│   ├── src/
│   ├── components/
│   └── pages/
│
├── workbuddy/
│   ├── orchestrator.py
│   ├── nodes.json
│
├── prompts/
│   ├── deepseek_router.md
│   ├── coder_prompt.md
│
└── config/
    ├── config.yaml
```

---

## 6. DeepSeek Prompt Router（核心）

### 输入模板：

```
[ROLE]
You are Intent Router for AI Agent OS

[USER REQUEST]
{input}

[OUTPUT RULE]
Return JSON only
```

---

## 7. Agent 调度规则（WorkBuddy）

规则：

- 每个任务必须拆 Node
- Node 必须有 input/process/output
- Node 执行必须串行或 DAG

示例：

```
Planner → Coder → Debug → Coder Fix → Done
```

---

## 8. 自愈系统（Self-Healing）

触发条件：
- runtime error
- API failure
- frontend crash

流程：

1. 捕获 error log
2. Debug Agent 分析
3. 自动生成 patch
4. 重新执行

---

## 9. 执行原则（强约束）

- ❌ 不允许只解释
- ❌ 不允许无文件代码
- ❌ 不允许无路径输出
- ❌ 不允许非结构化输出

- ✅ 必须可运行
- ✅ 必须可部署
- ✅ 必须可扩展

---

## 10. 系统升级方向

下一阶段：

- 多 Agent 并行执行
- 自动 Git 提交系统
- 自动 CI/CD pipeline
- 向量记忆系统（长期项目理解）

---

## 结论

AI Agent OS = LLM + Orchestration + Execution Layer

目标不是“回答问题”，而是：

👉 自动生成软件系统
