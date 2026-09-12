"use client";

import { useCallback, useEffect, useState } from "react";
import ApiErrorNotice from "@/components/ApiErrorNotice";
import Badge, { type BadgeTone } from "@/components/Badge";
import SettingsFieldRow from "@/components/SettingsFieldRow";
import {
  API_BASE_URL,
  ApiError,
  deleteProject,
  getHealth,
  getSettings,
  updateSettings,
} from "@/lib/api";
import { fullDate } from "@/lib/display";
import { useWorkspace } from "@/lib/workspace";
import type { AppSettings, HealthResponse } from "@/types/api";

function DependencyRow({ label, value }: { label: string; value: string }) {
  const tone: BadgeTone = value === "ok" ? "success" : "error";
  return (
    <div className="flex w-full shrink-0 items-center gap-4 bg-surface px-[18px] py-3.5">
      <p className="min-w-px flex-1 font-ui text-[13px] text-secondary">{label}</p>
      <Badge tone={tone} label={value} />
    </div>
  );
}

const TUNABLES: {
  key: "search_top_k" | "rerank_top_k" | "context_max_tokens";
  label: string;
  hint: string;
  min: number;
  max: number;
}[] = [
  {
    key: "search_top_k",
    label: "Candidates retrieved",
    hint: "Chunks fetched by embedding search before reranking.",
    min: 1,
    max: 100,
  },
  {
    key: "rerank_top_k",
    label: "Evidence blocks kept",
    hint: "Survivors of reranking that become citable evidence.",
    min: 1,
    max: 20,
  },
  {
    key: "context_max_tokens",
    label: "Evidence token budget",
    hint: "Evidence beyond this is dropped lowest-rank-first, and reported.",
    min: 500,
    max: 32000,
  },
];

function NumberSetting({
  label,
  hint,
  value,
  overridden,
  min,
  max,
  onCommit,
}: {
  label: string;
  hint: string;
  value: number;
  overridden: boolean;
  min: number;
  max: number;
  onCommit: (value: number) => void;
}) {
  // Keyed on the saved value by the parent, so a save re-mounts this with the
  // new value rather than syncing prop into state.
  const [draft, setDraft] = useState(String(value));

  const commit = () => {
    const parsed = Number(draft);
    if (!Number.isInteger(parsed) || parsed < min || parsed > max) {
      setDraft(String(value));
      return;
    }
    if (parsed !== value) onCommit(parsed);
  };

  return (
    <div className="flex w-full items-center gap-4 bg-surface px-[18px] py-3">
      <div className="flex min-w-px flex-1 flex-col items-start gap-0.5">
        <div className="flex items-center gap-2">
          <p className="font-ui text-[13px] text-primary">{label}</p>
          {overridden && (
            <span className="rounded-[3px] bg-surface-raised px-1.5 py-[1px] font-mono text-[9px] text-brass">
              overridden
            </span>
          )}
        </div>
        <p className="font-ui text-[11px] text-muted">{hint}</p>
      </div>
      <input
        type="number"
        value={draft}
        min={min}
        max={max}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => event.key === "Enter" && commit()}
        className="w-24 shrink-0 rounded-md border border-hairline bg-base px-3 py-1.5 text-right font-mono text-xs text-primary focus:border-brass focus:outline-none"
      />
    </div>
  );
}

export default function SettingsClient() {
  const { project, projectId, projects, papers } = useWorkspace();
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);

  const check = useCallback(
    () =>
      getHealth().then(
        (next) => {
          setHealth(next);
          setError(null);
        },
        (err: unknown) => {
          setHealth(null);
          setError(err instanceof ApiError ? err.message : "Health check failed.");
        },
      ),
    [],
  );

  useEffect(() => {
    void check();
  }, [check]);

  useEffect(() => {
    let cancelled = false;
    getSettings().then(
      (next) => {
        if (!cancelled) setSettings(next);
      },
      (err: unknown) => {
        if (!cancelled) {
          setSettingsError(
            err instanceof ApiError ? err.message : "Could not load settings.",
          );
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const save = async (changes: Partial<AppSettings>) => {
    setSaving(true);
    setSettingsError(null);
    try {
      setSettings(await updateSettings(changes));
    } catch (cause) {
      setSettingsError(
        cause instanceof Error ? cause.message : "Could not save settings.",
      );
    } finally {
      setSaving(false);
    }
  };

  const removeProject = async () => {
    if (!projectId || confirmText !== "DELETE") return;
    setDeleting(true);
    setSettingsError(null);
    try {
      await deleteProject(projectId);
      try {
        window.localStorage.removeItem("aletheia.projectId");
      } catch {
        /* private mode or blocked storage */
      }
      // A full reload, not router.push: WorkspaceProvider only resolves a
      // project once on mount, so it must remount to notice this one is gone.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/library");
    } catch (cause) {
      setSettingsError(
        cause instanceof Error ? cause.message : "Could not delete.",
      );
      setDeleting(false);
    }
  };

  return (
    <div className="flex w-full flex-col items-start gap-6">
      <h1 className="font-display text-[28px] font-semibold text-primary">
        Settings
      </h1>

      <div className="flex w-full shrink-0 flex-col items-start gap-3">
        <div className="flex w-full flex-col items-start gap-1">
          <p className="font-ui text-[15px] font-semibold text-primary">Backend</p>
          <p className="font-ui text-xs text-muted">
            Live from <span className="font-mono">GET /health</span> — real
            database and storage reachability, not a hardcoded ok.
          </p>
        </div>

        {error && <ApiErrorNotice message={error} onRetry={() => void check()} />}

        <div className="flex w-full flex-col items-start gap-px">
          <SettingsFieldRow label="API URL" value={API_BASE_URL} />
          {health && (
            <>
              <DependencyRow label="Overall" value={health.status} />
              <DependencyRow label="Database" value={health.database} />
              <DependencyRow label="Storage" value={health.storage} />
            </>
          )}
        </div>
      </div>

      <div className="flex w-full shrink-0 flex-col items-start gap-3">
        <p className="font-ui text-[15px] font-semibold text-primary">Workspace</p>
        <div className="flex w-full flex-col items-start gap-px">
          <SettingsFieldRow label="Project" value={project?.name ?? "—"} />
          <SettingsFieldRow label="Project ID" value={project?.id ?? "—"} />
          <SettingsFieldRow
            label="Created"
            value={project ? fullDate(project.created_at) : "—"}
          />
          <SettingsFieldRow label="Projects" value={String(projects.length)} />
          <SettingsFieldRow label="Papers" value={String(papers.length)} />
          <SettingsFieldRow
            label="Indexed"
            value={String(papers.filter((p) => p.status === "ready").length)}
          />
        </div>
      </div>

      <div className="flex w-full shrink-0 flex-col items-start gap-3">
        <div className="flex w-full flex-col items-start gap-1">
          <p className="font-ui text-[15px] font-semibold text-primary">
            Retrieval
          </p>
          <p className="font-ui text-xs text-muted">
            Applied to search, answering, claim checks and audits on the next
            request. {saving && "Saving…"}
          </p>
        </div>

        {settingsError && (
          <ApiErrorNotice message={settingsError} />
        )}

        {settings && (
          <>
            <div className="flex w-full flex-col items-start gap-px">
              {TUNABLES.map((tunable) => (
                <NumberSetting
                  key={`${tunable.key}-${settings[tunable.key]}`}
                  label={tunable.label}
                  hint={tunable.hint}
                  min={tunable.min}
                  max={tunable.max}
                  value={settings[tunable.key]}
                  overridden={settings.overridden.includes(tunable.key)}
                  onCommit={(value) => save({ [tunable.key]: value })}
                />
              ))}
            </div>
            {settings.overridden.length > 0 && (
              <button
                type="button"
                onClick={() =>
                  save({
                    search_top_k: null as unknown as number,
                    rerank_top_k: null as unknown as number,
                    context_max_tokens: null as unknown as number,
                    llm_model: null as unknown as string,
                  })
                }
                className="font-ui text-xs font-semibold text-brass hover:text-brass-bright"
              >
                Reset to environment defaults
              </button>
            )}
          </>
        )}
      </div>

      <div className="flex w-full shrink-0 flex-col items-start gap-3">
        <div className="flex w-full flex-col items-start gap-1">
          <p className="font-ui text-[15px] font-semibold text-primary">
            AI provider
          </p>
          <p className="font-ui text-xs text-muted">
            Configured server-side, not here. Embeddings and reranking run
            locally through fastembed — no key, no spend. Only answering calls a
            hosted model.
          </p>
        </div>
        <div className="flex w-full flex-col items-start gap-px">
          <SettingsFieldRow label="Embeddings" value="fastembed · local ONNX" />
          <SettingsFieldRow label="Reranking" value="fastembed cross-encoder · local" />
          <SettingsFieldRow label="PDF assets" value="PyMuPDF · local · no key" />
          <SettingsFieldRow label="Model training" value="NumPy MLP · local · no key" />
          <SettingsFieldRow label="Answering" value="OpenAI · LLM_MODEL in backend/.env" />
          <SettingsFieldRow label="Research agent" value="OpenAI · Gemini failover when configured" />
        </div>
        <p className="font-ui text-xs text-muted">
          OpenAI is primary; Gemini is retried only if OpenAI cannot complete a
          request. To change the model or provider, edit{" "}
          <span className="font-mono text-secondary">backend/.env</span> and restart the API.
        </p>
      </div>

      {settings && (
        <div className="flex w-full shrink-0 flex-col items-start gap-3">
          <div className="flex w-full flex-col items-start gap-1">
            <p className="font-ui text-[15px] font-semibold text-primary">
              Credentials
            </p>
            <p className="font-ui text-xs text-muted">
              Keys live in the server environment and are never sent to this
              page — only whether they are set.
            </p>
          </div>
          <div className="flex w-full flex-col items-start gap-px">
            <SettingsFieldRow
              label={settings.llm_provider}
              value={
                settings.llm_key_configured ? "Configured" : "Not configured"
              }
            />
            <SettingsFieldRow
              label="GitHub (reproducibility)"
              value={
                settings.github_token_configured
                  ? "Configured"
                  : "Not configured · 60 lookups/hour"
              }
            />
          </div>
        </div>
      )}

      <div className="flex w-full shrink-0 flex-col items-start gap-3">
        <p className="font-ui text-[15px] font-semibold text-primary">
          Authentication
        </p>
        <div className="flex w-full items-center gap-4 rounded-md border border-hairline bg-surface px-[18px] py-4">
          <p className="min-w-px flex-1 font-ui text-[13px] text-secondary">
            The API has no auth yet — every project belongs to a seeded dev user.
            The sign-in screen is not wired to anything. Do not expose this
            deployment publicly.
          </p>
        </div>
      </div>

      <div className="flex w-full shrink-0 flex-col items-start gap-3">
        <p className="font-ui text-[15px] font-semibold text-primary">
          Danger zone
        </p>
        <div className="flex w-full flex-col items-start gap-3 rounded-md border border-oxblood px-[18px] py-4">
          <p className="font-ui text-[13px] text-secondary">
            Delete this project and every paper, chunk, claim and conversation
            in it. The original PDF files are left on disk.
          </p>
          <div className="flex w-full items-center gap-3">
            <input
              type="text"
              value={confirmText}
              onChange={(event) => setConfirmText(event.target.value)}
              placeholder="Type DELETE to confirm"
              className="min-w-[220px] rounded-md border border-hairline bg-base px-3 py-2 font-ui text-xs text-primary placeholder:text-muted focus:border-oxblood focus:outline-none"
            />
            <button
              type="button"
              onClick={removeProject}
              disabled={!projectId || confirmText !== "DELETE" || deleting}
              className="shrink-0 font-ui text-xs font-semibold whitespace-nowrap text-oxblood-bright disabled:text-muted"
            >
              {deleting ? "Deleting…" : "Delete project"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
