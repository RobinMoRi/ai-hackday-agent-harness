/**
 * Langfuse v5 (OTel) tracing extension for pi.
 *
 * Maps pi events to first-class Langfuse observation kinds so the trace
 * tree reflects the real shape of an agent run:
 *
 *   span(pi-session)            input=prompt, output=final assistant text
 *     └── agent(/invoke run)
 *           └── chain(turn)
 *                 ├── generation(LLM call)
 *                 └── tool(<semantic label>)
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
  let lastAssistantContent: unknown = undefined;

  const parentForLLM = (): LangfuseSpan | LangfuseAgent | undefined => turnSpan ?? agentObs ?? sessionSpan;

  pi.on("session_start", (_event: any, _ctx: any) => {
    sessionSpan = startObservation("pi-session", {}, { asType: "span" });
  });

  pi.on("before_agent_start", (event: any) => {
    if (!sessionSpan) return;
    const prompt = event?.prompt;
    sessionSpan.update({ input: prompt });
    agentObs = sessionSpan.startObservation(
      "agent",
      { input: prompt },
      { asType: "agent" },
    ) as LangfuseAgent;
  });

  pi.on("turn_start", (_event: any) => {
    if (!agentObs) return;
    turnSpan = agentObs.startObservation(
      "turn",
      {},
      { asType: "chain" },
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
    lastAssistantContent = extractText(msg.content);
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
      describeToolCall(event),
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
    const output = event?.output ?? event?.finalText ?? event?.message ?? lastAssistantContent;
    agentObs?.update({ output });
    agentObs?.end();
    agentObs = undefined;
    sessionSpan?.update({ output });
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

/**
 * Derive a more meaningful observation name than the raw `toolName`.
 *
 * Pi's `bash` tool is a catch-all — calling out "graphql" when the command
 * hits the Fabric endpoint, or showing the leading command word otherwise,
 * makes the trace tree much more readable.
 */
/**
 * Pi's assistant message content is an array of typed blocks
 * (`thinking`, `text`, …). For trace I/O we only want the human-readable
 * final answer, so concatenate the `text` blocks.
 */
function extractText(content: unknown): unknown {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    const parts: string[] = [];
    for (const c of content) {
      if (c && typeof c === "object" && (c as any).type === "text" && typeof (c as any).text === "string") {
        parts.push((c as any).text);
      }
    }
    if (parts.length) return parts.join("");
  }
  return content;
}

function describeToolCall(event: any): string {
  const name = String(event?.toolName ?? "tool");
  const args = event?.args;
  if (name === "bash" && args && typeof args === "object") {
    const cmd: unknown = args.command ?? args.cmd ?? args.script;
    if (typeof cmd === "string") {
      const trimmed = cmd.trim();
      if (/graphql/i.test(trimmed) || /fabric\.microsoft/i.test(trimmed)) return "graphql";
      if (/login\.microsoftonline\.com.*oauth2.*token/i.test(trimmed)) return "fabric:auth";
      const firstWord = trimmed.split(/\s+/)[0]?.replace(/^\W+/, "") || "bash";
      return `bash:${firstWord}`;
    }
  }
  return name;
}
