"""
SSE Manager 单元测试
"""
from __future__ import annotations

import asyncio
import json

import pytest
from app.core.sse_manager import SSEManager


@pytest.mark.asyncio
async def test_subscribe_unsubscribe():
    """订阅和取消订阅"""
    mgr = SSEManager()
    conn_id, queue = await mgr.subscribe(task_id="task-1")
    assert conn_id.startswith("sse-")
    assert isinstance(queue, asyncio.Queue)

    await mgr.unsubscribe(conn_id, task_id="task-1")
    # 验证队列已清空
    assert "task-1" not in mgr._task_queues


@pytest.mark.asyncio
async def test_publish_to_task_subscriber():
    """发布到特定 task 的订阅者"""
    mgr = SSEManager()
    _, queue = await mgr.subscribe(task_id="task-1")

    await mgr.publish("test_event", {"msg": "hello"}, task_id="task-1")
    payload = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert "test_event" in payload


@pytest.mark.asyncio
async def test_publish_to_global_subscriber():
    """发布到全局订阅者"""
    mgr = SSEManager()
    _, queue = await mgr.subscribe(task_id=None)  # 全局

    await mgr.publish("global_event", {"msg": "broadcast"}, task_id=None)
    payload = await asyncio.wait_for(queue.get(), timeout=1.0)
    data = json.loads(payload)
    assert data["event"] == "global_event"


@pytest.mark.asyncio
async def test_task_isolation():
    """不同 task 订阅者收到对应事件"""
    mgr = SSEManager()
    _, q1 = await mgr.subscribe(task_id="task-1")
    _, q2 = await mgr.subscribe(task_id="task-2")

    await mgr.publish("event_a", {"msg": "for task-1"}, task_id="task-1")
    payload = await asyncio.wait_for(q1.get(), timeout=1.0)
    assert "event_a" in payload

    # q2 应该没有收到 task-1 的事件（除了全局广播）
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(q2.get(), timeout=0.3)
