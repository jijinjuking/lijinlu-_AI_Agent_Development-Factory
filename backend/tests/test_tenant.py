"""W33-34 Multi-Tenant 隔离 — 测试套件

覆盖：模型层、TenantManager、ResourceQuotaManager、DataIsolator、IsolationPolicy、TenantAuditLogger、集成测试
"""

from __future__ import annotations

import pytest

from app.runtime.tenant import (
    AuditEventType,
    AuditQuery,
    CrossTenantPolicy,
    DataIsolator,
    IsolationMode,
    IsolationPolicy,
    QuotaCheckResult,
    QuotaStatus,
    ResourceQuota,
    ResourceQuotaManager,
    ResourceType,
    Tenant,
    TenantAuditLogger,
    TenantConfig,
    TenantFilter,
    TenantManager,
    TenantMember,
    TenantQuota,
    TenantStatus,
)


# ══════════════════════════════════════════════
# 模型测试
# ══════════════════════════════════════════════


class TestTenantModels:
    """数据模型单元测试"""

    def test_tenant_status_properties(self):
        assert TenantStatus.ACTIVE.is_operational is True
        assert TenantStatus.PENDING.is_operational is False
        assert TenantStatus.SUSPENDED.is_operational is False
        assert TenantStatus.ARCHIVED.is_operational is False

    def test_isolation_mode_filter_requirement(self):
        assert IsolationMode.ROW_LEVEL.requires_tenant_filter is True
        assert IsolationMode.HYBRID.requires_tenant_filter is True
        assert IsolationMode.SCHEMA.requires_tenant_filter is False
        assert IsolationMode.SHARED.requires_tenant_filter is False

    def test_tenant_quota_basic(self):
        q = TenantQuota(resource_type=ResourceType.CPU_CORES, limit=10, used=3)
        assert q.usage_pct == 0.3
        assert q.remaining == 7.0
        assert q.status == QuotaStatus.OK

    def test_tenant_quota_warning(self):
        q = TenantQuota(resource_type=ResourceType.CPU_CORES, limit=10, used=8.5,
                        alert_threshold=0.8)
        assert q.status == QuotaStatus.WARNING

    def test_tenant_quota_exceeded(self):
        q = TenantQuota(resource_type=ResourceType.CPU_CORES, limit=10, used=12)
        assert q.status == QuotaStatus.EXCEEDED
        assert q.remaining == 0.0

    def test_tenant_quota_zero_limit(self):
        q = TenantQuota(resource_type=ResourceType.CPU_CORES, limit=0)
        assert q.status == QuotaStatus.OK
        assert q.usage_pct == 0.0

    def test_resource_quota_set_limit(self):
        rq = ResourceQuota()
        rq.set_limit(ResourceType.CPU_CORES, 4)
        assert rq.get(ResourceType.CPU_CORES).limit == 4
        assert rq.get(ResourceType.CPU_CORES).used == 0.0

    def test_resource_quota_check_ok(self):
        rq = ResourceQuota()
        rq.set_limit(ResourceType.MEMORY_MB, 1024)
        assert rq.check(ResourceType.MEMORY_MB, 200) == QuotaStatus.OK

    def test_resource_quota_check_exceeded(self):
        rq = ResourceQuota()
        rq.set_limit(ResourceType.MEMORY_MB, 100)
        assert rq.check(ResourceType.MEMORY_MB, 200) == QuotaStatus.EXCEEDED

    def test_resource_quota_consume_release(self):
        rq = ResourceQuota()
        rq.set_limit(ResourceType.STORAGE_MB, 1000)
        rq.consume(ResourceType.STORAGE_MB, 300)
        assert rq.get(ResourceType.STORAGE_MB).used == 300.0
        rq.release(ResourceType.STORAGE_MB, 100)
        assert rq.get(ResourceType.STORAGE_MB).used == 200.0

    def test_resource_quota_to_summary(self):
        rq = ResourceQuota()
        rq.set_limit(ResourceType.CPU_CORES, 4)
        summary = rq.to_summary()
        assert "cpu_cores" in summary
        assert summary["cpu_cores"]["limit"] == 4

    def test_tenant_defaults(self):
        t = Tenant()
        assert t.tenant_id
        assert t.status == TenantStatus.PENDING
        assert t.isolation_mode == IsolationMode.ROW_LEVEL
        assert t.cross_tenant_policy == CrossTenantPolicy.BLOCK_ALL

    def test_tenant_config(self):
        cfg = TenantConfig(
            tenant_name="Acme Corp",
            tenant_slug="acme",
            isolation_mode=IsolationMode.SCHEMA,
        )
        assert cfg.tenant_slug == "acme"
        assert cfg.isolation_mode == IsolationMode.SCHEMA

    def test_tenant_member_defaults(self):
        m = TenantMember(tenant_id="t1", user_id="u1")
        assert m.role == "member"
        assert m.permissions == []

    def test_quota_check_result(self):
        r = QuotaCheckResult(allowed=True)
        assert r.allowed

        r2 = QuotaCheckResult(
            allowed=False,
            status=QuotaStatus.EXCEEDED,
            exceeded_resources=[ResourceType.CPU_CORES],
            message="CPU quota exceeded",
        )
        assert not r2.allowed

    def test_tenant_filter_basic(self):
        tf = TenantFilter(tenant_id="t1")
        params = tf.apply_to_query({"name": "test"})
        assert params["tenant_id"] == "t1"
        assert params["name"] == "test"

    def test_tenant_filter_shared(self):
        tf = TenantFilter(tenant_id="t1", isolation_mode=IsolationMode.SHARED)
        params = tf.apply_to_query({"name": "test"})
        assert "tenant_id" not in params  # 共享模式不注入

    def test_tenant_filter_can_access(self):
        tf = TenantFilter(tenant_id="t1")
        assert tf.can_access_tenant("t1") is True
        assert tf.can_access_tenant("t2") is False


# ══════════════════════════════════════════════
# TenantManager 测试
# ══════════════════════════════════════════════


@pytest.fixture
def tm():
    return TenantManager()


@pytest.fixture
def active_tenant(tm):
    t = tm.create_tenant(TenantConfig(tenant_name="Test", tenant_slug="test"))
    tm.activate_tenant(t.tenant_id)
    return t


@pytest.fixture
def second_tenant(tm):
    t = tm.create_tenant(TenantConfig(
        tenant_name="Second", tenant_slug="second",
        isolation_mode=IsolationMode.SCHEMA,
        cross_tenant_policy=CrossTenantPolicy.BLOCK_ALL,
    ))
    tm.activate_tenant(t.tenant_id)
    return t


class TestTenantManager:
    """租户管理器测试"""

    def test_create_tenant(self, tm):
        cfg = TenantConfig(tenant_name="Acme", tenant_slug="acme")
        t = tm.create_tenant(cfg)
        assert t.name == "Acme"
        assert t.slug == "acme"
        assert t.status == TenantStatus.PENDING
        assert t.tenant_id

    def test_create_tenant_duplicate_slug(self, tm):
        tm.create_tenant(TenantConfig(tenant_name="One", tenant_slug="acme"))
        with pytest.raises(ValueError, match="already exists"):
            tm.create_tenant(TenantConfig(tenant_name="Two", tenant_slug="acme"))

    def test_get_tenant(self, tm, active_tenant):
        assert tm.get_tenant(active_tenant.tenant_id) is not None
        assert tm.get_tenant("nonexistent") is None

    def test_get_tenant_by_slug(self, tm, active_tenant):
        t = tm.get_tenant_by_slug("test")
        assert t is not None
        assert t.name == "Test"
        assert tm.get_tenant_by_slug("nope") is None

    def test_list_tenants(self, tm):
        tm.create_tenant(TenantConfig(tenant_name="A", tenant_slug="a"))
        tm.create_tenant(TenantConfig(tenant_name="B", tenant_slug="b"))
        assert len(tm.list_tenants()) == 2

    def test_list_tenants_filter_by_status(self, tm, active_tenant):
        tm.create_tenant(TenantConfig(tenant_name="P", tenant_slug="p"))
        active = tm.list_tenants(status=TenantStatus.ACTIVE)
        pending = tm.list_tenants(status=TenantStatus.PENDING)
        assert len(active) >= 1
        assert len(pending) >= 1

    def test_list_tenants_filter_by_isolation(self, tm, active_tenant, second_tenant):
        schema = tm.list_tenants(isolation_mode=IsolationMode.SCHEMA)
        assert len(schema) == 1
        assert schema[0].slug == "second"

    def test_activate_tenant(self, tm):
        t = tm.create_tenant(TenantConfig(tenant_name="X", tenant_slug="x"))
        assert t.status == TenantStatus.PENDING
        tm.activate_tenant(t.tenant_id)
        assert t.status == TenantStatus.ACTIVE
        assert t.activated_at is not None

    def test_activate_archived_raises(self, tm):
        t = tm.create_tenant(TenantConfig(tenant_name="X", tenant_slug="x2"))
        tm.activate_tenant(t.tenant_id)
        tm.archive_tenant(t.tenant_id)
        with pytest.raises(ValueError, match="Cannot activate"):
            tm.activate_tenant(t.tenant_id)

    def test_suspend_tenant(self, tm, active_tenant):
        tm.suspend_tenant(active_tenant.tenant_id, "overdue")
        assert active_tenant.status == TenantStatus.SUSPENDED
        assert active_tenant.suspended_reason == "overdue"
        assert active_tenant.suspended_at is not None

    def test_suspend_pending_raises(self, tm):
        t = tm.create_tenant(TenantConfig(tenant_name="P", tenant_slug="p1"))
        with pytest.raises(ValueError, match="Cannot suspend"):
            tm.suspend_tenant(t.tenant_id)

    def test_archive_tenant(self, tm, active_tenant):
        tm.archive_tenant(active_tenant.tenant_id)
        assert active_tenant.status == TenantStatus.ARCHIVED

    def test_delete_tenant(self, tm):
        t = tm.create_tenant(TenantConfig(tenant_name="D", tenant_slug="d"))
        tm.activate_tenant(t.tenant_id)
        tm.archive_tenant(t.tenant_id)
        assert tm.delete_tenant(t.tenant_id) is True
        assert tm.get_tenant(t.tenant_id) is None

    def test_delete_non_archived_raises(self, tm, active_tenant):
        with pytest.raises(ValueError, match="Archive first"):
            tm.delete_tenant(active_tenant.tenant_id)

    def test_re_activate_suspended(self, tm, active_tenant):
        tm.suspend_tenant(active_tenant.tenant_id, "test")
        assert active_tenant.status == TenantStatus.SUSPENDED
        tm.activate_tenant(active_tenant.tenant_id)
        assert active_tenant.status == TenantStatus.ACTIVE

    def test_update_tenant(self, tm, active_tenant):
        tm.update_tenant(active_tenant.tenant_id,
                         name="Renamed", tags={"env": "prod"})
        assert active_tenant.name == "Renamed"
        assert active_tenant.tags == {"env": "prod"}

    def test_update_tenant_ignores_readonly(self, tm, active_tenant):
        old_slug = active_tenant.slug
        tm.update_tenant(active_tenant.tenant_id, slug="hacked")
        assert active_tenant.slug == old_slug  # slug not updatable

    # 成员管理

    def test_add_member(self, tm, active_tenant):
        m = tm.add_member(active_tenant.tenant_id, "user-1")
        assert m.role == "member"
        assert m.tenant_id == active_tenant.tenant_id

    def test_add_duplicate_member(self, tm, active_tenant):
        m1 = tm.add_member(active_tenant.tenant_id, "user-1")
        m2 = tm.add_member(active_tenant.tenant_id, "user-1")
        assert m1.member_id == m2.member_id  # 去重

    def test_remove_member(self, tm, active_tenant):
        tm.add_member(active_tenant.tenant_id, "user-2")
        assert tm.remove_member(active_tenant.tenant_id, "user-2") is True
        assert tm.remove_member(active_tenant.tenant_id, "user-2") is False

    def test_get_tenant_members(self, tm, active_tenant):
        tm.add_member(active_tenant.tenant_id, "u1")
        tm.add_member(active_tenant.tenant_id, "u2")
        members = tm.get_tenant_members(active_tenant.tenant_id)
        assert len(members) == 2

    def test_get_user_tenants(self, tm, active_tenant, second_tenant):
        tm.add_member(active_tenant.tenant_id, "user-x")
        tm.add_member(second_tenant.tenant_id, "user-x")
        tenants = tm.get_user_tenants("user-x")
        assert len(tenants) == 2

    # 配额操作

    def test_set_and_check_quota(self, tm, active_tenant):
        tm.set_quota(active_tenant.tenant_id, ResourceType.CPU_CORES, 4)
        assert tm.check_quota(active_tenant.tenant_id, ResourceType.CPU_CORES, 1) == QuotaStatus.OK
        assert tm.check_quota(active_tenant.tenant_id, ResourceType.CPU_CORES, 10) == QuotaStatus.EXCEEDED

    def test_consume_release_quota(self, tm, active_tenant):
        tm.set_quota(active_tenant.tenant_id, ResourceType.TOKENS_PER_DAY, 1000)
        status = tm.consume_quota(active_tenant.tenant_id, ResourceType.TOKENS_PER_DAY, 500)
        assert status == QuotaStatus.OK
        tm.release_quota(active_tenant.tenant_id, ResourceType.TOKENS_PER_DAY, 200)
        # used should be 300
        tenant = tm.get_tenant(active_tenant.tenant_id)
        assert tenant.quota.get(ResourceType.TOKENS_PER_DAY).used == 300.0

    def test_check_all_quotas_ok(self, tm, active_tenant):
        tm.set_quota(active_tenant.tenant_id, ResourceType.CPU_CORES, 10)
        tm.set_quota(active_tenant.tenant_id, ResourceType.MEMORY_MB, 1024)
        result = tm.check_all_quotas(active_tenant.tenant_id)
        assert result.allowed is True

    def test_check_all_quotas_null(self, tm, active_tenant):
        """配额上限为0或未设置时，跳过检查"""
        result = tm.check_all_quotas(active_tenant.tenant_id)
        assert result.allowed is True

    # 跨租户访问

    def test_cross_tenant_access_block_all(self, tm, active_tenant, second_tenant):
        assert tm.check_cross_tenant_access(
            active_tenant.tenant_id, second_tenant.tenant_id) is False

    def test_cross_tenant_access_open(self, tm, active_tenant):
        tm.update_tenant(active_tenant.tenant_id,
                         cross_tenant_policy=CrossTenantPolicy.OPEN)
        assert tm.check_cross_tenant_access(active_tenant.tenant_id, "other") is True

    def test_cross_tenant_access_allow_list(self, tm, active_tenant, second_tenant):
        tm.update_tenant(active_tenant.tenant_id,
                         cross_tenant_policy=CrossTenantPolicy.ALLOW_LIST,
                         allowed_tenant_ids=[second_tenant.tenant_id])
        assert tm.check_cross_tenant_access(
            active_tenant.tenant_id, second_tenant.tenant_id) is True
        assert tm.check_cross_tenant_access(
            active_tenant.tenant_id, "random") is False

    def test_cross_tenant_access_self(self, tm, active_tenant):
        assert tm.check_cross_tenant_access(
            active_tenant.tenant_id, active_tenant.tenant_id) is True

    # 统计

    def test_get_tenant_stats(self, tm, active_tenant):
        stats = tm.get_tenant_stats(active_tenant.tenant_id)
        assert stats.tenant_name == "Test"
        assert stats.total_members == 0

    def test_get_all_stats(self, tm, active_tenant, second_tenant):
        stats = tm.get_all_stats()
        assert len(stats) >= 2

    def test_tenant_count(self, tm):
        assert tm.tenant_count == 0
        tm.create_tenant(TenantConfig(tenant_name="C", tenant_slug="c1"))
        assert tm.tenant_count == 1

    # 过滤器

    def test_create_filter(self, tm, active_tenant):
        tf = tm.create_filter(active_tenant.tenant_id)
        assert tf.tenant_id == active_tenant.tenant_id
        assert tf.isolation_mode == IsolationMode.ROW_LEVEL


# ══════════════════════════════════════════════
# ResourceQuotaManager 测试
# ══════════════════════════════════════════════


@pytest.fixture
def qm():
    tm = TenantManager()
    return ResourceQuotaManager(tm)


@pytest.fixture
def qm_tenant(qm):
    tm = qm._tm
    t = tm.create_tenant(TenantConfig(tenant_name="QTest", tenant_slug="qtest"))
    tm.activate_tenant(t.tenant_id)
    qm.allocate_default_quotas(t.tenant_id, "free")
    return t


class TestResourceQuotaManager:
    """资源配额管理器测试"""

    def test_allocate_default_quotas_free(self, qm, qm_tenant):
        summary = qm.get_quota_summary(qm_tenant.tenant_id)
        assert "cpu_cores" in summary
        assert summary["cpu_cores"]["limit"] == 1  # free tier

    def test_allocate_default_quotas_standard(self, qm):
        tm = qm._tm
        t = tm.create_tenant(TenantConfig(tenant_name="STest", tenant_slug="stest"))
        tm.activate_tenant(t.tenant_id)
        qm.allocate_default_quotas(t.tenant_id, "standard")
        summary = qm.get_quota_summary(t.tenant_id)
        assert summary["cpu_cores"]["limit"] == 4

    def test_allocate_default_quotas_enterprise(self, qm):
        tm = qm._tm
        t = tm.create_tenant(TenantConfig(tenant_name="ETest", tenant_slug="etest"))
        tm.activate_tenant(t.tenant_id)
        qm.allocate_default_quotas(t.tenant_id, "enterprise")
        summary = qm.get_quota_summary(t.tenant_id)
        assert summary["cpu_cores"]["limit"] == 32

    def test_allocate_quota(self, qm, qm_tenant):
        qm.allocate_quota(qm_tenant.tenant_id, ResourceType.CPU_CORES, 8)
        summary = qm.get_quota_summary(qm_tenant.tenant_id)
        assert summary["cpu_cores"]["limit"] == 8

    def test_try_consume_ok(self, qm, qm_tenant):
        result = qm.try_consume(qm_tenant.tenant_id,
                                ResourceType.API_CALLS_PER_DAY, 10)
        assert result.allowed
        assert result.status == QuotaStatus.OK

    def test_try_consume_exceeded(self, qm, qm_tenant):
        result = qm.try_consume(qm_tenant.tenant_id,
                                ResourceType.API_CALLS_PER_DAY, 9999)
        assert not result.allowed
        assert result.status == QuotaStatus.EXCEEDED

    def test_try_consume_suspended_tenant(self, qm, qm_tenant):
        qm._tm.suspend_tenant(qm_tenant.tenant_id, "test")
        result = qm.try_consume(qm_tenant.tenant_id,
                                ResourceType.API_CALLS_PER_DAY, 1)
        assert not result.allowed

    def test_batch_consume(self, qm, qm_tenant):
        result = qm.batch_consume(qm_tenant.tenant_id, {
            ResourceType.CPU_CORES: 0.5,
            ResourceType.MEMORY_MB: 200,
        })
        assert result.allowed
        summary = qm.get_quota_summary(qm_tenant.tenant_id)
        assert summary["cpu_cores"]["used"] == 0.5
        assert summary["memory_mb"]["used"] == 200

    def test_batch_consume_exceeded(self, qm, qm_tenant):
        result = qm.batch_consume(qm_tenant.tenant_id, {
            ResourceType.CPU_CORES: 999,
            ResourceType.MEMORY_MB: 1,
        })
        assert not result.allowed
        assert ResourceType.CPU_CORES in result.exceeded_resources
        # 失败时应回滚，memory 不被消费
        summary = qm.get_quota_summary(qm_tenant.tenant_id)
        assert summary["memory_mb"]["used"] == 0

    def test_release(self, qm, qm_tenant):
        qm.try_consume(qm_tenant.tenant_id, ResourceType.MEMORY_MB, 500)
        qm.release(qm_tenant.tenant_id, ResourceType.MEMORY_MB, 200)
        summary = qm.get_quota_summary(qm_tenant.tenant_id)
        assert summary["memory_mb"]["used"] == 300

    def test_reset_usage(self, qm, qm_tenant):
        qm.try_consume(qm_tenant.tenant_id, ResourceType.CPU_CORES, 1)
        qm.try_consume(qm_tenant.tenant_id, ResourceType.MEMORY_MB, 100)
        qm.reset_usage(qm_tenant.tenant_id)
        summary = qm.get_quota_summary(qm_tenant.tenant_id)
        assert summary["cpu_cores"]["used"] == 0
        assert summary["memory_mb"]["used"] == 0

    def test_reset_all_usage(self, qm, qm_tenant):
        tm = qm._tm
        t2 = tm.create_tenant(TenantConfig(tenant_name="R2", tenant_slug="r2"))
        tm.activate_tenant(t2.tenant_id)
        qm.allocate_default_quotas(t2.tenant_id, "free")
        qm.try_consume(qm_tenant.tenant_id, ResourceType.CPU_CORES, 1)
        qm.try_consume(t2.tenant_id, ResourceType.CPU_CORES, 1)
        qm.reset_all_usage()
        assert qm.get_quota_summary(qm_tenant.tenant_id)["cpu_cores"]["used"] == 0
        assert qm.get_quota_summary(t2.tenant_id)["cpu_cores"]["used"] == 0

    def test_transfer_quota(self, qm, qm_tenant):
        tm = qm._tm
        t2 = tm.create_tenant(TenantConfig(tenant_name="Recv", tenant_slug="recv"))
        tm.activate_tenant(t2.tenant_id)
        qm.allocate_default_quotas(t2.tenant_id, "free")

        result = qm.transfer_quota(qm_tenant.tenant_id, t2.tenant_id,
                                    ResourceType.CPU_CORES, 0.5)
        assert result.allowed

    def test_transfer_quota_insufficient(self, qm, qm_tenant):
        tm = qm._tm
        t2 = tm.create_tenant(TenantConfig(tenant_name="Recv2", tenant_slug="recv2"))
        tm.activate_tenant(t2.tenant_id)
        qm.allocate_default_quotas(t2.tenant_id, "free")

        result = qm.transfer_quota(qm_tenant.tenant_id, t2.tenant_id,
                                    ResourceType.CPU_CORES, 999)
        assert not result.allowed

    def test_get_all_exceeded(self, qm, qm_tenant):
        qm.try_consume(qm_tenant.tenant_id, ResourceType.CPU_CORES, 999)
        exceeded = qm.get_all_exceeded()
        assert len(exceeded) >= 1

    def test_get_all_warnings(self, qm, qm_tenant):
        limit = qm_tenant.quota.get(ResourceType.API_CALLS_PER_DAY).limit
        qm.try_consume(qm_tenant.tenant_id,
                        ResourceType.API_CALLS_PER_DAY, limit * 0.85)
        warnings = qm.get_all_warnings()
        assert len(warnings) >= 1

    def test_get_usage_trends(self, qm, qm_tenant):
        qm.try_consume(qm_tenant.tenant_id, ResourceType.CPU_CORES, 1)
        qm.try_consume(qm_tenant.tenant_id, ResourceType.CPU_CORES, 1)
        trends = qm.get_usage_trends(qm_tenant.tenant_id)
        assert "cpu_cores" in trends
        assert len(trends["cpu_cores"]) == 2

    def test_tenant_not_found_raises(self, qm):
        with pytest.raises(ValueError, match="not found"):
            qm.try_consume("nonexistent", ResourceType.CPU_CORES, 1)

    def test_batch_release(self, qm, qm_tenant):
        qm.try_consume(qm_tenant.tenant_id, ResourceType.CPU_CORES, 1)
        qm.try_consume(qm_tenant.tenant_id, ResourceType.MEMORY_MB, 200)
        qm.batch_release(qm_tenant.tenant_id, {
            ResourceType.CPU_CORES: 0.5,
            ResourceType.MEMORY_MB: 100,
        })
        summary = qm.get_quota_summary(qm_tenant.tenant_id)
        assert summary["cpu_cores"]["used"] == 0.5
        assert summary["memory_mb"]["used"] == 100


# ══════════════════════════════════════════════
# DataIsolator 测试
# ══════════════════════════════════════════════


@pytest.fixture
def di():
    tm = TenantManager()
    return DataIsolator(tm)


@pytest.fixture
def di_tenant(di):
    tm = di._tm
    t = tm.create_tenant(TenantConfig(tenant_name="DI", tenant_slug="di"))
    tm.activate_tenant(t.tenant_id)
    return t


class TestDataIsolator:
    """数据隔离器测试"""

    def test_filter_query_row_level(self, di, di_tenant):
        result = di.filter_query(di_tenant.tenant_id, {"name": "test"})
        assert "tenant_id" in result
        assert result["tenant_id"] == di_tenant.tenant_id

    def test_filter_query_shared(self, di):
        tm = di._tm
        t = tm.create_tenant(TenantConfig(
            tenant_name="Shared", tenant_slug="shared",
            isolation_mode=IsolationMode.SHARED,
        ))
        tm.activate_tenant(t.tenant_id)
        result = di.filter_query(t.tenant_id, {"name": "test"})
        assert "tenant_id" not in result  # 共享模式不注入

    def test_filter_results(self, di, di_tenant):
        results = [
            {"id": 1, "tenant_id": di_tenant.tenant_id},
            {"id": 2, "tenant_id": "other"},
        ]
        filtered = di.filter_results(di_tenant.tenant_id, results)
        assert len(filtered) == 1
        assert filtered[0]["id"] == 1

    def test_filter_results_shared(self, di):
        tm = di._tm
        t = tm.create_tenant(TenantConfig(
            tenant_name="Shared2", tenant_slug="shared2",
            isolation_mode=IsolationMode.SHARED,
        ))
        tm.activate_tenant(t.tenant_id)
        results = [{"id": 1, "tenant_id": "any"}]
        filtered = di.filter_results(t.tenant_id, results)
        assert len(filtered) == 1  # 共享模式不过滤

    def test_can_read_own(self, di, di_tenant):
        assert di.can_read(di_tenant.tenant_id, di_tenant.tenant_id) is True

    def test_can_read_other_blocked(self, di, di_tenant):
        assert di.can_read(di_tenant.tenant_id, "other") is False

    def test_can_write_own(self, di, di_tenant):
        assert di.can_write(di_tenant.tenant_id, di_tenant.tenant_id) is True

    def test_can_write_other(self, di, di_tenant):
        assert di.can_write(di_tenant.tenant_id, "other") is False

    def test_get_schema_name(self, di, di_tenant):
        assert di.get_schema_name(di_tenant.tenant_id) == "tenant_di"

    def test_authorize_cross_tenant_write_denied(self, di, di_tenant):
        assert di.authorize_cross_tenant(di_tenant.tenant_id, "other", "write") is False

    def test_grant_revoke_access(self, di, di_tenant):
        assert di.grant_cross_tenant_access(di_tenant.tenant_id, "other-id") is True
        assert di.can_read(di_tenant.tenant_id, "other-id") is True
        assert di.revoke_cross_tenant_access(di_tenant.tenant_id, "other-id") is True
        assert di.can_read(di_tenant.tenant_id, "other-id") is False

    def test_get_isolation_mode(self, di, di_tenant):
        assert di.get_isolation_mode(di_tenant.tenant_id) == IsolationMode.ROW_LEVEL
        assert di.get_isolation_mode("nonexistent") == IsolationMode.ROW_LEVEL

    def test_can_read_all(self, di, di_tenant):
        assert di.can_read_all(di_tenant.tenant_id) is False


# ══════════════════════════════════════════════
# IsolationPolicy 测试
# ══════════════════════════════════════════════


@pytest.fixture
def ip():
    tm = TenantManager()
    return IsolationPolicy(tm)


@pytest.fixture
def ip_tenant(ip):
    tm = ip._tm
    t = tm.create_tenant(TenantConfig(tenant_name="IP", tenant_slug="ip"))
    tm.activate_tenant(t.tenant_id)
    return t


class TestIsolationPolicy:
    """隔离策略测试"""

    def test_check_access_blocked(self, ip, ip_tenant):
        assert ip.check_access(ip_tenant.tenant_id, "other") is False

    def test_check_access_self(self, ip, ip_tenant):
        assert ip.check_access(ip_tenant.tenant_id, ip_tenant.tenant_id) is True

    def test_get_effective_isolation(self, ip, ip_tenant):
        assert ip.get_effective_isolation_level(ip_tenant.tenant_id) == IsolationMode.ROW_LEVEL

    def test_recommend_isolation_high(self, ip):
        mode = ip.recommend_isolation_mode({"data_sensitivity": "high"})
        assert mode == IsolationMode.SCHEMA

    def test_recommend_isolation_medium(self, ip):
        mode = ip.recommend_isolation_mode({"data_sensitivity": "medium"})
        assert mode == IsolationMode.HYBRID

    def test_recommend_isolation_low(self, ip):
        mode = ip.recommend_isolation_mode({"data_sensitivity": "low"})
        assert mode == IsolationMode.ROW_LEVEL

    def test_validate_isolation_downgrade_blocked(self, ip, ip_tenant):
        ip_tenant.isolation_mode = IsolationMode.SCHEMA
        assert ip.validate_isolation_mode(ip_tenant.tenant_id, IsolationMode.ROW_LEVEL) is False

    def test_validate_isolation_upgrade_allowed(self, ip, ip_tenant):
        ip_tenant.isolation_mode = IsolationMode.ROW_LEVEL
        assert ip.validate_isolation_mode(ip_tenant.tenant_id, IsolationMode.SCHEMA) is True

    def test_evaluate_tenant_rules_suspended(self, ip, ip_tenant):
        ip._tm.suspend_tenant(ip_tenant.tenant_id, "test")
        assert ip.evaluate_tenant_rules(ip_tenant.tenant_id, "any", "any") is False

    def test_evaluate_tenant_rules_active(self, ip, ip_tenant):
        assert ip.evaluate_tenant_rules(ip_tenant.tenant_id, "delete_data", "record-1") is True

    def test_validate_tenant_isolation(self, ip):
        tm = ip._tm
        t1 = tm.create_tenant(TenantConfig(tenant_name="V1", tenant_slug="v1"))
        t2 = tm.create_tenant(TenantConfig(tenant_name="V2", tenant_slug="v2"))
        tm.activate_tenant(t1.tenant_id)
        tm.activate_tenant(t2.tenant_id)
        result = ip.validate_tenant_isolation([t1.tenant_id, t2.tenant_id])
        key = f"{t1.tenant_id}↔{t2.tenant_id}"
        assert result[key] is True  # BLOCK_ALL → 应互相隔离


# ══════════════════════════════════════════════
# TenantAuditLogger 测试
# ══════════════════════════════════════════════


@pytest.fixture
def al():
    return TenantAuditLogger()


class TestTenantAuditLogger:
    """审计日志测试"""

    def test_log_basic(self, al):
        r = al.log("t1", AuditEventType.TENANT_CREATED)
        assert r.tenant_id == "t1"
        assert r.event_type == AuditEventType.TENANT_CREATED
        assert r.success

    def test_log_tenant_event(self, al):
        r = al.log_tenant_event("t1", AuditEventType.TENANT_ACTIVATED)
        assert r.event_type == AuditEventType.TENANT_ACTIVATED
        assert r.resource_id == "t1"

    def test_query_by_tenant(self, al):
        al.log("t1", AuditEventType.TENANT_CREATED)
        al.log("t2", AuditEventType.TENANT_CREATED)
        al.log("t1", AuditEventType.TENANT_SUSPENDED)
        records = al.query(AuditQuery(tenant_id="t1"))
        assert len(records) == 2

    def test_query_by_event_type(self, al):
        al.log("t1", AuditEventType.TENANT_CREATED)
        al.log("t1", AuditEventType.QUOTA_EXCEEDED)
        records = al.query(AuditQuery(event_type=AuditEventType.QUOTA_EXCEEDED))
        assert len(records) == 1

    def test_query_by_time_range(self, al):
        from datetime import datetime, timedelta
        r = al.log("t1", AuditEventType.TENANT_CREATED)
        now = datetime.now()
        before = now - timedelta(hours=1)
        after = now + timedelta(hours=1)
        records = al.query(AuditQuery(start_time=before, end_time=after))
        assert len(records) == 1
        empty = al.query(AuditQuery(start_time=now + timedelta(hours=2)))
        assert len(empty) == 0

    def test_get_by_tenant(self, al):
        al.log("t1", AuditEventType.TENANT_CREATED)
        records = al.get_by_tenant("t1")
        assert len(records) == 1

    def test_get_violations(self, al):
        al.log("t1", AuditEventType.ISOLATION_VIOLATION)
        al.log("t1", AuditEventType.TENANT_CREATED)
        records = al.get_violations("t1")
        assert len(records) == 1

    def test_get_quota_exceeded(self, al):
        al.log("t1", AuditEventType.QUOTA_EXCEEDED)
        records = al.get_quota_exceeded("t1")
        assert len(records) == 1

    def test_get_stats(self, al):
        al.log("t1", AuditEventType.TENANT_CREATED)
        al.log("t1", AuditEventType.QUOTA_EXCEEDED, success=False)
        stats = al.get_stats()
        assert stats["total"] == 2
        assert stats["success"] == 1
        assert stats["failed"] == 1

    def test_get_tenant_timeline(self, al):
        al.log("t1", AuditEventType.TENANT_CREATED)
        al.log("t1", AuditEventType.TENANT_ACTIVATED)
        timeline = al.get_tenant_timeline("t1")
        assert len(timeline) == 2
        assert timeline[0]["event"] == "tenant.activated"  # 逆序

    def test_purge_older_than(self, al):
        from datetime import datetime, timedelta
        al.log("t1", AuditEventType.TENANT_CREATED)
        removed = al.purge_older_than(datetime.now() + timedelta(days=1))
        assert removed == 1
        assert al.record_count == 0

    def test_purge_tenant(self, al):
        al.log("t1", AuditEventType.TENANT_CREATED)
        al.log("t2", AuditEventType.TENANT_CREATED)
        removed = al.purge_tenant("t1")
        assert removed == 1
        assert al.record_count == 1

    def test_clear(self, al):
        al.log("t1", AuditEventType.TENANT_CREATED)
        al.clear()
        assert al.record_count == 0

    def test_capacity_limit(self):
        al = TenantAuditLogger(capacity=5)
        for i in range(10):
            al.log("t1", AuditEventType.RESOURCE_CONSUMED)
        assert al.record_count == 5  # 淘汰旧记录


# ══════════════════════════════════════════════
# 集成测试
# ══════════════════════════════════════════════


class TestTenantIntegration:
    """端到端集成测试"""

    def test_full_tenant_lifecycle(self):
        """完整租户生命周期"""
        tm = TenantManager()
        audit = TenantAuditLogger()

        # 创建
        t = tm.create_tenant(TenantConfig(
            tenant_name="Acme Corp",
            tenant_slug="acme",
            isolation_mode=IsolationMode.SCHEMA,
        ))
        audit.log_tenant_event(t.tenant_id, AuditEventType.TENANT_CREATED)
        assert t.status == TenantStatus.PENDING

        # 激活
        tm.activate_tenant(t.tenant_id)
        audit.log_tenant_event(t.tenant_id, AuditEventType.TENANT_ACTIVATED)
        assert t.status == TenantStatus.ACTIVE

        # 暂停
        tm.suspend_tenant(t.tenant_id, "payment overdue")
        audit.log_tenant_event(t.tenant_id, AuditEventType.TENANT_SUSPENDED,
                               detail={"reason": "payment overdue"})
        assert t.status == TenantStatus.SUSPENDED

        # 重新激活
        tm.activate_tenant(t.tenant_id)
        assert t.status == TenantStatus.ACTIVE

        # 追加配额
        tm.set_quota(t.tenant_id, ResourceType.CPU_CORES, 8)
        tm.set_quota(t.tenant_id, ResourceType.MEMORY_MB, 8192)
        assert len(t.quota.quotas) == 2

        # 归档
        tm.archive_tenant(t.tenant_id)
        audit.log_tenant_event(t.tenant_id, AuditEventType.TENANT_ARCHIVED)

        # 删除
        assert tm.delete_tenant(t.tenant_id) is True
        assert tm.get_tenant(t.tenant_id) is None

        # 审计完整性
        stats = audit.get_stats()
        assert stats["total"] == 4

    def test_multi_tenant_isolation(self):
        """多租户数据隔离"""
        tm = TenantManager()
        isolator = DataIsolator(tm)

        t1 = tm.create_tenant(TenantConfig(
            tenant_name="Company A", tenant_slug="company-a",
            isolation_mode=IsolationMode.ROW_LEVEL,
        ))
        tm.activate_tenant(t1.tenant_id)

        t2 = tm.create_tenant(TenantConfig(
            tenant_name="Company B", tenant_slug="company-b",
            isolation_mode=IsolationMode.ROW_LEVEL,
        ))
        tm.activate_tenant(t2.tenant_id)

        # t1 和 t2 不能互相访问
        assert isolator.can_read(t1.tenant_id, t2.tenant_id) is False
        assert isolator.can_read(t2.tenant_id, t1.tenant_id) is False

        # 各自可以访问自己的数据
        assert isolator.can_read(t1.tenant_id, t1.tenant_id) is True
        assert isolator.can_read(t2.tenant_id, t2.tenant_id) is True

        # t1 的查询注入自己的 tenant_id
        q1 = isolator.filter_query(t1.tenant_id, {})
        assert q1["tenant_id"] == t1.tenant_id

        q2 = isolator.filter_query(t2.tenant_id, {})
        assert q2["tenant_id"] == t2.tenant_id

        # 结果过滤
        results = [
            {"id": 1, "tenant_id": t1.tenant_id},
            {"id": 2, "tenant_id": t2.tenant_id},
        ]
        assert len(isolator.filter_results(t1.tenant_id, results)) == 1
        assert len(isolator.filter_results(t2.tenant_id, results)) == 1

    def test_quota_with_tenant_lifecycle(self):
        """配额 + 租户生命周期联动"""
        tm = TenantManager()
        qm = ResourceQuotaManager(tm)

        t = tm.create_tenant(TenantConfig(tenant_name="QLife", tenant_slug="qlife"))
        tm.activate_tenant(t.tenant_id)
        qm.allocate_default_quotas(t.tenant_id, "standard")

        # 正常消费
        result = qm.try_consume(t.tenant_id, ResourceType.API_CALLS_PER_DAY, 1000)
        assert result.allowed

        # 暂停后不能消费
        tm.suspend_tenant(t.tenant_id, "overdue")
        result = qm.try_consume(t.tenant_id, ResourceType.API_CALLS_PER_DAY, 1)
        assert not result.allowed

        # 重新激活后可恢复
        tm.activate_tenant(t.tenant_id)
        result = qm.try_consume(t.tenant_id, ResourceType.API_CALLS_PER_DAY, 1)
        assert result.allowed

    def test_cross_tenant_communication(self):
        """跨租户通信策略"""
        tm = TenantManager()
        policy = IsolationPolicy(tm)

        tA = tm.create_tenant(TenantConfig(
            tenant_name="A", tenant_slug="ta",
            cross_tenant_policy=CrossTenantPolicy.BLOCK_ALL,
        ))
        tB = tm.create_tenant(TenantConfig(
            tenant_name="B", tenant_slug="tb",
        ))
        tm.activate_tenant(tA.tenant_id)
        tm.activate_tenant(tB.tenant_id)

        # 默认 BLOCK_ALL
        assert policy.check_access_with_audit(tA.tenant_id, tB.tenant_id) is False

        # 切换为 ALLOW_LIST + 白名单
        tm.update_tenant(tA.tenant_id,
                         cross_tenant_policy=CrossTenantPolicy.ALLOW_LIST,
                         allowed_tenant_ids=[tB.tenant_id])
        assert policy.check_access_with_audit(tA.tenant_id, tB.tenant_id, "admin") is True

        # 切换为 OPEN
        tm.update_tenant(tA.tenant_id, cross_tenant_policy=CrossTenantPolicy.OPEN)
        assert policy.check_access(tA.tenant_id, "any-tenant") is True

    def test_audit_integration(self):
        """审计 + 配额 + 隔离联动"""
        tm = TenantManager()
        qm = ResourceQuotaManager(tm)
        audit = TenantAuditLogger()

        t = tm.create_tenant(TenantConfig(tenant_name="AuditTest", tenant_slug="at"))
        tm.activate_tenant(t.tenant_id)
        qm.allocate_default_quotas(t.tenant_id, "free")

        # 触发配额消费事件（QM 内部审计）
        qm.try_consume(t.tenant_id, ResourceType.CPU_CORES, 1)
        qm.try_consume(t.tenant_id, ResourceType.API_CALLS_PER_DAY, 9999)  # 超限

        # 外部审计记录
        audit.log_tenant_event(t.tenant_id, AuditEventType.TENANT_ACTIVATED)
        audit.log(t.tenant_id, AuditEventType.ISOLATION_VIOLATION,
                   actor_id="user-x", success=False,
                   error_message="cross-tenant access denied")

        # QM 内部审计 + 外部审计
        qm_records = qm.get_audit_logs()
        assert len(qm_records) >= 2  # 2个consume事件

        stats = audit.get_stats()
        assert stats["total"] == 2  # 2个手动审计事件

        timeline = audit.get_tenant_timeline(t.tenant_id)
        assert len(timeline) == 2

    def test_allow_list_access_chain(self):
        """白名单链式访问"""
        tm = TenantManager()
        policy = IsolationPolicy(tm)

        tA = tm.create_tenant(TenantConfig(
            tenant_name="ChainA", tenant_slug="chain-a",
            cross_tenant_policy=CrossTenantPolicy.ALLOW_LIST,
        ))
        tB = tm.create_tenant(TenantConfig(
            tenant_name="ChainB", tenant_slug="chain-b",
            cross_tenant_policy=CrossTenantPolicy.ALLOW_LIST,
        ))
        tC = tm.create_tenant(TenantConfig(
            tenant_name="ChainC", tenant_slug="chain-c",
        ))
        tm.activate_tenant(tA.tenant_id)
        tm.activate_tenant(tB.tenant_id)
        tm.activate_tenant(tC.tenant_id)

        # 用实际 tenant_id（UUID）设置白名单
        tm.update_tenant(tA.tenant_id, allowed_tenant_ids=[tB.tenant_id])
        tm.update_tenant(tB.tenant_id, allowed_tenant_ids=[tC.tenant_id])

        # A → B ✓
        assert policy.check_access(tA.tenant_id, tB.tenant_id) is True
        # B → C ✓
        assert policy.check_access(tB.tenant_id, tC.tenant_id) is True
        # A → C ✗ (白名单不传递)
        assert policy.check_access(tA.tenant_id, tC.tenant_id) is False
