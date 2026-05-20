"""Prompt construction for /investigateCase.

Per-request user message is just the snapshot. All standing instructions
(agent role, skill usage rules, investigation guidelines, output contract
pointer) live in /workspace/AGENTS.md, which pi auto-discovers and merges
into the system prompt.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.schema.case_snapshot import CaseSnapshot


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
        "domain": snapshot.system.domain,
        "activities": activities,
        "case_metadata": snapshot.case_metadata.model_dump(
            by_alias=False, exclude_none=True
        ),
        "classifications": (
            snapshot.classifications.model_dump(by_alias=False, exclude_none=True)
            if snapshot.classifications
            else None
        ),
        "attachments": [
            a.model_dump(by_alias=False, exclude_none=True)
            for a in snapshot.attachments
        ],
    }
    return json.dumps(payload, indent=2, default=str)


def build_prompt(snapshot: CaseSnapshot) -> str:
    return f"### CASE SNAPSHOT \n\n{render_snapshot(snapshot)}"
