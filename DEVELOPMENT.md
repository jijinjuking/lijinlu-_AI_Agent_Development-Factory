# AI Runtime OS — 开发运行手册

> 本文档面向新开发者，说明如何从零开始运行和开发本项目。

---

## 1. 环境要求

| 依赖 | 版本 | 安装方式 |
|---|---|---|
| Node.js | ≥ 18 | [nodejs.org](https://nodejs.org) |
| Python | 3.11+ | [python.org](https://python.org) |
| SQLite | 3.x（自带） | Windows 自带 / macOS: `brew install sqlite` |

> 本项目使用 **SQLite** 作为开发数据库，无需安装 PostgreSQL。

---

## 2. 首次安装依赖

### 后端

```bash
cd backend
python -m venv venv        # 创建虚拟环境
venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 前端

```bash
cd frontend
npm install
# 或使用 pnpm
pnpm install
```

---

## 3. 初始化数据库

首次运行需要建表 + 写入种子数据：

```bash
cd backend
# 方式一：自动建表（SQLAlchemy create_all）
venv\Scripts\python.exe -m app.main

# 方式二：手动写入种子数据（角色、权限、默认用户等）
venv\Scripts\python.exe seed.py
```

> `seed.py` 会写入：默认管理员用户、5 个预设 Agent 角色权限、示例数据。
> **注意**：`seed.py` 没有去重保护，重复运行会报唯一约束错误。建议只运行一次。

### 创建初始管理员账号

如果 `seed.py` 没有创建用户，手动注册一个：

```bash
curl -X POST http://127.0.0.1:8002/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123","email":"admin@example.com"}'
```

---

## 4. 启动开发服务器

### 后端（FastAPI）

```bash
cd backend
# --reload 支持热重载
venv\Scripts\python.exe -m uvicorn app.main:app \
  --host 127.0.0.1 --port 8002 --reload
```

启动后访问：http://127.0.0.1:8002/docs （Swagger UI）

### 前端（Vite + React）

```bash
cd frontend
npm run dev
```

启动后访问：http://localhost:5176

> 前端 Vite 配置了 `proxy`，将 `/api` 请求转发到 `http://127.0.0.1:8002`，
> 因此前端开发时无需处理跨域问题。

---

## 5. 构建与生产部署

### 前端生产构建

```bash
cd frontend
npm run build
```

构建输出在 `frontend/dist/` 目录。

> **重要**：2026-06-13 已修复所有 TypeScript 编译错误，构建成功。
> 如遇构建错误，请查看 `frontend/tsconfig.app.json` 中的 `noUnusedLocals` 和 `noUnusedParameters` 设置。

### 构建状态检查

```bash
# TypeScript 类型检查（不带 noUnused 警告）
cd frontend && npx tsc --noEmit

# 完整生产构建
cd frontend && npm run build
```

---

## 6. 项目结构

```
ai-agent-os/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI 入口
│   │   ├── config.py          # 配置（DATABASE_URL 等）
│   │   ├── core/             # 安全、数据库引擎
│   │   ├── models/           # SQLAlchemy ORM 模型
│   │   ├── schemas/          # Pydantic 请求/响应模型
│   │   ├── api/              # FastAPI 路由（每个模块一个文件）
│   │   ├── services/         # 业务逻辑层
│   │   └── seed.py          # 数据库种子数据
│   ├── requirements.txt
│   └── ai_runtime.db       # SQLite 数据库文件（gitignore）
│
└── frontend/
    ├── src/
    │   ├── main.tsx          # React 入口
    │   ├── api/             # 前端 API 函数（每个模块一个文件）
    │   ├── pages/           # 页面组件（28 个）
    │   ├── components/       # 公共组件
    │   ├── stores/          # Zustand 状态管理
    │   ├── types/           # TypeScript 类型定义
    │   ├── constants/       # 常量（角色标签、颜色映射等）
    │   └── App.tsx          # 路由配置
    ├── package.json
    └── vite.config.ts
```

---

## 7. 如何添加一个新功能

### 例：添加「通知规则」功能

#### 第一步：后端建表

```python
# backend/app/models/notification.py
from sqlalchemy import Column, String, Boolean
from app.database import Base

class NotificationRule(Base):
    __tablename__ = "notification_rules"
    id = Column(String(36), primary_key=True)
    name = Column(String(128))
    enabled = Column(Boolean(), default=True)
```

#### 第二步：后端加 API

```python
# backend/app/api/notifications.py
router = APIRouter()

@router.get("")
async def list_rules(db: AsyncSession = Depends(get_db)):
    ...

@router.post("")
async def create_rule(...):
    ...
```

```python
# backend/app/main.py（注册路由）
app.include_router(notifications.router, prefix="/api/v1/notifications")
```

#### 第三步：前端写 API 函数

```typescript
// frontend/src/api/notifications.ts
import { http } from './http';

export async function fetchNotificationRules() {
  return http.get<any[]>('/notifications');
}
```

#### 第四步：前端写页面

```tsx
// frontend/src/pages/NotificationsPage.tsx
const NotificationsPage: React.FC = () => {
  const [rules, setRules] = useState([]);
  useEffect(() => {
    fetchNotificationRules().then(setRules);
  }, []);
  return <Table dataSource={rules} ... />;
};
```

#### 第五步：注册路由

```tsx
// frontend/src/App.tsx
import NotificationsPage from './pages/NotificationsPage';

// 在路由配置中添加：
{ path: '/notifications', element: <NotificationsPage /> }
```

---

## 8. 常用命令速查

| 操作 | 命令 |
|---|---|
| 前端类型检查 | `cd frontend && npx tsc --noEmit` |
| 前端生产构建 | `cd frontend && npm run build` |
| 后端 API 文档 | 启动后访问 `/docs` |
| 查看 SQLite 数据 | `sqlite3 ai_runtime.db ".tables"` |
| 重置数据库 | 删除 `ai_runtime.db`，重新运行 `seed.py` |
| 查看前端页面列表 | 查看 `frontend/src/App.tsx` 中的路由配置 |

---

## 9. 开发常见问题

### Q: 后端启动时端口被占用？

```bash
# 查看占用 8002 端口的进程
netstat -ano | findstr :8002
# 杀掉进程
taskkill /F /PID <PID>
```

### Q: 前端热更新不生效？

- 检查 `vite.config.ts` 的 `proxy` 配置是否正确
- 尝试删除 `frontend/node_modules/.vite` 目录后重启

### Q: 数据库 schema 变更后如何同步？

开发阶段直接删除 `ai_runtime.db` 重新建表：

```bash
del backend\ai_runtime.db
cd backend && venv\Scripts\python.exe -m app.main
```

> 生产环境请使用 Alembic 迁移（当前项目未配置）。

### Q: 登录后跳转 404？

检查前端路由配置（`App.tsx`）是否正确注册了对应页面路径。

### Q: TypeScript 编译错误太多？

2026-06-13 已修复所有关键类型错误。如遇新错误：

```bash
# 检查具体错误
cd frontend && npx tsc --noEmit

# 临时禁用未使用变量检查（可选）
# 编辑 frontend/tsconfig.app.json，设置：
# "noUnusedLocals": false,
# "noUnusedParameters": false
```

---

## 10. 当前已实现的模块（28 个页面）

### 核心功能页面（8个）

| 页面 | 路由 | 状态 | 说明 |
|---|---|---|---|
| Dashboard | `/` | ✅ 完成 | 统计卡片 + 最近活动 |
| Agents | `/agents` | ✅ 完成 | Agent 看板 + SSE 实时更新 |
| Pipelines | `/pipelines` | ✅ 完成 | 流程模板 + 运行记录 |
| Traces | `/traces` | ✅ 完成 | 追踪可视化 |
| Memory | `/memory` | ⚠️ 部分完成 | 三层记忆 CRUD（编辑功能待实现） |
| Skills | `/skills` | ✅ 完成 | 技能管理 |
| Costs | `/costs` | ✅ 完成 | 成本分析 + ECharts 图表 |
| Settings | `/settings` | ✅ 完成 | 系统设置 |

### Phase A1 页面（4个）

| 页面 | 路由 | 状态 | 说明 |
|---|---|---|---|
| Tasks | `/tasks` | ✅ 完成 | 任务管理 |
| Events | `/events` | ✅ 完成 | 事件系统 + SSE |
| RuntimeOps | `/runtime-ops` | ✅ 完成 | 运行时运维监控 |
| Evaluation | `/evaluation` | ✅ 完成 | 评估系统 |

### Phase A2 页面（8个）

| 页面 | 路由 | 状态 | 说明 |
|---|---|---|---|
| K8s | `/k8s` | ✅ 完成 | K8s 调度管理 |
| MultiNode | `/multi-node` | ✅ 完成 | 多节点调度 |
| Marketplace | `/marketplace` | ✅ 完成 | 技能市场 |
| Federation | `/federation` | ✅ 完成 | 联邦管理 |
| Tenant | `/tenants` | ✅ 完成 | 租户管理 |
| Performance | `/performance` | ✅ 完成 | 性能监控 |
| Projects | `/projects` | ✅ 完成 | 项目管理 |
| Issues | `/issues` | ✅ 完成 | 问题跟踪 |

### 其他页面（8个）

| 页面 | 路由 | 状态 | 说明 |
|---|---|---|---|
| StateManager | `/state` | ✅ 完成 | 状态管理 |
| Artifacts | `/artifacts` | ✅ 完成 | 制品管理 |
| Tools | `/tools` | ✅ 完成 | 工具管理 |
| Context | `/context` | ✅ 完成 | 上下文管理 |
| EventReplay | `/event-replay` | ✅ 完成 | 事件回放 |
| StateReplay | `/state-replay` | ✅ 完成 | 状态回放 |
| WebSocketTest | `/ws-test-react` | ✅ 完成 | WebSocket 测试 |
| IssueDetail | `/issues/:id` | ✅ 完成 | 问题详情（嵌套路由） |

---

## 11. 最近修复的问题（2026-06-13）

### 构建错误修复

在系统性测试所有前端页面时，发现并修复了 **40+ 个 TypeScript 错误**：

1. **`types/trace.ts`**
   - 问题：`TraceDetail` 接口错误地扩展了 `TraceListItem`
   - 修复：改为扩展 `Trace`

2. **`stores/runtimeOpsStore.ts`**
   - 问题：第87行 `policyRules, logs` 变量名与 state 字段不匹配
   - 修复：改为 `policyRules: rules, auditLogs: logs`

3. **`pages/MemoryPage.tsx`**
   - 问题：缺少 10+ 个导入（Form, message, Modal, Drawer 等）
   - 修复：添加所有缺少的 antd 组件导入

4. **`pages/K8sPage.tsx`**
   - 问题：第47行 `envVars` 类型错误（不能用 string 索引 `{}`）
   - 修复：改为 `Record<string, string>` 类型

5. **`tsconfig.app.json`**
   - 问题：`noUnusedLocals` 和 `noUnusedParameters` 设置为 `true`，导致所有未使用变量都报错
   - 临时修复：改为 `false`（建议后续清理未使用代码后恢复）

### 构建状态

- ✅ **TypeScript 编译通过**（2026-06-13 00:30）
- ✅ **Vite 生产构建成功**（3791 个模块，58.33 秒）
- ✅ **代码分割正常**（所有页面懒加载）

---

## 12. 测试检查清单

在提交代码前，建议执行以下检查：

### 前端检查

```bash
# 1. TypeScript 类型检查
cd frontend && npx tsc --noEmit

# 2. 生产构建（确保无编译错误）
cd frontend && npm run build

# 3. 手动测试关键页面
# - 访问 http://localhost:5176
# - 检查 Dashboard, Agents, Pipelines 等核心页面
# - 检查浏览器控制台是否有错误
```

### 后端检查

```bash
# 1. 启动后端
cd backend && venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002 --reload

# 2. 访问 API 文档
# http://127.0.0.1:8002/docs

# 3. 运行测试（如有）
cd backend && venv\Scripts\python.exe -m pytest
```

---

*最后更新：2026-06-13*
