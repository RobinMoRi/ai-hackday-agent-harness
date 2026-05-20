import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Langfuse } from "langfuse";
import { randomUUID } from "node:crypto";

export default function (pi: ExtensionAPI) {
  const publicKey = process.env.LANGFUSE_PUBLIC_KEY;
  const secretKey = process.env.LANGFUSE_SECRET_KEY;
  if (!publicKey || !secretKey) {
    console.warn("[langfuse] LANGFUSE_PUBLIC_KEY/SECRET_KEY not set; extension disabled");
    return;
  }

  const lf = new Langfuse({
    publicKey,
    secretKey,
    baseUrl: process.env.LANGFUSE_HOST ?? "https://cloud.langfuse.com",
  });

  const sessionId = randomUUID();
  let trace: ReturnType<typeof lf.trace> | undefined;
  let turnSpan: ReturnType<NonNullable<typeof trace>["span"]> | undefined;
  let currentGeneration: ReturnType<NonNullable<typeof trace>["generation"]> | undefined;
  const toolSpans = new Map<string, ReturnType<NonNullable<typeof trace>["span"]>>();

  pi.on("session_start", async (event: any, ctx: any) => {
    trace = lf.trace({
      name: pi.getSessionName?.() ?? "pi-session",
      sessionId,
      userId: process.env.USER,
      metadata: { reason: event.reason, cwd: ctx.cwd },
    });
  });

  pi.on("before_agent_start", async (event: any) => {
    if (!trace) return;
    turnSpan = trace.span({
      name: "agent-turn",
      input: { prompt: event.prompt, images: event.images?.length ?? 0 },
    });
  });

  pi.on("before_provider_request", (event: any) => {
    if (!trace) return;
    const parent = turnSpan ?? trace;
    const payload = event.payload ?? {};
    currentGeneration = parent.generation({
      name: "llm-call",
      model: payload.model,
      input: payload.messages ?? payload.input ?? payload,
      modelParameters: {
        temperature: payload.temperature,
        max_tokens: payload.max_tokens,
        top_p: payload.top_p,
      },
    });
  });

  pi.on("after_provider_response", (event: any) => {
    if (!currentGeneration) return;
    if (typeof event.status === "number" && event.status >= 400) {
      currentGeneration.update({
        level: "ERROR",
        statusMessage: `HTTP ${event.status}`,
      });
    }
  });

  pi.on("message_end", async (event: any) => {
    if (!currentGeneration) return;
    const msg: any = event.message;
    if (msg?.role !== "assistant") return;
    const usage = msg.usage ?? msg.metadata?.usage;
    currentGeneration.end({
      output: msg.content,
      usage: usage && {
        input: usage.input_tokens ?? usage.prompt_tokens,
        output: usage.output_tokens ?? usage.completion_tokens,
        total: usage.total_tokens,
      },
    });
    currentGeneration = undefined;
  });

  pi.on("tool_execution_start", async (event: any) => {
    if (!turnSpan) return;
    const span = turnSpan.span({
      name: `tool:${event.toolName}`,
      input: event.args,
    });
    toolSpans.set(event.toolCallId, span);
  });

  pi.on("tool_execution_end", async (event: any) => {
    const span = toolSpans.get(event.toolCallId);
    if (!span) return;
    span.end({
      output: event.result,
      level: event.isError ? "ERROR" : undefined,
    });
    toolSpans.delete(event.toolCallId);
  });

  pi.on("agent_end", async () => {
    turnSpan?.end();
    turnSpan = undefined;
  });

  pi.on("session_shutdown", async () => {
    try {
      await lf.shutdownAsync();
    } catch (err) {
      console.warn("[langfuse] shutdown failed:", err);
    }
  });
}
