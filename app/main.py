from dataclasses import asdict

from fastapi import FastAPI
from pydantic import BaseModel, Field

from pi_harness import run_pi

app = FastAPI(title="pi-agent-harness")


class InvokeRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    cwd: str | None = None
    model: str | None = None
    provider: str | None = None
    timeout_ms: int = Field(default=120_000, ge=1_000, le=600_000)


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.post("/invoke")
async def invoke(req: InvokeRequest) -> dict:
    result = await run_pi(
        prompt=req.prompt,
        cwd=req.cwd or "/workspace",
        model=req.model,
        provider=req.provider,
        timeout=req.timeout_ms / 1000.0,
    )
    return asdict(result)
