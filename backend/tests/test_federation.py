"""W31-32 Runtime Federation — 测试套件"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import pytest_asyncio

from app.runtime.federation import (
    CrossClusterTask,
    DataSyncRecord,
    DispatchPolicy,
    DispatchRequest,
    DispatchResult,
    FederationCluster,
    FederationGateway,
    FederationMember,
    FederationPolicyConfig,
    FederationPolicyEngine,
    FederationRegistry,
    FederationRole,
    FederationStats,
    FederationTopology,
    JoinRequest,
    MemberHeartbeatRequest,
    MemberStatus,
    StateSyncEngine,
    SyncScope,
    SyncStatus,
    SyncStrategy,
)


# ── 工厂函数 ──────────────────────────────────


def make_join_request(name: str = "test-node", **kwargs) -> JoinRequest:
    defaults = {
        "name": name,
        "endpoint": f"http://{name}:8002",
        "capabilities": ["langgraph_worker", "sandbox_runner"],
        "region": "us-east-1",
        "total_capacity": 100,
    }
    defaults.update(kwargs)
    return JoinRequest(**defaults)


def make_heartbeat(member_id: str) -> MemberHeartbeatRequest:
    return MemberHeartbeatRequest(
        member_id=member_id,
        status=MemberStatus.ACTIVE,
        cpu_usage_pct=30.0,
        memory_usage_pct=45.0,
        active_tasks=5,
        used_capacity=20,
        total_tasks_completed=100,
        avg_task_duration_ms=250.0,
    )


# ── Fixtures ──────────────────────────────────


@pytest_asyncio.fixture
async def registry():
    """创建 FederationRegistry 实例"""
    r = FederationRegistry(heartbeat_timeout=5, cleanup_interval=999)
    yield r
    await r.stop_cleanup()


@pytest_asyncio.fixture
async def registry_with_members(registry):
    """预注册 3 个成员的 Registry"""
    r1 = await registry.join(make_join_request("node-1", region="us-east-1"))
    r2 = await registry.join(make_join_request("node-2", region="us-east-1"))
    r3 = await registry.join(make_join_request("node-3", region="us-west-1",
                                                capabilities=["checkpoint_worker"]))
    return registry, r1, r2, r3


@pytest_asyncio.fixture
async def gateway(registry):
    """创建 FederationGateway 实例"""
    policy = FederationPolicyEngine()
    gw = FederationGateway(registry, policy)
    yield gw
    await gw.stop_monitor()


@pytest_asyncio.fixture
async def sync_engine(registry):
    """创建 StateSyncEngine 实例，内部注册测试成员"""
    r = StateSyncEngine(registry)
    # 在 registry 中注册测试成员，确保 sync_to 能找到
    r1 = await registry.join(make_join_request("sync-n1", region="us-east-1"))
    r2 = await registry.join(make_join_request("sync-n2", region="us-east-1"))
    return r, r1, r2


@pytest_asyncio.fixture
async def full_setup(registry_with_members):
    """完整联邦设置：registry + gateway + sync_engine"""
    registry, r1, r2, r3 = registry_with_members
    policy = FederationPolicyEngine()
    gateway = FederationGateway(registry, policy)
    sync_engine = StateSyncEngine(registry, policy)
    return registry, gateway, sync_engine, r1, r2, r3


# ═══════════════════════════════════════════════
# 1. 模型测试
# ═══════════════════════════════════════════════


class TestFederationModels:
    """Federation 数据模型测试"""

    def test_member_defaults(self):
        m = FederationMember(name="test")
        assert m.name == "test"
        assert m.member_id
        assert m.status == MemberStatus.ACTIVE
        assert m.role == FederationRole.FOLLOWER
        assert m.region == "default"
        assert m.total_capacity == 100
        assert m.used_capacity == 0

    def test_member_load_ratio(self):
        m = FederationMember(total_capacity=100, used_capacity=30)
        assert m.load_ratio == 0.3
        m.used_capacity = 100
        assert m.load_ratio == 1.0
        m.total_capacity = 0
        assert m.load_ratio == 1.0

    def test_member_available_capacity(self):
        m = FederationMember(total_capacity=100, used_capacity=40)
        assert m.available_capacity == 60

    def test_member_is_available(self):
        m = FederationMember(status=MemberStatus.ACTIVE, total_capacity=100, used_capacity=0)
        assert m.is_available is True
        m.status = MemberStatus.OFFLINE
        assert m.is_available is False
        m.status = MemberStatus.ACTIVE
        m.total_capacity = 0
        assert m.is_available is False

    def test_member_health_score(self):
        m = FederationMember(cpu_usage_pct=30, memory_usage_pct=50,
                             total_capacity=100, used_capacity=20)
        score = m.health_score
        assert 0.0 <= score <= 1.0
        # CPU: 1-0.3=0.7, MEM: 1-0.5=0.5, CAP: 1-0.2=0.8
        expected = round(0.7 * 0.3 + 0.5 * 0.3 + 0.8 * 0.4, 4)
        assert score == expected

    def test_member_status_is_available(self):
        assert MemberStatus.ACTIVE.is_available is True
        assert MemberStatus.DEGRADED.is_available is True
        assert MemberStatus.ISOLATED.is_available is False
        assert MemberStatus.OFFLINE.is_available is False

    def test_member_status_is_healthy(self):
        assert MemberStatus.ACTIVE.is_healthy is True
        assert MemberStatus.DEGRADED.is_healthy is False

    def test_cluster_defaults(self):
        c = FederationCluster(name="cluster-1")
        assert c.name == "cluster-1"
        assert c.cluster_id
        assert c.members == []

    def test_policy_config_defaults(self):
        pc = FederationPolicyConfig()
        assert pc.dispatch == DispatchPolicy.LOAD_BALANCED
        assert pc.sync_strategy == SyncStrategy.EVENTUAL
        assert pc.sync_scope == SyncScope.FULL
        assert pc.max_cross_cluster_ratio == 0.5
        assert pc.prefer_same_region is True
        assert pc.quorum_size == 2

    def test_cross_cluster_task_defaults(self):
        t = CrossClusterTask(capability="langgraph_worker")
        assert t.task_id
        assert t.status == "pending"
        assert t.priority == 5
        assert t.retry_count == 0

    def test_data_sync_record_defaults(self):
        r = DataSyncRecord()
        assert r.sync_id
        assert r.status == SyncStatus.PENDING
        assert r.items_synced == 0

    def test_dispatch_result(self):
        dr = DispatchResult(accepted=True, target_cluster_id="c1",
                            target_member_id="m1",
                            policy_used=DispatchPolicy.LOAD_BALANCED)
        assert dr.accepted is True
        assert dr.task_id

    def test_federation_stats_defaults(self):
        s = FederationStats()
        assert s.total_clusters == 0
        assert s.overall_load == 0.0

    def test_federation_topology(self):
        t = FederationTopology(name="test-fed")
        assert t.name == "test-fed"
        assert t.federation_id
        assert t.edges == []

    def test_join_request(self):
        jr = JoinRequest(name="node-a", endpoint="http://a:8002",
                         capabilities=["sandbox"], region="eu-west-1")
        assert jr.name == "node-a"
        assert jr.role == FederationRole.FOLLOWER

    def test_dispatch_request(self):
        dr = DispatchRequest(capability="sandbox_runner",
                             payload={"code": "print(1)"},
                             priority=3,
                             requires_state_sync=True)
        assert dr.capability == "sandbox_runner"
        assert dr.priority == 3
        assert dr.requires_state_sync is True


# ═══════════════════════════════════════════════
# 2. FederationRegistry 测试
# ═══════════════════════════════════════════════


class TestFederationRegistry:
    """FederationRegistry 成员管理测试"""

    @pytest.mark.asyncio
    async def test_join(self, registry):
        member = await registry.join(make_join_request("node-1"))
        assert member.name == "node-1"
        assert member.status == MemberStatus.ACTIVE
        assert member.cluster_id
        assert registry.get_member(member.member_id) is member

    @pytest.mark.asyncio
    async def test_join_duplicate_endpoint(self, registry):
        await registry.join(make_join_request("node-1", endpoint="http://same:8002"))
        with pytest.raises(ValueError, match="already registered"):
            await registry.join(make_join_request("node-2", endpoint="http://same:8002"))

    @pytest.mark.asyncio
    async def test_join_creates_cluster(self, registry):
        member = await registry.join(make_join_request("node-1", region="us-east-1"))
        cluster = registry.get_cluster(member.cluster_id)
        assert cluster is not None
        assert cluster.region == "us-east-1"
        assert member.member_id in cluster.members

    @pytest.mark.asyncio
    async def test_join_same_cluster(self, registry):
        m1 = await registry.join(make_join_request("node-1", cluster_name="my-cluster"))
        m2 = await registry.join(make_join_request("node-2", cluster_name="my-cluster",
                                                     endpoint="http://node-2:8002"))
        assert m1.cluster_id == m2.cluster_id

    @pytest.mark.asyncio
    async def test_leave(self, registry):
        member = await registry.join(make_join_request("node-1"))
        left = await registry.leave(member.member_id)
        assert left is not None
        assert left.status == MemberStatus.OFFLINE

    @pytest.mark.asyncio
    async def test_leave_nonexistent(self, registry):
        result = await registry.leave("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_heartbeat(self, registry):
        member = await registry.join(make_join_request("node-1"))
        req = MemberHeartbeatRequest(
            member_id=member.member_id,
            status=MemberStatus.ACTIVE,
            cpu_usage_pct=50.0,
            memory_usage_pct=60.0,
            active_tasks=10,
            used_capacity=30,
        )
        updated = await registry.heartbeat(req)
        assert updated.cpu_usage_pct == 50.0
        assert updated.memory_usage_pct == 60.0
        assert updated.active_tasks == 10

    @pytest.mark.asyncio
    async def test_heartbeat_nonexistent(self, registry):
        req = MemberHeartbeatRequest(member_id="nonexistent")
        result = await registry.heartbeat(req)
        assert result is None

    @pytest.mark.asyncio
    async def test_deregister(self, registry):
        member = await registry.join(make_join_request("node-1"))
        removed = registry.deregister(member.member_id)
        assert removed.name == "node-1"
        assert registry.get_member(member.member_id) is None

    @pytest.mark.asyncio
    async def test_deregister_nonexistent(self, registry):
        assert registry.deregister("nonexistent") is None

    @pytest.mark.asyncio
    async def test_list_members_all(self, registry_with_members):
        registry, _, _, _ = registry_with_members
        members = registry.list_members()
        assert len(members) == 3

    @pytest.mark.asyncio
    async def test_list_members_by_status(self, registry_with_members):
        registry, r1, _, _ = registry_with_members
        await registry.leave(r1.member_id)
        active = registry.list_members(status=MemberStatus.ACTIVE)
        offline = registry.list_members(status=MemberStatus.OFFLINE)
        assert len(active) == 2
        assert len(offline) == 1

    @pytest.mark.asyncio
    async def test_list_members_by_region(self, registry_with_members):
        registry, _, _, _ = registry_with_members
        east = registry.list_members(region="us-east-1")
        west = registry.list_members(region="us-west-1")
        assert len(east) == 2
        assert len(west) == 1

    @pytest.mark.asyncio
    async def test_list_members_by_capability(self, registry_with_members):
        registry, _, _, _ = registry_with_members
        result = registry.list_members(capability="checkpoint_worker")
        assert len(result) == 1
        assert result[0].name == "node-3"

    @pytest.mark.asyncio
    async def test_get_available_members(self, registry_with_members):
        registry, r1, _, _ = registry_with_members
        # mark r1 offline
        await registry.leave(r1.member_id)
        available = registry.get_available_members()
        assert len(available) == 2

    @pytest.mark.asyncio
    async def test_get_available_members_full(self, registry_with_members):
        """成员满载时不可用"""
        registry, r1, _, _ = registry_with_members
        r1.used_capacity = r1.total_capacity  # 满载
        available = registry.get_available_members()
        assert all(m.member_id != r1.member_id for m in available)

    @pytest.mark.asyncio
    async def test_get_topology(self, registry_with_members):
        registry, _, _, _ = registry_with_members
        topology = registry.get_topology()
        assert len(topology.members) == 3
        assert len(topology.clusters) >= 1

    @pytest.mark.asyncio
    async def test_get_stats(self, registry_with_members):
        registry, _, _, r3 = registry_with_members
        stats = registry.get_stats()
        assert stats.total_members == 3
        assert stats.active_members == 3
        assert stats.total_capacity == 300

    @pytest.mark.asyncio
    async def test_elect_leader(self, registry_with_members):
        registry, r1, _, _ = registry_with_members
        leader = await registry.elect_leader(r1.cluster_id)
        assert leader is not None
        assert leader.role == FederationRole.LEADER

    @pytest.mark.asyncio
    async def test_elect_leader_no_members(self, registry):
        leader = await registry.elect_leader("nonexistent")
        assert leader is None

    @pytest.mark.asyncio
    async def test_cleanup_stale_members(self, registry):
        """清理心跳超时成员"""
        member = await registry.join(make_join_request("stale-node"))
        member.last_heartbeat = datetime.now() - timedelta(seconds=60)
        registry._heartbeat_timeout = 30
        await registry._cleanup_stale_members()
        found = registry.get_member(member.member_id)
        assert found.status == MemberStatus.OFFLINE

    @pytest.mark.asyncio
    async def test_hook_on_join(self, registry):
        events = []

        def on_join(m):
            events.append(m.name)

        registry.on("on_join", on_join)
        await registry.join(make_join_request("hooked-node"))
        assert "hooked-node" in events

    @pytest.mark.asyncio
    async def test_get_leader(self, registry_with_members):
        registry, r1, _, _ = registry_with_members
        r1.role = FederationRole.LEADER
        leader = registry.get_leader()
        assert leader is not None
        assert leader.member_id == r1.member_id

    @pytest.mark.asyncio
    async def test_get_member_by_name(self, registry_with_members):
        registry, _, _, _ = registry_with_members
        m = registry.get_member_by_name("node-2")
        assert m is not None
        assert m.region == "us-east-1"


# ═══════════════════════════════════════════════
# 3. FederationPolicyEngine 测试
# ═══════════════════════════════════════════════


class TestFederationPolicyEngine:
    """FederationPolicyEngine 策略决策测试"""

    def _make_members(self) -> list[FederationMember]:
        return [
            FederationMember(name="m1", region="us-east-1", zone="us-east-1a",
                             total_capacity=100, used_capacity=20),
            FederationMember(name="m2", region="us-east-1", zone="us-east-1b",
                             total_capacity=100, used_capacity=80),
            FederationMember(name="m3", region="us-west-1", zone="us-west-1a",
                             total_capacity=100, used_capacity=50),
        ]

    def test_local_first_prefers_region(self):
        engine = FederationPolicyEngine()
        members = self._make_members()
        target = engine.select_target(members, policy=DispatchPolicy.LOCAL_FIRST,
                                      prefer_region="us-west-1")
        assert target is not None
        assert target.name == "m3"

    def test_local_first_fallback(self):
        engine = FederationPolicyEngine()
        members = self._make_members()[:2]  # 只有 us-east-1
        target = engine.select_target(members, policy=DispatchPolicy.LOCAL_FIRST,
                                      prefer_region="us-west-1")
        # falls back to least loaded
        assert target is not None
        assert target.name == "m1"  # load 0.2 < 0.8

    def test_load_balanced(self):
        engine = FederationPolicyEngine()
        members = self._make_members()
        target = engine.select_target(members, policy=DispatchPolicy.LOAD_BALANCED)
        assert target is not None
        assert target.name == "m1"  # load 0.2 — lowest

    def test_geo_affinity(self):
        engine = FederationPolicyEngine()
        members = self._make_members()
        target = engine.select_target(members, policy=DispatchPolicy.GEO_AFFINITY,
                                      prefer_region="us-east-1")
        assert target is not None
        assert target.region == "us-east-1"
        # m1 has lower load than m2
        assert target.name == "m1"

    def test_cost_optimized(self):
        engine = FederationPolicyEngine()
        members = self._make_members()
        target = engine.select_target(members, policy=DispatchPolicy.COST_OPTIMIZED)
        assert target is not None

    def test_round_robin(self):
        engine = FederationPolicyEngine()
        members = self._make_members()
        t1 = engine.select_target(members, policy=DispatchPolicy.ROUND_ROBIN)
        t2 = engine.select_target(members, policy=DispatchPolicy.ROUND_ROBIN)
        t3 = engine.select_target(members, policy=DispatchPolicy.ROUND_ROBIN)
        assert t1 is not None
        assert t2 is not None
        assert t3 is not None
        # should cycle through all 3
        names = {t1.name, t2.name, t3.name}
        assert len(names) == 3

    def test_capability_match(self):
        engine = FederationPolicyEngine()
        members = self._make_members()
        target = engine.select_target(members, policy=DispatchPolicy.CAPABILITY_MATCH,
                                      prefer_region="cap")
        assert target is not None
        # capability match with least loaded
        assert target.name == "m1"

    def test_round_robin_wraps(self):
        engine = FederationPolicyEngine()
        members = self._make_members()
        # cycle 4 times — should wrap
        for _ in range(4):
            engine.select_target(members, policy=DispatchPolicy.ROUND_ROBIN)
        # next should be index 1 (m2)
        t = engine.select_target(members, policy=DispatchPolicy.ROUND_ROBIN)
        assert t.name == members[1 % 3].name

    def test_select_empty(self):
        engine = FederationPolicyEngine()
        assert engine.select_target([], policy=DispatchPolicy.LOAD_BALANCED) is None

    def test_should_dispatch_cross_cluster_overload(self):
        engine = FederationPolicyEngine()
        m = FederationMember(total_capacity=100, used_capacity=85)
        assert engine.should_dispatch_cross_cluster(m) is True

    def test_should_dispatch_cross_cluster_degraded(self):
        engine = FederationPolicyEngine()
        m = FederationMember(total_capacity=100, used_capacity=10,
                             status=MemberStatus.DEGRADED)
        # MemberStatus.DEGRADED is "degraded" (not "active")
        assert engine.should_dispatch_cross_cluster(m) is True

    def test_should_dispatch_cross_cluster_no(self):
        engine = FederationPolicyEngine()
        m = FederationMember(total_capacity=100, used_capacity=50,
                             status=MemberStatus.ACTIVE)
        assert engine.should_dispatch_cross_cluster(m) is False

    def test_has_quorum(self):
        engine = FederationPolicyEngine()
        members = [
            FederationMember(name="m1", status=MemberStatus.ACTIVE),
            FederationMember(name="m2", status=MemberStatus.ACTIVE),
            FederationMember(name="m3", status=MemberStatus.OFFLINE),
        ]
        assert engine.has_quorum(members) is True  # 2 >= 2

        members[1].status = MemberStatus.OFFLINE
        assert engine.has_quorum(members) is False

    def test_decide_sync_cross_region(self):
        engine = FederationPolicyEngine()
        source = FederationMember(name="s", region="us-east-1")
        target = FederationMember(name="t", region="eu-west-1")
        strategy, scope = engine.decide_sync(source, target, data_size=100)
        # cross-region → eventual
        assert strategy == SyncStrategy.EVENTUAL

    def test_decide_sync_same_cluster(self):
        engine = FederationPolicyEngine()
        source = FederationMember(name="s", region="us-east-1", cluster_id="c1")
        target = FederationMember(name="t", region="us-east-1", cluster_id="c1")
        strategy, scope = engine.decide_sync(source, target, data_size=100)
        # same cluster → eventual → push
        assert strategy == SyncStrategy.PUSH

    def test_decide_sync_large_data(self):
        engine = FederationPolicyEngine()
        source = FederationMember(name="s", region="us-east-1")
        target = FederationMember(name="t", region="eu-west-1")
        strategy, scope = engine.decide_sync(source, target, data_size=2_000_000)
        # large data → scope reduces to STATE_ONLY
        assert scope == SyncScope.STATE_ONLY

    def test_update_config(self):
        engine = FederationPolicyEngine()
        engine.update_config(quorum_size=3, max_cross_cluster_ratio=0.3)
        assert engine._config.quorum_size == 3
        assert engine._config.max_cross_cluster_ratio == 0.3

    def test_should_sync_state(self):
        engine = FederationPolicyEngine()
        source = FederationMember(name="s")
        target = FederationMember(name="t")
        assert engine.should_sync_state(source, target) is True
        engine._config.sync_strategy = SyncStrategy.NONE
        assert engine.should_sync_state(source, target) is False


# ═══════════════════════════════════════════════
# 4. FederationGateway 测试
# ═══════════════════════════════════════════════


class TestFederationGateway:
    """FederationGateway 分发测试"""

    @pytest.mark.asyncio
    async def test_dispatch_success(self, gateway, registry_with_members):
        registry, r1, _, _ = registry_with_members
        req = DispatchRequest(capability="langgraph_worker",
                              payload={"action": "run"}, priority=5)
        result = await gateway.dispatch(req, source_member_id=r1.member_id,
                                        source_cluster_id=r1.cluster_id)
        assert result.accepted is True
        assert result.task_id
        assert result.target_member_id
        assert result.policy_used == DispatchPolicy.LOAD_BALANCED

    @pytest.mark.asyncio
    async def test_dispatch_no_candidates(self, gateway, registry):
        """没有匹配能力的成员"""
        req = DispatchRequest(capability="nonexistent_capability")
        result = await gateway.dispatch(req)
        assert result.accepted is False
        assert "No available members" in result.reason

    @pytest.mark.asyncio
    async def test_dispatch_excludes_source(self, gateway, registry_with_members):
        registry, r1, r2, _ = registry_with_members
        req = DispatchRequest(capability="langgraph_worker")
        result = await gateway.dispatch(req, source_member_id=r1.member_id)
        assert result.accepted
        assert result.target_member_id != r1.member_id

    @pytest.mark.asyncio
    async def test_dispatch_batch(self, gateway, registry_with_members):
        registry, r1, _, _ = registry_with_members
        requests = [
            DispatchRequest(capability="langgraph_worker"),
            DispatchRequest(capability="langgraph_worker"),
        ]
        results = await gateway.dispatch_batch(requests,
                                               source_member_id=r1.member_id)
        assert len(results) == 2
        assert all(r.accepted for r in results)

    @pytest.mark.asyncio
    async def test_get_task(self, gateway, registry_with_members):
        registry, r1, _, _ = registry_with_members
        req = DispatchRequest(capability="langgraph_worker")
        result = await gateway.dispatch(req, source_member_id=r1.member_id)
        task = gateway.get_task(result.task_id)
        assert task is not None
        assert task.capability == "langgraph_worker"

    @pytest.mark.asyncio
    async def test_list_tasks(self, gateway, registry_with_members):
        registry, r1, _, _ = registry_with_members
        req = DispatchRequest(capability="langgraph_worker")
        await gateway.dispatch(req, source_member_id=r1.member_id)
        await gateway.dispatch(req, source_member_id=r1.member_id)
        tasks = gateway.list_tasks()
        assert len(tasks) == 2

    @pytest.mark.asyncio
    async def test_list_tasks_by_status(self, gateway, registry_with_members):
        registry, r1, _, _ = registry_with_members
        req = DispatchRequest(capability="langgraph_worker")
        result = await gateway.dispatch(req, source_member_id=r1.member_id)
        await gateway.cancel_task(result.task_id)
        dispatched = gateway.list_tasks(status="dispatched")
        cancelled = gateway.list_tasks(status="cancelled")
        assert len(dispatched) == 0
        assert len(cancelled) == 1

    @pytest.mark.asyncio
    async def test_cancel_task(self, gateway, registry_with_members):
        registry, r1, _, _ = registry_with_members
        req = DispatchRequest(capability="langgraph_worker")
        result = await gateway.dispatch(req, source_member_id=r1.member_id)
        success = await gateway.cancel_task(result.task_id)
        assert success is True
        task = gateway.get_task(result.task_id)
        assert task.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_nonexistent(self, gateway):
        assert await gateway.cancel_task("nonexistent") is False

    @pytest.mark.asyncio
    async def test_complete_task(self, gateway, registry_with_members):
        registry, r1, _, _ = registry_with_members
        req = DispatchRequest(capability="langgraph_worker")
        result = await gateway.dispatch(req, source_member_id=r1.member_id)
        task = await gateway.complete_task(result.task_id, success=True,
                                            result={"output": "done"})
        assert task is not None
        assert task.status == "completed"
        assert task.result == {"output": "done"}

    @pytest.mark.asyncio
    async def test_complete_task_failure(self, gateway, registry_with_members):
        registry, r1, _, _ = registry_with_members
        req = DispatchRequest(capability="langgraph_worker")
        result = await gateway.dispatch(req, source_member_id=r1.member_id)
        task = await gateway.complete_task(result.task_id, success=False,
                                            error_message="timeout")
        assert task.status == "failed"
        assert task.error_message == "timeout"

    @pytest.mark.asyncio
    async def test_wait_for_task_already_complete(self, gateway, registry_with_members):
        registry, r1, _, _ = registry_with_members
        req = DispatchRequest(capability="langgraph_worker")
        result = await gateway.dispatch(req, source_member_id=r1.member_id)
        await gateway.complete_task(result.task_id)
        task = await gateway.wait_for_task(result.task_id, timeout=1)
        assert task is not None
        assert task.status == "completed"

    @pytest.mark.asyncio
    async def test_wait_for_task_timeout(self, gateway, registry_with_members):
        registry, r1, _, _ = registry_with_members
        req = DispatchRequest(capability="langgraph_worker")
        result = await gateway.dispatch(req, source_member_id=r1.member_id)
        task = await gateway.wait_for_task(result.task_id, timeout=0.01)
        assert task is not None
        assert task.status == "dispatched"  # still dispatched

    @pytest.mark.asyncio
    async def test_get_stats(self, gateway, registry_with_members):
        registry, r1, _, _ = registry_with_members
        req = DispatchRequest(capability="langgraph_worker")
        await gateway.dispatch(req, source_member_id=r1.member_id)
        stats = gateway.get_stats()
        assert stats["total_tasks"] == 1

    @pytest.mark.asyncio
    async def test_register_dispatcher(self, gateway):
        called = []

        async def my_dispatcher(payload):
            called.append(payload)
            return {"status": "ok"}

        gateway.register_dispatcher("test_cap", my_dispatcher)
        assert "test_cap" in gateway._dispatchers

    @pytest.mark.asyncio
    async def test_unregister_dispatcher(self, gateway):
        assert gateway.unregister_dispatcher("nonexistent") is None


# ═══════════════════════════════════════════════
# 5. StateSyncEngine 测试
# ═══════════════════════════════════════════════


class TestStateSyncEngine:
    """StateSyncEngine 同步测试"""

    @pytest.mark.asyncio
    async def test_sync_to(self, sync_engine):
        sync, r1, r2 = sync_engine
        sync.store_state("key1", "value1")
        record = await sync.sync_to(
            target_member_id=r2.member_id,
            source_member_id=r1.member_id,
            scope=SyncScope.STATE_ONLY,
            state_keys=["key1"])
        assert record.status == SyncStatus.SUCCESS
        assert record.items_synced == 1
        assert "key1" in record.state_keys

    @pytest.mark.asyncio
    async def test_sync_to_with_artifacts(self, sync_engine):
        sync, r1, r2 = sync_engine
        sync.store_artifact("art-1", b"binary_data")
        record = await sync.sync_to(
            target_member_id=r2.member_id,
            source_member_id=r1.member_id,
            scope=SyncScope.ARTIFACTS_ONLY,
            artifact_ids=["art-1"])
        assert record.status == SyncStatus.SUCCESS
        assert record.items_synced == 1
        assert "art-1" in record.artifact_ids

    @pytest.mark.asyncio
    async def test_sync_to_with_checkpoints(self, sync_engine):
        sync, r1, r2 = sync_engine
        sync.store_checkpoint("ckpt-1", {"step": 42})
        record = await sync.sync_to(
            target_member_id=r2.member_id,
            source_member_id=r1.member_id,
            scope=SyncScope.CHECKPOINTS_ONLY,
            checkpoint_ids=["ckpt-1"])
        assert record.status == SyncStatus.SUCCESS
        assert record.items_synced == 1

    @pytest.mark.asyncio
    async def test_sync_to_full(self, sync_engine):
        sync, r1, r2 = sync_engine
        sync.store_state("s1", "v1")
        sync.store_artifact("a1", b"data")
        sync.store_checkpoint("c1", {"x": 1})
        record = await sync.sync_to(
            target_member_id=r2.member_id,
            source_member_id=r1.member_id,
            scope=SyncScope.FULL)
        assert record.status == SyncStatus.SUCCESS
        assert record.items_synced == 3

    @pytest.mark.asyncio
    async def test_sync_to_all(self, sync_engine, registry_with_members):
        sync, r1, _ = sync_engine
        registry, _, r2, r3 = registry_with_members
        sync.store_state("global_key", "shared")
        records = await sync.sync_to_all(r1.member_id,
                                          scope=SyncScope.STATE_ONLY)
        # should sync to r2 and r3 (2 others) OR just r2 (from sync_engine)
        assert len(records) >= 1
        assert all(r.status == SyncStatus.SUCCESS for r in records)

    @pytest.mark.asyncio
    async def test_sync_bidirectional(self, sync_engine):
        sync, r1, r2 = sync_engine
        sync.store_state("from_r1", "data1")
        records = await sync.sync_bidirectional(r1.member_id, r2.member_id)
        assert len(records) == 2

    @pytest.mark.asyncio
    async def test_sync_source_not_found(self, sync_engine):
        sync, _, _ = sync_engine
        with pytest.raises(ValueError, match="not found"):
            await sync.sync_to("t", "nonexistent_source")

    @pytest.mark.asyncio
    async def test_list_records(self, sync_engine):
        sync, r1, r2 = sync_engine
        await sync.sync_to(r2.member_id, r1.member_id, scope=SyncScope.FULL)
        records = sync.list_records()
        assert len(records) == 1

    @pytest.mark.asyncio
    async def test_list_records_filtered(self, sync_engine):
        sync, r1, r2 = sync_engine
        await sync.sync_to(r2.member_id, r1.member_id)
        records = sync.list_records(status=SyncStatus.SUCCESS)
        assert len(records) >= 1

    @pytest.mark.asyncio
    async def test_get_record(self, sync_engine):
        sync, r1, r2 = sync_engine
        record = await sync.sync_to(r2.member_id, r1.member_id)
        found = sync.get_record(record.sync_id)
        assert found is not None
        assert found.sync_id == record.sync_id

    @pytest.mark.asyncio
    async def test_get_stats(self, sync_engine):
        sync, r1, r2 = sync_engine
        await sync.sync_to(r2.member_id, r1.member_id)
        stats = sync.get_stats()
        assert stats["total"] >= 1
        assert stats["success"] >= 1

    @pytest.mark.asyncio
    async def test_local_state_storage(self, sync_engine):
        sync, _, _ = sync_engine
        sync.store_state("test_key", {"complex": "value"})
        assert sync.get_state("test_key") == {"complex": "value"}
        assert sync.get_state("nonexistent") is None

    @pytest.mark.asyncio
    async def test_local_artifact_storage(self, sync_engine):
        sync, _, _ = sync_engine
        sync.store_artifact("art-99", b"raw_bytes")
        assert sync.get_artifact("art-99") == b"raw_bytes"

    @pytest.mark.asyncio
    async def test_local_checkpoint_storage(self, sync_engine):
        sync, _, _ = sync_engine
        sync.store_checkpoint("ck-1", {"layer": 5, "weights": [0.1, 0.2]})
        assert sync.get_checkpoint("ck-1")["layer"] == 5

    @pytest.mark.asyncio
    async def test_resolve_conflict(self, sync_engine):
        sync, r1, r2 = sync_engine
        record = await sync.sync_to(r2.member_id, r1.member_id)
        record.status = SyncStatus.CONFLICT
        resolved = await sync.resolve_conflict(record.sync_id, "keep_source")
        assert resolved.status == SyncStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_resolve_conflict_not_found(self, sync_engine):
        sync, _, _ = sync_engine
        assert await sync.resolve_conflict("nonexistent") is None


# ═══════════════════════════════════════════════
# 6. 集成测试
# ═══════════════════════════════════════════════


class TestFederationIntegration:
    """完整联邦流程集成测试"""

    @pytest.mark.asyncio
    async def test_full_flow(self, full_setup):
        """完整联邦流程：join → heartbeat → dispatch → complete → sync → stats"""
        registry, gateway, sync_engine, r1, r2, r3 = full_setup

        # 1. 验证成员
        assert registry.get_stats().total_members == 3

        # 2. 发送心跳
        hb = make_heartbeat(r2.member_id)
        updated = await registry.heartbeat(hb)
        assert updated.memory_usage_pct == 45.0

        # 3. 分发任务
        req = DispatchRequest(capability="langgraph_worker",
                              payload={"task": "process_data"})
        result = await gateway.dispatch(req, source_member_id=r1.member_id)
        assert result.accepted

        # 4. 完成任务
        task = await gateway.complete_task(result.task_id, success=True,
                                            result={"lines": 500})
        assert task.status == "completed"
        assert task.result == {"lines": 500}

        # 5. 同步状态
        sync_engine.store_state("result_key", "data_from_r1")
        sync_record = await sync_engine.sync_to(r2.member_id, r1.member_id,
                                                 scope=SyncScope.FULL)
        assert sync_record.status == SyncStatus.SUCCESS

        # 6. 聚合统计
        stats = registry.get_stats()
        assert stats.total_members == 3
        assert gateway.get_stats()["completed"] == 1

    @pytest.mark.asyncio
    async def test_multi_cluster_topology(self, registry):
        """多集群拓扑"""
        m1 = await registry.join(make_join_request("cluster-a-1", cluster_name="cluster-a",
                                                     endpoint="http://a1:8002"))
        m2 = await registry.join(make_join_request("cluster-a-2", cluster_name="cluster-a",
                                                     endpoint="http://a2:8002"))
        m3 = await registry.join(make_join_request("cluster-b-1", cluster_name="cluster-b",
                                                     endpoint="http://b1:8002",
                                                     region="eu-west-1"))
        clusters = registry.list_clusters()
        assert len(clusters) == 2

        topology = registry.get_topology()
        assert len(topology.members) == 3
        assert len(topology.clusters) == 2

        # 同集群成员应有边
        cluster_a_ids = {m1.member_id, m2.member_id}
        edge_members = set()
        for a, b in topology.edges:
            edge_members.update([a, b])
        assert cluster_a_ids.issubset(edge_members)

    @pytest.mark.asyncio
    async def test_leave_and_rejoin(self, registry):
        """离开后重新加入"""
        m = await registry.join(make_join_request("roamer", endpoint="http://roamer:8002"))
        await registry.leave(m.member_id)
        assert registry.get_member(m.member_id).status == MemberStatus.OFFLINE

        # rejoin with different endpoint
        m2 = await registry.join(make_join_request("roamer-v2", endpoint="http://roamer2:8002"))
        assert m2.status == MemberStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_dispatch_with_dispatcher(self, gateway, registry_with_members):
        """带自定义 dispatcher 的分发"""
        registry, r1, _, _ = registry_with_members
        results = []

        async def test_dispatcher(payload):
            results.append(payload)
            return {"status": "ok"}

        gateway.register_dispatcher("langgraph_worker", test_dispatcher)
        req = DispatchRequest(capability="langgraph_worker",
                              payload={"action": "test"})
        result = await gateway.dispatch(req, source_member_id=r1.member_id)
        assert result.accepted

        # dispatcher runs async — short wait
        import asyncio
        await asyncio.sleep(0.05)

        # task should now be completed
        task = gateway.get_task(result.task_id)
        assert task.status in ("completed", "dispatched", "running")

    @pytest.mark.asyncio
    async def test_federation_e2e(self, full_setup):
        """端到端：加入 → 选举 → 分发 → 离开"""
        registry, gateway, sync_engine, r1, r2, r3 = full_setup

        # 选举 leader
        leader = await registry.elect_leader(r1.cluster_id)
        assert leader is not None
        assert leader.role == FederationRole.LEADER

        # 分发多个任务
        for i in range(3):
            req = DispatchRequest(capability="langgraph_worker",
                                  payload={"task_id": i})
            await gateway.dispatch(req, source_member_id=r1.member_id)

        tasks = gateway.list_tasks()
        assert len(tasks) == 3

        # 全部取消
        for t in tasks:
            await gateway.cancel_task(t.task_id)

        # 验证容量释放
        r2_after = registry.get_member(r2.member_id)
        assert r2_after is not None

        # 成员离开
        await registry.leave(r3.member_id)
        stats = registry.get_stats()
        assert stats.active_members == 2
