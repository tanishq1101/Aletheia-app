import type {
  AnswerResponse,
  Paper,
  PaperSection,
  Project,
  SearchResult,
} from "@/types/api";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, init);
  } catch {
    throw new ApiError(
      `Cannot reach the API at ${BASE_URL}. Is the backend running?`,
    );
  }

  if (!response.ok) {
    // Surface the backend's own message rather than a generic failure.
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") {
        detail = body.detail;
      } else if (typeof body?.detail?.message === "string") {
        // Structured errors (e.g. duplicate upload) carry extra fields.
        detail = body.detail.message;
      }
    } catch {
      /* response had no JSON body; keep the status-based message */
    }
    throw new ApiError(detail);
  }

  return response.json() as Promise<T>;
}

export const listProjects = () => request<Project[]>("/projects");

export const createProject = (name: string, description?: string) =>
  request<Project>("/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description: description || null }),
  });

export const listPapers = (projectId: string) =>
  request<Paper[]>(`/projects/${projectId}/papers`);

export const uploadPaper = (projectId: string, file: File) => {
  const form = new FormData();
  form.append("file", file);
  return request<Paper>(`/projects/${projectId}/papers`, {
    method: "POST",
    body: form,
  });
};

export const listSections = (paperId: string) =>
  request<PaperSection[]>(`/papers/${paperId}/sections`);

export const reprocessPaper = (paperId: string) =>
  request<Paper>(`/papers/${paperId}/reprocess`, { method: "POST" });

export const searchProject = (projectId: string, query: string, topK?: number) =>
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
