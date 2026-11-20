"""
WebSocket Manager — 管理 WebSocket 连接，支持双向通信
集成到现有 SSE 事件系统，实现事件实时推送
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        # task_id → set of WebSocket
        self._task_connections: dict[str, set[WebSocket]] = defaultdict(set)
        # user_id → set of WebSocket (用户级连接)
        self._user_connections: dict[str, set[WebSocket]] = defaultdict(set)
        # WebSocket → metadata (用于快速查找)
        self._meta: dict[WebSocket, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self,
        websocket: WebSocket,
        user_id: str | None = None,
        task_id: str | None = None,
    ) -> str:
        """接受 WebSocket 连接，返回 conn_id"""
        await websocket.accept()
        conn_id = str(uuid.uuid4())

        async with self._lock:
            self._meta[websocket] = {
                "conn_id": conn_id,
                "user_id": user_id,
                "task_id": task_id,
            }
            if user_id:
                self._user_connections[user_id].add(websocket)
            if task_id:
                self._task_connections[task_id].add(websocket)

        logger.info(f"WebSocket connected: conn_id={conn_id}, user_id={user_id}, task_id={task_id}")
        return conn_id

    async def disconnect(self, websocket: WebSocket):
        """移除 WebSocket 连接"""
        async with self._lock:
            meta = self._meta.pop(websocket, None)
            if not meta:
                return
            conn_id = meta["conn_id"]
            user_id = meta.get("user_id")
            task_id = meta.get("task_id")

            if user_id and websocket in self._user_connections.get(user_id, set()):
                self._user_connections[user_id].discard(websocket)
                if not self._user_connections[user_id]:
                    del self._user_connections[user_id]

            if task_id and websocket in self._task_connections.get(task_id, set()):
                self._task_connections[task_id].discard(websocket)
                if not self._task_connections[task_id]:
                    del self._task_connections[task_id]

        logger.info(f"WebSocket disconnected: conn_id={conn_id}")

    async def send_to_task(self, task_id: str, event_type: str, data: dict):
        """发送事件到特定 task 的所有连接"""
        ws_set = self._task_connections.get(task_id, set())
        if not ws_set:
            return

        payload = json.dumps({"event": event_type, "data": data})
        disconnected = []
        for ws in ws_set:
            try:
                await ws.send_text(payload)
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket: {e}")
                disconnected.append(ws)

        # 清理断开的连接
        for ws in disconnected:
            await self.disconnect(ws)

    async def send_to_user(self, user_id: str, event_type: str, data: dict):
        """发送事件到特定用户的所有连接"""
        ws_set = self._user_connections.get(user_id, set())
        if not ws_set:
            return

        payload = json.dumps({"event": event_type, "data": data})
        disconnected = []
        for ws in ws_set:
            try:
                await ws.send_text(payload)
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket: {e}")
                disconnected.append(ws)

        for ws in disconnected:
            await self.disconnect(ws)

    async def broadcast(self, event_type: str, data: dict):
        """广播事件到所有连接"""
        payload = json.dumps({"event": event_type, "data": data})
        all_ws = set()
        async with self._lock:
            for ws_set in self._user_connections.values():
                all_ws.update(ws_set)
            for ws_set in self._task_connections.values():
                all_ws.update(ws_set)

        disconnected = []
        for ws in all_ws:
            try:
                await ws.send_text(payload)
            except Exception as e:
                logger.warning(f"Failed to broadcast to WebSocket: {e}")
                disconnected.append(ws)

        for ws in disconnected:
            await self.disconnect(ws)

    def get_connection_count(self) -> int:
        """获取当前连接数"""
        return len(self._meta)

    def get_task_connection_count(self, task_id: str) -> int:
        """获取特定 task 的连接数"""
        return len(self._task_connections.get(task_id, set()))

    def get_user_connection_count(self, user_id: str) -> int:
        """获取特定用户的连接数"""
        return len(self._user_connections.get(user_id, set()))


# 全局单例
manager = ConnectionManager()
