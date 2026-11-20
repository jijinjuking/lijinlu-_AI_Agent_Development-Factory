"""
LLM Service — 统一 LLM 调用层
支持: OpenAI / Anthropic / Ollama (本地) / Mock (测试)
自动记录 LLMCall 到数据库（成本追踪）
自动发布 Event 到 EventBus
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Awaitable, Callable, Optional, List

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.event_bus import event_bus, Event
from app.core.event_types import EventType
from app.models.event import LLMCall


# ---- 模型定价 (USD / 1K tokens) ----
# 当 provider 未返回 cost 时使用，或用于预估算
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o":            {"prompt": 0.005,   "completion": 0.015},
    "gpt-4o-mini":       {"prompt": 0.00015, "completion": 0.0006},
    "gpt-4-turbo":       {"prompt": 0.01,    "completion": 0.03},
    "gpt-3.5-turbo":     {"prompt": 0.0005,  "completion": 0.0015},
    "claude-3-5-sonnet":  {"prompt": 0.003,   "completion": 0.015},
    "claude-3-haiku":    {"prompt": 0.00025, "completion": 0.00125},
    "claude-3-opus":      {"prompt": 0.015,   "completion": 0.075},
    "llama3":              {"prompt": 0.0,      "completion": 0.0},
    "qwen2.5":            {"prompt": 0.0,      "completion": 0.0},
    "deepseek-coder":      {"prompt": 0.00014,  "completion": 0.00028},
    "deepseek-chat":       {"prompt": 0.00014,  "completion": 0.00028},
    "deepseek-reasoner":   {"prompt": 0.00055,  "completion": 0.00219},
}


def _calc_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """根据定价表计算估算成本 (USD)"""
    key = model.split(":")[-1].lower()
    pricing = MODEL_PRICING.get(key) or next(
        (v for k, v in MODEL_PRICING.items() if k in key), {}
    )
    if not pricing:
        return 0.0
    return round(
        prompt_tokens / 1000 * pricing.get("prompt", 0)
        + completion_tokens / 1000 * pricing.get("completion", 0),
        6,
    )


# ---- 多模型凭证解析（DB → fallback .env） ----

def _get_db_path() -> str:
    """从 settings.database_url 提取 sqlite 文件路径"""
    url = settings.database_url
    if url.startswith("sqlite+aiosqlite:///"):
        return url.replace("sqlite+aiosqlite:///", "")
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "")
    return "ai_runtime.db"


def _resolve_model_credentials(model: str) -> tuple[str, str, str]:
    """
    根据 model 名从 model_configs + api_keys 表查找 API Key 和 Base URL。
    
    返回 (api_key, api_base, provider)
    
    查找顺序:
    1. model_configs WHERE model_id = model（精确匹配）
    2. model_configs WHERE name = model（模糊匹配）
    3. 如果找到且 api_key_id 不为空 → 查 api_keys 表取真实 Key
    4. 都没找到 → fallback 到 .env 环境变量
    """
    db_path = _get_db_path()
    if not os.path.exists(db_path):
        return _env_fallback(model)
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        # 先按 model_id 精确匹配，再按 name 模糊匹配
        row = conn.execute(
            "SELECT api_key_id, api_base, provider FROM model_configs "
            "WHERE enabled = 1 AND (model_id = ? OR name = ?) "
            "ORDER BY CASE WHEN model_id = ? THEN 0 ELSE 1 END LIMIT 1",
            (model, model, model)
        ).fetchone()
        
        if row and row["api_key_id"]:
            # 查 api_keys 表取真实 Key
            key_row = conn.execute(
                "SELECT encrypted_key FROM api_keys WHERE id = ? AND enabled = 1",
                (row["api_key_id"],)
            ).fetchone()
            if key_row and key_row["encrypted_key"]:
                api_key = key_row["encrypted_key"]
                api_base = row["api_base"] or ""
                provider = row["provider"] or _detect_provider(model)
                conn.close()
                return api_key, api_base, provider
        
        conn.close()
    except Exception:
        pass
    
    return _env_fallback(model)


def _env_fallback(model: str) -> tuple[str, str, str]:
    """当 DB 中查不到凭证时，回退到 .env 环境变量"""
    provider = _detect_provider(model)
    if provider == "anthropic":
        return settings.anthropic_api_key or "", settings.anthropic_base_url or "", "anthropic"
    if provider == "ollama":
        return "", settings.ollama_base_url or "", "ollama"
    # openai / custom → 走 OpenAI 兼容
    return (
        settings.openai_api_key or "",
        settings.openai_base_url or "https://api.openai.com/v1",
        provider,
    )


async def _record_call(
    db: AsyncSession | None,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    cost: float,
    latency_ms: int,
    task_id: str = "",
    agent_id: str = "",
    agent_name: str = "",
    task_type: str = "",
) -> LLMCall | None:
    """写入 LLMCall 记录；无 db 则跳过"""
    if db is None:
        return None
    now = datetime.now(timezone.utc)
    uid = uuid.uuid4()
    call = LLMCall(
        id=uid,
        task_id=uuid.UUID(task_id) if task_id else None,
        agent_id=uuid.UUID(agent_id) if agent_id else None,
        agent_name=agent_name,
        model=model,
        task_type=task_type,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        estimated_cost=cost,
        latency_ms=latency_ms,
        created_at=now,
    )
    db.add(call)
    await db.flush()  # 不 commit（由调用方统一管理事务）
    return call


def _detect_provider(model: str) -> str:
    """
    根据 model 字符串推断 provider。
    """
    m = model.lower()
    if m.startswith("ollama:") or m.startswith("local:"):
        return "ollama"
    if "claude" in m:
        return "anthropic"
    if "gpt" in m or "openai" in m:
        return "openai"
    if m.startswith("mock:"):
        return "mock"
    return (settings.default_llm_provider or "openai").lower()


# ========== 各 provider 实现 ==========

async def _openai_chat(
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    stream: bool,
    tools: list[dict] | None = None,
    api_key: str = "",
    api_base: str = "",
) -> tuple[str | None, dict | None, AsyncGenerator[str, None] | None, list[dict] | None]:
    """
    OpenAI 兼容接口。
    返回 (content, usage, stream_generator, tool_calls)
    - 非流式: (content, usage, None, tool_calls)
    - 流式:     (None, None, stream_generator, None)
    """
    _key = api_key or settings.openai_api_key or ""
    _base = (api_base or settings.openai_base_url or "https://api.openai.com/v1").rstrip("/")
    headers = {
        "Authorization": f"Bearer {_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    if not stream:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{_base}/chat/completions",
                headers=headers,
                json=payload,
            )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        message = choice.get("message", {})
        content = message.get("content")
        usage = data.get("usage")

        # 解析 tool_calls
        raw_tool_calls = message.get("tool_calls", [])
        tool_calls = None
        if raw_tool_calls:
            tool_calls = []
            for tc in raw_tool_calls:
                func = tc.get("function", {})
                tool_calls.append({
                    "id": tc.get("id", ""),
                    "name": func.get("name", ""),
                    "arguments": func.get("arguments", "{}"),
                })

        return content, usage, None, tool_calls
    else:
        async def _gen() -> AsyncGenerator[str, None]:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST", f"{_base}/chat/completions",
                    headers=headers,
                    json=payload,
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk["choices"][0].get("delta", {})
                            text = delta.get("content", "")
                            if text:
                                yield text
                        except (json.JSONDecodeError, KeyError):
                            continue
        return None, None, _gen(), None


async def _anthropic_chat(
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    stream: bool,
    tools: list[dict] | None = None,
    api_key: str = "",
    api_base: str = "",
) -> tuple[str | None, dict | None, AsyncGenerator[str, None] | None, list[dict] | None]:
    _key = api_key or settings.anthropic_api_key or ""
    _base = (api_base or settings.anthropic_base_url or "https://api.anthropic.com").rstrip("/")
    headers = {
        "x-api-key": _key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    system_msg = ""
    anthropic_messages = []
    for m in messages:
        if m["role"] == "system":
            system_msg = m["content"]
        else:
            anthropic_messages.append(m)

    payload = {
        "model": model,
        "messages": anthropic_messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": stream,
    }
    if system_msg:
        payload["system"] = system_msg

    if not stream:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{_base}/v1/messages",
                headers=headers,
                json=payload,
            )
        resp.raise_for_status()
        data = resp.json()
        content = data["content"][0]["text"]
        usage = {
            "prompt_tokens": data.get("usage", {}).get("input_tokens", 0),
            "completion_tokens": data.get("usage", {}).get("output_tokens", 0),
        }
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        return content, usage, None, None
    else:
        async def _gen() -> AsyncGenerator[str, None]:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST", f"{_base}/v1/messages",
                    headers=headers,
                    json=payload,
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        try:
                            chunk = json.loads(line[6:])
                            if chunk.get("type") == "content_block_delta":
                                text = chunk.get("delta", {}).get("text", "")
                                if text:
                                    yield text
                        except (json.JSONDecodeError, KeyError):
                            continue
        return None, None, _gen(), None


async def _ollama_chat(
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    stream: bool,
    tools: list[dict] | None = None,
) -> tuple[str | None, dict | None, AsyncGenerator[str, None] | None, list[dict] | None]:
    base_url = (settings.ollama_base_url or "http://localhost:11434").rstrip("/")
    real_model = model.split(":", 1)[1] if ":" in model and model.startswith("ollama") else model
    payload = {
        "model": real_model,
        "messages": messages,
        "temperature": temperature,
        "num_predict": max_tokens,
        "stream": stream,
    }

    if not stream:
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                f"{base_url}/api/chat",
                json=payload,
            )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("message", {}).get("content", "")
        # Ollama 不返回 token 用量，做粗略估算
        prompt_text = " ".join(m.get("content", "") for m in messages)
        prompt_tokens = len(prompt_text) // 4
        completion_tokens = len(content) // 4
        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
        return content, usage, None, None
    else:
        async def _gen() -> AsyncGenerator[str, None]:
            async with httpx.AsyncClient(timeout=300.0) as client:
                async with client.stream(
                    "POST", f"{base_url}/api/chat",
                    json=payload,
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                            msg = chunk.get("message", {})
                            text = msg.get("content", "")
                            if text:
                                yield text
                            if chunk.get("done", False):
                                break
                        except json.JSONDecodeError:
                            continue
        return None, None, _gen(), None


async def _mock_chat(
    model: str,
    messages: list[dict],
    stream: bool,
    tools: list[dict] | None = None,
) -> tuple[str | None, dict | None, AsyncGenerator[str, None] | None, list[dict] | None]:
    last_msg = messages[-1]["content"] if messages else ""
    content = f"[MOCK] You said: {last_msg[:200]}"
    usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}

    if not stream:
        return content, usage, None, None

    async def _gen() -> AsyncGenerator[str, None]:
        for ch in content:
            yield ch
    return None, None, _gen(), None


# ========== 公开 Service 类 ==========

class LLMService:
    """
    统一 LLM 调用服务。
    用法:
        svc = LLMService()
        content, usage, _ = await svc.chat(...)
        # 或流式:
        _, _, stream_gen = await svc.chat(..., stream=True)
        async for chunk in stream_gen:
            ...
    """

    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        db: AsyncSession | None = None,
        task_id: str = "",
        agent_id: str = "",
        agent_name: str = "",
        task_type: str = "",
        tools: list[dict] | None = None,
    ) -> tuple[str | None, dict | None, AsyncGenerator[str, None] | None, list[dict] | None]:
        """
        统一 chat 接口。
        返回 (content, usage, stream_generator, tool_calls)
        - stream=False: content=str, usage=dict, stream_generator=None, tool_calls=list|None
        - stream=True:  content=None, usage=None, stream_generator=AsyncGenerator, tool_calls=None
        """
        provider = _detect_provider(model)
        t0 = time.time()

        # 发布 LLM_CALL_STARTED 事件
        await event_bus.publish(Event(
            type=EventType.LLM_CALL_STARTED,
            task_id=task_id,
            payload={"model": model, "provider": provider},
            produced_by=agent_name or "system",
        ))

        content, usage, stream_gen, tool_calls = await self._dispatch(
            provider, model, messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
            tools=tools,
        )

        latency_ms = int((time.time() - t0) * 1000)

        # 计算成本
        if usage:
            cost = _calc_cost(
                model,
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
            )
        else:
            # 流式或无 usage 时做粗略估算
            prompt_text = " ".join(m.get("content", "") for m in messages)
            est_prompt = len(prompt_text) // 4
            est_completion = 0
            if content:
                est_completion = len(content) // 4
            cost = _calc_cost(model, est_prompt, est_completion)
            usage = {
                "prompt_tokens": est_prompt,
                "completion_tokens": est_completion,
                "total_tokens": est_prompt + est_completion,
            }

        # 写 LLMCall 记录
        await _record_call(
            db, model,
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
            usage.get("total_tokens", 0),
            cost, latency_ms,
            task_id=task_id,
            agent_id=agent_id,
            agent_name=agent_name,
            task_type=task_type,
        )

        # 发布 LLM_CALL_COMPLETE 事件
        await event_bus.publish(Event(
            type=EventType.LLM_CALL_COMPLETE,
            task_id=task_id,
            payload={
                "model": model,
                "tokens": usage.get("total_tokens", 0),
                "cost": cost,
                "latency_ms": latency_ms,
            },
            produced_by=agent_name or "system",
        ))

        return content, usage, stream_gen, tool_calls

    async def _dispatch(
        self,
        provider: str,
        model: str,
        messages: list[dict],
        *,
        temperature: float,
        max_tokens: int,
        stream: bool,
        tools: list[dict] | None = None,
    ) -> tuple[str | None, dict | None, AsyncGenerator[str, None] | None, list[dict] | None]:
        # 按 model 名从 DB 查找 API Key + Base URL（DB 无则 fallback .env）
        api_key, api_base, db_provider = _resolve_model_credentials(model)
        # DB 中配了非 openai 的明确 provider（anthropic/ollama/mock/custom）则覆盖启发式推断
        if db_provider in ("anthropic", "ollama", "mock", "custom"):
            provider = db_provider

        if provider == "openai" or provider == "custom":
            return await _openai_chat(model, messages, temperature, max_tokens, stream, tools,
                                      api_key=api_key, api_base=api_base)
        if provider == "anthropic":
            return await _anthropic_chat(model, messages, temperature, max_tokens, stream, tools,
                                         api_key=api_key, api_base=api_base)
        if provider == "ollama":
            return await _ollama_chat(model, messages, temperature, max_tokens, stream, tools)
        if provider == "mock":
            return await _mock_chat(model, messages, stream, tools)
        raise ValueError(f"Unsupported provider: {provider}")

    async def close(self):
        """关闭底层资源（预留）"""
        pass


# ---- 全局单例 ----
llm_service = LLMService()
