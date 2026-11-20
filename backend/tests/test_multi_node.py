"""
W27-28: Multi-Node Scheduling — 测试套件

覆盖:
- NodeInfo / NodeHeartbeat 数据模型
- NodeRegistry 注册/发现/心跳/清理
- CrossNodeRouter 5种路由策略
- NodeHealthChecker 健康检查
- MultiNodeScheduler 集成调度
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
import pytest_asyncio

from app.runtime.multi_node.cross_node_router import CrossNodeRouter
from app.runtime.multi_node.models import (
    CrossNodeTask,
    NodeHeartbeat,
    NodeInfo,
    NodeStatus,
    RoutingDecision,
    RoutingStrategy,
)
from app.runtime.multi_node.node_health import NodeHealthChecker
from app.runtime.multi_node.node_registry import NodeRegistry
from app.runtime.multi_node.node_scheduler import MultiNodeScheduler


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def registry():
    """NodeRegistry fixture"""
    reg = NodeRegistry(
        heartbeat_timeout_seconds=5,
        cleanup_interval_seconds=2,
    )
    await reg.start()
    yield reg
    await reg.stop()


@pytest_asyncio.fixture
async def populated_registry(registry):
    """带有3个测试节点的注册中心"""
    for i in range(3):
        node = NodeInfo(
            node_name=f"test-node-{i}",
            host=f"192.168.1.{i+1}",
            port=8000 + i,
            capabilities=["code_generation", "data_analysis"],
            max_tasks=50,
            region="us-east",
            weight=1.0,
        )
        await registry.register(node)
    return registry


@pytest_asyncio.fixture
async def router(populated_registry):
    """CrossNodeRouter fixture"""
    return CrossNodeRouter(populated_registry)


@pytest_asyncio.fixture
async def multi_scheduler():
    """MultiNodeScheduler fixture"""
    sched = MultiNodeScheduler(
        node_name="scheduler-test",
        node_host="127.0.0.1",
        node_port=9000,
        capabilities=["test"],
        max_tasks=50,
    )
    await sched.start()
    yield sched
    await sched.stop()


def make_node(name: str = "test", **overrides) -> NodeInfo:
    defaults = {
        "node_name": name,
        "host": "127.0.0.1",
        "port": 8000,
        "capabilities": ["code_generation"],
        "max_tasks": 50,
    }
    defaults.update(overrides)
    return NodeInfo(**defaults)


# ─── 模型测试 ────────────────────────────────────────────────────────────────


class TestNodeInfo:
    """节点信息模型"""

    def test_default_node(self):
        node = make_node("default")
        assert node.node_name == "default"
        assert node.status == NodeStatus.ONLINE
        assert node.load_ratio == 0.0
        assert node.is_available

    def test_full_node(self):
        node = make_node("full", max_tasks=10)
        node.active_tasks = 10
        assert node.load_ratio == 1.0
        assert not node.is_available

    def test_health_score(self):
        node = make_node("healthy")
        assert node.health_score >= 90

        node.cpu_usage_percent = 90
        node.active_tasks = 45  # 45/50 = 0.9
        score = node.health_score
        assert score < 60

    def test_to_dict(self):
        node = make_node("dict-test")
        d = node.to_dict()
        assert d["node_name"] == "dict-test"
        assert d["status"] == "online"
        assert "load_ratio" in d
        assert "health_score" in d

    def test_node_status_values(self):
        assert NodeStatus.ONLINE.value == "online"
        assert NodeStatus.OFFLINE.value == "offline"
        assert NodeStatus.DEGRADED.value == "degraded"
        assert NodeStatus.DRAINING.value == "draining"


class TestNodeHeartbeat:
    """心跳模型"""

    def test_heartbeat_default(self):
        hb = NodeHeartbeat(node_id="n1")
        assert hb.node_id == "n1"
        assert hb.status == NodeStatus.ONLINE

    def test_heartbeat_to_dict(self):
        hb = NodeHeartbeat(
            node_id="n1",
            active_tasks=5,
            cpu_usage_percent=45.0,
        )
        d = hb.to_dict()
        assert d["active_tasks"] == 5
        assert d["cpu_usage_percent"] == 45.0


class TestRoutingDecision:
    """路由决策模型"""

    def test_decision_default(self):
        decision = RoutingDecision(
            target_node_id="n1",
            target_host="192.168.1.1",
            target_port=8000,
            strategy_used=RoutingStrategy.LEAST_LOADED,
        )
        assert decision.target_node_id == "n1"
        assert decision.strategy_used == RoutingStrategy.LEAST_LOADED

    def test_decision_to_dict(self):
        decision = RoutingDecision(
            target_node_id="n1",
            target_host="192.168.1.1",
            target_port=8000,
            strategy_used=RoutingStrategy.ROUND_ROBIN,
            reason="test",
            score=85.5,
        )
        d = decision.to_dict()
        assert d["strategy_used"] == "round_robin"
        assert d["score"] == 85.5


class TestCrossNodeTask:
    """跨节点任务模型"""

    def test_task_default(self):
        task = CrossNodeTask(
            task_id="t1",
            source_node_id="src",
        )
        assert task.task_id == "t1"
        assert task.status == "pending"

    def test_task_to_dict(self):
        task = CrossNodeTask(
            task_id="t1",
            source_node_id="src",
            target_node_id="dst",
        )
        d = task.to_dict()
        assert d["task_id"] == "t1"
        assert d["target_node_id"] == "dst"


# ─── NodeRegistry 测试 ───────────────────────────────────────────────────────


class TestNodeRegistry:
    """节点注册中心"""

    @pytest.mark.asyncio
    async def test_register_node(self, registry):
        node = make_node("reg-test")
        registered = await registry.register(node)
        assert registered.node_id == node.node_id

    @pytest.mark.asyncio
    async def test_register_updates_existing(self, registry):
        node = make_node("update-test", max_tasks=10)
        await registry.register(node)

        node.max_tasks = 20
        updated = await registry.register(node)
        assert updated.max_tasks == 20

    @pytest.mark.asyncio
    async def test_deregister_node(self, registry):
        node = make_node("dereg-test")
        await registry.register(node)

        success = await registry.deregister(node.node_id)
        assert success

        found = await registry.get_node(node.node_id)
        assert found is None

    @pytest.mark.asyncio
    async def test_deregister_nonexistent(self, registry):
        success = await registry.deregister("no-such-id")
        assert not success

    @pytest.mark.asyncio
    async def test_heartbeat_updates_metrics(self, registry):
        node = make_node("hb-test")
        await registry.register(node)

        hb = NodeHeartbeat(
            node_id=node.node_id,
            active_tasks=10,
            cpu_usage_percent=80.0,
        )
        result = await registry.heartbeat(hb)
        assert result

        updated = await registry.get_node(node.node_id)
        assert updated.active_tasks == 10
        assert updated.cpu_usage_percent == 80.0

    @pytest.mark.asyncio
    async def test_heartbeat_unknown_node(self, registry):
        hb = NodeHeartbeat(node_id="ghost")
        result = await registry.heartbeat(hb)
        assert not result

    @pytest.mark.asyncio
    async def test_list_nodes(self, populated_registry):
        nodes = await populated_registry.list_nodes()
        assert len(nodes) >= 3

    @pytest.mark.asyncio
    async def test_list_nodes_by_status(self, registry):
        node = make_node("online-node")
        await registry.register(node)

        online = await registry.list_nodes(status_filter="online")
        assert len(online) >= 1

        offline = await registry.list_nodes(status_filter="offline")
        assert len(offline) == 0

    @pytest.mark.asyncio
    async def test_get_available_nodes(self, populated_registry):
        nodes = await populated_registry.get_available_nodes()
        assert len(nodes) >= 3
        for n in nodes:
            assert n.is_available

    @pytest.mark.asyncio
    async def test_get_nodes_by_capability(self, populated_registry):
        nodes = await populated_registry.get_nodes_by_capability("code_generation")
        assert len(nodes) >= 3

        nodes = await populated_registry.get_nodes_by_capability("nonexistent")
        assert len(nodes) == 0

    @pytest.mark.asyncio
    async def test_get_nodes_by_region(self, populated_registry):
        nodes = await populated_registry.get_nodes_by_region("us-east")
        assert len(nodes) >= 3

        nodes = await populated_registry.get_nodes_by_region("eu-west")
        assert len(nodes) == 0

    @pytest.mark.asyncio
    async def test_get_cluster_stats(self, populated_registry):
        stats = await populated_registry.get_cluster_stats()
        assert stats["total_nodes"] >= 3
        assert stats["online_nodes"] >= 3
        assert "avg_load_ratio" in stats
        assert "total_capacity" in stats

    @pytest.mark.asyncio
    async def test_get_least_loaded_node(self, populated_registry):
        node = await populated_registry.get_least_loaded_node()
        assert node is not None
        assert node.load_ratio == 0.0

    @pytest.mark.asyncio
    async def test_cleanup_stale_nodes(self, registry):
        """测试心跳超时节点清理"""
        node = make_node("stale-test")
        await registry.register(node)
        # register() 会重置 last_heartbeat，所以在注册后再设为过期
        node.last_heartbeat = datetime.now() - timedelta(seconds=60)

        await registry._cleanup_stale_nodes()

        found = await registry.get_node(node.node_id)
        assert found.status == NodeStatus.OFFLINE


# ─── CrossNodeRouter 测试 ────────────────────────────────────────────────────


class TestCrossNodeRouter:
    """跨节点路由器"""

    @pytest.mark.asyncio
    async def test_route_least_loaded(self, router):
        decision = await router.route(
            capability="code_generation",
            strategy=RoutingStrategy.LEAST_LOADED,
        )
        assert decision is not None
        assert decision.strategy_used == RoutingStrategy.LEAST_LOADED
        assert decision.target_node_id
        assert decision.target_host

    @pytest.mark.asyncio
    async def test_route_round_robin(self, router):
        """轮询应轮流分配节点"""
        node_ids = set()
        for _ in range(6):
            decision = await router.route(
                capability="code_generation",
                strategy=RoutingStrategy.ROUND_ROBIN,
            )
            assert decision is not None
            node_ids.add(decision.target_node_id)
        # 3 个节点应该都被轮询到
        assert len(node_ids) >= 2

    @pytest.mark.asyncio
    async def test_route_consistent_hash(self, router):
        """一致性哈希：相同 task_id 应路由到相同节点"""
        decision1 = await router.route(
            capability="code_generation",
            strategy=RoutingStrategy.CONSISTENT_HASH,
            task_id="task-abc",
        )
        decision2 = await router.route(
            capability="code_generation",
            strategy=RoutingStrategy.CONSISTENT_HASH,
            task_id="task-abc",
        )
        assert decision1.target_node_id == decision2.target_node_id

    @pytest.mark.asyncio
    async def test_route_weighted(self, router):
        decision = await router.route(
            capability="code_generation",
            strategy=RoutingStrategy.WEIGHTED,
        )
        assert decision is not None
        assert decision.strategy_used == RoutingStrategy.WEIGHTED

    @pytest.mark.asyncio
    async def test_route_random(self, router):
        decision = await router.route(
            capability="code_generation",
            strategy=RoutingStrategy.RANDOM,
        )
        assert decision is not None
        assert decision.strategy_used == RoutingStrategy.RANDOM

    @pytest.mark.asyncio
    async def test_route_no_capability_match(self, router):
        decision = await router.route(
            capability="browser_control",
            strategy=RoutingStrategy.LEAST_LOADED,
        )
        assert decision is None

    @pytest.mark.asyncio
    async def test_route_batch(self, router):
        tasks = [
            {"task_id": f"batch-{i}", "capability": "code_generation"}
            for i in range(5)
        ]
        results = await router.route_batch(tasks)
        assert len(results) == 5
        for tid, decision in results:
            assert decision is not None

    @pytest.mark.asyncio
    async def test_hash_ring_consistency(self, router):
        """验证哈希环构建不会崩溃"""
        ring = router._build_hash_ring([
            make_node("n1"), make_node("n2"), make_node("n3"),
        ])
        assert len(ring) == 3 * router._virtual_nodes
        # 验证有序
        for i in range(1, len(ring)):
            assert ring[i][0] >= ring[i-1][0]


# ─── NodeHealthChecker 测试 ──────────────────────────────────────────────────


class TestNodeHealthChecker:
    """节点健康检查器"""

    @pytest.mark.asyncio
    async def test_initialization(self, populated_registry):
        checker = NodeHealthChecker(populated_registry)
        assert checker._unhealthy_threshold == 3
        assert checker._healthy_threshold == 2

    @pytest.mark.asyncio
    async def test_get_probe_stats(self, populated_registry):
        checker = NodeHealthChecker(populated_registry)
        stats = await checker.get_probe_stats()
        assert "failure_counts" in stats
        assert "unhealthy_threshold" in stats


# ─── MultiNodeScheduler 集成测试 ─────────────────────────────────────────────


class TestMultiNodeScheduler:
    """多节点调度器集成"""

    @pytest.mark.asyncio
    async def test_start_and_stop(self, multi_scheduler):
        assert multi_scheduler._running

    @pytest.mark.asyncio
    async def test_schedule_task_local(self, multi_scheduler):
        """当只有一个节点时，任务应调度到自身"""
        decision = await multi_scheduler.schedule_task(
            task_id="task-1",
            capability="test",
        )
        assert decision is not None
        assert decision.target_node_id == multi_scheduler.this_node_id

    @pytest.mark.asyncio
    async def test_schedule_task_with_peer(self, multi_scheduler):
        """当存在对等节点时，任务可能路由到对等节点"""
        peer = make_node(
            "peer-1",
            host="192.168.1.100",
            port=9001,
            capabilities=["test"],
            max_tasks=10,
        )
        await multi_scheduler.register_peer(peer)

        decision = await multi_scheduler.schedule_task(
            task_id="task-2",
            capability="test",
        )
        assert decision is not None

    @pytest.mark.asyncio
    async def test_schedule_no_matching_capability(self, multi_scheduler):
        """没有节点具有所需能力时应失败"""
        decision = await multi_scheduler.schedule_task(
            task_id="task-no-cap",
            capability="quantum_computing",
        )
        assert decision is None

    @pytest.mark.asyncio
    async def test_complete_task(self, multi_scheduler):
        """完成任务应更新状态"""
        decision = await multi_scheduler.schedule_task(
            task_id="complete-me",
            capability="test",
        )
        assert decision is not None

        success = await multi_scheduler.complete_task("complete-me", {"ok": True})
        assert success

    @pytest.mark.asyncio
    async def test_complete_nonexistent_task(self, multi_scheduler):
        success = await multi_scheduler.complete_task("phantom")
        assert not success

    @pytest.mark.asyncio
    async def test_schedule_batch(self, multi_scheduler):
        tasks = [
            {"task_id": f"sched-batch-{i}", "capability": "test"}
            for i in range(5)
        ]
        results = await multi_scheduler.schedule_batch(tasks)
        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_register_and_deregister_peer(self, multi_scheduler):
        peer = make_node("temp-peer", host="10.0.0.1", port=9999)
        registered = await multi_scheduler.register_peer(peer)
        assert registered.node_id

        peers_before = await multi_scheduler.list_peers()
        assert any(p["node_id"] == peer.node_id for p in peers_before)

        await multi_scheduler.deregister_peer(peer.node_id)
        peers_after = await multi_scheduler.list_peers()
        assert not any(p["node_id"] == peer.node_id for p in peers_after)

    @pytest.mark.asyncio
    async def test_send_heartbeat(self, multi_scheduler):
        hb = await multi_scheduler.send_heartbeat()
        assert hb.node_id == multi_scheduler.this_node_id

    @pytest.mark.asyncio
    async def test_get_cluster_topology(self, multi_scheduler):
        topology = await multi_scheduler.get_cluster_topology()
        assert "this_node" in topology
        assert "peers" in topology
        assert "stats" in topology
        assert "routing_strategy" in topology

    @pytest.mark.asyncio
    async def test_get_node_detail(self, multi_scheduler):
        detail = await multi_scheduler.get_node_detail(
            multi_scheduler.this_node_id
        )
        assert detail is not None
        assert detail["node_id"] == multi_scheduler.this_node_id

    @pytest.mark.asyncio
    async def test_get_nonexistent_node(self, multi_scheduler):
        detail = await multi_scheduler.get_node_detail("nonexistent")
        assert detail is None

    @pytest.mark.asyncio
    async def test_this_node_properties(self, multi_scheduler):
        assert multi_scheduler.this_node_id
        assert multi_scheduler.this_node_name == "scheduler-test"


# ─── 策略枚举测试 ────────────────────────────────────────────────────────────


class TestRoutingStrategy:
    """路由策略枚举"""

    def test_all_strategies(self):
        strategies = list(RoutingStrategy)
        assert RoutingStrategy.LEAST_LOADED in strategies
        assert RoutingStrategy.ROUND_ROBIN in strategies
        assert RoutingStrategy.CONSISTENT_HASH in strategies
        assert RoutingStrategy.WEIGHTED in strategies
        assert RoutingStrategy.RANDOM in strategies

    def test_parse_from_string(self):
        assert RoutingStrategy("least_loaded") == RoutingStrategy.LEAST_LOADED
        assert RoutingStrategy("random") == RoutingStrategy.RANDOM

    def test_invalid_strategy(self):
        with pytest.raises(ValueError):
            RoutingStrategy("invalid")
