# Issue 附件上传功能 — 开发设计文档

> 版本：v1.0
> 日期：2026-06-13
> 作者：AI Runtime OS 开发组
> 状态：待审核
> 对应需求：用户需在创建 Issue 时上传开发文档（DOCX/PDF/MD/TXT），供架构师 Agent 分解任务时作为上下文参考

---

## 目录

1. [需求背景](#1-需求背景)
2. [现状分析](#2-现状分析)
3. [设计方案](#3-设计方案)
4. [数据库设计](#4-数据库设计)
5. [后端设计](#5-后端设计)
6. [前端设计](#6-前端设计)
7. [集成方案](#7-集成方案)
8. [测试方案](#8-测试方案)
9. [实施顺序](#9-实施顺序)
10. [风险与注意事项](#10-风险与注意事项)

---

## 1. 需求背景

### 1.1 问题描述

当前系统创建 Issue（需求/提案）时，描述字段仅为**纯文本框**，用户无法上传配套的开发文档。

用户的实际场景：
- 已有完整的开发方案文档（PRD、架构设计、API设计、数据库设计等，共 14 份 DOCX 文档）
- 期望将这些文档作为上下文喂给架构师 Agent
- 架构师 Agent 分解任务时能参考这些文档内容，生成更准确的任务树

### 1.2 目标

1. 用户能在创建 Issue 时（以及创建后）上传文档附件
2. 系统自动提取附件文本内容，存入数据库
3. 架构师 Agent 分解 Issue 时，自动读取附件内容作为上下文
4. Issue 详情页展示附件列表，支持下载和删除

### 1.3 范围

| 范围 | 包含 | 不包含 |
|------|------|--------|
| 文件类型 | DOCX、PDF、MD、TXT | 图片、视频、压缩包 |
| 上传位置 | Issue 创建页、Issue 详情页 | Task 附件、Project 附件 |
| 文本提取 | 自动提取并存储 | 不做了在线预览（只存文本） |
| Agent 集成 | 分解时注入附件内容 | 不涉及 Vector 检索（v1 直接拼文本） |

---

## 2. 现状分析

### 2.1 Issue 相关数据模型

**现有 `issues` 表关键字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键 |
| `project_id` | UUID | 所属项目 |
| `title` | String | 标题 |
| `description` | Text | 描述（纯文本） |
| `status` | Enum | open → in_progress → pending_review → resolved |
| `priority` | Enum | critical / high / medium / low |
| `assigned_agent_id` | UUID | 分配的架构师 Agent |
| `task_tree_json` | JSON | 分解后的任务树 |
| `decomposition_strategy` | String | 分解策略 |
| `created_by` | UUID | 创建人 |

**问题：** 没有附件相关字段，也没有关联表。

### 2.2 现有上传能力

| 能力 | 状态 | 说明 |
|------|------|------|
| Artifact Store | ✅ 有 | 但绑定 `task_id`，Issue 阶段无 task_id |
| Context Engine | ✅ 有 | 但无文件上传 API 入口 |
| 前端 Upload 组件 | ❌ 无 | Issues 页面无上传组件 |
| 后端文件上传 API | ❌ 无 | 无 `multipart/form-data` 处理 |

### 2.3 架构师 Agent 分解流程（当前）

```
用户点"分解"按钮
  → POST /api/v1/issues/{id}/decompose
  → IssueDecomposer.decompose(issue_id)
  → _build_goal(issue): 读取 issue.title + issue.description
  → 调用 LLM 生成任务树
  → 存 task_tree_json
```

**问题：** `_build_goal()` 只读了 `title` 和 `description`，没有读附件。

---

## 3. 设计方案

### 3.1 设计决策

**决策：新建独立表 `issue_attachments`，不复用 Artifact Store**

理由：
1. Artifact Store 的 `save()` 方法强制要求 `task_id`，Issue 阶段无 task_id
2. Artifact 存储路径是 `data/artifacts/{task_id}/...`，无 task_id 时路径无法生成
3. 改动 Artifact Store 会牵连所有现有调用方，成本高且风险大
4. Issue 附件是**输入文档**，Artifact 是**任务产物**，概念上应分离
5. 独立表更灵活，后续可扩展版本管理、权限控制等

### 3.2 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│  前端 IssuesPage / IssueDetailPage                          │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Upload 组件（Ant Design Upload）                    │   │
│  │  → beforeUpload 返回 false（阻止自动上传）          │   │
│  │  → 手动构造 FormData → 调 uploadAttachment API     │   │
│  └─────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────┘
                         │ multipart/form-data
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  后端 POST /api/v1/issues/{issue_id}/attachments           │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  1. 接收 UploadFile                                 │   │
│  │  2. 校验文件类型 + 大小                             │   │
│  │  3. 保存文件到 data/issue_attachments/{issue_id}/   │   │
│  │  4. 提取文本内容（按文件类型）                      │   │
│  │  5. 写入 issue_attachments 表                       │   │
│  │  6. 返回 AttachmentResponse                          │   │
│  └─────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  数据库                                                    │
│  ┌─────────────────────┐  ┌──────────────────────────┐    │
│  │  issues              │  │  issue_attachments       │    │
│  │  (已有)             │  │  (新建)                  │    │
│  │  id  ──────────────┼──┤  issue_id (FK)          │    │
│  │  ...                │  │  filename                │    │
│  └─────────────────────┘  │  file_type               │    │
│                            │  file_size               │    │
│                            │  file_path               │    │
│                            │  content_text            │    │
│                            │  content_hash            │    │
│                            │  id (PK)                │    │
│                            │  created_at              │    │
│                            │  updated_at              │    │
│                            └──────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  分解时集成                                                │
│  IssueDecomposer._build_goal()                             │
│  → 查询 issue_attachments                                  │
│  → 拼接 content_text 到 goal.raw_text                      │
│  → LLM 参考附件内容生成任务树                              │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 文件存储方案

**存储位置：** `data/issue_attachments/{issue_id}/{attachment_id}/{filename}`

**目录结构示例：**
```
data/
  issue_attachments/
    issue_001/
      att_001/
        PRD文档.docx
      att_002/
        架构设计.md
```

**为什么这样设计：**
- 按 issue_id 分目录，便于管理和清理
- 按 attachment_id 分子目录，避免同名文件覆盖
- 原始文件保留，支持下载

### 3.4 文本提取方案

| 文件类型 | 提取方式 | Python 库 |
|----------|----------|-----------|
| `.txt` / `.md` | 直接 `read()`，UTF-8 编码 | 内置 |
| `.docx` | 读取所有 paragraph 文本 | `python-docx` |
| `.pdf` | 逐页提取文本 | `PyPDF2` |
| 其他 | 拒绝上传 | — |

**注意：** v1 不做 Vector 检索，直接把附件文本拼接到 `goal.raw_text`。如果附件内容很长（超过 LLM context window），后续需做摘要或 RAG。

---

## 4. 数据库设计

### 4.1 新建表：`issue_attachments`

```sql
CREATE TABLE issue_attachments (
    id CHAR(36) PRIMARY KEY,          -- UUID hex string
    issue_id CHAR(36) NOT NULL,       -- FK → issues.id
    filename VARCHAR(255) NOT NULL,    -- 原始文件名
    file_type VARCHAR(32) NOT NULL,   -- docx / pdf / md / txt
    file_size INTEGER NOT NULL,        -- 字节数
    file_path VARCHAR(512) NOT NULL,   -- 存储路径（相对路径）
    content_text TEXT,                 -- 提取的文本内容
    content_hash VARCHAR(64),          -- SHA256，去重/校验用
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (issue_id) REFERENCES issues(id) ON DELETE CASCADE
);

CREATE INDEX idx_issue_attachments_issue_id ON issue_attachments(issue_id);
```

### 4.2 模型类定义

**文件：** `backend/app/models/issue_attachment.py`（新建）

```python
from sqlalchemy import Column, String, Integer, Text, ForeignKey
from sqlalchemy.orm import relationship
from backend.app.models.base import UUIDPrimaryKey, TimestampMixin, Base

class IssueAttachment(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "issue_attachments"

    issue_id = Column(String(36), ForeignKey("issues.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(32), nullable=False)
    file_size = Column(Integer, nullable=False)
    file_path = Column(String(512), nullable=False)
    content_text = Column(Text)
    content_hash = Column(String(64))

    # 关系
    issue = relationship("Issue", back_populates="attachments")
```

### 4.3 Issue 模型补充

**文件：** `backend/app/models/issue.py`（修改）

在 Issue 模型类中追加：

```python
attachments = relationship("IssueAttachment", back_populates="issue", cascade="all, delete-orphan")
```

---

## 5. 后端设计

### 5.1 文件存储工具函数

**新建文件：** `backend/app/utils/file_storage.py`

```python
import os
import hashlib
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ATTACHMENTS_DIR = BASE_DIR / "data" / "issue_attachments"

def save_upload_file(upload_file, issue_id: str, attachment_id: str) -> tuple[str, str, int]:
    """
    保存上传文件到本地存储。
    返回：(file_path, content_hash, file_size)
    """
    # 创建目录
    dir_path = ATTACHMENTS_DIR / issue_id / attachment_id
    dir_path.mkdir(parents=True, exist_ok=True)

    # 保存文件
    file_path = dir_path / upload_file.filename
    content = await upload_file.read()
    file_path.write_bytes(content)

    # 计算 hash
    content_hash = hashlib.sha256(content).hexdigest()
    file_size = len(content)

    # 返回相对路径（存数据库用）
    rel_path = f"data/issue_attachments/{issue_id}/{attachment_id}/{upload_file.filename}"
    return rel_path, content_hash, file_size

def delete_attachment_file(issue_id: str, attachment_id: str):
    """删除附件文件目录"""
    dir_path = ATTACHMENTS_DIR / issue_id / attachment_id
    if dir_path.exists():
        import shutil
        shutil.rmtree(dir_path)
```

### 5.2 文本提取工具函数

**新建文件：** `backend/app/utils/text_extractor.py`

```python
import docx
import PyPDF2
from io import BytesIO

async def extract_text_from_file(file_path: str, file_type: str) -> str:
    """
    根据文件类型提取文本内容。
    """
    if file_type in ("txt", "md"):
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    elif file_type == "docx":
        doc = docx.Document(file_path)
        return "\n".join([p.text for p in doc.paragraphs])

    elif file_type == "pdf":
        text_parts = []
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text_parts.append(page.extract_text() or "")
        return "\n".join(text_parts)

    else:
        raise ValueError(f"不支持的文件类型: {file_type}")
```

### 5.3 Schema 定义

**修改文件：** `backend/app/schemas/issue.py`（在文件末尾追加）

```python
# ─── 附件相关 Schema ─────────────────────────────────────────

class AttachmentResponse(BaseModel):
    """附件响应（返回给前端）"""
    attachment_id: str = Field(..., alias="id")
    issue_id: str
    filename: str
    file_type: str
    file_size: int
    created_at: str

    class Config:
        orm_mode = True
        allow_population_by_field_name = True

class AttachmentUploadResponse(AttachmentResponse):
    """上传成功后的响应（含下载链接）"""
    download_url: str
    pass

# ─── 修改 IssueResponse ─────────────────────────────────────
# 在 IssueResponse 类中追加字段：

class IssueResponse(BaseModel):
    # ... 现有字段 ...
    attachments: list["AttachmentResponse"] = []  # 追加这一行
```

### 5.4 API 端点设计

**修改文件：** `backend/app/api/issues.py`（追加以下端点）

#### 端点 1：上传附件

```
POST /api/v1/issues/{issue_id}/attachments
Content-Type: multipart/form-data

请求：
  - file: UploadFile（上传的文件）
  - 可附加 description（可选）

响应：200 OK
{
  "id": "attachment-uuid",
  "issue_id": "issue-uuid",
  "filename": "PRD文档.docx",
  "file_type": "docx",
  "file_size": 131072,
  "created_at": "2026-06-13T10:00:00",
  "download_url": "/api/v1/issues/{issue_id}/attachments/{id}/download"
}
```

**实现逻辑：**
1. 校验 issue_id 存在
2. 校验文件类型（只接受 docx/pdf/md/txt）
3. 校验文件大小（≤ 10MB）
4. 调用 `save_upload_file()` 保存文件
5. 调用 `extract_text_from_file()` 提取文本
6. 写入 `issue_attachments` 表
7. 返回响应

#### 端点 2：列出附件

```
GET /api/v1/issues/{issue_id}/attachments

响应：200 OK
[
  {
    "id": "attachment-uuid",
    "issue_id": "issue-uuid",
    "filename": "PRD文档.docx",
    "file_type": "docx",
    "file_size": 131072,
    "created_at": "2026-06-13T10:00:00"
  }
]
```

#### 端点 3：删除附件

```
DELETE /api/v1/issues/{issue_id}/attachments/{attachment_id}

响应：204 No Content
```

**实现逻辑：**
1. 查询 attachment 存在且属于该 issue
2. 删除数据库记录
3. 调用 `delete_attachment_file()` 删除物理文件

#### 端点 4：下载附件

```
GET /api/v1/issues/{issue_id}/attachments/{attachment_id}/download

响应：文件流（Content-Disposition: attachment）
```

### 5.5 集成到 Issue 分解器

**修改文件：** `backend/app/services/issue_decomposer.py`

在 `decompose()` 方法中，构建 `PlanningGoal` 之前，追加附件内容：

```python
async def decompose(self, issue_id: str) -> dict:
    async with async_session() as db:
        # 查询 Issue
        result = await db.execute(select(Issue).where(Issue.id == issue_id))
        issue = result.scalar_one_or_none()
        if not issue:
            raise ValueError(f"Issue {issue_id} 不存在")

        # 【新增】加载附件内容
        att_result = await db.execute(
            select(IssueAttachment)
            .where(IssueAttachment.issue_id == issue_id)
            .order_by(IssueAttachment.created_at)
        )
        attachments = att_result.scalars().all()

        # 构建 goal（传入附件内容）
        goal = await self._build_goal(issue, attachments)

        # ... 后续分解逻辑不变 ...

async def _build_goal(self, issue: Issue, attachments: list = None) -> PlanningGoal:
    """构建分解目标，集成附件内容。"""
    raw_text = f"# {issue.title}\n\n{issue.description}"

    # 【新增】拼接附件内容
    if attachments:
        raw_text += "\n\n# 附件文档内容\n\n"
        for att in attachments:
            if att.content_text:
                raw_text += f"## {att.filename}\n\n{att.content_text}\n\n"

    return PlanningGoal(raw_text=raw_text, ...)
```

### 5.6 数据库迁移

**修改文件：** `backend/app/database.py`

在 `init_db()` 函数中，确保 import 新模型：

```python
from backend.app.models.issue_attachment import IssueAttachment
```

SQLite 支持直接 `CREATE TABLE`（如果表不存在），所以不需要写 ALTER 语句。FastAPI 启动时自动创建新表。

---

## 6. 前端设计

### 6.1 HTTP 工具新增 upload 方法

**修改文件：** `frontend/src/api/http.ts`

```typescript
/**
 * 上传文件（multipart/form-data）
 */
export async function upload<T = any>(path: string, formData: FormData): Promise<T> {
  const token = localStorage.getItem('access_token');
  const headers: Record<string, string> = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  // 注意：不手动设置 Content-Type，让浏览器自动设置 multipart/form-data + boundary

  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers,
    body: formData,
  });

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Upload failed: ${res.status} ${errorText}`);
  }

  return res.json();
}
```

### 6.2 Issues API 新增附件函数

**修改文件：** `frontend/src/api/issues.ts`

```typescript
// ─── 附件类型定义 ───────────────────────────────────────────
export interface Attachment {
  attachment_id: string;
  issue_id: string;
  filename: string;
  file_type: string;
  file_size: number;
  created_at: string;
  download_url?: string;
}

// ─── API 函数 ───────────────────────────────────────────────

/** 上传附件 */
export async function uploadAttachment(issueId: string, file: File): Promise<Attachment> {
  const formData = new FormData();
  formData.append('file', file);
  return upload<Attachment>(`/issues/${issueId}/attachments`, formData);
}

/** 获取 Issue 的所有附件 */
export async function fetchAttachments(issueId: string): Promise<Attachment[]> {
  return get<Attachment[]>(`/issues/${issueId}/attachments`);
}

/** 删除附件 */
export async function deleteAttachment(issueId: string, attId: string): Promise<void> {
  return del<void>(`/issues/${issueId}/attachments/${attId}`);
}

/** 获取下载链接 */
export function getAttachmentDownloadUrl(issueId: string, attId: string): string {
  return `${BASE}/issues/${issueId}/attachments/${attId}/download`;
}
```

同时修改 `Issue` 接口定义，追加 `attachments` 字段：

```typescript
export interface Issue {
  // ... 现有字段 ...
  attachments?: Attachment[];
}
```

### 6.3 Issues Store 新增附件状态

**修改文件：** `frontend/src/stores/issuesStore.ts`

```typescript
import { create } from 'zustand';
import * as issuesApi from '../api/issues';
import type { Issue, Attachment } from '../api/issues';

interface IssuesState {
  // ... 现有状态 ...
  attachments: Attachment[];
  attachmentsLoading: boolean;
}

interface IssuesActions {
  // ... 现有 actions ...
  loadAttachments: (issueId: string) => Promise<void>;
  uploadAttachment: (issueId: string, file: File) => Promise<void>;
  deleteAttachment: (issueId: string, attachmentId: string) => Promise<void>;
}

export const useIssuesStore = create<IssuesState & IssuesActions>((set, get) => ({
  // ... 现有状态初始值 ...
  attachments: [],
  attachmentsLoading: false,

  // ─── 附件相关 actions ──────────────────────────────────

  async loadAttachments(issueId: string) {
    set({ attachmentsLoading: true });
    try {
      const attachments = await issuesApi.fetchAttachments(issueId);
      set({ attachments, attachmentsLoading: false });
    } catch (e: any) {
      set({ attachmentsLoading: false });
      message.error(`加载附件失败: ${e.message}`);
    }
  },

  async uploadAttachment(issueId: string, file: File) {
    try {
      await issuesApi.uploadAttachment(issueId, file);
      message.success(`上传成功: ${file.name}`);
      // 刷新附件列表
      await get().loadAttachments(issueId);
    } catch (e: any) {
      message.error(`上传失败: ${e.message}`);
      throw e;
    }
  },

  async deleteAttachment(issueId: string, attachmentId: string) {
    try {
      await issuesApi.deleteAttachment(issueId, attachmentId);
      message.success('删除成功');
      set(state => ({
        attachments: state.attachments.filter(a => a.attachment_id !== attachmentId)
      }));
    } catch (e: any) {
      message.error(`删除失败: ${e.message}`);
    }
  },
}));
```

### 6.4 IssueDetailPage 新增附件区域

**修改文件：** `frontend/src/pages/IssueDetailPage.tsx`

在页面描述区（`<Typography.Paragraph>` 或 `<pre>` 标签）下方，新增附件卡片：

```tsx
import { Upload, List, Button, Space, Typography } from 'antd';
import {
  PaperClipOutlined,
  DownloadOutlined,
  DeleteOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import { useIssuesStore } from '../stores/issuesStore';

// 在组件内：
const { attachments, loadAttachments, uploadAttachment, deleteAttachment } = useIssuesStore();

// 组件加载时获取附件
useEffect(() => {
  if (issueId) {
    loadAttachments(issueId);
  }
}, [issueId]);

// 上传配置
const uploadProps = {
  accept: '.docx,.pdf,.md,.txt',
  beforeUpload: (file: File) => {
    // 阻止自动上传，手动处理
    handleUpload(file);
    return false;
  },
  showUploadList: false,
};

async function handleUpload(file: File) {
  await uploadAttachment(issueId, file);
}

// 渲染附件列表
function renderAttachments() {
  if (!attachments || attachments.length === 0) {
    return <Typography.Text type="secondary">暂无附件</Typography.Text>;
  }

  return (
    <List
      dataSource={attachments}
      renderItem={(att) => (
        <List.Item
          actions={[
            <Button
              key="download"
              type="link"
              icon={<DownloadOutlined />}
              onClick={() => {
                window.open(getAttachmentDownloadUrl(issueId, att.attachment_id));
              }}
            >
              下载
            </Button>,
            <Button
              key="delete"
              type="link"
              danger
              icon={<DeleteOutlined />}
              onClick={() => deleteAttachment(issueId, att.attachment_id)}
            >
              删除
            </Button>,
          ]}
        >
          <List.Item.Meta
            avatar={<PaperClipOutlined style={{ fontSize: 20 }} />}
            title={att.filename}
            description={`${(att.file_size / 1024).toFixed(1)} KB · ${att.file_type.toUpperCase()} · ${att.created_at}`}
          />
        </List.Item>
      )}
    />
  );
}

// 在 JSX 中（描述区下方）：
<Card title="附件" extra={
  <Upload {...uploadProps}>
    <Button icon={<UploadOutlined />} size="small">上传附件</Button>
  </Upload>
}>
  {renderAttachments()}
</Card>
```

### 6.5 IssuesPage 新建 Issue 时支持附件

**修改文件：** `frontend/src/pages/IssuesPage.tsx`

在新建 Issue 的 Modal 中，`description` 表单项下方新增：

```tsx
<Form.Item label="附件">
  <Upload
    accept=".docx,.pdf,.md,.txt"
    beforeUpload={(file) => {
      // 暂存到组件状态，等 Issue 创建成功后上传
      setPendingFiles(prev => [...prev, file]);
      return false;
    }}
    onRemove={(file) => {
      setPendingFiles(prev => prev.filter(f => f.name !== file.name));
    }}
  >
    <Button icon={<UploadOutlined />}>选择文件</Button>
  </Upload>
  <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
    支持 DOCX、PDF、MD、TXT，单个文件 ≤ 10MB
  </Typography.Text>
</Form.Item>
```

在 `handleCreate` 函数中，创建 Issue 成功后，逐个上传暂存的文件：

```typescript
async function handleCreate(values: any) {
  try {
    const newIssue = await issuesApi.createIssue(values);
    message.success('Issue 创建成功');

    // 【新增】上传暂存的附件
    if (pendingFiles.length > 0) {
      for (const file of pendingFiles) {
        await issuesApi.uploadAttachment(newIssue.issue_id, file);
      }
      setPendingFiles([]);
    }

    setCreateModalVisible(false);
    form.resetFields();
    loadIssues();
  } catch (e: any) {
    message.error(`创建失败: ${e.message}`);
  }
}
```

---

## 7. 集成方案

### 7.1 与 Issue 分解流程的集成

**集成点：** `IssueDecomposer._build_goal()`

**集成方式：**
1. `decompose()` 方法查询 `issue_attachments` 表
2. 将附件的 `content_text` 拼接到 `goal.raw_text`
3. LLM 在生成任务树时能看到附件内容

**拼接格式：**
```
# {Issue 标题}

{Issue 描述}

# 附件文档内容

## PRD文档.docx

{附件1的文本内容}

## 架构设计.md

{附件2的文本内容}
```

### 7.2 与 Issue 派发流程的集成

派发流程（`IssueTaskDispatcher`）本身不需要改动，因为：
- 派发是基于任务树的 `role` 字段分配 Agent
- 附件内容已经通过分解流程影响了任务树的结构
- 派发时不需要再读附件

### 7.3 与前端实时状态的集成

附件上传/删除后，需要刷新 Issue 详情页的附件列表。使用 Zustand store 管理状态，组件内调用 `loadAttachments()` 刷新。

---

## 8. 测试方案

### 8.1 后端单元测试

| 测试对象 | 测试用例 | 预期结果 |
|----------|----------|----------|
| `text_extractor.py` | 提取 TXT 文件 | 返回正确文本 |
| `text_extractor.py` | 提取 MD 文件 | 返回正确文本 |
| `text_extractor.py` | 提取 DOCX 文件 | 返回所有段落文本 |
| `text_extractor.py` | 提取 PDF 文件 | 返回所有页面文本 |
| `text_extractor.py` | 不支持的类型 | 抛出 ValueError |
| `file_storage.py` | 保存文件 | 文件写入正确位置 |
| `file_storage.py` | 删除文件 | 目录被删除 |
| API `/attachments` POST | 上传 DOCX | 返回 200，数据库有记录 |
| API `/attachments` POST | 上传不支持的类型 | 返回 400 |
| API `/attachments` POST | 文件超大（>10MB） | 返回 400 |
| API `/attachments` GET | 列出附件 | 返回附件列表 |
| API `/attachments` DELETE | 删除附件 | 返回 204，文件删除 |
| API `/attachments` DELETE | 删除不存在的附件 | 返回 404 |

### 8.2 集成测试

| 测试场景 | 步骤 | 预期结果 |
|----------|------|----------|
| 上传附件 → 分解 Issue | 1. 创建 Issue 2. 上传附件 3. 点分解 | 任务树内容参考了附件 |
| 上传多个附件 | 上传 3 个文件 | 附件列表显示 3 个 |
| 删除附件后分解 | 删除一个附件再分解 | 任务树不包含已删除附件内容 |
| 创建 Issue 时上传 | 新建 Issue 时同时上传附件 | Issue 创建成功，附件也上传成功 |

### 8.3 前端测试

| 测试对象 | 测试用例 | 预期结果 |
|----------|----------|----------|
| IssueDetailPage | 上传按钮点击 | 文件选择器打开 |
| IssueDetailPage | 上传成功 | 附件列表增加一项 |
| IssueDetailPage | 删除附件 | 确认弹窗 → 删除成功 |
| IssueDetailPage | 下载附件 | 文件下载开始 |
| IssuesPage 新建 Modal | 选择文件 | Upload 组件显示文件名 |
| IssuesPage 新建 Modal | 提交表单 | Issue 创建 + 附件上传 |

---

## 9. 实施顺序

按依赖关系排序，每步完成后可独立测试。

```
步骤 1：安装 Python 依赖
  执行：pip install python-docx PyPDF2
  验证：import docx, PyPDF2 无报错

步骤 2：新建 IssueAttachment 模型
  文件：backend/app/models/issue_attachment.py（新建）
  验证：重启后端，检查 issues_attachments 表已创建

步骤 3：修改 Issue 模型（添加 relationship）
  文件：backend/app/models/issue.py
  验证：无语法错误

步骤 4：新建工具函数
  文件：backend/app/utils/file_storage.py（新建）
  文件：backend/app/utils/text_extractor.py（新建）
  验证：单元测试通过

步骤 5：修改 Schema
  文件：backend/app/schemas/issue.py
  验证：Pydantic 模型校验通过

步骤 6：新增 API 端点
  文件：backend/app/api/issues.py
  验证：用 curl 测试上传/列表/删除/下载

步骤 7：集成到分解器
  文件：backend/app/services/issue_decomposer.py
  验证：上传附件后点分解，检查任务树是否参考了附件

步骤 8：前端 HTTP 工具
  文件：frontend/src/api/http.ts
  验证：TypeScript 编译无报错

步骤 9：前端 Issues API
  文件：frontend/src/api/issues.ts
  验证：TypeScript 编译无报错

步骤 10：前端 Store
  文件：frontend/src/stores/issuesStore.ts
  验证：Zustand store 无报错

步骤 11：IssueDetailPage 附件区域
  文件：frontend/src/pages/IssueDetailPage.tsx
  验证：页面显示附件卡片，可上传/删除/下载

步骤 12：IssuesPage 新建时上传
  文件：frontend/src/pages/IssuesPage.tsx
  验证：新建 Issue 时可同时上传附件

步骤 13：端到端测试
  验证：完整流程走通
```

---

## 10. 风险与注意事项

### 10.1 风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| PDF 文本提取质量差（扫描版 PDF） | Agent 读不到内容 | v1 不支持 OCR，文档需为文本型 PDF |
| 附件内容过长，超过 LLM context window | 分解失败或内容被截断 | v1 直接拼接，后续需做摘要或 RAG |
| 文件上传并发冲突（同一 Issue 同时上传多个文件） | 文件覆盖或数据库死锁 | 用 attachment_id 分子目录，无覆盖风险 |
| python-docx / PyPDF2 未安装 | API 报错 | 步骤 1 必须执行，写进 requirements.txt |

### 10.2 注意事项

1. **文件大小限制：** 当前设为 10MB，可在环境变量配置
2. **文件类型限制：** 只接受 docx/pdf/md/txt，其他类型直接拒绝
3. **文本内容存储：** `content_text` 存数据库，如果内容很长（>64KB）需用 TEXT 类型（已用 TEXT）
4. **原始文件保留：** 不删除原始文件，支持用户下载
5. **删除 Issue 时：** 由于外键 `ON DELETE CASCADE`，附件记录自动删除，但物理文件需手动清理（可在删除 Issue 的 API 中处理）

### 10.3 后续扩展方向

1. **Vector 检索：** 将附件内容存入 Vector DB，分解时做语义检索，避免 context 过长
2. **OCR 支持：** 支持扫描版 PDF
3. **图片附件：** 支持截图、设计稿等图片类型
4. **版本管理：** 同一附件多次上传，保留历史版本
5. **权限控制：** 不同用户对不同 Issue 的附件有不同的读写权限

---

## 附录 A：API 端点完整清单

| 方法 | 路径 | 功能 | 请求体 | 响应 |
|------|------|------|--------|------|
| `POST` | `/api/v1/issues/{id}/attachments` | 上传附件 | `multipart/form-data` | `AttachmentResponse` |
| `GET` | `/api/v1/issues/{id}/attachments` | 列出附件 | — | `AttachmentResponse[]` |
| `DELETE` | `/api/v1/issues/{id}/attachments/{aid}` | 删除附件 | — | `204 No Content` |
| `GET` | `/api/v1/issues/{id}/attachments/{aid}/download` | 下载附件 | — | 文件流 |

## 附录 B：修改文件清单

| 序号 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 1 | `backend/app/models/issue_attachment.py` | 新建 | 附件数据模型 |
| 2 | `backend/app/models/issue.py` | 修改 | 添加 attachments 关系 |
| 3 | `backend/app/utils/file_storage.py` | 新建 | 文件存储工具函数 |
| 4 | `backend/app/utils/text_extractor.py` | 新建 | 文本提取工具函数 |
| 5 | `backend/app/schemas/issue.py` | 修改 | 追加 AttachmentResponse Schema |
| 6 | `backend/app/api/issues.py` | 修改 | 新增 4 个附件端点 |
| 7 | `backend/app/services/issue_decomposer.py` | 修改 | 集成附件内容到分解流程 |
| 8 | `backend/app/database.py` | 修改 | import 新模型 |
| 9 | `frontend/src/api/http.ts` | 修改 | 新增 upload() 方法 |
| 10 | `frontend/src/api/issues.ts` | 修改 | 新增附件 API 函数 |
| 11 | `frontend/src/stores/issuesStore.ts` | 修改 | 新增附件状态管理 |
| 12 | `frontend/src/pages/IssueDetailPage.tsx` | 修改 | 新增附件卡片 UI |
| 13 | `frontend/src/pages/IssuesPage.tsx` | 修改 | 新建时支持上传附件 |

---

> 文档结束。请审核后反馈，确认无误后开始编码实施。
