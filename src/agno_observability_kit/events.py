"""Versioned operational events. Document bodies and raw model messages are excluded."""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_.:-]+$")]
Service = Literal["acessilia", "acessilia-toolbox"]
Phase = Literal["intake", "queue", "cache", "manifest", "media_inspect", "enrichment", "planning", "execution", "validation", "export", "delivery", "model", "tool"]
Status = Literal["queued", "running", "succeeded", "failed", "cancelled", "retrying", "skipped"]
TERMINAL = {"succeeded", "failed", "cancelled"}
ATTRIBUTE_KEYS = {
    "pipeline", "planner_backend", "preferred_plan", "dry_run", "noop", "capability",
    "provider", "provider_version", "method", "obligation_id", "page", "step_index",
    "retry", "cache_hit", "fallback", "alternatives", "selected", "reason_code",
    "rationale", "model", "prompt_version", "tokens_input", "tokens_output", "cost_usd",
    "duration_ms", "validation", "outcome", "error_type", "error_code", "format",
    "git_commit", "plan_id", "manifest_id", "replan_required", "queue_position",
    "dropped_events", "http_status", "operation", "count", "mode",
}


def redact(text: str) -> str:
    text = re.sub(r"(?i)\b(Bearer|Basic)\s+[a-z0-9+/=_\-.]+", r"\1 [REDACTED]", text)
    text = re.sub(r"(?i)\b(?:sk-(?:proj-)?[a-z0-9_-]{8,}|gh[pousr]_[a-z0-9_]{12,}|github_pat_[a-z0-9_]{12,})", "[REDACTED]", text)
    text = re.sub(r"(?i)(\b(?:password|secret|token|api[_-]?key|authorization)\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}", "[EMAIL]", text)
    text = re.sub(r"https?://[^\s]+", "[URL]", text)
    return text


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Event(StrictModel):
    schema_version: Literal["1"] = "1"
    event_id: Identifier
    timestamp: datetime
    service: Service
    environment: Identifier = "develop"
    host_id: Identifier = "unassigned"
    job_id: Identifier
    message_id: Identifier = "unassigned"
    session_id: Identifier = "unassigned"
    trace_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    span_id: str = Field(pattern=r"^[a-f0-9]{16}$")
    parent_span_id: str = Field(default="", pattern=r"^(?:[a-f0-9]{16})?$")
    kind: Literal["job", "span", "decision"]
    phase: Phase
    status: Status
    name: str = Field(min_length=1, max_length=160)
    attributes: dict[str, str | bool | int | float | list[str]] = Field(default_factory=dict, max_length=40)

    @field_validator("timestamp")
    @classmethod
    def aware_timestamp(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        difference = (datetime.now(timezone.utc) - value).total_seconds()
        if difference > 90 * 86400 or difference < -300:
            raise ValueError("timestamp is outside the 90-day ingestion window")
        return value.astimezone(timezone.utc)

    @field_validator("trace_id", "span_id", "parent_span_id")
    @classmethod
    def nonzero_id(cls, value):
        if value and set(value) == {"0"}:
            raise ValueError("trace and span IDs cannot be zero")
        return value

    @field_validator("name")
    @classmethod
    def safe_name(cls, value):
        return redact(value)

    @field_validator("attributes")
    @classmethod
    def safe_attributes(cls, values):
        # Allowlist drops input/output, prompts, documents, paths and credentials.
        result = {}
        for key, value in values.items():
            if key not in ATTRIBUTE_KEYS:
                continue
            if key in {'tokens_input', 'tokens_output', 'duration_ms', 'cost_usd', 'dropped_events'}:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ValueError('metric attributes must be finite non-negative numbers')
            if isinstance(value, str):
                result[key] = redact(value[:1000])
            elif isinstance(value, list):
                result[key] = [redact(item[:128]) for item in value[:20]]
            elif isinstance(value, float) and not math.isfinite(value):
                raise ValueError("attribute numbers must be finite")
            else:
                result[key] = value
        return result


class EventBatch(StrictModel):
    events: list[Event] = Field(min_length=1, max_length=100)


class Process(StrictModel):
    pid: int = Field(ge=1)
    ppid: int = Field(ge=0)
    name: str = Field(min_length=1, max_length=80)
    status: str = Field(max_length=32)
    cpu_percent: float = Field(ge=0, le=100_000)
    memory_bytes: int = Field(ge=0)
    age_seconds: float = Field(ge=0)
    service: Literal["", "acessilia", "acessilia-toolbox"] = ""


class HostSnapshot(StrictModel):
    host_id: Identifier
    timestamp: datetime
    cpu_percent: float = Field(ge=0, le=100)
    cpu_count: int = Field(ge=1, le=65536)
    memory_total_bytes: int = Field(ge=1)
    memory_used_bytes: int = Field(ge=0)
    disk_percent: float = Field(ge=0, le=100)
    process_count: int = Field(ge=0)
    processes: list[Process] = Field(max_length=200)

    @field_validator("timestamp")
    @classmethod
    def recent_timestamp(cls, value):
        if value.tzinfo is None or abs((datetime.now(timezone.utc) - value).total_seconds()) > 300:
            raise ValueError("host timestamp must be timezone-aware and within five minutes")
        return value.astimezone(timezone.utc)
