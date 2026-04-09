"""Pydantic schemas for rules APIs."""

from typing import Any

from pydantic import BaseModel, Field


class RuleItem(BaseModel):
    id: str
    enabled: bool
    order: int
    priority: Any = None


class RulesPayload(BaseModel):
    rules: list[RuleItem] = Field(default_factory=list)


class RulesResponse(RulesPayload):
    pass
