"use client";

import { useCallback, useEffect, useState } from "react";
import ApiErrorNotice from "@/components/ApiErrorNotice";
import Badge, { type BadgeTone } from "@/components/Badge";
import SettingsFieldRow from "@/components/SettingsFieldRow";
import { API_BASE_URL, ApiError, getHealth } from "@/lib/api";
import { fullDate } from "@/lib/display";
import { useWorkspace } from "@/lib/workspace";
import type { HealthResponse } from "@/types/api";

function DependencyRow({ label, value }: { label: string; value: string }) {
  // The API reports real reachability, so "ok" is the only healthy string.
  const tone: BadgeTone = value === "ok" ? "success" : "error";
  return (
    <div className="flex w-full shrink-0 items-center gap-4 bg-surface px-[18px] py-3.5">
      <p className="min-w-px flex-1 font-ui text-[13px] text-secondary">{label}</p>
      <Badge tone={tone} label={value} />
    </div>
  );
}

export default function SettingsPage() {
  const { project, projects, papers } = useWorkspace();
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Promise chain rather than async/await so the setStates land in callbacks
  // and not synchronously inside the effect below.
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
          <SettingsFieldRow label="Answering" value="OPENROUTER_MODEL in backend/.env" />
        </div>
        <p className="font-ui text-xs text-muted">
          To change the answering model or set a key, edit{" "}
          <span className="font-mono text-secondary">backend/.env</span> (or run{" "}
          <span className="font-mono text-secondary">
            backend/scripts/set-openrouter-key.sh
          </span>
          ) and restart the API.
        </p>
      </div>

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
    </div>
  );
}
