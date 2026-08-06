from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class RoundCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    inquiry: str = Field(min_length=1, max_length=12_000)
    feedback_project_id: str = Field(min_length=1, max_length=160)
    folding_project_id: str = Field(min_length=1, max_length=160)
    motif_ids: list[str] = Field(default_factory=list, max_length=20)
    checkpoint_ids: list[str] = Field(default_factory=list, max_length=12)
    human_note: str = Field(default="", max_length=4_000)


class FoldSelection(BaseModel):
    fold_id: str = Field(min_length=1, max_length=160)
    aim: str = Field(min_length=1, max_length=4_000)
    scope: str = Field(min_length=1, max_length=2_000)
    stop_condition: str = Field(min_length=1, max_length=2_000)
    protected_boundary: str = Field(default="", max_length=2_000)
    participants: list[Literal["agent_a", "agent_b", "agent_c"]] = Field(
        default_factory=lambda: ["agent_a", "agent_b", "agent_c"]
    )

    @field_validator("participants")
    @classmethod
    def unique_participants(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value)) or ["agent_a", "agent_b", "agent_c"]


class RoundCloseout(BaseModel):
    observation: str = Field(min_length=1, max_length=8_000)
    surprise: str = Field(default="", max_length=4_000)
    contradiction: str = Field(default="", max_length=4_000)
    human_report: str = Field(default="", max_length=4_000)
    disposition: Literal["continued", "held", "retired"]


class RefoldRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    inquiry: str = Field(min_length=1, max_length=12_000)
