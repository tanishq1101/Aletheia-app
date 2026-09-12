/** Thin fetch client for the FastAPI backend in `backend/`.
 *
 * Every call goes through `request` so that an unreachable API and a rejected
 * request produce different, actionable messages instead of a bare "failed to
 * fetch". The backend's own `detail` is preserved wherever it sends one. */

import type {
  AnswerResponse,
  AgentResearchResponse,
  AppSettings,
  Claim,
  ClaimVerification,
  Conversation,
  CrossPaperMatrix,
  FigureInterpretationResponse,
  HealthResponse,
  Message,
  MessageExchange,
  Paper,
  PaperAsset,
  PaperPage,
  PaperSection,
  Project,
  ReproducibilityReport,
  SearchResult,
} from "@/types/api";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Supplies a fresh session token, registered once by `<AuthBridge />`.
 *
 * Null when the app is running without authentication, in which case requests
 * go out bare and the API answers as the seeded development user. Kept as a
 * module-level hook rather than a parameter so no call site can forget it. */
let authTokenProvider: (() => Promise<string | null>) | null = null;

export function setAuthTokenProvider(
  provider: (() => Promise<string | null>) | null,
) {
  authTokenProvider = provider;
}

/** Merges the bearer token into a request's headers.
 *
 * Tokens are short-lived, so this asks for one per request rather than
 * caching: the SDK returns a cached token until it is close to expiry, and
 * holding our own copy is how a long-lived tab starts sending expired ones. */
async function withAuth(init?: RequestInit): Promise<RequestInit | undefined> {
  if (!authTokenProvider) return init;
  let token: string | null = null;
  try {
    token = await authTokenProvider();
  } catch {
    // A token that cannot be minted is a signed-out session. Let the request
    // go out unauthenticated and let the API's 401 say so, rather than
    // throwing a different error here for the same underlying state.
  }
  if (!token) return init;
  return {
    ...init,
    headers: { ...(init?.headers ?? {}), Authorization: `Bearer ${token}` },
  };
}

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
    response = await fetch(`${API_BASE_URL}${path}`, await withAuth(init));
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
    response = await fetch(`${API_BASE_URL}/health`, await withAuth());
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

// --- Settings -----------------------------------------------------------------

export const getSettings = () => request<AppSettings>("/settings");

export const updateSettings = (changes: Partial<AppSettings>) =>
  request<AppSettings>("/settings", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(changes),
  });

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

/** Idempotent: returns the existing default project, or creates one if the
 *  workspace is empty. Safe to call concurrently — the server serialises the
 *  decision, so a double mount or a second tab cannot produce two libraries. */
export const ensureDefaultProject = () =>
  request<Project>("/projects/default", { method: "POST" });

export const deleteProject = (projectId: string) =>
  request<void>(`/projects/${projectId}`, { method: "DELETE" });

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
  paperIds?: string[],
) =>
  request<SearchResult[]>(`/projects/${projectId}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, top_k: topK ?? null, paper_ids: paperIds?.length ? paperIds : null }),
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

// --- Claim verification and cross-paper agreement ---------------------------

export const extractClaims = (paperId: string, limit = 8) =>
  request<Claim[]>(`/papers/${paperId}/claims/extract`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ limit }),
  });

export const listPaperClaims = (paperId: string) =>
  request<Claim[]>(`/papers/${paperId}/claims`);

export const listProjectClaims = (projectId: string) =>
  request<Claim[]>(`/projects/${projectId}/claims`);

export const createClaim = (
  projectId: string,
  text: string,
  paperId?: string,
) =>
  request<Claim>(`/projects/${projectId}/claims`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, paper_id: paperId ?? null }),
  });

export const verifyClaim = (claimId: string) =>
  request<ClaimVerification>(`/claims/${claimId}/verify`, { method: "POST" });

export const buildCrossPaperMatrix = (
  projectId: string,
  claimIds: string[],
  paperIds: string[],
  refresh = false,
) =>
  request<CrossPaperMatrix>(`/projects/${projectId}/cross-paper`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      claim_ids: claimIds,
      paper_ids: paperIds,
      refresh,
    }),
  });

export function getStoredCrossPaperMatrix(
  projectId: string,
  claimIds: string[],
  paperIds: string[],
) {
  const params = new URLSearchParams();
  claimIds.forEach((id) => params.append("claim_ids", id));
  paperIds.forEach((id) => params.append("paper_ids", id));
  return request<CrossPaperMatrix>(
    `/projects/${projectId}/cross-paper?${params.toString()}`,
  );
}

// --- Reproducibility ----------------------------------------------------------

export const getReproducibilityReport = (paperId: string) =>
  request<ReproducibilityReport | null>(`/papers/${paperId}/reproducibility`);

export const runReproducibilityReport = (
  paperId: string,
  checkGithub = true,
) =>
  request<ReproducibilityReport>(`/papers/${paperId}/reproducibility`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ check_github: checkGithub }),
  });

// --- Conversations (Ask persistence) ----------------------------------------

export const listConversations = (projectId: string) =>
  request<Conversation[]>(`/projects/${projectId}/conversations`);

export const createConversation = (projectId: string, paperId?: string) =>
  request<Conversation>(`/projects/${projectId}/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paper_id: paperId ?? null }),
  });

export const listMessages = (conversationId: string) =>
  request<Message[]>(`/conversations/${conversationId}/messages`);

export const sendMessage = (conversationId: string, query: string) =>
  request<MessageExchange>(`/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
