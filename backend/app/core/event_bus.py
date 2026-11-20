"""
AI Runtime OS — Event Bus（Phase 1: 内存实现，Phase 2: Redis Streams）
所有行为都转为 Event → 发布到 Event Bus → 消费者处理
"""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import AsyncIterator, Callable, Awaitable

from app.core.event_types import EventType


Subscriber = Callable[[dict], Awaitable[None]]


class Event:
    """事件对象"""
    __slots__ = ("type", "task_id", "payload", "produced_by", "produced_at")

    def __init__(
        self,
        type: EventType,
        task_id: str = "",
        payload: dict | None = None,
        produced_by: str = "system",
    ):
        self.type = type
        self.task_id = task_id
        self.payload = payload or {}
        self.produced_by = produced_by
        self.produced_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "task_id": self.task_id,
            "payload": self.payload,
            "produced_by": self.produced_by,
            "produced_at": self.produced_at.isoformat(),
        }


class EventBus:
    """
    Event Bus — Phase 1 内存实现。
    Phase 2 替换为 RedisStreamsEventBus（继承相同接口）。
    """

    def __init__(self):
        self._subscribers: dict[str, list[Subscriber]] = defaultdict(list)
        self._history: dict[str, list[dict]] = defaultdict(list)
        self._seq_counter: dict[str, int] = defaultdict(int)

    def event_stream_key(self, task_id: str) -> str:
        return f"events:task:{task_id}"

    # ---- 发布 ----

    async def publish(self, event: Event) -> None:
        """发布事件到总线和历史存储"""
        key = self.event_stream_key(event.task_id) if event.task_id else "events:global"
        data = event.to_dict()
        self._seq_counter[key] += 1
        data["seq_num"] = self._seq_counter[key]
        self._history[key].append(data)

        # 通知 subscribers
        subs = self._subscribers.get(key, []) + self._subscribers.get("events:*", [])
        for sub in subs:
            try:
                await sub(data)
            except Exception:
                pass  # 单个 subscriber 失败不影响其他

    # ---- 订阅 ----

    def subscribe(self, task_id: str, handler: Subscriber) -> None:
        key = self.event_stream_key(task_id)
        self._subscribers[key].append(handler)

    def subscribe_all(self, handler: Subscriber) -> None:
        self._subscribers["events:*"].append(handler)

    # ---- Replay ----

    async def replay(
        self, task_id: str, after_seq_num: int = 0
    ) -> AsyncIterator[dict]:
        """Replay 指定任务 after_seq_num 之后的事件（用于故障恢复）"""
        key = self.event_stream_key(task_id)
        for event_data in self._history.get(key, []):
            if event_data.get("seq_num", 0) > after_seq_num:
                yield event_data

    # ---- 查询 ----

    def get_events(self, task_id: str, limit: int = 50) -> list[dict]:
        key = self.event_stream_key(task_id)
        events = self._history.get(key, [])
        return events[-limit:]


# 全局单例
event_bus = EventBus()
