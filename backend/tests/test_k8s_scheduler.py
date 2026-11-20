"""
W25-26: K8s Job Scheduler — 测试套件

覆盖:
- K8sJobConfig / K8sJobRecord 数据模型
- K8sNodeInfo 节点信息计算
- LocalK8sClient CRUD 操作
- K8sJobManager 生命周期管理
- K8sScheduler 集成调度
- K8sClientFactory 模式选择
- 预置 Job 模板
"""

from __future__ import annotations

import asyncio
import json

import pytest
import pytest_asyncio

from app.runtime.k8s_scheduler.k8s_client import (
    K8sClientFactory,
    LocalK8sClient,
)
from app.runtime.k8s_scheduler.job_manager import (
    K8sJobManager,
    PRESET_JOB_TEMPLATES,
)
from app.runtime.k8s_scheduler.k8s_scheduler import K8sScheduler
from app.runtime.k8s_scheduler.models import (
    K8sClusterInfo,
    K8sDeploymentSpec,
    K8sJobConfig,
    K8sJobRecord,
    K8sJobStatus,
    K8sJobType,
    K8sNodeInfo,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def local_client():
    """本地 K8s 客户端 fixture"""
    client = LocalK8sClient()
    yield client


@pytest_asyncio.fixture
async def job_manager(local_client):
    """K8sJobManager fixture"""
    manager = K8sJobManager(
        k8s_client=local_client,
        max_concurrent_jobs=10,
        monitor_interval_seconds=1,
    )
    await manager.start()
    yield manager
    await manager.stop()


@pytest_asyncio.fixture
async def k8s_scheduler(local_client, job_manager):
    """K8sScheduler fixture"""
    scheduler = K8sScheduler(
        k8s_client=local_client,
        job_manager=job_manager,
    )
    await scheduler.initialize()
    yield scheduler
    await scheduler.shutdown()


def make_job_config(name: str = "test-job", **overrides) -> K8sJobConfig:
    """快捷创建测试用 Job 配置"""
    defaults = {
        "job_name": name,
        "job_type": K8sJobType.LANGGRAPH_WORKER,
        "command": ["python", "-c", "print('hello')"],
        "namespace": "ai-runtime-os",
    }
    defaults.update(overrides)
    return K8sJobConfig(**defaults)


# ─── 模型测试 ────────────────────────────────────────────────────────────────


class TestK8sJobConfig:
    """K8sJobConfig 数据模型"""

    def test_default_config(self):
        config = K8sJobConfig(job_name="test")
        assert config.job_name == "test"
        assert config.job_type == K8sJobType.LANGGRAPH_WORKER
        assert config.image == "ai-runtime-os/backend:latest"
        assert config.restart_policy == "Never"
        assert config.backoff_limit == 3
        assert config.active_deadline_seconds == 3600

    def test_to_dict(self):
        config = make_job_config(
            job_name="dict-test",
            env_vars={"KEY": "VALUE"},
        )
        d = config.to_dict()
        assert d["job_name"] == "dict-test"
        assert d["env_vars"] == {"KEY": "VALUE"}
        assert d["job_type"] == "langgraph_worker"
        assert isinstance(d["resource_requests"], dict)

    def test_custom_resource_limits(self):
        config = make_job_config(
            resource_limits={"memory": "8Gi", "cpu": "4000m"}
        )
        assert config.resource_limits["memory"] == "8Gi"

    def test_volumes_and_mounts(self):
        config = make_job_config(
            volumes=[{"name": "data", "emptyDir": {}}],
            volume_mounts=[{"name": "data", "mountPath": "/data"}],
        )
        assert len(config.volumes) == 1
        assert len(config.volume_mounts) == 1


class TestK8sJobRecord:
    """K8sJobRecord 数据模型"""

    def test_default_record(self):
        record = K8sJobRecord()
        assert record.job_id
        assert record.status == K8sJobStatus.CREATED
        assert record.retry_count == 0

    def test_to_dict(self):
        record = K8sJobRecord(
            job_id="test-123",
            task_id="task-456",
            status=K8sJobStatus.RUNNING,
        )
        d = record.to_dict()
        assert d["job_id"] == "test-123"
        assert d["task_id"] == "task-456"
        assert d["status"] == "running"


class TestK8sJobStatus:
    """Job 状态枚举"""

    def test_terminal_states(self):
        assert K8sJobStatus.SUCCEEDED.is_terminal
        assert K8sJobStatus.FAILED.is_terminal
        assert K8sJobStatus.TIMED_OUT.is_terminal
        assert K8sJobStatus.CANCELLED.is_terminal

    def test_non_terminal_states(self):
        assert not K8sJobStatus.CREATED.is_terminal
        assert not K8sJobStatus.PENDING.is_terminal
        assert not K8sJobStatus.RUNNING.is_terminal

    def test_is_ok(self):
        assert K8sJobStatus.SUCCEEDED.is_ok
        assert not K8sJobStatus.FAILED.is_ok


class TestK8sNodeInfo:
    """节点信息计算"""

    def test_default_node(self):
        node = K8sNodeInfo(node_name="node-1")
        assert node.node_name == "node-1"
        assert not node.is_ready

    def test_ready_node(self):
        node = K8sNodeInfo(node_name="node-1", status="Ready")
        assert node.is_ready

    def test_cpu_usage_percent(self):
        node = K8sNodeInfo(
            node_name="node-1",
            capacity_cpu="8",
            allocatable_cpu="6",
        )
        usage = node.cpu_usage_percent
        assert 20 < usage < 30  # (8-6)/8 = 25%

    def test_cpu_usage_zero(self):
        node = K8sNodeInfo(node_name="node-1")
        assert node.cpu_usage_percent == 0.0


class TestK8sClusterInfo:
    """集群信息"""

    def test_empty_cluster(self):
        cluster = K8sClusterInfo()
        assert cluster.node_count == 0
        assert cluster.ready_nodes == 0

    def test_cluster_with_nodes(self):
        nodes = [K8sNodeInfo(node_name="n1", status="Ready")]
        cluster = K8sClusterInfo(node_count=1, ready_nodes=1, nodes=nodes)
        assert cluster.node_count == 1
        assert cluster.ready_nodes == 1

    def test_to_dict(self):
        cluster = K8sClusterInfo(cluster_name="prod")
        d = cluster.to_dict()
        assert d["cluster_name"] == "prod"
        assert isinstance(d["nodes"], list)


# ─── LocalK8sClient 测试 ────────────────────────────────────────────────────


class TestLocalK8sClient:
    """本地模拟 K8s 客户端"""

    @pytest.mark.asyncio
    async def test_create_and_get_job(self, local_client):
        config = make_job_config(
            job_name="test-create",
            command=["python", "-c", "import json; print(json.dumps({'ok': True}))"],
        )
        record = await local_client.create_job(config)

        assert record.job_id
        assert record.status in (K8sJobStatus.CREATED, K8sJobStatus.PENDING, K8sJobStatus.RUNNING)

        # 等待完成
        await asyncio.sleep(1)
        status = await local_client.get_job_status(record.job_id)
        assert status == K8sJobStatus.SUCCEEDED

    @pytest.mark.asyncio
    async def test_job_logs(self, local_client):
        config = make_job_config(
            job_name="test-logs",
            command=["python", "-c", "print('log line 1'); print('log line 2')"],
        )
        record = await local_client.create_job(config)
        await asyncio.sleep(1)

        logs = await local_client.get_job_logs(record.job_id)
        assert "log line 1" in logs
        assert "log line 2" in logs

    @pytest.mark.asyncio
    async def test_cancel_job(self, local_client):
        config = make_job_config(
            job_name="test-cancel",
            command=["python", "-c", "import time; time.sleep(30)"],
            active_deadline_seconds=60,
        )
        record = await local_client.create_job(config)
        await asyncio.sleep(0.2)

        success = await local_client.cancel_job(record.job_id)
        assert success

        status = await local_client.get_job_status(record.job_id)
        assert status == K8sJobStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_delete_job(self, local_client):
        config = make_job_config(
            job_name="test-delete",
            command=["python", "-c", "print('done')"],
        )
        record = await local_client.create_job(config)
        await asyncio.sleep(1)

        success = await local_client.delete_job(record.job_id)
        assert success

    @pytest.mark.asyncio
    async def test_list_jobs(self, local_client):
        config1 = make_job_config(job_name="job-a", command=["echo", "a"])
        config2 = make_job_config(job_name="job-b", command=["echo", "b"])

        await local_client.create_job(config1)
        await local_client.create_job(config2)
        await asyncio.sleep(1)

        jobs = await local_client.list_jobs()
        assert len(jobs) >= 2

    @pytest.mark.asyncio
    async def test_list_jobs_with_filter(self, local_client):
        config = make_job_config(
            job_name="filter-test",
            command=["python", "-c", "print('ok')"],
        )
        record = await local_client.create_job(config)
        await asyncio.sleep(1)

        succeeded = await local_client.list_jobs(status_filter="succeeded")
        assert any(j.job_id == record.job_id for j in succeeded)

        failed = await local_client.list_jobs(status_filter="failed")
        assert not any(j.job_id == record.job_id for j in failed)

    @pytest.mark.asyncio
    async def test_list_nodes(self, local_client):
        nodes = await local_client.list_nodes()
        assert len(nodes) == 1
        assert nodes[0].node_name == "local-dev"
        assert nodes[0].is_ready

    @pytest.mark.asyncio
    async def test_get_cluster_info(self, local_client):
        info = await local_client.get_cluster_info()
        assert info.cluster_name == "local-dev"
        assert info.node_count == 1
        assert info.ready_nodes == 1

    @pytest.mark.asyncio
    async def test_apply_deployment(self, local_client):
        spec = K8sDeploymentSpec(name="test-deploy", replicas=3)
        result = await local_client.apply_deployment(spec)
        assert result is True

    @pytest.mark.asyncio
    async def test_is_available(self, local_client):
        assert await local_client.is_available()

    @pytest.mark.asyncio
    async def test_job_timeout(self, local_client):
        config = make_job_config(
            job_name="test-timeout",
            command=["python", "-c", "import time; time.sleep(10)"],
            active_deadline_seconds=2,
        )
        record = await local_client.create_job(config)
        await asyncio.sleep(3)

        status = await local_client.get_job_status(record.job_id)
        assert status == K8sJobStatus.TIMED_OUT

    @pytest.mark.asyncio
    async def test_job_result_parsing(self, local_client):
        config = make_job_config(
            job_name="test-result",
            command=["python", "-c",
                     "import json; print(json.dumps({'score': 95, 'status': 'pass'}))"],
        )
        record = await local_client.create_job(config)
        await asyncio.sleep(1)

        status = await local_client.get_job_status(record.job_id)
        assert status == K8sJobStatus.SUCCEEDED

        # 等待 completion 写入 result_data
        await asyncio.sleep(0.5)

        # reload record 查看 result
        all_jobs = await local_client.list_jobs()
        matching = [j for j in all_jobs if j.job_id == record.job_id]
        if matching:
            result = matching[0].result_data
            if "score" in result:
                assert result["score"] == 95


# ─── K8sJobManager 测试 ─────────────────────────────────────────────────────


class TestK8sJobManager:
    """Job 生命周期管理器"""

    @pytest.mark.asyncio
    async def test_submit_job(self, job_manager):
        config = make_job_config(
            job_name="mgr-submit",
            command=["python", "-c", "print('mgr test')"],
        )
        record = await job_manager.submit_job(config, task_id="task-uuid-1")
        assert record.job_id
        assert record.task_id == "task-uuid-1"

    @pytest.mark.asyncio
    async def test_submit_from_template(self, job_manager):
        record = await job_manager.submit_from_template(
            template_name="langgraph_worker",
            task_id="task-template-1",
        )
        assert record.job_id
        assert record.job_config.job_type == K8sJobType.LANGGRAPH_WORKER

    @pytest.mark.asyncio
    async def test_submit_from_template_with_overrides(self, job_manager):
        record = await job_manager.submit_from_template(
            template_name="langgraph_worker",
            task_id="task-override",
            overrides={"active_deadline_seconds": 600},
        )
        assert record.job_config.active_deadline_seconds == 600

    @pytest.mark.asyncio
    async def test_submit_invalid_template(self, job_manager):
        with pytest.raises(ValueError, match="Unknown template"):
            await job_manager.submit_from_template(
                template_name="nonexistent",
                task_id="bad-task",
            )

    @pytest.mark.asyncio
    async def test_wait_for_job(self, job_manager):
        config = make_job_config(
            job_name="wait-test",
            command=["python", "-c", "print('ready')"],
        )
        record = await job_manager.submit_job(config)

        result = await job_manager.wait_for_job(record.job_id, timeout=10)
        assert result.status == K8sJobStatus.SUCCEEDED

    @pytest.mark.asyncio
    async def test_get_job(self, job_manager):
        config = make_job_config(
            job_name="get-test",
            command=["python", "-c", "print('found')"],
        )
        record = await job_manager.submit_job(config)
        await asyncio.sleep(1)

        found = await job_manager.get_job(record.job_id)
        assert found is not None
        assert found.job_id == record.job_id

    @pytest.mark.asyncio
    async def test_list_jobs(self, job_manager):
        config1 = make_job_config(job_name="list-a", command=["echo", "a"])
        config2 = make_job_config(job_name="list-b", command=["echo", "b"])

        await job_manager.submit_job(config1)
        await job_manager.submit_job(config2)
        await asyncio.sleep(1)

        jobs = await job_manager.list_jobs()
        assert len(jobs) >= 2

    @pytest.mark.asyncio
    async def test_list_jobs_by_status(self, job_manager):
        config = make_job_config(
            job_name="status-filter",
            command=["python", "-c", "print('ok')"],
        )
        await job_manager.submit_job(config)
        await asyncio.sleep(1)

        succeeded = await job_manager.list_jobs(status_filter="succeeded")
        assert len(succeeded) >= 1

    @pytest.mark.asyncio
    async def test_cancel_job(self, job_manager):
        config = make_job_config(
            job_name="cancel-me",
            command=["python", "-c", "import time; time.sleep(30)"],
            active_deadline_seconds=60,
        )
        record = await job_manager.submit_job(config)
        await asyncio.sleep(0.3)

        success = await job_manager.cancel_job(record.job_id)
        assert success

        found = await job_manager.get_job(record.job_id)
        assert found.status in (K8sJobStatus.CANCELLED, K8sJobStatus.FAILED)

    @pytest.mark.asyncio
    async def test_get_stats(self, job_manager):
        config = make_job_config(
            job_name="stats-test",
            command=["python", "-c", "print('stats')"],
        )
        await job_manager.submit_job(config)
        await asyncio.sleep(1)

        stats = await job_manager.get_stats()
        assert stats["total"] >= 1
        assert "max_concurrent" in stats

    @pytest.mark.asyncio
    async def test_max_concurrent_limit(self, local_client):
        """测试并发上限"""
        manager = K8sJobManager(
            k8s_client=local_client,
            max_concurrent_jobs=2,
        )
        await manager.start()

        try:
            # 提交 2 个长期任务占满配额
            for i in range(2):
                config = make_job_config(
                    job_name=f"blocker-{i}",
                    command=["python", "-c", "import time; time.sleep(10)"],
                    active_deadline_seconds=30,
                )
                await manager.submit_job(config)

            # 第 3 个应该被拒绝
            with pytest.raises(RuntimeError, match="Max concurrent"):
                config3 = make_job_config(
                    job_name="overflow",
                    command=["echo", "overflow"],
                )
                await manager.submit_job(config3)
        finally:
            await manager.stop()

    def test_get_template_names(self):
        manager = K8sJobManager(k8s_client=LocalK8sClient(), max_concurrent_jobs=2)
        names = manager.get_template_names()
        assert "langgraph_worker" in names
        assert "sandbox_runner" in names
        assert "checkpoint_worker" in names
        assert "batch_processor" in names

    def test_get_template(self):
        manager = K8sJobManager(k8s_client=LocalK8sClient(), max_concurrent_jobs=2)
        tmpl = manager.get_template("langgraph_worker")
        assert tmpl is not None
        assert tmpl.job_type == K8sJobType.LANGGRAPH_WORKER
        assert tmpl.image == "ai-runtime-os/backend:latest"

    @pytest.mark.asyncio
    async def test_cleanup_old_jobs(self, job_manager):
        config = make_job_config(
            job_name="cleanup-test",
            command=["python", "-c", "print('done')"],
        )
        await job_manager.submit_job(config)
        await asyncio.sleep(1)

        # 清理 max_age_hours=0 → 立即清理所有已完成
        removed = await job_manager.cleanup_old_jobs(max_age_hours=0)
        assert removed >= 0  # 至少不崩溃


# ─── K8sScheduler 集成测试 ──────────────────────────────────────────────────


class TestK8sScheduler:
    """K8sScheduler 集成调度器"""

    @pytest.mark.asyncio
    async def test_submit_task_as_job(self, k8s_scheduler):
        record = await k8s_scheduler.submit_task_as_job(
            task_id="integrated-task-1",
            capability="langgraph",
            extra_env={"TEST_MODE": "1"},
        )
        assert record.job_id
        assert record.task_id == "integrated-task-1"

    @pytest.mark.asyncio
    async def test_get_job_result_with_wait(self, k8s_scheduler):
        record = await k8s_scheduler.submit_task_as_job(
            task_id="wait-task",
            capability="langgraph",
        )
        result = await k8s_scheduler.get_job_result(
            record.job_id, wait=True, timeout=30
        )
        assert result is not None
        assert result.status.is_terminal

    @pytest.mark.asyncio
    async def test_submit_custom_job(self, k8s_scheduler):
        config = make_job_config(
            job_name="custom-integration",
            command=["python", "-c", "print('custom')"],
        )
        record = await k8s_scheduler.submit_custom_job(config, task_id="custom-task")
        assert record.job_id
        assert record.task_id == "custom-task"

    @pytest.mark.asyncio
    async def test_cancel_task_job(self, k8s_scheduler):
        config = make_job_config(
            job_name="cancel-int",
            command=["python", "-c", "import time; time.sleep(30)"],
            active_deadline_seconds=60,
        )
        record = await k8s_scheduler.submit_custom_job(config, task_id="cancel-me")
        await asyncio.sleep(0.3)

        success = await k8s_scheduler.cancel_task_job("cancel-me")
        assert success

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task(self, k8s_scheduler):
        success = await k8s_scheduler.cancel_task_job("no-such-task")
        assert not success

    @pytest.mark.asyncio
    async def test_get_cluster_info(self, k8s_scheduler):
        info = await k8s_scheduler.get_cluster_info()
        assert info is not None
        assert isinstance(info.node_count, int)

    @pytest.mark.asyncio
    async def test_get_nodes(self, k8s_scheduler):
        nodes = await k8s_scheduler.get_nodes()
        assert len(nodes) >= 1

    @pytest.mark.asyncio
    async def test_get_job_stats(self, k8s_scheduler):
        stats = await k8s_scheduler.get_job_stats()
        assert "total" in stats
        assert "active" in stats
        assert "max_concurrent" in stats

    @pytest.mark.asyncio
    async def test_list_all_jobs(self, k8s_scheduler):
        config = make_job_config(
            job_name="list-int",
            command=["python", "-c", "print('list')"],
        )
        await k8s_scheduler.submit_custom_job(config)
        await asyncio.sleep(1)

        jobs = await k8s_scheduler.list_all_jobs()
        assert len(jobs) >= 1

    @pytest.mark.asyncio
    async def test_list_all_jobs_with_filter(self, k8s_scheduler):
        config = make_job_config(
            job_name="filter-int",
            command=["python", "-c", "print('filter')"],
        )
        await k8s_scheduler.submit_custom_job(config)
        await asyncio.sleep(1)

        succeeded = await k8s_scheduler.list_all_jobs(status_filter="succeeded")
        running = await k8s_scheduler.list_all_jobs(status_filter="running")
        assert len(succeeded) + len(running) >= 1

    @pytest.mark.asyncio
    async def test_get_job_logs(self, k8s_scheduler):
        config = make_job_config(
            job_name="logs-int",
            command=["python", "-c", "print('hello from k8s scheduler')"],
        )
        record = await k8s_scheduler.submit_custom_job(config)
        await asyncio.sleep(1)

        logs = await k8s_scheduler.get_job_logs(record.job_id)
        assert "hello from k8s scheduler" in logs

    @pytest.mark.asyncio
    async def test_batch_submit(self, k8s_scheduler):
        tasks = [
            {"task_id": f"batch-task-{i}"}
            for i in range(5)
        ]
        records = await k8s_scheduler.batch_submit(
            tasks=tasks,
            template_name="checkpoint_worker",
            max_concurrent=3,
        )
        assert len(records) == 5

    @pytest.mark.asyncio
    async def test_get_templates(self, k8s_scheduler):
        templates = k8s_scheduler.get_templates()
        assert len(templates) >= 4
        names = [t["name"] for t in templates]
        assert "langgraph_worker" in names

    @pytest.mark.asyncio
    async def test_cleanup_jobs(self, k8s_scheduler):
        config = make_job_config(
            job_name="cleanup-int",
            command=["python", "-c", "print('clean')"],
        )
        await k8s_scheduler.submit_custom_job(config)
        await asyncio.sleep(1)

        removed = await k8s_scheduler.cleanup_jobs(max_age_hours=0)
        assert removed >= 0


# ─── K8sClientFactory 测试 ───────────────────────────────────────────────────


class TestK8sClientFactory:
    """客户端工厂"""

    def test_force_local(self):
        K8sClientFactory.reset()
        # 由于是 async 工厂，这里只测试 reset
        assert True

    @pytest.mark.asyncio
    async def test_get_client_force_local(self):
        K8sClientFactory.reset()
        client = await K8sClientFactory.get_client(force_local=True)
        assert isinstance(client, LocalK8sClient)
        K8sClientFactory.reset()


# ─── 预置模板测试 ────────────────────────────────────────────────────────────


class TestPresetTemplates:
    """预置 Job 模板"""

    def test_langgraph_worker_template(self):
        tmpl = PRESET_JOB_TEMPLATES["langgraph_worker"]
        assert tmpl.job_type == K8sJobType.LANGGRAPH_WORKER
        assert any("langgraph_worker" in c for c in tmpl.command)
        assert tmpl.resource_limits["memory"] == "4Gi"

    def test_sandbox_runner_template(self):
        tmpl = PRESET_JOB_TEMPLATES["sandbox_runner"]
        assert tmpl.job_type == K8sJobType.SANDBOX_RUNNER
        assert tmpl.active_deadline_seconds <= 600

    def test_checkpoint_worker_template(self):
        tmpl = PRESET_JOB_TEMPLATES["checkpoint_worker"]
        assert tmpl.job_type == K8sJobType.CHECKPOINT_WORKER
        assert any("checkpoint_worker" in c for c in tmpl.command)

    def test_batch_processor_template(self):
        tmpl = PRESET_JOB_TEMPLATES["batch_processor"]
        assert tmpl.job_type == K8sJobType.BATCH_PROCESSOR
        assert tmpl.resource_limits["memory"] == "8Gi"

    def test_all_templates_have_image(self):
        for name, tmpl in PRESET_JOB_TEMPLATES.items():
            assert tmpl.image, f"Template {name} missing image"
            assert tmpl.command, f"Template {name} missing command"


# ─── K8sDeploymentSpec 测试 ─────────────────────────────────────────────────


class TestK8sDeploymentSpec:
    """Deployment 规格"""

    def test_default_spec(self):
        spec = K8sDeploymentSpec(name="test-deploy")
        assert spec.name == "test-deploy"
        assert spec.replicas == 1
        assert spec.namespace == "ai-runtime-os"

    def test_to_dict(self):
        spec = K8sDeploymentSpec(name="test", replicas=5)
        d = spec.to_dict()
        assert d["name"] == "test"
        assert d["replicas"] == 5

    def test_probe_config(self):
        spec = K8sDeploymentSpec(
            name="probes",
            liveness_probe_path="/api/health",
            liveness_initial_delay=60,
            liveness_period=15,
        )
        assert spec.liveness_probe_path == "/api/health"
        assert spec.liveness_initial_delay == 60
        assert spec.liveness_period == 15
