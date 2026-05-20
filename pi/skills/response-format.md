---
name: response-format
description: The exact JSON shape your FINAL assistant message must take for /investigateCase. Read this before answering — the harness parses your output strictly.
---

# response-format — /investigateCase patch payload

Your FINAL assistant message must be a single JSON object, with **no prose
before or after, and no markdown fences**, matching this exact shape:

```json
{
  "action_proposals": [
    {
      "type": "SEND_REPLY",
      "body": "string (required for SEND_REPLY; omit for RESOLVE_CASE)",
      "reasoning": "short why-this-action",
      "approval_mode": "REVIEW"
    }
  ],
  "reasoning": "concise human-readable summary of what you investigated and concluded"
}
```

## Field rules

- `type` — `"SEND_REPLY"` or `"RESOLVE_CASE"`. Pick one per proposal.
- `body` — required when `type` is `"SEND_REPLY"`; the customer-facing reply.
  Plain text. Omit for `RESOLVE_CASE`.
- `reasoning` (per proposal) — one or two sentences explaining why this
  action is the right next step, grounded in evidence you retrieved.
- `approval_mode` — one of `"AUTO"`, `"REVIEW"`, `"AMEND"`. Default to
  `"REVIEW"` unless you are highly confident the message is ready to send.
- top-level `reasoning` — a concise summary of what you investigated
  (queries you ran, what they returned) and what you concluded.

## Hard requirements

- Output MUST be valid JSON — `json.loads` must accept it.
- Do NOT wrap in ```` ```json ```` fences.
- Do NOT add any explanatory text outside the JSON object.
- `action_proposals` is a list; usually one entry is correct.
