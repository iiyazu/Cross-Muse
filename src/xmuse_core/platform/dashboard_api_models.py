from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LaneCreate(BaseModel):
    model_config = ConfigDict(extra="allow")

    feature_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    task_type: str = "execute"
    status: str = "pending"
    capabilities: list[str] = Field(default_factory=lambda: ["code"])


class LaneReject(BaseModel):
    reason: str | None = None
    rework: bool = False
