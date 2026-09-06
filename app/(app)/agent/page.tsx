"use client";

import { useState, type FormEvent } from "react";
import AnswerView from "@/components/AnswerView";
import ApiErrorNotice from "@/components/ApiErrorNotice";
import ProjectSources from "@/components/ProjectSources";
import { ApiError, runResearchAgent } from "@/lib/api";
import { useWorkspace } from "@/lib/workspace";
import type { AgentResearchResponse } from "@/types/api";

export default function ResearchAgentPage() {
  const { projectId, project, papers } = useWorkspace();
  const [goal, setGoal] = useState("");
  const [maxSteps, setMaxSteps] = useState(3);
  const [result, setResult] = useState<AgentResearchResponse | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!projectId || !goal.trim()) return;
    setPending(true);
    setError(null);
    setResult(null);
    try {
      setResult(await runResearchAgent(projectId, goal.trim(), maxSteps));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The research agent failed.");
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex w-full flex-col items-start gap-8">
      <div className="flex w-full flex-col items-start gap-2">
        <div className="flex items-center gap-2">
          <h1 className="font-display text-3xl font-semibold text-primary">
            Research Agent
          </h1>
          <span className="rounded-full border border-brass px-2 py-1 font-mono text-[9px] text-brass">
            BOUNDED
          </span>
        </div>
        <p className="max-w-3xl font-ui text-[13px] leading-relaxed text-secondary">
          Plans focused subquestions, retrieves and reranks your indexed papers,
          searches Europe PMC and Crossref, and combines available evidence into a cited research report. Review the findings, limitations, public sources, and each research step below.
        </p>
      </div>

      <form
        onSubmit={submit}
        className="flex w-full flex-col items-start gap-4 rounded-lg border border-brass bg-surface px-6 py-5"
      >
        <textarea
          rows={4}
          value={goal}
          onChange={(event) => setGoal(event.target.value)}
          placeholder="Compare the methods, datasets, and reported limitations across the papers in this project."
          className="w-full resize-y bg-transparent font-ui text-[15px] leading-relaxed text-primary placeholder:text-muted focus:outline-none"
        />
        <div className="flex w-full items-center gap-4">
          <label className="flex items-center gap-2 font-ui text-xs text-muted">
            Steps
            <select
              value={maxSteps}
              onChange={(event) => setMaxSteps(Number(event.target.value))}
              className="rounded border border-hairline bg-base px-2 py-1 font-mono text-xs text-primary"
            >
              {[1, 2, 3, 4].map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>
          </label>
          <p className="min-w-px flex-1 font-mono text-[10px] text-muted">
            {papers.filter((paper) => paper.status === "ready").length} indexed papers ·{" "}
            {project?.name ?? "current project"}
          </p>
          <button
            type="submit"
            disabled={!projectId || !goal.trim() || pending}
            className="rounded-md bg-oxblood px-5 py-2.5 font-ui text-[13px] font-semibold text-primary disabled:bg-surface-raised disabled:text-muted"
          >
            {pending ? "Running agent…" : "Run research agent"}
          </button>
        </div>
      </form>

      {pending && (
        <p className="font-ui text-[13px] text-muted">
          Planning the run, then grounding each subquestion. Every step is bounded and auditable.
        </p>
      )}
      {error && <ApiErrorNotice message={error} />}

      <ProjectSources />

      {result && (
        <div className="flex w-full flex-col items-start gap-6">
          <div className="flex w-full flex-col gap-3 rounded-lg border border-hairline-subtle bg-surface px-6 py-5">
            <div className="flex items-center gap-3">
              <p className="font-ui text-sm font-semibold text-primary">Execution plan</p>
              <span className="font-mono text-[9px] text-muted">{result.model}</span>
              {result.planner_fallback_used && (
                <span className="font-mono text-[9px] text-warning">planner fallback used</span>
              )}
            </div>
            {result.planned_questions.map((question, index) => (
              <div key={question} className="flex items-start gap-3">
                <span className="mt-0.5 rounded border border-brass px-1.5 py-0.5 font-mono text-[9px] text-brass">
                  {index + 1}
                </span>
                <p className="font-ui text-[13px] text-secondary">{question}</p>
              </div>
            ))}
          </div>

          {result.synthesis_error && <ApiErrorNotice message={result.synthesis_error} />}
          {result.synthesis && <section className="w-full space-y-4"><h2 className="font-display text-2xl text-primary">Research report</h2><AnswerView result={result.synthesis} /></section>}
          {(result.discovery_errors ?? []).map((message) => <p key={message} className="text-sm text-warning">{message}</p>)}
          {(result.discoveries ?? []).length > 0 && <section className="w-full space-y-3"><h2 className="font-ui text-lg font-semibold">Public sources discovered</h2><p className="text-sm text-secondary">Discovery is not endorsement. Only available abstracts can contribute to the report; full texts have not been reviewed.</p>{result.discoveries!.map((source) => <article key={source.url} className="rounded-md border border-hairline p-4"><a href={source.url} target="_blank" rel="noopener noreferrer" className="font-semibold text-brass hover:underline">{source.title}</a><p className="mt-1 text-xs text-muted">{source.provider} · {source.year} · {source.evidence_scope}</p></article>)}</section>}
          {result.steps.map((step, index) => (
            <section key={`${index}-${step.question}`} className="flex w-full flex-col items-start gap-4">
              <div className="flex w-full items-center gap-3 border-b border-hairline-subtle pb-3">
                <span className={`size-2 rounded-full ${step.status === "succeeded" ? "bg-success" : "bg-error"}`} />
                <p className="min-w-px flex-1 font-ui text-[15px] font-semibold text-primary">
                  {step.question}
                </p>
                <span className="font-mono text-[9px] uppercase text-muted">{step.status}</span>
              </div>
              {step.error && <ApiErrorNotice message={step.error} />}
              {step.answer && <AnswerView result={step.answer} />}
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
