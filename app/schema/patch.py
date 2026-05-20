"""Flat minimal InvestigatePatch output schema (hackday MVP).

Not a faithful port of ai-case-service's InvestigateCasePatch; just enough
to express the agent's verdict. See plan for the deferred fields.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from app.schema.case_snapshot import ALIAS_GENERATOR_CONFIG


class ActionType(StrEnum):
    SEND_REPLY = "SEND_REPLY"
    RESOLVE_CASE = "RESOLVE_CASE"


class ApprovalMode(StrEnum):
    AUTO = "AUTO"
    REVIEW = "REVIEW"
    AMEND = "AMEND"


class ActionProposal(BaseModel):
    model_config = ALIAS_GENERATOR_CONFIG

    type: ActionType
    body: str | None = None
    reasoning: str
    approval_mode: ApprovalMode = ApprovalMode.REVIEW


class InvestigatePatch(BaseModel):
    model_config = ALIAS_GENERATOR_CONFIG

    action_proposals: list[ActionProposal]
    reasoning: str
