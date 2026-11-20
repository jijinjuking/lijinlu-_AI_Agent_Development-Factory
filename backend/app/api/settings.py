"""
Settings API — 系统设置（真实数据库）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.settings import ModelConfig, ApiKey, AgentPermission, RuntimeSetting
from app.schemas.mixed import (
    ModelConfigResponse, ModelConfigCreate, ApiKeyResponse, ApiKeyCreate,
    AgentPermissionResponse, AgentPermissionUpdate,
)
from app.api._orm import model_to_dict, apikey_to_dict, perm_to_dict, _to_str
import uuid
from uuid import UUID

router = APIRouter()


# ---- 根路由 ----

@router.get("")
async def settings_index(db: AsyncSession = Depends(get_db)):
    """设置概览"""
    models_result = await db.execute(select(ModelConfig))
    keys_result = await db.execute(select(ApiKey))
    perms_result = await db.execute(select(AgentPermission))
    return {
        "models": [model_to_dict(m) for m in models_result.scalars().all()],
        "api_keys": [apikey_to_dict(k) for k in keys_result.scalars().all()],
        "permissions": [perm_to_dict(p) for p in perms_result.scalars().all()],
    }


# ---- 模型配置 ----

@router.get("/models", response_model=list[ModelConfigResponse])
async def list_models(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ModelConfig))
    models = result.scalars().all()
    # JOIN api_keys 获取 label — ApiKey.id 是 UUID 对象，需要把字符串 key_ids 转成 UUID
    key_ids_raw = [m.api_key_id for m in models if m.api_key_id]
    key_ids: list[UUID] = []
    for k in key_ids_raw:
        try:
            key_ids.append(UUID(k))
        except (ValueError, TypeError):
            pass
    key_labels: dict[str, str] = {}
    if key_ids:
        keys_result = await db.execute(select(ApiKey).where(ApiKey.id.in_(key_ids)))
        for k in keys_result.scalars().all():
            key_labels[_to_str(k.id)] = k.label
    output = []
    for m in models:
        d = model_to_dict(m)
        if m.api_key_id:
            d["api_key_label"] = key_labels.get(m.api_key_id, "")
        output.append(d)
    return output


@router.post("/models", response_model=ModelConfigResponse, status_code=201)
async def create_model(body: ModelConfigCreate, db: AsyncSession = Depends(get_db)):
    api_key_id_val = str(body.api_key_id) if body.api_key_id else None
    model = ModelConfig(
        name=body.name,
        model_id=body.model_id,
        provider=body.provider,
        endpoint=body.endpoint,
        api_base=body.api_base or body.endpoint,
        api_key_id=api_key_id_val,
        enabled=body.enabled,
        default_for=",".join(body.default_for) if body.default_for else "",
        max_tokens=body.max_tokens,
        temperature=body.temperature,
        cost_input_per_1k=body.cost_input_per_1k,
        cost_output_per_1k=body.cost_output_per_1k,
        api_key_configured=bool(api_key_id_val),
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    d = model_to_dict(model)
    if model.api_key_id:
        key_result = await db.execute(select(ApiKey).where(ApiKey.id == model.api_key_id))
        key = key_result.scalar_one_or_none()
        if key:
            d["api_key_label"] = key.label
    return d


@router.put("/models/{model_id}", response_model=ModelConfigResponse)
async def update_model(model_id: str, body: dict, db: AsyncSession = Depends(get_db)):
    uid = uuid.UUID(model_id)
    result = await db.execute(select(ModelConfig).where(ModelConfig.id == uid))
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Model not found")
    allowed = {"name", "model_id", "provider", "endpoint", "api_base", "api_key_id",
               "enabled", "default_for", "max_tokens", "temperature",
               "cost_input_per_1k", "cost_output_per_1k", "api_key_configured"}
    for k, v in body.items():
        if k in allowed:
            if k == "api_key_id":
                setattr(m, k, str(v) if v else None)
                m.api_key_configured = bool(v)
            elif k == "api_base":
                setattr(m, k, v)
                if v and not m.endpoint:
                    m.endpoint = v  # 同步旧字段
            else:
                setattr(m, k, v)
    await db.commit()
    await db.refresh(m)
    d = model_to_dict(m)
    if m.api_key_id:
        key_result = await db.execute(select(ApiKey).where(ApiKey.id == m.api_key_id))
        key = key_result.scalar_one_or_none()
        if key:
            d["api_key_label"] = key.label
    return d


@router.delete("/models/{model_id}")
async def delete_model(model_id: str, db: AsyncSession = Depends(get_db)):
    uid = uuid.UUID(model_id)
    result = await db.execute(select(ModelConfig).where(ModelConfig.id == uid))
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Model not found")
    await db.delete(m)
    await db.commit()
    return {"status": "deleted"}


# ---- API Keys ----

@router.get("/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiKey))
    return [apikey_to_dict(k) for k in result.scalars().all()]


@router.post("/api-keys", response_model=ApiKeyResponse, status_code=201)
async def create_api_key(body: ApiKeyCreate, db: AsyncSession = Depends(get_db)):
    masked = body.key[:3] + "****" + body.key[-3:] if len(body.key) > 6 else "****"
    key = ApiKey(
        provider=body.provider, label=body.label,
        masked_key=masked, encrypted_key=body.key, enabled=True,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return apikey_to_dict(key)


@router.delete("/api-keys/{key_id}")
async def delete_api_key(key_id: str, db: AsyncSession = Depends(get_db)):
    uid = uuid.UUID(key_id)
    result = await db.execute(select(ApiKey).where(ApiKey.id == uid))
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="API Key not found")
    await db.delete(key)
    await db.commit()
    return {"status": "deleted"}


# ---- Agent 权限 ----

@router.get("/permissions", response_model=list[AgentPermissionResponse])
async def list_permissions(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentPermission))
    return [perm_to_dict(p) for p in result.scalars().all()]


@router.put("/permissions/{role_id}", response_model=AgentPermissionResponse)
async def update_permission(role_id: str, body: AgentPermissionUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentPermission).where(AgentPermission.role_id == role_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Permission not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(p, k, v)
    await db.commit()
    await db.refresh(p)
    return perm_to_dict(p)


# ---- 运行时配置（通用设置） ----

# 默认值
DEFAULT_RUNTIME_SETTINGS = {
    "max_concurrency": {"value": "8", "description": "最大并发 Agent 数"},
    "default_timeout_minutes": {"value": "30", "description": "默认任务超时（分钟）"},
    "auto_retry_count": {"value": "2", "description": "自动重试次数"},
    "log_retention_days": {"value": "30", "description": "日志保留天数"},
    "notify_on_complete": {"value": "true", "description": "任务完成通知"},
    "notify_on_failure": {"value": "true", "description": "任务失败通知"},
    "cost_alert_threshold": {"value": "20", "description": "费用告警阈值（¥/天）"},
    "notification_channels": {"value": '["webhook"]', "description": "通知渠道"},
}


def _parse_runtime_value(key: str, raw: str):
    """将存储的字符串值解析为对应类型"""
    int_keys = {"max_concurrency", "default_timeout_minutes", "auto_retry_count", "log_retention_days"}
    float_keys = {"cost_alert_threshold"}
    bool_keys = {"notify_on_complete", "notify_on_failure"}
    list_keys = {"notification_channels"}

    if key in int_keys:
        return int(raw) if raw else 0
    if key in float_keys:
        return float(raw) if raw else 0.0
    if key in bool_keys:
        return raw.lower() == "true"
    if key in list_keys:
        import json
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    return raw


async def _ensure_defaults(db: AsyncSession):
    """确保默认配置存在"""
    existing = await db.execute(select(RuntimeSetting.key))
    existing_keys = {r[0] for r in existing.all()}
    for key, info in DEFAULT_RUNTIME_SETTINGS.items():
        if key not in existing_keys:
            db.add(RuntimeSetting(key=key, value=info["value"], description=info["description"]))
    await db.commit()


@router.get("/runtime")
async def get_runtime_settings(db: AsyncSession = Depends(get_db)):
    """获取运行时配置（通用设置）"""
    await _ensure_defaults(db)
    result = await db.execute(select(RuntimeSetting))
    rows = result.scalars().all()
    settings = {}
    for row in rows:
        settings[row.key] = _parse_runtime_value(row.key, row.value)
    # 确保所有默认 key 都在响应中
    for key, info in DEFAULT_RUNTIME_SETTINGS.items():
        if key not in settings:
            settings[key] = _parse_runtime_value(key, info["value"])
    return settings


@router.put("/runtime")
async def update_runtime_settings(body: dict, db: AsyncSession = Depends(get_db)):
    """更新运行时配置（通用设置）"""
    await _ensure_defaults(db)
    result = await db.execute(select(RuntimeSetting))
    rows = {r.key: r for r in result.scalars().all()}

    for key, value in body.items():
        if key in rows:
            rows[key].value = str(value)
        elif key in DEFAULT_RUNTIME_SETTINGS:
            db.add(RuntimeSetting(key=key, value=str(value), description=DEFAULT_RUNTIME_SETTINGS[key]["description"]))

    await db.commit()

    # 返回更新后的完整配置
    result2 = await db.execute(select(RuntimeSetting))
    settings = {}
    for row in result2.scalars().all():
        settings[row.key] = _parse_runtime_value(row.key, row.value)
    for key, info in DEFAULT_RUNTIME_SETTINGS.items():
        if key not in settings:
            settings[key] = _parse_runtime_value(key, info["value"])
    return settings
