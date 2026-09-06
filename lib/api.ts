/** Thin fetch client for the FastAPI backend in `backend/`.
 *
 * Every call goes through `request` so that an unreachable API and a rejected
 * request produce different, actionable messages instead of a bare "failed to
 * fetch". The backend's own `detail` is preserved wherever it sends one. */

import type {
  AnswerResponse,
  AgentResearchResponse,
  FigureInterpretationResponse,
  HealthResponse,
  Paper,
  PaperAsset,
  PaperPage,
  PaperSection,
  Project,
  SearchResult,
} from "@/types/api";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  /** 0 when the request never reached the server. */
  readonly status: number;
  /** Structured `detail` payload, for errors that carry more than a message
   *  (a duplicate upload returns `existing_paper_id` alongside its text). */
  readonly detail: unknown;

  constructor(message: string, status = 0, detail: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }

  /** True when the API could not be reached at all — a different problem from
   *  a request the API understood and refused. */
  get isUnreachable() {
    return this.status === 0;
  }
}

async function readError(response: Response): Promise<ApiError> {
  let message = `Request failed (${response.status})`;
  let detail: unknown = null;

  try {
    const body = await response.json();
    detail = body?.detail ?? null;
    if (typeof body?.detail === "string") {
      message = body.detail;
    } else if (typeof body?.detail?.message === "string") {
      message = body.detail.message;
    }
  } catch {
    /* no JSON body; the status-based message stands */
  }

  return new ApiError(message, response.status, detail);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new ApiError(
      `Cannot reach the API at ${API_BASE_URL}. Is the backend running?`,
    );
  }

  if (!response.ok) throw await readError(response);

  return response.json() as Promise<T>;
}

// --- Health -----------------------------------------------------------------

/** Health reports degradation as a 503 *with* a body, so the body is what
 *  matters — a 503 here is a successful read of a bad state, not a failure. */
export async function getHealth(): Promise<HealthResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/health`);
  } catch {
    throw new ApiError(
      `Cannot reach the API at ${API_BASE_URL}. Is the backend running?`,
    );
  }

  try {
    return (await response.json()) as HealthResponse;
  } catch {
    throw await readError(response);
  }
}

// --- Projects ---------------------------------------------------------------

export const listProjects = () => request<Project[]>("/projects");

export const getProject = (projectId: string) =>
  request<Project>(`/projects/${projectId}`);

export const createProject = (name: string, description?: string) =>
  request<Project>("/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description: description || null }),
  });

// --- Papers -----------------------------------------------------------------

export const listPapers = (projectId: string) =>
  request<Paper[]>(`/projects/${projectId}/papers`);

export const getPaper = (paperId: string) =>
  request<Paper>(`/papers/${paperId}`);

export const deletePaper = (paperId: string) =>
  request<void>(`/papers/${paperId}`, { method: "DELETE" });

export const uploadPaper = (projectId: string, file: File) => {
  const form = new FormData();
  form.append("file", file);
  return request<Paper>(`/projects/${projectId}/papers`, {
    method: "POST",
    body: form,
  });
};

export const listPages = (paperId: string) =>
  request<PaperPage[]>(`/papers/${paperId}/pages`);

export const listSections = (paperId: string) =>
  request<PaperSection[]>(`/papers/${paperId}/sections`);

export const listAssets = (paperId: string) =>
  request<PaperAsset[]>(`/papers/${paperId}/assets`);

export const assetContentUrl = (assetId: string) =>
  `${API_BASE_URL}/assets/${assetId}/content`;

export const interpretFigure = (assetId: string) =>
  request<FigureInterpretationResponse>(`/assets/${assetId}/interpret`, {
    method: "POST",
  });

export const reprocessPaper = (paperId: string) =>
  request<Paper>(`/papers/${paperId}/reprocess`, { method: "POST" });

// --- Retrieval and answering ------------------------------------------------

export const searchProject = (
  projectId: string,
  query: string,
  topK?: number,
) =>
  request<SearchResult[]>(`/projects/${projectId}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, top_k: topK ?? null }),
  });

export const answerQuestion = (projectId: string, query: string) =>
  request<AnswerResponse>(`/projects/${projectId}/answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });

export const runResearchAgent = (
  projectId: string,
  goal: string,
  maxSteps = 3,
) =>
  request<AgentResearchResponse>(`/projects/${projectId}/agent/research`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ goal, max_steps: maxSteps, synthesize: true, discover_sources: true }),
  });
