"""Prompt construction for /investigateCase.

Single-stage MVP: one Solution-style instruction set, snapshot rendered
inline as JSON. The agent has bash + the GraphQL skill markdown; it
decides whether and how to query.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.schema.case_snapshot import CaseSnapshot

SYSTEM_INSTRUCTIONS = """\
You are a case investigation agent. You receive a CaseSnapshot and must decide
what action to propose: either reply to the customer (SEND_REPLY with a body)
or close the case (RESOLVE_CASE).

You have access to:
- bash (use `curl` for HTTP / GraphQL calls)
- a GraphQL data source documented in the loaded skill file (`graphql`). Read it
  before querying. Use only the env vars and queries it documents.

Investigation guidelines:
- Read the case activities to understand the customer's intent.
- If the case requires data from the GraphQL source to answer, query it.
- Ground your draft reply in evidence you actually retrieved; do not invent facts.
- If you cannot find sufficient evidence, prefer a partial answer or a
  clarifying question over hallucinating.

Output contract: your FINAL assistant message must be a single JSON object,
with no prose, no markdown fences, matching this exact shape:

{
  "action_proposals": [
    {
      "type": "SEND_REPLY" | "RESOLVE_CASE",
      "body": "string or null (required for SEND_REPLY)",
      "reasoning": "short why-this-action",
      "approval_mode": "AUTO" | "REVIEW" | "AMEND"
    }
  ],
  "reasoning": "concise human-readable summary of what you investigated and concluded"
}

Default approval_mode to REVIEW unless you are highly confident.
"""


def _ms_to_iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def render_snapshot(snapshot: CaseSnapshot) -> str:
    """Render the snapshot as compact JSON with ms timestamps converted to ISO.

    Trims to fields the agent reasons over: activities, case_metadata,
    classifications, attachments. Drops system/state/events to reduce tokens.
    """
    activities = []
    for a in snapshot.activities:
        d = a.model_dump(by_alias=False, exclude_none=True)
        meta = d.get("metadata", {})
        if "created_at" in meta:
            meta["created_at"] = _ms_to_iso(meta["created_at"])
        if meta.get("updated_at") is not None:
            meta["updated_at"] = _ms_to_iso(meta["updated_at"])
        activities.append(d)

    payload = {
        "activities": activities,
        "case_metadata": snapshot.case_metadata.model_dump(by_alias=False, exclude_none=True),
        "classifications": (
            snapshot.classifications.model_dump(by_alias=False, exclude_none=True)
            if snapshot.classifications
            else None
        ),
        "attachments": [
            a.model_dump(by_alias=False, exclude_none=True) for a in snapshot.attachments
        ],
    }
    return json.dumps(payload, indent=2, default=str)


def build_prompt(snapshot: CaseSnapshot) -> str:
    return f"{SYSTEM_INSTRUCTIONS}\n\n--- CASE SNAPSHOT ---\n{render_snapshot(snapshot)}"
