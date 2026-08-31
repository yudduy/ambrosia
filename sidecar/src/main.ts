import {
  getOAuthApiKey,
  refreshOAuthToken,
  streamSimple,
  type AssistantMessage,
  type Context,
  type OAuthCredentials,
  type Tool,
  type ToolCall,
} from "@oh-my-pi/pi-ai";
import { loginOpenAICodex } from "@oh-my-pi/pi-ai/oauth/openai-codex";
import { getBundledModel } from "@oh-my-pi/pi-catalog/models";
import { Effort } from "@oh-my-pi/pi-catalog/effort";
import { DEFAULT_MODEL_PER_PROVIDER } from "@oh-my-pi/pi-catalog/provider-models";
import { createInterface } from "node:readline";
import { chmod, mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, join, resolve, sep } from "node:path";

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
type Request = { id: number; method: string; params?: Record<string, unknown> };

const runtimeHome = resolve(process.env.AMBROSIA_HOME || join(process.env.HOME || ".", ".ambrosia"));
const ompHome = join(runtimeHome, "omp");
const uploadRoot = resolve(runtimeHome, "uploads");
const credentialPath = join(ompHome, "credentials.json");
const threadDir = join(ompHome, "threads");
const apiRoot = process.env.AMBROSIA_API_URL || "http://127.0.0.1:8787/api";
const provider = "openai-codex" as const;
const defaultModelId = DEFAULT_MODEL_PER_PROVIDER[provider];
const model = getBundledModel(provider, defaultModelId);
const contexts = new Map<string, Context>();
const abortControllers = new Map<string, AbortController>();
let loginTask: Promise<OAuthCredentials> | undefined;

const safetyContext = `You are Ambrosia, a private personal health coach. Use only the bounded
health tools declared in this conversation and user-provided text or meal images. Describe patterns
and uncertainty; do not diagnose, prescribe treatment, recommend medication changes, or claim
causation. Ask no more than three short questions when essential context is missing. Never write
health data or profile changes. Propose profile facts only as explicit 'Remember this' confirmations.`;

const tools: Tool[] = [
  tool("get_health_overview", "Get the seven-day overview and personal baseline.", {
    type: "object", properties: { as_of: { type: "string" } }, additionalProperties: false,
  }),
  tool("get_domain_summary", "Get bounded daily aggregates for one dashboard domain.", {
    type: "object",
    properties: {
      domain: { type: "string", enum: ["fitness", "sleep", "nutrition"] },
      range_name: { type: "string", enum: ["7d", "28d", "90d"], default: "28d" },
    },
    required: ["domain"], additionalProperties: false,
  }),
  tool("compare_periods", "Compare one metric with the preceding 28 valid days.", {
    type: "object",
    properties: { metric: { type: "string" }, as_of: { type: "string" } },
    required: ["metric"], additionalProperties: false,
  }),
  tool("analyze_relationship", "Get one predeclared exploratory relationship.", {
    type: "object", properties: { relationship: { type: "string" } },
    required: ["relationship"], additionalProperties: false,
  }),
  tool("get_profile_and_data_quality", "Get confirmed profile preferences and aggregate coverage.", {
    type: "object", properties: {}, additionalProperties: false,
  }),
];

function tool(name: string, description: string, parameters: Record<string, unknown>): Tool {
  return { name, description, parameters } as Tool;
}

function send(value: unknown): void {
  process.stdout.write(`${JSON.stringify(value)}\n`);
}

function result(id: number, value: unknown): void {
  send({ id, result: value });
}

function failure(id: number, error: unknown): void {
  send({ id, error: { code: -32000, message: error instanceof Error ? error.message : String(error) } });
}

function event(threadId: string, method: string, params: Record<string, unknown>): void {
  send({ method, params: { threadId, ...params } });
}

async function privateJson(path: string, value: unknown): Promise<void> {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = `${path}.part`;
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  await chmod(temporary, 0o600);
  await rename(temporary, path);
}

async function loadCredential(): Promise<OAuthCredentials | undefined> {
  try {
    return JSON.parse(await readFile(credentialPath, "utf8")) as OAuthCredentials;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined;
    throw error;
  }
}

async function activeApiKey(): Promise<string> {
  let credential = await loadCredential();
  if (!credential) throw new Error("Sign in with ChatGPT to use the restricted assistant fallback.");
  if (credential.expires <= Date.now() + 60_000) {
    credential = await refreshOAuthToken(provider, credential);
    await privateJson(credentialPath, credential);
  }
  const resolved = await getOAuthApiKey(provider, { [provider]: credential });
  if (!resolved) throw new Error("The ChatGPT credential is unavailable.");
  if (JSON.stringify(resolved.newCredentials) !== JSON.stringify(credential)) {
    await privateJson(credentialPath, resolved.newCredentials);
  }
  return resolved.apiKey;
}

async function refreshCredential(): Promise<Record<string, unknown>> {
  const credential = await loadCredential();
  if (!credential) throw new Error("No ChatGPT credential is available to refresh.");
  const refreshed = await refreshOAuthToken(provider, credential);
  await privateJson(credentialPath, refreshed);
  await activeApiKey();
  return { refreshed: true };
}

async function status(): Promise<Record<string, unknown>> {
  try {
    await activeApiKey();
    return {
      provider: "omp", running: true, authenticated: true,
      image_capable_model: model.input.includes("image"), model: model.id, reason: null,
    };
  } catch (error) {
    return {
      provider: "omp", running: true, authenticated: false,
      image_capable_model: model.input.includes("image"), model: model.id,
      reason: error instanceof Error ? error.message : String(error),
    };
  }
}

async function startLogin(): Promise<Record<string, unknown>> {
  let revealAuth: (value: Record<string, unknown>) => void;
  const authReady = new Promise<Record<string, unknown>>((resolveAuth) => { revealAuth = resolveAuth; });
  loginTask = loginOpenAICodex({
    originator: "ambrosia",
    onAuth: (info) => revealAuth!({ authUrl: info.launchUrl || info.url }),
  });
  void loginTask.then((credential) => privateJson(credentialPath, credential)).catch((error) => {
    send({ method: "login/failed", params: { message: error instanceof Error ? error.message : String(error) } });
  });
  return await authReady;
}

function threadPath(threadId: string): string {
  return join(threadDir, `${threadId}.json`);
}

async function saveThread(threadId: string, context: Context): Promise<void> {
  await privateJson(threadPath(threadId), context);
}

async function loadThread(threadId: string): Promise<Context> {
  const existing = contexts.get(threadId);
  if (existing) return existing;
  const context = JSON.parse(await readFile(threadPath(threadId), "utf8")) as Context;
  context.tools = tools;
  contexts.set(threadId, context);
  return context;
}

async function createThread(): Promise<string> {
  const threadId = crypto.randomUUID();
  const context: Context = { systemPrompt: [safetyContext], messages: [], tools };
  contexts.set(threadId, context);
  await saveThread(threadId, context);
  return threadId;
}

function validatedImagePath(value: unknown): string | undefined {
  if (!value) return undefined;
  const imagePath = resolve(String(value));
  if (imagePath !== uploadRoot && !imagePath.startsWith(`${uploadRoot}${sep}`)) {
    throw new Error("Meal images must be inside Ambrosia's sanitized upload directory.");
  }
  return imagePath;
}

async function executeTool(call: ToolCall): Promise<Json> {
  const args = call.arguments;
  let path: string;
  let query = new URLSearchParams();
  if (call.name === "get_health_overview") {
    path = "/home";
    if (args.as_of) query.set("date", String(args.as_of));
  } else if (call.name === "get_domain_summary") {
    if (!["fitness", "sleep", "nutrition"].includes(String(args.domain))) throw new Error("Invalid domain.");
    path = `/${String(args.domain)}`;
    query.set("range", String(args.range_name || "28d"));
  } else if (call.name === "compare_periods") {
    path = `/compare/${encodeURIComponent(String(args.metric))}`;
    if (args.as_of) query.set("date", String(args.as_of));
  } else if (call.name === "analyze_relationship") {
    path = `/relationships/${encodeURIComponent(String(args.relationship))}`;
  } else if (call.name === "get_profile_and_data_quality") {
    path = "/profile-and-quality";
  } else {
    throw new Error(`Unknown bounded tool: ${call.name}`);
  }
  const response = await fetch(`${apiRoot}${path}${query.size ? `?${query}` : ""}`);
  if (!response.ok) throw new Error(`Ambrosia API returned HTTP ${response.status}.`);
  return await response.json() as Json;
}

async function runTurn(
  threadId: string,
  turnId: string,
  text: string,
  imagePath: string | undefined,
  outputSchema: Record<string, unknown> | undefined,
): Promise<void> {
  const abort = new AbortController();
  abortControllers.set(turnId, abort);
  try {
    const context = await loadThread(threadId);
    const content: Array<Record<string, unknown>> = [{ type: "text", text }];
    if (outputSchema) {
      content[0].text = `${text}\n\nReturn only JSON matching this schema:\n${JSON.stringify(outputSchema)}`;
    }
    if (imagePath) {
      const bytes = await Bun.file(imagePath).arrayBuffer();
      content.push({ type: "image", data: Buffer.from(bytes).toString("base64"), mimeType: "image/webp" });
    }
    context.messages.push({ role: "user", content: content as never, timestamp: Date.now() });
    const apiKey = await activeApiKey();
    let finalText = "";
    for (let round = 0; round < 6; round += 1) {
      const response = streamSimple(model, context, {
        apiKey, reasoning: Effort.Medium, hideThinkingSummary: true,
        sessionId: threadId, signal: abort.signal, maxTokens: outputSchema ? 3000 : 4000,
      });
      for await (const item of response) {
        if (item.type === "text_delta") {
          finalText += item.delta;
          event(threadId, "item/agentMessage/delta", { turnId, delta: item.delta });
        }
      }
      const assistant = await response.result();
      context.messages.push(assistant);
      const calls = assistant.content.filter((item): item is ToolCall => item.type === "toolCall");
      if (!calls.length) {
        const textBlocks = assistant.content.filter((item) => item.type === "text").map((item) => item.text);
        finalText = textBlocks.join("\n") || finalText;
        event(threadId, "item/completed", {
          turnId, item: { type: "agentMessage", text: finalText },
        });
        await saveThread(threadId, context);
        event(threadId, "turn/completed", { turn: { id: turnId, status: "completed" } });
        return;
      }
      for (const call of calls) {
        try {
          const toolResult = await executeTool(call);
          context.messages.push({
            role: "toolResult", toolCallId: call.id, toolName: call.name,
            content: [{ type: "text", text: JSON.stringify(toolResult) }],
            isError: false, timestamp: Date.now(),
          });
          event(threadId, "item/completed", {
            turnId, item: { type: "mcpToolCall", tool: call.name, status: "completed" },
          });
        } catch (error) {
          context.messages.push({
            role: "toolResult", toolCallId: call.id, toolName: call.name,
            content: [{ type: "text", text: error instanceof Error ? error.message : String(error) }],
            isError: true, timestamp: Date.now(),
          });
        }
      }
    }
    throw new Error("The assistant exceeded the bounded tool-call loop.");
  } catch (error) {
    const aborted = abort.signal.aborted;
    event(threadId, "turn/completed", {
      turn: {
        id: turnId, status: aborted ? "interrupted" : "failed",
        error: aborted ? null : (error instanceof Error ? error.message : String(error)),
      },
    });
  } finally {
    abortControllers.delete(turnId);
  }
}

async function handle(request: Request): Promise<void> {
  const params = request.params || {};
  if (request.method === "status") return result(request.id, await status());
  if (request.method === "auth/refresh") return result(request.id, await refreshCredential());
  if (request.method === "login/start") return result(request.id, await startLogin());
  if (request.method === "thread/create") return result(request.id, { threadId: await createThread() });
  if (request.method === "thread/resume") {
    await loadThread(String(params.threadId));
    return result(request.id, { resumed: true });
  }
  if (request.method === "turn/start") {
    const threadId = String(params.threadId);
    const turnId = crypto.randomUUID();
    const imagePath = validatedImagePath(params.imagePath);
    void runTurn(
      threadId, turnId, String(params.text || ""), imagePath,
      params.outputSchema as Record<string, unknown> | undefined,
    );
    return result(request.id, { turnId });
  }
  if (request.method === "turn/interrupt") {
    abortControllers.get(String(params.turnId))?.abort();
    return result(request.id, { interrupted: true });
  }
  throw new Error(`Unknown sidecar method: ${request.method}`);
}

await mkdir(threadDir, { recursive: true, mode: 0o700 });
const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of lines) {
  if (!line.trim()) continue;
  let request: Request;
  try {
    request = JSON.parse(line) as Request;
  } catch (error) {
    send({ error: { code: -32700, message: error instanceof Error ? error.message : String(error) } });
    continue;
  }
  void handle(request).catch((error) => failure(request.id, error));
}
