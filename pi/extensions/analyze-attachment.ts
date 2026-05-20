/**
 * `analyzeAttachment` typed pi tool.
 *
 * Pattern: an isolated multimodal sub-call inside execute(). The raw file
 * bytes never enter the main agent's context — they're fetched from the
 * file service, sent in the body of a single OpenAI vision call, and only
 * the parsed `{ dataPoints, interpretation }` summary is returned to the
 * main agent as the tool's `content`.
 *
 * Required env:
 *   FILE_SERVICE_BASE_URL  e.g. https://file-service.example.com/
 *   OPENAI_API_KEY
 * Optional env:
 *   OPENAI_BASE_URL        default https://eu.api.openai.com/v1
 *   OPENAI_VISION_MODEL    default gpt-5.4o
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";

const FILE_SERVICE_BASE_URL = (process.env.FILE_SERVICE_BASE_URL ?? "").replace(/\/$/, "");
const OPENAI_API_KEY = process.env.OPENAI_API_KEY ?? "";
const OPENAI_BASE_URL = (process.env.OPENAI_BASE_URL ?? "https://eu.api.openai.com/v1").replace(/\/$/, "");
const OPENAI_VISION_MODEL = process.env.OPENAI_VISION_MODEL ?? "gpt-5.4o";

const MAX_FILES_PER_CALL = 5;
const MAX_FILE_BYTES = 10 * 1024 * 1024;

interface DataPoint {
  label: string;
  value: string;
}

interface AnalysisResult {
  filename: string;
  mimeType: string;
  dataPoints: DataPoint[];
  interpretation: string;
  error?: string;
}

export default function (pi: ExtensionAPI) {
  if (!FILE_SERVICE_BASE_URL || !OPENAI_API_KEY) {
    console.warn(
      "[analyzeAttachment] FILE_SERVICE_BASE_URL or OPENAI_API_KEY not set; tool disabled",
    );
    return;
  }

  pi.registerTool({
    name: "analyzeAttachment",
    label: "Analyze attachment",
    description:
      "Fetch one or more case attachments (image, currently images only) and extract structured data points + a short interpretation via a vision-capable sub-model. The raw file bytes never enter your context — you only receive the extracted findings.",
    parameters: Type.Object({
      attachments: Type.Array(
        Type.Object({
          filename: Type.String({
            description: "Storage filename, from snapshot.attachments[].filename",
          }),
          domain: Type.String({
            description: "Case domain, from snapshot.system.domain (e.g. 'rr')",
          }),
          storage_type: Type.String({
            description: "From snapshot.attachments[].storage_type",
          }),
          content_type: Type.Optional(
            Type.String({
              description: "MIME type, e.g. image/png. Used as a hint; the server's content-type wins.",
            }),
          ),
        }),
        { minItems: 1, maxItems: MAX_FILES_PER_CALL },
      ),
      instruction: Type.Optional(
        Type.String({
          description:
            "Free-text guidance for the sub-model, e.g. 'look for £150 charges, dates, and reference numbers'",
        }),
      ),
    }),
    async execute(_toolCallId, params) {
      const { attachments, instruction } = params;
      const analyses = await Promise.all(
        attachments.map((att) => analyzeOne(att, instruction)),
      );
      return {
        content: [{ type: "text", text: summarize(analyses) }],
        details: { analyses },
      };
    },
  });
}

async function analyzeOne(
  att: { filename: string; domain: string; storage_type: string; content_type?: string },
  instruction: string | undefined,
): Promise<AnalysisResult> {
  try {
    const { bytes, mime } = await fetchFile(att);
    if (bytes.byteLength > MAX_FILE_BYTES) {
      return errorResult(att.filename, mime, `file exceeds ${MAX_FILE_BYTES} bytes`);
    }
    if (!mime.startsWith("image/")) {
      return errorResult(
        att.filename,
        mime,
        `unsupported MIME type ${mime} — only images are supported in v1`,
      );
    }
    const result = await callVisionModel(bytes, mime, att.filename, instruction);
    return { filename: att.filename, mimeType: mime, ...result };
  } catch (e: any) {
    return errorResult(att.filename, att.content_type ?? "unknown", e?.message ?? String(e));
  }
}

async function fetchFile(att: {
  filename: string;
  domain: string;
  storage_type: string;
  content_type?: string;
}): Promise<{ bytes: Uint8Array; mime: string }> {
  const url = `${FILE_SERVICE_BASE_URL}/${encodeURIComponent(att.domain)}/files/${encodeURIComponent(att.storage_type)}/${encodeURIComponent(att.filename)}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`file service ${res.status} for ${url}`);
  const mime = res.headers.get("content-type") ?? att.content_type ?? "application/octet-stream";
  const bytes = new Uint8Array(await res.arrayBuffer());
  return { bytes, mime };
}

async function callVisionModel(
  bytes: Uint8Array,
  mime: string,
  filename: string,
  instruction: string | undefined,
): Promise<{ dataPoints: DataPoint[]; interpretation: string }> {
  const base64 = Buffer.from(bytes).toString("base64");
  const dataUrl = `data:${mime};base64,${base64}`;

  const systemPrompt =
    "You analyze a single document image. Extract concrete data points (label/value pairs of facts visible in the image: dates, amounts, references, names) and a 1-2 sentence interpretation describing what the document is. Be precise — only include facts you can read from the image.";
  const userText = [
    `Filename: ${filename}`,
    instruction ? `Instruction: ${instruction}` : null,
    "Return JSON matching the provided schema.",
  ]
    .filter(Boolean)
    .join("\n");

  const body = {
    model: OPENAI_VISION_MODEL,
    messages: [
      { role: "system", content: systemPrompt },
      {
        role: "user",
        content: [
          { type: "text", text: userText },
          { type: "image_url", image_url: { url: dataUrl } },
        ],
      },
    ],
    response_format: {
      type: "json_schema",
      json_schema: {
        name: "AttachmentAnalysis",
        strict: true,
        schema: {
          type: "object",
          properties: {
            dataPoints: {
              type: "array",
              items: {
                type: "object",
                properties: {
                  label: { type: "string" },
                  value: { type: "string" },
                },
                required: ["label", "value"],
                additionalProperties: false,
              },
            },
            interpretation: { type: "string" },
          },
          required: ["dataPoints", "interpretation"],
          additionalProperties: false,
        },
      },
    },
  };

  const res = await fetch(`${OPENAI_BASE_URL}/chat/completions`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${OPENAI_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`openai ${res.status}: ${txt.slice(0, 300)}`);
  }
  const data = (await res.json()) as any;
  const content = data?.choices?.[0]?.message?.content ?? "{}";
  const parsed = JSON.parse(content) as { dataPoints: DataPoint[]; interpretation: string };
  return parsed;
}

function errorResult(filename: string, mime: string, error: string): AnalysisResult {
  return { filename, mimeType: mime, dataPoints: [], interpretation: "", error };
}

function summarize(analyses: AnalysisResult[]): string {
  return analyses
    .map((a) => {
      if (a.error) return `## ${a.filename}\n[ERROR] ${a.error}`;
      const dps =
        a.dataPoints.length === 0
          ? "(none)"
          : a.dataPoints.map((dp) => `- ${dp.label}: ${dp.value}`).join("\n");
      return `## ${a.filename}\n${a.interpretation}\n\nData points:\n${dps}`;
    })
    .join("\n\n---\n\n");
}
