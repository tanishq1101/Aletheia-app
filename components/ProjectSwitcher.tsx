"use client";

import { useState } from "react";
import { useWorkspace } from "@/lib/workspace";

/** The API scopes everything to a project. This is where that choice lives. */
export default function ProjectSwitcher() {
  const { projects, project, selectProject, addProject } = useWorkspace();
  const [isOpen, setIsOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      await addProject(trimmed);
      setName("");
      setCreating(false);
      setIsOpen(false);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create project.");
    }
  };

  return (
    <div className="relative shrink-0">
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        className="flex items-center gap-2 rounded-md border border-hairline bg-surface px-3 py-[7px] transition-colors hover:border-brass"
      >
        <span className="size-[6px] shrink-0 rounded-full bg-brass" />
        <span className="max-w-[180px] truncate font-ui text-[13px] text-primary">
          {project?.name ?? "Loading…"}
        </span>
        <span className="font-mono text-[10px] text-muted">▾</span>
      </button>

      {isOpen && (
        <div className="absolute right-0 top-[calc(100%+6px)] z-20 flex w-[280px] flex-col items-start gap-px overflow-hidden rounded-md border border-hairline-subtle bg-surface shadow-lg">
          {projects.map((candidate) => (
            <button
              key={candidate.id}
              type="button"
              onClick={() => {
                selectProject(candidate.id);
                setIsOpen(false);
              }}
              className={`flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-surface-raised ${
                candidate.id === project?.id ? "bg-surface-raised" : ""
              }`}
            >
              <span
                className={`size-1.5 shrink-0 rounded-full ${
                  candidate.id === project?.id ? "bg-brass" : "bg-hairline"
                }`}
              />
              <span className="min-w-px flex-1 truncate font-ui text-[13px] text-primary">
                {candidate.name}
              </span>
            </button>
          ))}

          <div className="w-full border-t border-hairline-subtle p-3">
            {creating ? (
              <div className="flex w-full flex-col gap-2">
                <input
                  autoFocus
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void submit();
                    if (event.key === "Escape") setCreating(false);
                  }}
                  placeholder="Project name"
                  className="w-full rounded border border-hairline bg-base px-2.5 py-2 font-ui text-[13px] text-primary placeholder:text-muted focus:border-brass focus:outline-none"
                />
                {error && <p className="font-ui text-[11px] text-error">{error}</p>}
                <button
                  type="button"
                  onClick={() => void submit()}
                  className="rounded bg-oxblood px-3 py-2 font-ui text-xs font-semibold text-primary"
                >
                  Create
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setCreating(true)}
                className="font-ui text-xs font-medium text-brass"
              >
                + New project
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
