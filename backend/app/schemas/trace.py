"""
AI Runtime OS — Trace Schema
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class TraceListItem(BaseModel):
    id: str
    pipeline_name: str = ""
    agent_name: str = ""
    status: str = "running"
    start_time: str = ""
    duration: int | None = None
    total_tokens: int = 0
    total_cost: float = 0.0


class TraceNodeResponse(BaseModel):
    id: str
    parent_id: str | None = None
    type: str  # chain | agent_action | llm_call | tool_call | error
    name: str
    status: str
    start_time: str = ""
    end_time: str = ""
    duration: int = 0
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost: float | None = None
    tool_name: str | None = None
    error: str | None = None
    input: str = ""
    output: str = ""
    agent_name: str = ""
    children: list[str] = Field(default_factory=list)


class TraceResponse(BaseModel):
    id: str
    pipeline_id: str = ""
    pipeline_name: str = ""
    agent_id: str = ""
    agent_name: str = ""
    start_time: str = ""
    end_time: str | None = None
    duration: int | None = None
    status: str
    total_tokens: int = 0
    total_cost: float = 0.0
    node_count: int = 0
    error_count: int = 0
    root_node_id: str = ""
    nodes: list[TraceNodeResponse] = Field(default_factory=list)
