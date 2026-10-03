/**
 * Thin typed client for the FastAPI backend (src/cloud_diagram/web/app.py).
 * No business logic lives here — every shape mirrors a backend Pydantic model.
 */

export type Provider = "aws" | "azure" | "gcp";

export interface LlmOverride {
  endpoint?: string;
  model?: string;
  api_key?: string;
}

export interface IconResult {
  id: string;
  provider: string;
  kind: string;
  category: string;
  display_name: string;
  aliases: string[];
  deprecated: boolean;
}

export interface IconSearchResponse {
  count: number;
  results: IconResult[];
}

export interface HealthResponse {
  status: "ok";
  ruleset_id: string;
  ruleset_version: string;
  icon_count: number;
  registry_valid: boolean;
}

export interface DiagnosticFinding {
  severity: "info" | "warning" | "error";
  code: string;
  message: string;
  object_ids: string[];
}

export interface DiagnosticReport {
  diagram_id: string;
  hard_pass: boolean;
  quality_score: number;
  findings: DiagnosticFinding[];
  hard_gates: Record<string, number>;
  [key: string]: unknown;
}

export interface ResolvedIcon {
  node_id: string;
  icon_id: string;
  display_name: string;
  provider: string;
  [key: string]: unknown;
}

export interface CompilationResponse {
  diagram_id: string;
  drawio_xml: string;
  diagnostics: DiagnosticReport;
  quality_score: number;
  resolved_icons: ResolvedIcon[];
}

export interface DiagnosticsResponse {
  diagram_id: string;
  diagnostics: DiagnosticReport;
  valid: boolean;
}

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    const message =
      typeof detail === "string"
        ? detail
        : typeof detail === "object" && detail !== null && "message" in detail
          ? String((detail as { message: unknown }).message)
          : "request failed";
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  const isJson = response.headers.get("content-type")?.includes("application/json");
  const body = isJson ? await response.json() : await response.text();
  if (!response.ok) {
    throw new ApiError(response.status, isJson ? (body as { detail?: unknown }).detail ?? body : body);
  }
  return body as T;
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/api/health");
}

export function searchIcons(params: {
  q: string;
  provider?: Provider;
  kind?: string;
  limit?: number;
}): Promise<IconSearchResponse> {
  const search = new URLSearchParams();
  search.set("q", params.q);
  if (params.provider) search.set("provider", params.provider);
  if (params.kind) search.set("kind", params.kind);
  if (params.limit !== undefined) search.set("limit", String(params.limit));
  return request<IconSearchResponse>(`/api/icons/search?${search.toString()}`);
}

export function generateDiagram(params: {
  prompt: string;
  provider: Provider;
  llm?: LlmOverride;
}): Promise<CompilationResponse> {
  return request<CompilationResponse>("/api/generate", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export function renderSpec(spec: Record<string, unknown>): Promise<CompilationResponse> {
  return request<CompilationResponse>("/api/render", {
    method: "POST",
    body: JSON.stringify({ spec }),
  });
}

export function validateSpec(
  spec: Record<string, unknown>,
  drawioXml?: string,
): Promise<DiagnosticsResponse> {
  return request<DiagnosticsResponse>("/api/validate", {
    method: "POST",
    body: JSON.stringify({ spec, drawio_xml: drawioXml }),
  });
}
