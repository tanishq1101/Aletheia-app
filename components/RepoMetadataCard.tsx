import type { PaperLink, RepoMetadata } from "@/types/api";

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex shrink-0 flex-col items-start gap-1">
      <p className="font-mono text-[10px] tracking-[0.6px] whitespace-nowrap text-muted">
        {label}
      </p>
      <p className="font-ui text-[13px] font-medium whitespace-nowrap text-primary">
        {value}
      </p>
    </div>
  );
}

const unavailableMessage: Record<string, string> = {
  not_found: "The linked repository no longer exists on GitHub.",
  rate_limited: "GitHub rate-limited the lookup — try again shortly.",
  unavailable: "GitHub could not be reached for this lookup.",
};

/** Live GitHub facts for a repo the paper itself links to. */
export default function RepoMetadataCard({
  repo,
  links,
}: {
  repo: RepoMetadata | null;
  links: PaperLink[];
}) {
  if (!repo) {
    const codeLink = links.find(
      (link) => link.kind === "github" || link.kind === "gitlab"
    );
    return (
      <div className="flex w-full shrink-0 flex-col items-start gap-1 rounded-md border border-hairline-subtle bg-surface px-6 py-5">
        <p className="font-ui text-[13px] text-primary">
          {codeLink
            ? "A code link was found in the paper, but no GitHub metadata was fetched."
            : "This paper links no code repository."}
        </p>
        {codeLink && (
          <a
            href={codeLink.url}
            target="_blank"
            rel="noreferrer noopener"
            className="font-mono text-xs text-brass hover:text-brass-bright"
          >
            {codeLink.url}
          </a>
        )}
      </div>
    );
  }

  if (repo.status !== "ok") {
    return (
      <div className="flex w-full shrink-0 flex-col items-start gap-1 rounded-md border border-hairline bg-surface px-6 py-5">
        <p className="font-ui text-[13px] text-primary">{repo.repository}</p>
        <p className="font-ui text-xs text-warning">
          {unavailableMessage[repo.status] ?? "GitHub metadata is unavailable."}
        </p>
      </div>
    );
  }

  const pushed = repo.last_pushed_at
    ? new Date(repo.last_pushed_at).toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      })
    : "unknown";

  return (
    <div className="flex w-full shrink-0 flex-wrap items-center gap-6 rounded-md border border-hairline-subtle bg-surface px-6 py-5">
      <div className="flex min-w-px flex-1 flex-col items-start gap-1">
        <p className="font-mono text-[10px] tracking-[0.6px] text-muted">
          REPOSITORY
        </p>
        <a
          href={repo.url}
          target="_blank"
          rel="noreferrer noopener"
          className="font-ui text-[13px] font-medium text-primary hover:text-brass"
        >
          {repo.repository}
        </a>
      </div>
      <Field label="STARS" value={repo.stars?.toLocaleString() ?? "—"} />
      <Field label="LICENSE" value={repo.license ?? "none declared"} />
      <Field label="LANGUAGE" value={repo.language ?? "—"} />
      <Field label="LAST PUSH" value={pushed} />
      {repo.archived && <Field label="STATE" value="Archived" />}
    </div>
  );
}
