"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import AnswerView from "@/components/AnswerView";
import ApiErrorNotice from "@/components/ApiErrorNotice";
import ProjectSources from "@/components/ProjectSources";
import { ApiError, runResearchAgent } from "@/lib/api";
import { useWorkspace } from "@/lib/workspace";
import type { AgentResearchResponse } from "@/types/api";

const RUN_STAGES = [
  { label: "Clarifying your question", detail: "Turning your goal into focused, answerable research questions." },
  { label: "Finding relevant evidence", detail: "Searching and reranking passages from your indexed library." },
  { label: "Checking the wider literature", detail: "Looking for clearly labelled public abstracts to fill gaps." },
  { label: "Writing your cited brief", detail: "Combining only supported findings and keeping the evidence trail visible." },
];

function RunProgress({ activeStage }: { activeStage: number }) {
  return (
    <section aria-live="polite" aria-label="Research agent progress" className="w-full rounded-lg border border-brass bg-surface px-5 py-5 sm:px-6">
      <div className="mb-5 flex items-center gap-3">
        <span className="agent-orbit relative flex size-8 shrink-0 items-center justify-center rounded-full border border-brass" aria-hidden="true"><span className="size-2 rounded-full bg-brass" /></span>
        <div><p className="font-ui text-sm font-semibold text-primary">Your research brief is in progress</p><p className="font-ui text-xs text-muted">The agent is bounded: it cannot browse indefinitely or answer beyond its evidence.</p></div>
      </div>
      <ol className="grid gap-3 md:grid-cols-2">
        {RUN_STAGES.map((stage, index) => {
          const state = index < activeStage ? "complete" : index === activeStage ? "active" : "waiting";
          return <li key={stage.label} className={`flex min-w-0 items-start gap-3 rounded-md border px-4 py-3 transition-colors ${state === "active" ? "border-brass bg-surface-raised" : state === "complete" ? "border-hairline-subtle bg-surface-raised/50" : "border-hairline-subtle"}`}>
            <span className={`mt-1 flex size-4 shrink-0 items-center justify-center rounded-full border text-[9px] ${state === "complete" ? "border-success bg-success text-base" : state === "active" ? "agent-pulse border-brass bg-brass" : "border-hairline text-muted"}`} aria-hidden="true">{state === "complete" ? "✓" : index + 1}</span>
            <div className="min-w-0"><p className="font-ui text-[13px] font-semibold text-primary">{stage.label}</p><p className="mt-1 font-ui text-xs leading-relaxed text-muted">{stage.detail}</p></div>
          </li>;
        })}
      </ol>
    </section>
  );
}

export default function ResearchAgentPage() {
  const { projectId, project, papers } = useWorkspace();
  const [goal, setGoal] = useState("");
  const [maxSteps, setMaxSteps] = useState(3);
  const [result, setResult] = useState<AgentResearchResponse | null>(null);
  const [pending, setPending] = useState(false);
  const [activeStage, setActiveStage] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const indexed = papers.filter((paper) => paper.status === "ready").length;
  const summary = useMemo(() => {
    if (!result) return null;
    return { completed: result.steps.filter((step) => step.status === "succeeded").length, citations: result.synthesis?.citations.length ?? 0, discoveries: result.discoveries?.length ?? 0 };
  }, [result]);

  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => setActiveStage((current) => Math.min(current + 1, RUN_STAGES.length - 1)), 1800);
    return () => window.clearInterval(timer);
  }, [pending]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const requestGoal = goal.trim();
    if (!projectId || !requestGoal) return;
    setActiveStage(0); setPending(true); setError(null); setResult(null);
    try { setResult(await runResearchAgent(projectId, requestGoal, maxSteps)); }
    catch (err) { setError(err instanceof ApiError ? err.message : "The research agent could not complete this run."); }
    finally { setPending(false); }
  };

  return <div className="flex w-full flex-col items-start gap-8">
    <header className="flex w-full flex-col items-start gap-2">
      <div className="flex items-center gap-2"><h1 className="font-display text-3xl font-semibold text-primary">Research Agent</h1><span className="rounded-full border border-brass px-2 py-1 font-mono text-[9px] text-brass">EVIDENCE-FIRST</span></div>
      <p className="max-w-3xl font-ui text-[14px] leading-relaxed text-secondary">Get a research brief tailored to your library. The agent breaks your goal into a few checkable questions, compares the evidence, and shows exactly where each finding came from.</p>
    </header>

    <form onSubmit={submit} className="flex w-full flex-col items-start gap-4 rounded-lg border border-brass bg-surface px-5 py-5 sm:px-6">
      <label htmlFor="research-goal" className="font-ui text-sm font-semibold text-primary">What would you like to understand?</label>
      <textarea id="research-goal" rows={4} value={goal} onChange={(event) => setGoal(event.target.value)} placeholder="For example: What do these papers agree and disagree on about the best retrieval method?" className="w-full resize-y rounded-md border border-hairline bg-base px-4 py-3 font-ui text-[15px] leading-relaxed text-primary placeholder:text-muted focus:border-brass focus:outline-none" />
      <div className="flex w-full flex-col gap-3 sm:flex-row sm:items-center">
        <label className="flex items-center gap-2 font-ui text-xs text-secondary">Depth
          <select value={maxSteps} onChange={(event) => setMaxSteps(Number(event.target.value))} className="min-h-9 rounded border border-hairline bg-base px-2 font-mono text-xs text-primary focus:border-brass focus:outline-none">
            <option value={1}>Quick · 1 question</option><option value={2}>Focused · 2 questions</option><option value={3}>Balanced · 3 questions</option><option value={4}>Thorough · 4 questions</option>
          </select>
        </label>
        <p className="min-w-px flex-1 font-mono text-[10px] text-muted">{indexed} indexed paper{indexed === 1 ? "" : "s"} · {project?.name ?? "current project"}</p>
        <button type="submit" disabled={!projectId || !goal.trim() || pending || indexed === 0} className="min-h-11 rounded-md bg-oxblood px-5 font-ui text-[13px] font-semibold text-primary transition-colors hover:bg-oxblood-bright disabled:cursor-not-allowed disabled:bg-surface-raised disabled:text-muted">{pending ? "Building brief…" : "Build research brief"}</button>
      </div>
      {indexed === 0 && <p className="font-ui text-xs text-warning">Add and process at least one source before running a research brief.</p>}
    </form>

    {pending && <RunProgress activeStage={activeStage} />}
    {error && <ApiErrorNotice message={error} />}
    <ProjectSources />

    {result && summary && <div className="flex w-full flex-col items-start gap-6">
      <section className="w-full rounded-lg border border-hairline-subtle bg-surface px-5 py-5 sm:px-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between"><div><p className="font-ui text-lg font-semibold text-primary">Your research brief</p><p className="mt-1 font-ui text-sm text-secondary">{result.goal}</p></div><span className="font-mono text-[10px] text-muted">Answered by {result.model}</span></div>
        <div className="mt-5 grid grid-cols-3 divide-x divide-hairline-subtle rounded-md border border-hairline-subtle bg-surface-raised"><div className="px-3 py-3 text-center"><p className="font-mono text-lg text-brass">{summary.completed}/{result.steps.length}</p><p className="font-ui text-[11px] text-muted">questions answered</p></div><div className="px-3 py-3 text-center"><p className="font-mono text-lg text-brass">{summary.citations}</p><p className="font-ui text-[11px] text-muted">report citations</p></div><div className="px-3 py-3 text-center"><p className="font-mono text-lg text-brass">{summary.discoveries}</p><p className="font-ui text-[11px] text-muted">public sources checked</p></div></div>
        {result.planner_fallback_used && <p className="mt-4 font-ui text-xs text-warning">The planner used your original question directly, so this brief has one focused evidence check.</p>}
      </section>

      {result.synthesis_error && <ApiErrorNotice message={result.synthesis_error} />}
      {result.synthesis ? <section className="w-full space-y-4"><div><h2 className="font-display text-2xl text-primary">What the evidence says</h2><p className="mt-1 font-ui text-sm text-muted">Claims link to passages below, so you can check the reasoning rather than take it on trust.</p></div><AnswerView result={result.synthesis} /></section> : <ApiErrorNotice message="The agent completed its checks, but could not assemble a combined report. You can still review every completed evidence check below." />}

      <section className="w-full rounded-lg border border-hairline-subtle bg-surface"><div className="border-b border-hairline-subtle px-5 py-4 sm:px-6"><h2 className="font-ui text-base font-semibold text-primary">How this brief was built</h2><p className="mt-1 font-ui text-xs text-muted">Expand a question to inspect its answer, citations, and all evidence supplied to the model.</p></div><ol className="divide-y divide-hairline-subtle">{result.steps.map((step, index) => <li key={`${index}-${step.question}`} className="px-5 py-4 sm:px-6"><details><summary className="flex cursor-pointer list-none items-start gap-3 focus:outline-none focus-visible:ring-2 focus-visible:ring-brass"><span className={`mt-1 flex size-5 shrink-0 items-center justify-center rounded-full font-mono text-[10px] ${step.status === "succeeded" ? "bg-success text-base" : "bg-error text-base"}`}>{step.status === "succeeded" ? "✓" : "!"}</span><span className="min-w-0 flex-1 font-ui text-[14px] font-semibold text-primary">{index + 1}. {step.question}</span><span className="shrink-0 font-mono text-[10px] uppercase text-muted">{step.status === "succeeded" ? "review evidence" : "needs attention"}</span></summary><div className="pt-5">{step.error ? <ApiErrorNotice message={step.error} /> : step.answer ? <AnswerView result={step.answer} /> : null}</div></details></li>)}</ol></section>

      {(result.discovery_errors ?? []).map((message) => <p key={message} className="font-ui text-sm text-warning">{message}</p>)}
      {(result.discoveries ?? []).length > 0 && <section className="w-full space-y-3"><div><h2 className="font-ui text-lg font-semibold text-primary">Public sources considered</h2><p className="mt-1 font-ui text-sm text-secondary">These are discovery leads, not automatically trusted evidence. Abstract-only sources are labelled as such.</p></div>{result.discoveries!.map((source) => <article key={source.url} className="rounded-md border border-hairline-subtle bg-surface px-4 py-4"><a href={source.url} target="_blank" rel="noopener noreferrer" className="font-ui text-sm font-semibold text-brass hover:text-brass-bright hover:underline">{source.title}</a><p className="mt-1 font-mono text-[10px] text-muted">{source.provider} · {source.year} · {source.evidence_scope}</p></article>)}</section>}
    </div>}
  </div>;
}
