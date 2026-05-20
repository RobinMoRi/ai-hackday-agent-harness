/**
 * Langfuse v5 (OTel) tracing extension for pi.
 *
 * Maps pi events to first-class Langfuse observation kinds so the trace
 * tree reflects the real shape of an agent run:
 *
 *   span(pi-session)
 *     └── agent(/invoke run)
 *           └── span(turn N)
 *                 ├── generation(LLM call)
 *                 └── tool(<toolName>)
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { LangfuseSpanProcessor } from "@langfuse/otel";
import {
  startObservation,
  type LangfuseAgent,
  type LangfuseGeneration,
  type LangfuseSpan,
  type LangfuseTool,
} from "@langfuse/tracing";
import { NodeSDK } from "@opentelemetry/sdk-node";

export default function (pi: ExtensionAPI) {
  const publicKey = process.env.LANGFUSE_PUBLIC_KEY;
  const secretKey = process.env.LANGFUSE_SECRET_KEY;
  if (!publicKey || !secretKey) {
    console.warn("[langfuse] LANGFUSE_PUBLIC_KEY/SECRET_KEY not set; extension disabled");
    return;
  }

  const sdk = new NodeSDK({
    spanProcessors: [
      new LangfuseSpanProcessor({
        publicKey,
        secretKey,
        baseUrl: process.env.LANGFUSE_HOST ?? "https://cloud.langfuse.com",
      }),
    ],
  });
  sdk.start();

  let sessionSpan: LangfuseSpan | undefined;
  let agentObs: LangfuseAgent | undefined;
  let turnSpan: LangfuseSpan | undefined;
  let currentGen: LangfuseGeneration | undefined;
  const toolByCallId = new Map<string, LangfuseTool>();
  let turnIdx = 0;

  const parentForLLM = (): LangfuseSpan | LangfuseAgent | undefined => turnSpan ?? agentObs ?? sessionSpan;

  pi.on("session_start", (event: any, ctx: any) => {
    sessionSpan = startObservation(
      "pi-session",
      { input: { reason: event?.reason, cwd: ctx?.cwd } },
      { asType: "span" },
    );
  });

  pi.on("before_agent_start", (event: any) => {
    if (!sessionSpan) return;
    turnIdx = 0;
    agentObs = sessionSpan.startObservation(
      "agent",
      { input: { prompt: event?.prompt, images: event?.images?.length ?? 0 } },
      { asType: "agent" },
    ) as LangfuseAgent;
  });

  pi.on("turn_start", (_event: any) => {
    if (!agentObs) return;
    turnIdx += 1;
    turnSpan = agentObs.startObservation(
      `turn-${turnIdx}`,
      {},
      { asType: "span" },
    ) as LangfuseSpan;
  });

  pi.on("before_provider_request", (event: any) => {
    const parent = parentForLLM();
    if (!parent) return;
    const payload = event?.payload ?? {};
    currentGen = parent.startObservation(
      "llm-call",
      {
        input: payload.messages ?? payload.input ?? payload,
        model: payload.model,
        modelParameters: {
          temperature: payload.temperature,
          max_tokens: payload.max_tokens,
          top_p: payload.top_p,
        },
      },
      { asType: "generation" },
    ) as LangfuseGeneration;
  });

  pi.on("message_end", (event: any) => {
    if (!currentGen) return;
    const msg: any = event?.message;
    if (msg?.role !== "assistant") return;
    const usage = msg.usage ?? msg.metadata?.usage;
    currentGen.update({
      output: msg.content,
      ...(usage && {
        usageDetails: {
          input: usage.input_tokens ?? usage.prompt_tokens,
          output: usage.output_tokens ?? usage.completion_tokens,
          total: usage.total_tokens,
        },
      }),
    });
    currentGen.end();
    currentGen = undefined;
  });

  pi.on("tool_execution_start", (event: any) => {
    const parent = turnSpan ?? agentObs;
    if (!parent) return;
    const tool = parent.startObservation(
      event?.toolName ?? "tool",
      { input: event?.args },
      { asType: "tool" },
    ) as LangfuseTool;
    if (event?.toolCallId) toolByCallId.set(event.toolCallId, tool);
  });

  pi.on("tool_execution_end", (event: any) => {
    const id = event?.toolCallId;
    const tool = id ? toolByCallId.get(id) : undefined;
    if (!tool) return;
    tool.update({
      output: event?.result?.content,
      ...(event?.isError && { level: "ERROR" as const }),
    });
    tool.end();
    if (id) toolByCallId.delete(id);
  });

  pi.on("turn_end", (_event: any) => {
    turnSpan?.end();
    turnSpan = undefined;
  });

  pi.on("agent_end", (event: any) => {
    agentObs?.update({ output: event?.output });
    agentObs?.end();
    agentObs = undefined;
  });

  pi.on("session_shutdown", async () => {
    sessionSpan?.end();
    sessionSpan = undefined;
    try {
      await sdk.shutdown();
    } catch (e) {
      console.warn("[langfuse] sdk shutdown failed:", e);
    }
  });
}
