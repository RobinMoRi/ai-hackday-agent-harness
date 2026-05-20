import json
import re

from fastapi import FastAPI, HTTPException

from app.prompt import build_prompt
from app.schema.case_snapshot import CaseSnapshot
from app.schema.patch import InvestigatePatch
from pi_harness import run_pi

app = FastAPI(title="pi-agent-harness")

SKILL_PATH = "/workspace/pi/skills/graphql.md"
TIMEOUT_S = 240.0


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.post("/investigateCase", response_model=InvestigatePatch)
async def investigate_case(snapshot: CaseSnapshot) -> InvestigatePatch:
    result = await run_pi(
        prompt=build_prompt(snapshot),
        cwd="/workspace",
        timeout=TIMEOUT_S,
        extra_args=["--skill", SKILL_PATH],
    )

    if result.status != "ok":
        raise HTTPException(
            status_code=502,
            detail={
                "status": result.status,
                "error": result.error,
                "final_text": result.final_text,
            },
        )

    try:
        return InvestigatePatch.model_validate_json(_extract_json(result.final_text))
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail={
                "error": f"agent output did not parse as InvestigatePatch: {e}",
                "final_text": result.final_text,
            },
        )


_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)


def _extract_json(text: str) -> str:
    """Strip optional ```json fences; return raw JSON candidate."""
    text = text.strip()
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    return text
