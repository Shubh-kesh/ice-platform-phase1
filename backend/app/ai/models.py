"""Pydantic schemas for the ICE Copilot (AI-1).

Structured output is used only where it adds product value: `CopilotInsight`
is an OPTIONAL reply shape for insight-style answers (rendered as a card by
the future UI). Ordinary conversational replies stay free-form — structured
output is never forced onto every turn.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CopilotInsight(BaseModel):
    """A tool-grounded project insight the assistant may emit (optional).

    Always derived from tool results; `recommended_actions` are suggestions
    only — the ICE Copilot never mutates data.
    """

    summary: str = Field(description="One or two sentences, grounded in tool results.")
    severity: Literal["info", "ok", "watch", "attention", "critical"] | None = Field(
        default=None,
        description="Optional severity label for the insight card.",
    )
    findings: list[str] = Field(
        default_factory=list,
        description="Tool-backed points supporting the summary.",
    )
    recommended_actions: list[str] = Field(
        default_factory=list,
        description="Suggested next steps (read-only; never auto-executed).",
    )
