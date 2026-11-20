"""
AI Runtime OS — Issue Schema
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---- 基础 ----
class IssueBase(BaseModel):
    project_id: str
    title: str = Field(max_length=255)
    description: str = ""
    priority: str = Field(default="medium", pattern=r"^(critical|high|medium|low)$")
    assigned_agent_id: str | None = None
    decomposition_strategy: str | None = Field(
        default=None,
        pattern=r"^(template_match|llm_generate|hybrid|query_expansion)?$",
    )


# ---- 创建 ----
class IssueCreate(IssueBase):
    created_by: str = ""


# ---- 更新 ----
class IssueUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = Field(
        default=None,
        pattern=r"^(open|in_progress|pending_review|resolved|closed)$",
    )
    priority: str | None = Field(default=None, pattern=r"^(critical|high|medium|low)$")
    assigned_agent_id: str | None = None
    decomposition_strategy: str | None = None


# ---- 分解请求 ----
class IssueDecomposeRequest(BaseModel):
    strategy: str = Field(
        default="hybrid",
        pattern=r"^(template_match|llm_generate|hybrid|query_expansion)$",
    )


# ---- 派发请求 ----
class IssueDispatchRequest(BaseModel):
    task_tree: dict | None = None  # 可选：手动调整后的任务树
    auto_assign: bool = True


# ---- 响应 ----
class IssueResponse(IssueBase):
    id: str
    status: str = "open"
    created_by: str = ""
    assigned_agent_name: str | None = None

    # 分解结果
    decomposition_strategy: str | None = None
    task_tree: str | None = None  # JSON string，前端解析
    decomposed_at: str | None = None

    # 时间戳
    created_at: str = ""
    updated_at: str = ""
    resolved_at: str | None = None

    # 统计
    task_count: int = 0
    completed_task_count: int = 0

    # 附件
    attachments: list["AttachmentResponse"] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


# ---- 评论 ----
class CommentCreate(BaseModel):
    content: str = Field(min_length=1)
    author: str = "system"
    parent_id: str | None = None


class CommentResponse(BaseModel):
    id: str
    issue_id: str
    content: str
    author: str
    parent_id: str | None = None
    created_at: str = ""
    updated_at: str = ""

    model_config = ConfigDict(from_attributes=True)


# ---- 附件 ----
class AttachmentResponse(BaseModel):
    """附件响应"""
    id: str
    issue_id: str
    filename: str
    file_type: str
    file_size: int
    created_at: str

    model_config = ConfigDict(from_attributes=True)


# ---- 子任务树节点（前端渲染用）----
class TaskTreeNode(BaseModel):
    id: str
    name: str
    title: str | None = None
    role: str = ""
    status: str = "pending"
    kanban_column: str = "todo"
    agent_name: str | None = None
    children: list["TaskTreeNode"] = Field(default_factory=list)
