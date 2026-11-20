"""
WebSocket API 端点
提供双向实时通信：客户端可发送消息，服务端推送事件
"""
from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.core.websocket_manager import manager
from app.database import async_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])


async def get_user_from_websocket(websocket: WebSocket) -> str | None:
    """从 WebSocket query params 或 headers 解析 token，返回 user_id"""
    # 尝试从 query params 获取 token
    token = None
    logger.info(f"WebSocket auth: query_params={dict(websocket.query_params)}")
    if websocket.query_params:
        token = websocket.query_params.get("token")

    # 尝试从 headers 获取
    if not token:
        auth_header = websocket.headers.get("authorization", "")
        logger.info(f"WebSocket auth: auth_header={auth_header[:50] if auth_header else 'EMPTY'}")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        logger.warning("WebSocket auth: no token found in query or headers")
        return None

    logger.info(f"WebSocket auth: token extracted, length={len(token)}")
    try:
        payload = decode_token(token)
        if payload and "sub" in payload:
            logger.info(f"WebSocket auth: success, user_id={payload['sub']}")
            return payload["sub"]
    except Exception as e:
        logger.warning(f"WebSocket auth failed: {e}")
        return None

    return None


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, task_id: str | None = None):
    """
    WebSocket 端点：/ws?token=xxx&task_id=xxx

    - 客户端发送：JSON 消息 {"type": "subscribe", "task_id": "xxx"}
    - 服务端推送：JSON 消息 {"event": "task_update", "data": {...}}
    """
    # 认证
    user_id = await get_user_from_websocket(websocket)
    if not user_id:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    conn_id = await manager.connect(websocket, user_id=user_id, task_id=task_id)
    logger.info(f"WebSocket {conn_id} connected (user_id={user_id})")

    try:
        # 发送欢迎消息
        await websocket.send_text(json.dumps({
            "event": "connected",
            "data": {"conn_id": conn_id, "user_id": user_id}
        }))

        # 消息接收循环
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                msg_type = msg.get("type", "unknown")

                # 处理客户端消息
                if msg_type == "subscribe":
                    # 订阅特定 task 的事件
                    new_task_id = msg.get("task_id")
                    if new_task_id:
                        # 更新连接的 task_id
                        async with manager._lock:
                            old_meta = manager._meta.get(websocket)
                            if old_meta:
                                old_task = old_meta.get("task_id")
                                if old_task:
                                    manager._task_connections[old_task].discard(websocket)
                                manager._meta[websocket]["task_id"] = new_task_id
                                manager._task_connections[new_task_id].add(websocket)
                        await websocket.send_text(json.dumps({
                            "event": "subscribed",
                            "data": {"task_id": new_task_id}
                        }))
                        logger.info(f"WebSocket {conn_id} subscribed to task {new_task_id}")

                elif msg_type == "ping":
                    await websocket.send_text(json.dumps({
                        "event": "pong",
                        "data": {"timestamp": msg.get("timestamp")}
                    }))

                elif msg_type == "execute_task":
                    # 客户端请求执行任务（通过 WebSocket）
                    task_id_req = msg.get("task_id")
                    if task_id_req:
                        # 这里可以触发任务执行，暂时只回显
                        await websocket.send_text(json.dumps({
                            "event": "task_queued",
                            "data": {"task_id": task_id_req, "status": "pending"}
                        }))

                else:
                    logger.warning(f"Unknown message type from {conn_id}: {msg_type}")
                    await websocket.send_text(json.dumps({
                        "event": "error",
                        "data": {"message": f"Unknown message type: {msg_type}"}
                    }))

            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "event": "error",
                    "data": {"message": "Invalid JSON"}
                }))
            except Exception as e:
                logger.error(f"Error processing message from {conn_id}: {e}")
                await websocket.send_text(json.dumps({
                    "event": "error",
                    "data": {"message": str(e)}
                }))

    except WebSocketDisconnect:
        logger.info(f"WebSocket {conn_id} disconnected (normal)")
    except Exception as e:
        logger.error(f"WebSocket {conn_id} error: {e}")
    finally:
        await manager.disconnect(websocket)
