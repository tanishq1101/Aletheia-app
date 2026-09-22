"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import ProjectSwitcher from "@/components/ProjectSwitcher";
import ThemeToggle from "@/components/ThemeToggle";
import UserMenu from "@/components/UserMenu";
import { isInFlight, useWorkspace } from "@/lib/workspace";

/** Clerk's components require its provider, which is only mounted when a
 *  publishable key exists. Same condition, one source. */
const authConfigured = Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY);

export default function Topbar() {
  const router = useRouter();
  const { papers, error, offline } = useWorkspace();
  const [query, setQuery] = useState("");

  const processing = papers.filter(isInFlight).length;
  const failed = papers.filter((p) => p.status === "failed").length;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = query.trim();
    if (trimmed) router.push(`/search?q=${encodeURIComponent(trimmed)}`);
  };

  return (
    <header className="flex w-full shrink-0 flex-wrap items-center gap-3 border-b border-hairline-subtle px-4 py-3 sm:px-6 md:flex-nowrap md:gap-5 md:px-10 md:py-5">
      <form onSubmit={submit} className="order-last flex w-full min-w-px items-center md:order-none md:flex-1">
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search papers, passages, claims…"
          className="w-full rounded-md border border-hairline bg-surface px-[14px] py-[9px] font-ui text-[13px] text-primary placeholder:text-muted focus:border-brass focus:outline-none"
        />
      </form>

      {/* Reflects the real job state, so it disappears when nothing is running. */}
      {error ? (
        <div
          title={error}
          className="flex shrink-0 items-center gap-[6px] rounded-full border border-oxblood bg-surface px-3 py-[7px]"
        >
          <span className="size-[6px] shrink-0 rounded-full bg-error" />
          <p className="font-mono text-[11px] whitespace-nowrap text-error">
            {offline ? "API offline" : "API error"}
          </p>
        </div>
      ) : processing > 0 ? (
        <div className="flex shrink-0 items-center gap-[6px] rounded-full border border-brass bg-surface px-3 py-[7px]">
          <span className="size-[6px] shrink-0 animate-pulse rounded-full bg-brass" />
          <p className="font-mono text-[11px] whitespace-nowrap text-brass">
            {processing} processing
          </p>
        </div>
      ) : failed > 0 ? (
        <div className="flex shrink-0 items-center gap-[6px] rounded-full border border-oxblood bg-surface px-3 py-[7px]">
          <span className="size-[6px] shrink-0 rounded-full bg-error" />
          <p className="font-mono text-[11px] whitespace-nowrap text-error">
            {failed} failed
          </p>
        </div>
      ) : null}

      <ThemeToggle />

      <ProjectSwitcher />

      {authConfigured ? <UserMenu /> : null}
    </header>
  );
}
