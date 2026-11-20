"""W31-32 Runtime Federation — 联邦注册中心

管理联邦成员的生命周期：加入、离开、心跳、发现、选举。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Callable

from .models import (
    FederationCluster,
    FederationMember,
    FederationRole,
    FederationStats,
    FederationTopology,
    JoinRequest,
    MemberHeartbeatRequest,
    MemberStatus,
)

logger = logging.getLogger(__name__)

# 心跳超时阈值（秒）
HEARTBEAT_TIMEOUT = 30
# 清理循环间隔（秒）
CLEANUP_INTERVAL = 15


class FederationRegistry:
    """联邦成员注册中心 — 管理所有联邦成员的加入/离开/心跳"""

    def __init__(self, heartbeat_timeout: int = HEARTBEAT_TIMEOUT,
                 cleanup_interval: int = CLEANUP_INTERVAL):
        self._members: dict[str, FederationMember] = {}
        self._clusters: dict[str, FederationCluster] = {}
        self._heartbeat_timeout = heartbeat_timeout
        self._cleanup_interval = cleanup_interval
        self._cleanup_task: asyncio.Task | None = None
        self._hooks: dict[str, list[Callable]] = {
            "on_join": [],
            "on_leave": [],
            "on_status_change": [],
        }

    # ── 生命周期管理 ──────────────────────────

    async def join(self, request: JoinRequest) -> FederationMember:
        """成员加入联邦"""
        # 检查是否已有同端点成员
        for m in self._members.values():
            if m.endpoint == request.endpoint and m.status.is_available:
                raise ValueError(f"Endpoint {request.endpoint} already registered as member {m.member_id}")

        member = FederationMember(
            name=request.name,
            endpoint=request.endpoint,
            capabilities=request.capabilities,
            labels=request.labels,
            region=request.region,
            zone=request.zone,
            total_capacity=request.total_capacity,
            role=request.role,
            joined_at=datetime.now(),
            last_heartbeat=datetime.now(),
        )

        # 分配集群
        cluster = await self._get_or_create_cluster(request.cluster_name, request.region)
        member.cluster_id = cluster.cluster_id
        cluster.members.append(member.member_id)
        cluster.total_members += 1
        cluster.active_members += 1
        cluster.total_capacity += member.total_capacity
        cluster.updated_at = datetime.now()

        self._members[member.member_id] = member
        logger.info("Member %s joined federation (cluster=%s, region=%s)",
                     member.name, cluster.name, member.region)

        await self._fire_hooks("on_join", member)
        return member

    async def leave(self, member_id: str, graceful: bool = True) -> FederationMember | None:
        """成员离开联邦"""
        member = self._members.get(member_id)
        if not member:
            return None

        member.status = MemberStatus.LEAVING
        member.updated_at = datetime.now()

        if graceful:
            # 等待正在执行的任务完成（简化：直接标记离开）
            await asyncio.sleep(0.01)

        member.status = MemberStatus.OFFLINE
        member.updated_at = datetime.now()

        # 从集群中移除
        cluster = self._clusters.get(member.cluster_id)
        if cluster and member.member_id in cluster.members:
            cluster.members.remove(member.member_id)
            cluster.total_members = max(0, cluster.total_members - 1)
            cluster.active_members = max(0, cluster.active_members - 1)
            cluster.total_capacity = max(0, cluster.total_capacity - member.total_capacity)
            cluster.updated_at = datetime.now()

        await self._fire_hooks("on_leave", member)
        logger.info("Member %s left federation", member.name)
        return member

    async def heartbeat(self, req: MemberHeartbeatRequest) -> FederationMember | None:
        """处理成员心跳"""
        member = self._members.get(req.member_id)
        if not member:
            return None

        prev_status = member.status
        member.status = req.status
        member.last_heartbeat = datetime.now()
        member.cpu_usage_pct = req.cpu_usage_pct
        member.memory_usage_pct = req.memory_usage_pct
        member.active_tasks = req.active_tasks
        member.used_capacity = req.used_capacity
        member.total_tasks_completed = req.total_tasks_completed
        member.avg_task_duration_ms = req.avg_task_duration_ms
        member.updated_at = datetime.now()

        if prev_status != req.status:
            await self._fire_hooks("on_status_change", member, prev_status, req.status)

        return member

    def deregister(self, member_id: str) -> FederationMember | None:
        """强制移除成员"""
        member = self._members.pop(member_id, None)
        if member:
            cluster = self._clusters.get(member.cluster_id)
            if cluster and member.member_id in cluster.members:
                cluster.members.remove(member.member_id)
                cluster.total_members = max(0, cluster.total_members - 1)
                cluster.active_members = max(0, cluster.active_members - 1)
                cluster.total_capacity = max(0, cluster.total_capacity - member.total_capacity)
            logger.info("Member %s deregistered from federation", member.name)
        return member

    # ── 查询 ──────────────────────────────────

    def get_member(self, member_id: str) -> FederationMember | None:
        return self._members.get(member_id)

    def get_member_by_name(self, name: str) -> FederationMember | None:
        for m in self._members.values():
            if m.name == name:
                return m
        return None

    def list_members(self, status: MemberStatus | None = None,
                     cluster_id: str = "",
                     region: str = "",
                     capability: str = "") -> list[FederationMember]:
        """列出成员，支持多维度过滤"""
        result = list(self._members.values())
        if status:
            result = [m for m in result if m.status == status]
        if cluster_id:
            result = [m for m in result if m.cluster_id == cluster_id]
        if region:
            result = [m for m in result if m.region == region]
        if capability:
            result = [m for m in result if capability in m.capabilities]
        return result

    def get_available_members(self, capability: str = "",
                              region: str = "") -> list[FederationMember]:
        """获取可用成员（可接新任务）"""
        members = self.list_members(region=region, capability=capability)
        return [m for m in members if m.is_available]

    def get_cluster(self, cluster_id: str) -> FederationCluster | None:
        return self._clusters.get(cluster_id)

    def list_clusters(self) -> list[FederationCluster]:
        return list(self._clusters.values())

    def get_topology(self) -> FederationTopology:
        """生成联邦拓扑视图"""
        topology = FederationTopology(
            members=dict(self._members),
            clusters=dict(self._clusters),
            snapshot_at=datetime.now(),
        )
        # 构建集群内成员的边
        for cluster in self._clusters.values():
            cluster_members = [mid for mid in cluster.members if mid in self._members]
            for i, ma in enumerate(cluster_members):
                for mb in cluster_members[i + 1:]:
                    topology.edges.append((ma, mb))
        return topology

    def get_stats(self) -> FederationStats:
        """聚合联邦统计信息"""
        members = list(self._members.values())
        active = sum(1 for m in members if m.status == MemberStatus.ACTIVE)
        degraded = sum(1 for m in members if m.status == MemberStatus.DEGRADED)
        offline = sum(1 for m in members if m.status == MemberStatus.OFFLINE)
        total_cap = sum(m.total_capacity for m in members)
        used_cap = sum(m.used_capacity for m in members)
        total_completed = sum(m.total_tasks_completed for m in members)

        overall_load = round(used_cap / total_cap, 4) if total_cap > 0 else 0.0

        return FederationStats(
            total_clusters=len(self._clusters),
            total_members=len(members),
            active_members=active,
            degraded_members=degraded,
            offline_members=offline,
            total_capacity=total_cap,
            used_capacity=used_cap,
            overall_load=overall_load,
            total_tasks_completed=total_completed,
            snapshot_at=datetime.now(),
        )

    def get_leader(self, cluster_id: str = "") -> FederationMember | None:
        """获取集群 Leader"""
        if cluster_id:
            cluster = self._clusters.get(cluster_id)
            if cluster and cluster.leader_id:
                return self._members.get(cluster.leader_id)
        # 全局 Leader：取第一个 ACTIVE 的 LEADER 角色成员
        for m in self._members.values():
            if m.role == FederationRole.LEADER and m.status == MemberStatus.ACTIVE:
                return m
        return None

    async def elect_leader(self, cluster_id: str) -> FederationMember | None:
        """选举集群 Leader — 选健康分数最高者"""
        cluster = self._clusters.get(cluster_id)
        if not cluster:
            return None

        available = [
            self._members[mid] for mid in cluster.members
            if mid in self._members and self._members[mid].status.is_available
        ]
        if not available:
            return None

        # 按健康分数排序，选最高
        available.sort(key=lambda m: m.health_score, reverse=True)
        new_leader = available[0]
        new_leader.role = FederationRole.LEADER
        cluster.leader_id = new_leader.member_id
        cluster.updated_at = datetime.now()
        logger.info("Elected new leader for cluster %s: %s", cluster.name, new_leader.name)
        return new_leader

    # ── 内部方法 ──────────────────────────────

    async def _get_or_create_cluster(self, name: str, region: str) -> FederationCluster:
        if not name:
            name = f"cluster-{region}"
        for c in self._clusters.values():
            if c.name == name:
                return c
        cluster = FederationCluster(name=name, region=region)
        self._clusters[cluster.cluster_id] = cluster
        logger.info("Created new cluster: %s", name)
        return cluster

    async def _cleanup_stale_members(self):
        """清理心跳超时的成员"""
        cutoff = datetime.now() - timedelta(seconds=self._heartbeat_timeout)
        for member in list(self._members.values()):
            if (member.last_heartbeat < cutoff
                    and member.status == MemberStatus.ACTIVE):
                member.status = MemberStatus.OFFLINE
                member.updated_at = datetime.now()
                cluster = self._clusters.get(member.cluster_id)
                if cluster:
                    cluster.active_members = max(0, cluster.active_members - 1)
                logger.warning("Member %s marked OFFLINE due to heartbeat timeout", member.name)

    async def _cleanup_loop(self):
        """后台清理循环"""
        while True:
            try:
                await self._cleanup_stale_members()
            except Exception:
                logger.exception("Error in federation cleanup loop")
            await asyncio.sleep(self._cleanup_interval)

    def start_cleanup(self):
        """启动后台清理任务"""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.ensure_future(self._cleanup_loop())

    async def stop_cleanup(self):
        """停止后台清理任务"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    # ── 钩子 ──────────────────────────────────

    def on(self, event: str, callback: Callable):
        """注册事件钩子"""
        if event in self._hooks:
            self._hooks[event].append(callback)

    async def _fire_hooks(self, event: str, *args):
        for cb in self._hooks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(*args)
                else:
                    cb(*args)
            except Exception:
                logger.exception("Hook error in %s", event)
