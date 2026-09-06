import type { AnswerResponse } from "@/types/api";

export default function EvidenceOverview({ result }: { result: AnswerResponse }) {
  const cited = new Set(result.citations.map((item) => item.evidence_id));
  const sources = new Map<string, { title: string; total: number; used: number }>();
  for (const item of result.evidence) {
    const row = sources.get(item.paper_id) ?? { title: item.paper_title ?? "Untitled source", total: 0, used: 0 };
    row.total += 1;
    row.used += Number(cited.has(item.evidence_id));
    sources.set(item.paper_id, row);
  }
  if (!sources.size) return null;
  const maximum = Math.max(...Array.from(sources.values()).map((r) => r.total));
  return <figure className="w-full rounded-lg border border-hairline-subtle bg-surface p-5">
    <figcaption className="mb-4 font-ui text-sm font-semibold">Evidence coverage by source</figcaption>
    <div className="space-y-4">{Array.from(sources.entries()).map(([id, row]) => <div key={id}>
      <div className="mb-1 flex justify-between gap-3 text-xs"><span className="truncate" title={row.title}>{row.title}</span><span className="shrink-0 text-muted">{row.used} cited / {row.total} available</span></div>
      <div role="img" aria-label={`${row.title}: ${row.used} cited passages out of ${row.total} available`} className="h-3 rounded bg-surface-raised" style={{ width: `${100 * row.total / maximum}%` }}><div className="h-full rounded bg-brass" style={{ width: `${100 * row.used / row.total}%` }} /></div>
    </div>)}</div>
    <p className="mt-4 text-xs italic text-muted">Bars count supplied passages. They do not measure study quality, agreement, or confidence.</p>
  </figure>;
}
