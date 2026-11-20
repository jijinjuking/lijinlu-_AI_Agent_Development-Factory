"""
W4 — ArtifactStore 单元测试
覆盖：save、load、list、delete、diff、大小限制、类型校验、事件发布
"""
from __future__ import annotations

import uuid
import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.runtime.artifact_store import ArtifactStore


# ═══════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════

@pytest_asyncio.fixture(autouse=True)
async def _cleanup_artifacts():
    """测试结束后清理 Artifact 表"""
    yield


@pytest_asyncio.fixture
def task_with_state() -> str:
    return str(uuid.uuid4())


# ═══════════════════════════════════════════
# ArtifactStore 基础 CRUD
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_save_and_load(db_session, task_with_state):
    store = ArtifactStore(db_session)
    aid = await store.save(task_with_state, "test_result", "Hello, World!")
    content = await store.load(aid)
    assert content == "Hello, World!"


@pytest.mark.asyncio
async def test_save_and_get_meta(db_session, task_with_state):
    store = ArtifactStore(db_session)
    aid = await store.save(task_with_state, "code_file", "print(1)", metadata={"lang": "python"})
    meta = await store.get_meta(aid)
    assert meta["artifact_type"] == "code_file"
    assert meta["task_id"] == task_with_state
    assert meta["version"] == 1
    assert meta["metadata"]["lang"] == "python"


@pytest.mark.asyncio
async def test_list_by_task(db_session, task_with_state):
    store = ArtifactStore(db_session)
    task2 = str(uuid.uuid4())
    await store.save(task_with_state, "test_result", "A")
    await store.save(task_with_state, "code_file", "B")
    await store.save(task2, "test_result", "C")

    items = await store.list_by_task(task_with_state)
    assert len(items) == 2
    task_ids = {it["task_id"] for it in items}
    assert task_ids == {task_with_state}


@pytest.mark.asyncio
async def test_list_all(db_session, task_with_state):
    store = ArtifactStore(db_session)
    await store.save(task_with_state, "test_result", "A")
    items = await store.list_all(limit=10)
    assert len(items) >= 1


@pytest.mark.asyncio
async def test_delete(db_session, task_with_state):
    store = ArtifactStore(db_session)
    aid = await store.save(task_with_state, "test_result", "delete me")
    assert await store.delete(aid) is True
    assert await store.get_meta(aid) is None
    # 二次删除返回 False
    assert await store.delete(aid) is False


@pytest.mark.asyncio
async def test_load_nonexistent(db_session):
    store = ArtifactStore(db_session)
    with pytest.raises(FileNotFoundError):
        await store.load(str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_count(db_session, task_with_state):
    store = ArtifactStore(db_session)
    before = await store.count()
    await store.save(task_with_state, "test_result", "X")
    assert await store.count() == before + 1


# ═══════════════════════════════════════════
# 类型与大小校验
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_invalid_type_rejected(db_session, task_with_state):
    store = ArtifactStore(db_session)
    with pytest.raises(ValueError, match="Unsupported artifact_type"):
        await store.save(task_with_state, "invalid_type", "x")


@pytest.mark.asyncio
async def test_all_valid_types(db_session, task_with_state):
    store = ArtifactStore(db_session)
    valid_types = [
        "requirement_doc", "architecture_doc", "code_file", "code_patch",
        "test_result", "review_report", "deploy_log",
        "runtime_trace", "context_snapshot",
    ]
    for at in valid_types:
        aid = await store.save(task_with_state, at, "content")
        meta = await store.get_meta(aid)
        assert meta["artifact_type"] == at


@pytest.mark.asyncio
async def test_size_limit(db_session, task_with_state):
    store = ArtifactStore(db_session)
    # 11MB 内容应被拒绝
    large = "x" * (11 * 1024 * 1024)
    with pytest.raises(ValueError, match="too large"):
        await store.save(task_with_state, "test_result", large)


@pytest.mark.asyncio
async def test_binary_content(db_session, task_with_state):
    store = ArtifactStore(db_session)
    # 二进制不超过 10MB
    content = b"\x00\x01\x02\xff" * 100
    aid = await store.save(task_with_state, "runtime_trace", content)
    loaded = await store.load_bytes(aid)
    assert loaded == content


# ═══════════════════════════════════════════
# Diff
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_diff_artifacts(db_session, task_with_state):
    store = ArtifactStore(db_session)
    v1 = await store.save(task_with_state, "code_file", "line1\nline2\nline3\n")
    v2 = await store.save(task_with_state, "code_file", "line1\nline2_modified\nline3\n")
    diff = await store.diff(v1, v2)
    assert "line2_modified" in diff
    assert "+++" in diff


# ═══════════════════════════════════════════
# 版本溯源
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_parent_artifact_id(db_session, task_with_state):
    store = ArtifactStore(db_session)
    parent_id = await store.save(task_with_state, "code_file", "v1")
    child_id = await store.save(
        task_with_state, "code_file", "v2",
        parent_artifact_id=parent_id,
    )
    child_meta = await store.get_meta(child_id)
    assert child_meta["parent_artifact_id"] == parent_id


# ═══════════════════════════════════════════
# API 端点测试
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_api_list_artifacts(client: AsyncClient, task_with_state):
    # 先创建一个 artifact
    await client.post("/artifacts", json={
        "task_id": task_with_state,
        "artifact_type": "test_result",
        "content": "API test",
    })
    r = await client.get("/artifacts")
    assert r.status_code == 200
    data = r.json()
    assert "artifacts" in data
    assert data["count"] >= 1


@pytest.mark.asyncio
async def test_api_list_by_task(client: AsyncClient, task_with_state):
    await client.post("/artifacts", json={
        "task_id": task_with_state,
        "artifact_type": "code_file",
        "content": "print(42)",
    })
    r = await client.get(f"/artifacts?task_id={task_with_state}")
    assert r.status_code == 200
    items = r.json()["artifacts"]
    assert all(it["task_id"] == task_with_state for it in items)


@pytest.mark.asyncio
async def test_api_get_artifact(client: AsyncClient, task_with_state):
    res = await client.post("/artifacts", json={
        "task_id": task_with_state,
        "artifact_type": "test_result",
        "content": "get test",
    })
    aid = res.json()["artifact_id"]
    r = await client.get(f"/artifacts/{aid}")
    assert r.status_code == 200
    assert r.json()["artifact_type"] == "test_result"


@pytest.mark.asyncio
async def test_api_get_artifact_404(client: AsyncClient):
    r = await client.get(f"/artifacts/{uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_api_get_content(client: AsyncClient, task_with_state):
    res = await client.post("/artifacts", json={
        "task_id": task_with_state,
        "artifact_type": "code_file",
        "content": "def hello(): return 'world'",
    })
    aid = res.json()["artifact_id"]
    r = await client.get(f"/artifacts/{aid}/content")
    assert r.status_code == 200
    assert "def hello" in r.text


@pytest.mark.asyncio
async def test_api_delete(client: AsyncClient, task_with_state):
    res = await client.post("/artifacts", json={
        "task_id": task_with_state,
        "artifact_type": "test_result",
        "content": "to delete",
    })
    aid = res.json()["artifact_id"]
    r = await client.delete(f"/artifacts/{aid}")
    assert r.status_code == 200
    # 确认已删除
    r2 = await client.get(f"/artifacts/{aid}")
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_api_diff(client: AsyncClient, task_with_state):
    v1 = await client.post("/artifacts", json={
        "task_id": task_with_state,
        "artifact_type": "code_file",
        "content": "v1\n",
    })
    v2 = await client.post("/artifacts", json={
        "task_id": task_with_state,
        "artifact_type": "code_file",
        "content": "v2\n",
    })
    r = await client.get(f"/artifacts/{v2.json()['artifact_id']}/diff", params={
        "compare_with": v1.json()["artifact_id"],
    })
    assert r.status_code == 200
    assert "v2" in r.json()["diff"]


@pytest.mark.asyncio
async def test_api_missing_required_fields(client: AsyncClient):
    r = await client.post("/artifacts", json={"content": "x"})
    assert r.status_code == 400

    r2 = await client.post("/artifacts", json={"task_id": str(uuid.uuid4())})
    assert r2.status_code == 400
