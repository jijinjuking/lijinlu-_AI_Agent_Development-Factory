"""
AI Runtime OS — Issue API（议题管理 + 分解 + 派发）
"""
from __future__ import annotations

import json
import logging
import shutil
import uuid as uuid_module
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.agent import Agent
from app.models.issue import Issue
from app.models.issue_attachment import IssueAttachment
from app.models.comment import Comment
from app.models.task import Task
from app.models.project import Project
from app.utils.file_storage import ATTACHMENTS_DIR
from app.schemas.issue import (
    IssueCreate,
    IssueDecomposeRequest,
    IssueDispatchRequest,
    IssueResponse,
    IssueUpdate,
    TaskTreeNode,
    CommentCreate,
    CommentResponse,
)
from app.schemas.task import TaskResponse
from app.core.sse_manager import sse_manager
from app.services.issue_decomposer import IssueDecomposer
from app.services.issue_dispatcher import IssueTaskDispatcher, DispatchResult

logger = logging.getLogger("ai_runtime_os.issues")
router = APIRouter()


# ==========================================================================
# SSE 事件辅助
# ==========================================================================

async def _publish_issue_event(
    event_type: str,
    issue_id: str,
    payload: dict | None = None,
) -> None:
    """推送 Issue 相关的 SSE 事件"""
    try:
        await sse_manager.publish(
            event_type,
            payload or {},
            str(issue_id),
        )
    except Exception:
        logger.exception(f"SSE publish failed for {event_type}")


# ==========================================================================
# CRUD
# ==========================================================================

@router.get("/")
async def list_issues(
    project_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None, pattern=r"^(open|in_progress|pending_review|resolved|closed)$"),
    priority: Optional[str] = Query(None, pattern=r"^(critical|high|medium|low)$"),
    db: AsyncSession = Depends(get_db),
):
    """获取 Issue 列表，支持按 project/status/priority 筛选"""
    query = select(Issue).options(
        selectinload(Issue.assigned_agent),
        selectinload(Issue.attachments),
    )
    if project_id:
        try:
            pid = uuid_module.UUID(project_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid project_id format: {project_id}")
        query = query.where(Issue.project_id == pid)
    if status:
        query = query.where(Issue.status == status)
    if priority:
        query = query.where(Issue.priority == priority)

    query = query.order_by(Issue.updated_at.desc())
    result = await db.execute(query)
    issues = result.scalars().all()

    return [
        _issue_to_response(issue) for issue in issues
    ]


@router.post("/")
async def create_issue(
    body: IssueCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建新 Issue"""
    # 验证 project 存在
    proj_result = await db.execute(
        select(Project).where(Project.id == uuid_module.UUID(body.project_id))
    )
    project = proj_result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, f"Project {body.project_id} not found")

    # 验证 Agent（如指定）
    if body.assigned_agent_id:
        agent_result = await db.execute(
            select(Agent).where(Agent.id == body.assigned_agent_id)
        )
        if not agent_result.scalar_one_or_none():
            raise HTTPException(404, f"Agent {body.assigned_agent_id} not found")

    issue = Issue(
        project_id=uuid_module.UUID(body.project_id),
        title=body.title,
        description=body.description,
        priority=body.priority,
        created_by=body.created_by,
        assigned_agent_id=(
            uuid_module.UUID(body.assigned_agent_id)
            if body.assigned_agent_id
            else None
        ),
        decomposition_strategy=body.decomposition_strategy,
    )

    db.add(issue)
    await db.commit()
    await db.refresh(issue, ["assigned_agent", "attachments"])

    await _publish_issue_event("issue_created", str(issue.id))

    return _issue_to_response(issue)


@router.get("/{issue_id}")
async def get_issue(
    issue_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取 Issue 详情"""
    issue = await _get_issue(db, issue_id)
    return _issue_to_response(issue)


@router.patch("/{issue_id}")
async def update_issue(
    issue_id: str,
    body: IssueUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新 Issue"""
    issue = await _get_issue(db, issue_id)

    data = body.model_dump(exclude_unset=True)
    for field, value in data.items():
        if value is not None:
            # 校验 assigned_agent_id 有效性
            if field == "assigned_agent_id":
                result = await db.execute(
                    select(Agent).where(Agent.id == uuid_module.UUID(value))
                )
                if not result.scalar_one_or_none():
                    raise HTTPException(400, f"Agent {value} 不存在")
            setattr(issue, field, value)

    await db.commit()
    await db.refresh(issue, ["assigned_agent", "attachments"])
    return _issue_to_response(issue)


@router.delete("/{issue_id}")
async def delete_issue(
    issue_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除 Issue 及其关联的子任务，同时清理附件物理文件"""
    issue = await _get_issue(db, issue_id)

    # 1. 先清理附件物理文件（在 DB 记录删除之前，避免 issue 对象被删后无法获取 issue_id）
    issue_dir = ATTACHMENTS_DIR / str(issue.id)
    if issue_dir.exists():
        shutil.rmtree(issue_dir, ignore_errors=True)
        logger.info(f"Deleted attachment files for issue {issue.id}: {issue_dir}")

    # 2. 删除关联子任务（DB 记录）
    tasks_result = await db.execute(
        select(Task).where(Task.issue_id == issue.id)
    )
    for task in tasks_result.scalars().all():
        await db.delete(task)

    # 3. 删除 Issue（cascade 自动删除 issue_attachments 表记录）
    await db.delete(issue)
    await db.commit()

    logger.info(f"Issue deleted: {issue_id}")
    return {"ok": True, "deleted_issue_id": issue_id}


# ==========================================================================
# 附件管理
# ==========================================================================

ALLOWED_FILE_TYPES = {"docx", "pdf", "md", "txt"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


@router.post("/{issue_id}/attachments", status_code=201)
async def upload_attachment(
    issue_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传 Issue 附件（支持 DOCX/PDF/MD/TXT，单个文件 ≤ 10MB）"""
    issue = await _get_issue(db, issue_id)

    # 校验文件类型
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_FILE_TYPES:
        raise HTTPException(
            400,
            f"不支持的文件类型: .{ext}，仅支持: {', '.join('.' + t for t in sorted(ALLOWED_FILE_TYPES))}",
        )

    # 校验文件大小
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, f"文件大小超过限制: {len(content)} > {MAX_FILE_SIZE} 字节")

    import hashlib
    import uuid as uuid_mod

    from app.utils.file_storage import save_upload_file
    from app.utils.text_extractor import extract_text_from_file

    att_id = str(uuid_mod.uuid4())

    # 保存文件
    file_path, content_hash, file_size = await save_upload_file(
        _RewindUploadFile(file, content), issue_id, att_id,
    )

    # 提取文本
    from app.utils.file_storage import ATTACHMENTS_DIR
    abs_path = str(ATTACHMENTS_DIR / issue_id / att_id / file.filename)
    try:
        text_content = extract_text_from_file(abs_path, ext)
    except Exception as e:
        logger.warning(f"提取文本失败: {file.filename}, error={e}")
        text_content = None

    # 存数据库
    attachment = IssueAttachment(
        id=uuid_mod.UUID(att_id),
        issue_id=issue.id,
        filename=file.filename,
        file_type=ext,
        file_size=file_size,
        file_path=file_path,
        content_text=text_content,
        content_hash=content_hash,
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)

    return {
        "id": str(attachment.id),
        "issue_id": str(attachment.issue_id),
        "filename": attachment.filename,
        "file_type": attachment.file_type,
        "file_size": attachment.file_size,
        "created_at": attachment.created_at.isoformat() if attachment.created_at else "",
        "download_url": f"/api/v1/issues/{issue_id}/attachments/{att_id}/download",
    }


class _RewindUploadFile:
    """包装 UploadFile，使 save_upload_file 能重新读取内容"""
    def __init__(self, original: UploadFile, content: bytes):
        self.filename = original.filename
        self._content = content

    async def read(self):
        return self._content


@router.get("/{issue_id}/attachments")
async def list_attachments(
    issue_id: str,
    db: AsyncSession = Depends(get_db),
):
    """列出 Issue 所有附件"""
    issue = await _get_issue(db, issue_id)

    result = await db.execute(
        select(IssueAttachment)
        .where(IssueAttachment.issue_id == issue.id)
        .order_by(IssueAttachment.created_at)
    )
    attachments = result.scalars().all()

    return [
        {
            "id": str(att.id),
            "issue_id": str(att.issue_id),
            "filename": att.filename,
            "file_type": att.file_type,
            "file_size": att.file_size,
            "created_at": att.created_at.isoformat() if att.created_at else "",
        }
        for att in attachments
    ]


@router.delete("/{issue_id}/attachments/{attachment_id}")
async def delete_attachment(
    issue_id: str,
    attachment_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除附件（数据库记录 + 物理文件）"""
    issue = await _get_issue(db, issue_id)

    try:
        att_uid = uuid_module.UUID(attachment_id)
    except ValueError:
        raise HTTPException(400, f"无效的 attachment_id: {attachment_id}")

    result = await db.execute(
        select(IssueAttachment).where(
            IssueAttachment.id == att_uid,
            IssueAttachment.issue_id == issue.id,
        )
    )
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(404, f"Attachment {attachment_id} not found")

    # 删除物理文件
    from app.utils.file_storage import delete_attachment_file
    delete_attachment_file(issue_id, attachment_id)

    # 删除数据库记录
    await db.delete(attachment)
    await db.commit()

    return {"ok": True}


@router.get("/{issue_id}/attachments/{attachment_id}/download")
async def download_attachment(
    issue_id: str,
    attachment_id: str,
    db: AsyncSession = Depends(get_db),
):
    """下载附件原文件"""
    issue = await _get_issue(db, issue_id)

    try:
        att_uid = uuid_module.UUID(attachment_id)
    except ValueError:
        raise HTTPException(400, f"无效的 attachment_id: {attachment_id}")

    result = await db.execute(
        select(IssueAttachment).where(
            IssueAttachment.id == att_uid,
            IssueAttachment.issue_id == issue.id,
        )
    )
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(404, f"Attachment {attachment_id} not found")

    from app.utils.file_storage import get_attachment_file_path
    file_path = get_attachment_file_path(issue_id, attachment_id, attachment.filename)

    if not file_path.exists():
        raise HTTPException(404, f"文件不存在: {attachment.filename}")

    return FileResponse(
        path=str(file_path),
        filename=attachment.filename,
        media_type=_get_media_type(attachment.file_type),
    )


def _get_media_type(file_type: str) -> str:
    """根据文件类型返回 Content-Type"""
    media_types = {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
        "md": "text/markdown",
        "txt": "text/plain",
    }
    return media_types.get(file_type, "application/octet-stream")


# ==========================================================================
# 分解 & 派发
# ==========================================================================


@router.post("/{issue_id}/decompose")
async def decompose_issue(
    issue_id: str,
    body: IssueDecomposeRequest = IssueDecomposeRequest(),
    db: AsyncSession = Depends(get_db),
):
    """
    分解 Issue 为子任务树。
    调用 PlannerAgent 生成 WorkflowSpec → 转换为 task_tree → 保存回 Issue。
    """
    issue = await _get_issue(db, issue_id)

    if issue.task_tree_json and issue.status not in ("open", "in_progress"):
        raise HTTPException(
            400,
            f"Issue {issue_id} already decomposed (status={issue.status}). "
            f"请先重置 status 为 open 再重新分解",
        )

    decomposer = IssueDecomposer(db)
    task_tree = await decomposer.decompose(issue, body.strategy)

    await _publish_issue_event(
        "issue_decomposed",
        str(issue.id),
        {
            "task_tree": task_tree,
            "strategy": body.strategy,
            "node_count": len(task_tree["nodes"]),
        },
    )

    return {
        "ok": True,
        "issue": _issue_to_response(issue),
        "task_tree": task_tree,
    }


@router.post("/{issue_id}/dispatch")
async def dispatch_issue(
    issue_id: str,
    body: IssueDispatchRequest = IssueDispatchRequest(),
    db: AsyncSession = Depends(get_db),
):
    """
    派发 Issue 下所有子任务到对应 Agent。
    必须先调用 decompose 生成任务树。
    """
    issue = await _get_issue(db, issue_id)

    if not issue.task_tree_json:
        raise HTTPException(400, "Issue 尚未分解，请先调用 /decompose")

    dispatcher = IssueTaskDispatcher(db)
    result = await dispatcher.dispatch_all(
        issue,
        auto_assign=body.auto_assign,
        overrides=body.task_tree,
    )

    await _publish_issue_event(
        "issue_dispatched",
        str(issue.id),
        result.to_dict(),
    )

    return {
        "ok": True,
        "issue": _issue_to_response(issue),
        **result.to_dict(),
    }


@router.post("/{issue_id}/dispatch/{node_id}")
async def dispatch_single_node(
    issue_id: str,
    node_id: str,
    body: IssueDispatchRequest = IssueDispatchRequest(),
    db: AsyncSession = Depends(get_db),
):
    """重新派发单个节点（手动调整后）"""
    issue = await _get_issue(db, issue_id)

    if not issue.task_tree_json:
        raise HTTPException(400, "Issue 尚未分解")

    dispatcher = IssueTaskDispatcher(db)
    task = await dispatcher.dispatch_single(
        issue=issue,
        node_id=node_id,
    )

    if task is None:
        raise HTTPException(500, "派发失败")

    return {
        "ok": True,
        "task": {
            "id": str(task.id),
            "name": task.name,
            "title": task.title,
            "status": task.status,
            "agent_name": task.agent_name or "",
        },
    }


# ==========================================================================
# 子任务查询
# ==========================================================================


@router.get("/{issue_id}/tasks")
async def get_issue_tasks(
    issue_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取 Issue 下所有子任务"""
    issue = await _get_issue(db, issue_id)

    result = await db.execute(
        select(Task).where(
            Task.issue_id == issue.id,
            Task.parent_task_id != None,  # 只取子任务，排除根
        ).order_by(Task.created_at)
    )
    tasks = result.scalars().all()

    return [
        {
            "id": str(t.id),
            "name": t.name,
            "title": t.title,
            "status": t.status,
            "kanban_column": t.kanban_column,
            "agent_id": str(t.agent_id) if t.agent_id else None,
            "agent_name": t.agent_name or "",
            "parent_task_id": str(t.parent_task_id) if t.parent_task_id else None,
            "priority": t.priority,
            "cost": t.cost,
            "duration": t.duration,
            "created_at": t.created_at.isoformat() if t.created_at else "",
        }
        for t in tasks
    ]


@router.get("/{issue_id}/task-tree")
async def get_issue_task_tree(
    issue_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取 Issue 的任务树（含执行状态）"""
    issue = await _get_issue(db, issue_id)

    if not issue.task_tree_json:
        # 从数据库重建
        result = await db.execute(
            select(Task).where(Task.issue_id == issue.id).order_by(Task.created_at)
        )
        tasks = result.scalars().all()
        return {
            "issue_id": issue_id,
            "root_task_id": None,
            "nodes": [
                {
                    "id": str(t.id),
                    "parent_id": str(t.parent_task_id) if t.parent_task_id else None,
                    "name": t.name,
                    "title": t.title,
                    "status": t.status,
                    "kanban_column": t.kanban_column,
                    "agent_name": t.agent_name or "",
                    "cost": t.cost,
                    "duration": t.duration,
                }
                for t in tasks
            ],
            "from_db": True,
        }

    task_tree = (
        json.loads(issue.task_tree_json)
        if isinstance(issue.task_tree_json, str)
        else issue.task_tree_json
    )

    # 补充 DB 中的执行状态
    result = await db.execute(
        select(Task).where(Task.issue_id == issue.id)
    )
    db_tasks = {str(t.id): t for t in result.scalars().all()}

    for node in task_tree.get("nodes", []):
        db_task = db_tasks.get(node["id"])
        if db_task:
            node["status"] = db_task.status
            node["kanban_column"] = db_task.kanban_column
            node["agent_name"] = db_task.agent_name or ""
            node["cost"] = db_task.cost
            node["duration"] = db_task.duration

    return task_tree


# ==========================================================================
# 辅助
# ==========================================================================


async def _get_issue(db: AsyncSession, issue_id: str) -> Issue:
    """获取 Issue，不存在时 404"""
    try:
        uid = uuid_module.UUID(issue_id)
    except ValueError:
        raise HTTPException(400, f"无效的 issue_id: {issue_id}")

    result = await db.execute(
        select(Issue)
        .options(selectinload(Issue.assigned_agent), selectinload(Issue.attachments))
        .where(Issue.id == uid)
    )
    issue = result.scalar_one_or_none()
    if not issue:
        raise HTTPException(404, f"Issue {issue_id} not found")
    return issue


# ==========================================================================
# 评论端点（暂用内存存储，后续迁移到 DB）
# ==========================================================================


@router.get("/{issue_id}/comments")
async def list_comments(
    issue_id: str,
    db: AsyncSession = Depends(get_db),
):
    """列出 Issue 所有评论"""
    issue = await _get_issue(db, issue_id)
    result = await db.execute(
        select(Comment)
        .where(Comment.issue_id == issue.id)
        .order_by(Comment.created_at)
    )
    comments = result.scalars().all()
    return [
        _comment_to_response(c)
        for c in comments
    ]


@router.post("/{issue_id}/comments", status_code=201)
async def create_comment(
    issue_id: str,
    body: CommentCreate,
    db: AsyncSession = Depends(get_db),
):
    """新建 Issue 评论"""
    issue = await _get_issue(db, issue_id)

    comment = Comment(
        issue_id=issue.id,
        content=body.content,
        author=body.author or "system",
        parent_id=uuid_module.UUID(body.parent_id) if body.parent_id else None,
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    await _publish_issue_event(
        "comment_added",
        str(issue.id),
        {"comment_id": str(comment.id), "author": comment.author},
    )

    return _comment_to_response(comment)


def _comment_to_response(comment: Comment) -> dict:
    """Comment ORM → dict 响应"""
    return {
        "id": str(comment.id),
        "issue_id": str(comment.issue_id),
        "content": comment.content,
        "author": comment.author,
        "parent_id": str(comment.parent_id) if comment.parent_id else None,
        "created_at": comment.created_at.isoformat() if comment.created_at else "",
        "updated_at": comment.updated_at.isoformat() if comment.updated_at else "",
    }


def _issue_to_response(issue: Issue) -> dict:
    """Issue ORM → dict 响应"""
    agent_name: Optional[str] = None
    if issue.assigned_agent:
        agent_name = issue.assigned_agent.name

    # 统计子任务
    task_count = 0
    completed_count = 0

    # 附件列表
    attachments = []
    if hasattr(issue, "attachments"):
        attachments = [
            {
                "id": str(att.id),
                "issue_id": str(att.issue_id),
                "filename": att.filename,
                "file_type": att.file_type,
                "file_size": att.file_size,
                "created_at": att.created_at.isoformat() if att.created_at else "",
            }
            for att in issue.attachments
        ]

    return {
        "id": str(issue.id),
        "project_id": str(issue.project_id),
        "title": issue.title,
        "description": issue.description or "",
        "status": issue.status,
        "priority": issue.priority,
        "created_by": issue.created_by or "",
        "assigned_agent_id": (
            str(issue.assigned_agent_id) if issue.assigned_agent_id else None
        ),
        "assigned_agent_name": agent_name,
        "decomposition_strategy": issue.decomposition_strategy,
        "task_tree": issue.task_tree_json,
        "decomposed_at": (
            issue.decomposed_at.isoformat() if issue.decomposed_at else None
        ),
        "resolved_at": (
            issue.resolved_at.isoformat() if issue.resolved_at else None
        ),
        "created_at": issue.created_at.isoformat() if issue.created_at else "",
        "updated_at": issue.updated_at.isoformat() if issue.updated_at else "",
        "task_count": task_count,
        "completed_task_count": completed_count,
        "attachments": attachments,
    }
