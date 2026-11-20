"""
SSE Manager — 管理 SSE 连接，支持事件广播和按 task_id 过滤
"""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict


class SSEManager:
    """内存版 SSE 连接管理器"""

    def __init__(self):
        # task_id → {conn_id → asyncio.Queue}
        self._task_queues: dict[str, dict[str, asyncio.Queue]] = defaultdict(dict)
        # 全局广播队列：conn_id → asyncio.Queue
        self._global_queues: dict[str, asyncio.Queue] = {}
        self._conn_counter = 0

    def _new_conn_id(self) -> str:
        self._conn_counter += 1
        return f"sse-{self._conn_counter}"

    async def subscribe(self, task_id: str | None = None) -> tuple[str, asyncio.Queue]:
        """创建新连接，返回 (conn_id, queue)"""
        conn_id = self._new_conn_id()
        q: asyncio.Queue = asyncio.Queue()

        if task_id:
            self._task_queues[task_id][conn_id] = q
        else:
            self._global_queues[conn_id] = q

        return conn_id, q

    async def unsubscribe(self, conn_id: str, task_id: str | None = None):
        """移除连接"""
        if task_id:
            self._task_queues.get(task_id, {}).pop(conn_id, None)
            if not self._task_queues.get(task_id):
                self._task_queues.pop(task_id, None)
        else:
            self._global_queues.pop(conn_id, None)

    async def publish(self, event_type: str, data: dict, task_id: str | None = None):
        """发布事件：推给全局 + 对应的 task 订阅者"""
        payload = json.dumps({"event": event_type, "data": data})

        # 广播到全局订阅者
        for q in self._global_queues.values():
            await q.put(payload)

        # 推送到 task 特定订阅者
        if task_id and task_id in self._task_queues:
            for q in self._task_queues[task_id].values():
                await q.put(payload)

    async def publish_raw(self, raw: str, task_id: str | None = None):
        """发布原始 SSE 事件字符串"""
        for q in self._global_queues.values():
            await q.put(raw)
        if task_id and task_id in self._task_queues:
            for q in self._task_queues[task_id].values():
                await q.put(raw)


# 全局单例
sse_manager = SSEManager()
