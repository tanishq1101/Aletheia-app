"use client";

/** Shared client state for the workspace shell.
 *
 * The backend is project-scoped — every paper, search and answer hangs off a
 * project id — but the UI never asked the user to pick one. This provider
 * bridges that: it selects a project on load (creating a default one the first
 * time), remembers the choice, and owns the single polling loop for the
 * project's papers so the sidebar count, the library grid and the upload page
 * all read the same data instead of each running their own timer. */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { ApiError, createProject, listPapers, listProjects } from "@/lib/api";
import type { Paper, Project } from "@/types/api";

const STORAGE_KEY = "aletheia.projectId";
const DEFAULT_PROJECT_NAME = "My Library";
/** Ingestion runs in-process on the API and takes seconds, not minutes. */
const POLL_INTERVAL_MS = 2500;

export function isInFlight(paper: Paper) {
  return paper.status === "uploaded" || paper.status === "processing";
}

type WorkspaceValue = {
  projects: Project[];
  project: Project | null;
  /** Null until a project has been resolved. Guard on it before calling the API. */
  projectId: string | null;
  selectProject: (id: string) => void;
  addProject: (name: string) => Promise<Project>;

  papers: Paper[];
  /** True only for the very first load, so refreshes don't blank the page. */
  loading: boolean;
  /** Set when the API is unreachable or refused; pages render it rather than
   *  showing an empty state that looks like "no papers yet". */
  error: string | null;
  refresh: () => Promise<void>;
};

const WorkspaceContext = createContext<WorkspaceValue | null>(null);

export function useWorkspace() {
  const value = useContext(WorkspaceContext);
  if (!value) {
    throw new Error("useWorkspace must be used inside <WorkspaceProvider>");
  }
  return value;
}

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Guards against a slow response for a project the user has since switched
  // away from overwriting the newer one's papers.
  const activeProject = useRef<string | null>(null);

  const selectProject = useCallback((id: string) => {
    setProjectId(id);
    setPapers([]);
    setLoading(true);
    try {
      window.localStorage.setItem(STORAGE_KEY, id);
    } catch {
      /* private mode or blocked storage — the selection just won't persist */
    }
  }, []);

  // Resolve a project once on mount.
  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        let found = await listProjects();
        if (found.length === 0) {
          // First run against an empty database: give the user somewhere for
          // their papers to land rather than an error they can't act on.
          found = [await createProject(DEFAULT_PROJECT_NAME)];
        }
        if (cancelled) return;

        let stored: string | null = null;
        try {
          stored = window.localStorage.getItem(STORAGE_KEY);
        } catch {
          /* ignore */
        }
        const chosen =
          found.find((p) => p.id === stored)?.id ?? found[0].id;

        setProjects(found);
        setProjectId(chosen);
      } catch (err) {
        if (cancelled) return;
        setError(
          err instanceof ApiError ? err.message : "Could not load projects.",
        );
        setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  // Written as a promise chain rather than async/await so every setState lands
  // in a callback: an effect body that updates state synchronously cascades
  // renders, and React's lint rule rightly rejects it.
  const refresh = useCallback(() => {
    if (!projectId) return Promise.resolve();
    const requested = projectId;
    // A response for a project the user has since switched away from is stale.
    const isCurrent = () => activeProject.current === requested;

    return listPapers(requested).then(
      (next) => {
        if (!isCurrent()) return;
        setPapers(next);
        setError(null);
        setLoading(false);
      },
      (err: unknown) => {
        if (!isCurrent()) return;
        setError(err instanceof ApiError ? err.message : "Could not load papers.");
        setLoading(false);
      },
    );
  }, [projectId]);

  // Load the selected project's papers once.
  useEffect(() => {
    activeProject.current = projectId;
    if (projectId) void refresh();
  }, [projectId, refresh]);

  // Ingestion runs in-process on the API, so the only way to see a job advance
  // is to ask. Poll while anything is in flight, and stop as soon as nothing
  // is — an upload calls `refresh` itself, which starts this again.
  const anyInFlight = papers.some(isInFlight);
  useEffect(() => {
    if (!projectId || !anyInFlight) return;
    const timer = setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [projectId, anyInFlight, refresh]);

  const addProject = useCallback(
    async (name: string) => {
      const created = await createProject(name);
      setProjects((current) => [created, ...current]);
      selectProject(created.id);
      return created;
    },
    [selectProject],
  );

  const project = useMemo(
    () => projects.find((p) => p.id === projectId) ?? null,
    [projects, projectId],
  );

  const value = useMemo<WorkspaceValue>(
    () => ({
      projects,
      project,
      projectId,
      selectProject,
      addProject,
      papers,
      loading,
      error,
      refresh,
    }),
    [
      projects,
      project,
      projectId,
      selectProject,
      addProject,
      papers,
      loading,
      error,
      refresh,
    ],
  );

  return (
    <WorkspaceContext.Provider value={value}>
      {children}
    </WorkspaceContext.Provider>
  );
}
