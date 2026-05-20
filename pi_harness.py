"""Thin Python wrapper around `pi --mode rpc`.

Spawns one pi subprocess per session, talks JSONL over stdin/stdout,
returns a structured result when the agent settles.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Optional


@dataclass
class ToolCall:
    name: str
    args: Any
    ok: bool
    duration_ms: int
    summary: Optional[str] = None


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass
class InvokeResult:
    session_id: str
    status: Literal["ok", "error", "timeout", "aborted"]
    final_text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Optional[Usage] = None
    duration_ms: int = 0
    error: Optional[str] = None


class PiSession:
    """One `pi --mode rpc` subprocess for its lifetime.

    Caller owns config: cwd, agent_dir, model, tools, etc.
    """

    def __init__(
        self,
        *,
        cwd: str,
        agent_dir: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        no_session: bool = True,
        extra_args: Optional[list[str]] = None,
        pi_path: str = "pi",
    ):
        self._cwd = cwd
        self._pi_path = pi_path
        self._args = self._build_args(agent_dir, model, provider, no_session, extra_args)
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._pending: dict[str, asyncio.Future[dict]] = {}
        self._current: Optional[_RunCollector] = None
        self._stderr_buf: list[str] = []

    @staticmethod
    def _build_args(agent_dir, model, provider, no_session, extra) -> list[str]:
        args = ["--mode", "rpc"]
        if no_session:
            args.append("--no-session")
        if agent_dir:
            args += ["--agent-dir", agent_dir]
        if provider:
            args += ["--provider", provider]
        if model:
            args += ["--model", model]
        if extra:
            args += extra
        return args

    async def __aenter__(self) -> "PiSession":
        self._proc = await asyncio.create_subprocess_exec(
            self._pi_path, *self._args,
            cwd=self._cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
        )
        self._reader_task = asyncio.create_task(self._reader_loop())
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self._proc.kill()
                except ProcessLookupError:
                    pass
        for t in (self._reader_task, self._stderr_task):
            if t and not t.done():
                t.cancel()

    async def prompt(self, message: str, *, timeout: float = 120.0) -> InvokeResult:
        """Send a prompt and wait for the agent to settle."""
        if self._current is not None:
            raise RuntimeError("a prompt is already in progress on this session")

        collector = _RunCollector()
        self._current = collector
        try:
            ack = await self._send({"type": "prompt", "message": message})
            if not ack.get("success"):
                return InvokeResult(
                    session_id="",
                    status="error",
                    final_text="",
                    error=ack.get("error", "prompt rejected"),
                )
            try:
                await asyncio.wait_for(collector.done.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                await self._send_nowait({"type": "abort"})
                collector.status = "timeout"
            return collector.finalize()
        finally:
            self._current = None

    async def abort(self) -> None:
        await self._send_nowait({"type": "abort"})

    @property
    def stderr(self) -> str:
        return "".join(self._stderr_buf)

    async def _send(self, cmd: dict) -> dict:
        cmd_id = str(uuid.uuid4())
        cmd["id"] = cmd_id
        fut: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        self._pending[cmd_id] = fut
        await self._write_line(cmd)
        try:
            return await fut
        finally:
            self._pending.pop(cmd_id, None)

    async def _send_nowait(self, cmd: dict) -> None:
        await self._write_line(cmd)

    async def _write_line(self, obj: dict) -> None:
        assert self._proc and self._proc.stdin
        self._proc.stdin.write((json.dumps(obj) + "\n").encode())
        await self._proc.stdin.drain()

    async def _reader_loop(self) -> None:
        """Strict JSONL framing per pi RPC docs: split on \\n only."""
        assert self._proc and self._proc.stdout
        buf = bytearray()
        while True:
            chunk = await self._proc.stdout.read(4096)
            if not chunk:
                break
            buf.extend(chunk)
            while True:
                nl = buf.find(b"\n")
                if nl < 0:
                    break
                raw = bytes(buf[:nl])
                del buf[:nl + 1]
                if raw.endswith(b"\r"):
                    raw = raw[:-1]
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                self._dispatch(msg)

    async def _drain_stderr(self) -> None:
        assert self._proc and self._proc.stderr
        while True:
            chunk = await self._proc.stderr.read(4096)
            if not chunk:
                break
            self._stderr_buf.append(chunk.decode(errors="replace"))

    def _dispatch(self, msg: dict) -> None:
        if msg.get("type") == "response":
            fut = self._pending.get(msg.get("id"))
            if fut and not fut.done():
                fut.set_result(msg)
            return
        if msg.get("type") == "session":
            if self._current is not None:
                self._current.on_session(msg)
            return
        if self._current is not None:
            self._current.on_event(msg)


class _RunCollector:
    """Accumulates events from agent_start..agent_end into an InvokeResult."""

    def __init__(self):
        self.done = asyncio.Event()
        self.status: Literal["ok", "error", "timeout", "aborted"] = "ok"
        self._tool_starts: dict[str, dict] = {}
        self._tool_calls: list[ToolCall] = []
        self._final_text: str = ""
        self._usage: Optional[Usage] = None
        self._session_id: str = ""
        self._t0_ms: int = _now_ms()
        self._duration_ms: int = 0
        self._error: Optional[str] = None

    def on_session(self, ev: dict) -> None:
        self._session_id = ev.get("id", "")

    def on_event(self, ev: dict) -> None:
        t = ev.get("type")

        if t == "tool_execution_start":
            self._tool_starts[ev["toolCallId"]] = {
                "name": ev.get("toolName"),
                "args": ev.get("args"),
                "t0": _now_ms(),
            }

        elif t == "tool_execution_end":
            start = self._tool_starts.pop(ev.get("toolCallId"), {})
            text = _extract_text(ev.get("result", {}).get("content"))[:500] or None
            self._tool_calls.append(ToolCall(
                name=start.get("name") or ev.get("toolName", "?"),
                args=start.get("args"),
                ok=not ev.get("isError", False),
                duration_ms=_now_ms() - start.get("t0", _now_ms()),
                summary=text,
            ))

        elif t == "message_end":
            msg = ev.get("message", {})
            if msg.get("role") == "assistant":
                text = _extract_text(msg.get("content"))
                if text:
                    self._final_text = text
                u = msg.get("usage")
                if u:
                    self._usage = Usage(
                        input_tokens=u.get("input", u.get("input_tokens", 0)),
                        output_tokens=u.get("output", u.get("output_tokens", 0)),
                    )

        elif t == "agent_end":
            self._duration_ms = _now_ms() - self._t0_ms
            self.done.set()

        elif t == "extension_error":
            self._error = self._error or ev.get("error")

    def finalize(self) -> InvokeResult:
        if not self.done.is_set():
            self._duration_ms = _now_ms() - self._t0_ms
        return InvokeResult(
            session_id=self._session_id,
            status=self.status,
            final_text=self._final_text,
            tool_calls=self._tool_calls,
            usage=self._usage,
            duration_ms=self._duration_ms,
            error=self._error,
        )


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                parts.append(c.get("text", ""))
        return "".join(parts)
    return ""


def _now_ms() -> int:
    return int(time.monotonic() * 1000)


async def run_pi(
    *,
    prompt: str,
    cwd: str = "/workspace",
    timeout: float = 120.0,
    **session_kwargs,
) -> InvokeResult:
    """One-shot helper: spawn a session, run one prompt, dispose."""
    async with PiSession(cwd=cwd, **session_kwargs) as s:
        return await s.prompt(prompt, timeout=timeout)
