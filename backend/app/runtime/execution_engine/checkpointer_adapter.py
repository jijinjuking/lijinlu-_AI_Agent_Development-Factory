"""
Checkpointer Adapter — 将项目的 CheckpointManager 适配为 LangGraph BaseCheckpointSaver

Phase 3.3: checkpointer 原生接入
- LangGraph compile(checkpointer=adapter) 后，原生支持 aget_state()/update_state() 等 API
- CheckpointManager 负责持久化，Adapter 负责 LangGraph 协议转换

设计：
- thread_id = task_id（一对一映射）
- checkpoint["id"] = checkpoint_id（UUID）
- checkpoint["ts"] = created_at (ISO 8601)
- checkpoint["channel_values"] = WorkflowState dict
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.checkpoint.base.id import uuid6

from app.runtime.checkpoint_manager.checkpoint_manager import CheckpointManager
from app.runtime.state_manager.lightweight_state import LightweightState

logger = logging.getLogger("ai_runtime_os.checkpointer_adapter")


class CheckpointerAdapter(BaseCheckpointSaver):
    """
    将 CheckpointManager 适配为 LangGraph BaseCheckpointSaver。

    用法：
        checkpoint_mgr = CheckpointManager(state_manager)
        adapter = CheckpointManagerAdapter(checkpoint_mgr)
        graph = builder.compile(checkpointer=adapter)
    """

    def __init__(self, checkpoint_manager: CheckpointManager):
        """
        Args:
            checkpoint_manager: 项目的 CheckpointManager 实例
        """
        # BaseCheckpointSaver 接受可选的 serde 参数
        super().__init__()
        self._mgr = checkpoint_manager

    # ── 核心：获取 checkpoint tuple ──

    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """
        根据 config 获取最新 checkpoint tuple。

        config 结构：
            {"configurable": {"thread_id": task_id, "checkpoint_id": optional}}
        """
        thread_id = config.get("configurable", {}).get("thread_id")
        if not thread_id:
            return None

        try:
            cp = await self._mgr.load_latest(thread_id)
        except Exception:
            logger.exception("aget_tuple: load_latest failed for %s", thread_id)
            return None

        if cp is None:
            return None

        checkpoint = self._lightweight_to_checkpoint(cp)
        metadata = self._build_metadata(cp)

        return CheckpointTuple(
            config=config,
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=None,  # TODO: 追踪 parent
            pending_writes=None,
        )

    # ── 核心：保存 checkpoint ──

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict[str, Any],
    ) -> RunnableConfig:
        """
        保存 checkpoint。

        LangGraph 在每次节点执行后调用此方法。
        我们将其转换为 CheckpointManager.save_checkpoint()。
        """
        thread_id = config.get("configurable", {}).get("thread_id", "")
        if not thread_id:
            return config

        try:
            # checkpoint["channel_values"] 包含完整 WorkflowState
            channel_values = checkpoint.get("channel_values", {})
            ls = self._dict_to_lightweight(thread_id, channel_values)
            await self._mgr.state_manager.save(thread_id, ls)
            await self._mgr.save_checkpoint(thread_id)
        except Exception:
            logger.exception("aput: save_checkpoint failed for %s", thread_id)

        return config

    # ── 列表：获取历史 checkpoint ──

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ):
        """
        列出 checkpoint 历史（按时间倒序）。

        Yields:
            CheckpointTuple
        """
        thread_id = config.get("configurable", {}).get("thread_id") if config else None
        if not thread_id:
            return

        try:
            cps = await self._mgr.list_checkpoints(
                thread_id, limit=limit or 50
            )
            for cp in reversed(cps):  # 最新在前
                checkpoint = self._lightweight_to_checkpoint(cp)
                md = self._build_metadata(cp)
                yield CheckpointTuple(
                    config=config,
                    checkpoint=checkpoint,
                    metadata=md,
                    parent_config=None,
                    pending_writes=None,
                )
        except Exception:
            logger.exception("alist: list_checkpoints failed for %s", thread_id)

    # ── 删除 ──

    async def adelete_thread(self, thread_id: str) -> None:
        """删除整个线程的所有 checkpoint"""
        try:
            await self._mgr.state_manager.delete(thread_id)
            logger.info("adelete_thread: deleted thread %s", thread_id)
        except Exception:
            logger.exception("adelete_thread failed for %s", thread_id)

    # ── 内部：thread_id 提取 ──

    @staticmethod
    def _thread_id(config: dict | RunnableConfig) -> str:
        """从 config 提取 thread_id（兼容 dict 和 RunnableConfig）"""
        if isinstance(config, dict):
            return config.get("configurable", {}).get("thread_id", "")
        return getattr(config, "configurable", {}).get("thread_id", "")

    # ── 内部：格式转换 ──

    @staticmethod
    def _lightweight_to_checkpoint(ls: Any) -> Checkpoint:
        """
        LightweightState | dict → LangGraph Checkpoint。
        兼容 dict 输入（来自 CheckpointManager.list_checkpoints 的 mock 返回）。
        """
        import json

        if isinstance(ls, dict):
            channel_values: dict[str, Any] = dict(ls)
            ls_id = ls.get("checkpoint_id") or ls.get("id") or str(uuid6())
            ls_ts = ls.get("updated_at") or ls.get("created_at") or datetime.now(timezone.utc).isoformat()
        else:
            channel_values: dict[str, Any] = dict(ls.to_dict())
            ls_id = ls.checkpoint_id or str(uuid6())
            ls_ts = ls.updated_at if hasattr(ls, "updated_at") else datetime.now(timezone.utc).isoformat()

        # 构建 LangGraph Checkpoint
        return Checkpoint(
            v=1,
            id=ls_id,
            ts=ls_ts,
            channel_values=channel_values,
            channel_versions={k: i + 1 for i, k in enumerate(channel_values.keys())},
            versions_seen={},
            pending_sends=[],
            updated_channels=None,
        )

    @staticmethod
    def _dict_to_lightweight(task_id: str, data: dict[str, Any]) -> LightweightState:
        """dict → LightweightState"""
        from app.runtime.state_manager.lightweight_state import LightweightState
        # 避免 task_id 重复传入（data 中可能也包含 task_id）
        safe_data = {k: v for k, v in data.items() if k != "task_id"}
        return LightweightState(
            task_id=task_id,
            **safe_data,
        )

    @staticmethod
    def _build_metadata(cp: Any) -> CheckpointMetadata:
        """从 LightweightState | dict 构建 CheckpointMetadata"""
        if isinstance(cp, dict):
            task_id = cp.get("task_id", "")
            step = cp.get("step", 0)
        else:
            task_id = cp.task_id
            step = getattr(cp, "step", 0)
        return CheckpointMetadata(
            source="loop",
            step=step,
            parents={},
            run_id=task_id,
        )

    # ── 同步版本（BaseCheckpointSaver 要求） ──

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """同步版本：在当前事件循环中调用异步版本"""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self.aget_tuple(config))
        except Exception:
            logger.exception("get_tuple sync failed")
            return None

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict[str, Any],
    ) -> RunnableConfig:
        """同步版本"""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(
                self.aput(config, checkpoint, metadata, new_versions)
            )
        except Exception:
            logger.exception("put sync failed")
            return config
