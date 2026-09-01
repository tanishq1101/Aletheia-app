"use client";

import { useState, type FormEvent } from "react";
import ApiErrorNotice from "@/components/ApiErrorNotice";
import AnswerView from "@/components/AnswerView";
import EmptyState from "@/components/EmptyState";
import { ApiError, answerQuestion } from "@/lib/api";
import { useWorkspace } from "@/lib/workspace";
import type { AnswerResponse } from "@/types/api";

export default function AskPage() {
  const { projectId, project, papers } = useWorkspace();
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState<string | null>(null);
  const [result, setResult] = useState<AnswerResponse | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsKey, setNeedsKey] = useState(false);

  const indexed = papers.filter((p) => p.status === "ready").length;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || !projectId) return;

    setPending(true);
    setError(null);
    setNeedsKey(false);
    setAsked(trimmed);
    setResult(null);
    try {
      setResult(await answerQuestion(projectId, trimmed));
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
        // The API returns 503 rather than degrading to an ungrounded answer
        // when no LLM key is configured. That is a setup step, not a bug.
        setNeedsKey(err.status === 503 && /key|configur/i.test(err.message));
      } else {
        setError("Could not generate an answer.");
      }
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex w-full flex-col items-start gap-8">
      <div className="flex w-full flex-col items-start gap-2">
        <h1 className="font-display text-3xl font-semibold text-primary">
          Ask your library
        </h1>
        <p className="font-ui text-[13px] text-secondary">
          Retrieve, rerank, then answer — every claim cited back to a passage the
          backend resolved itself.
        </p>
      </div>

      <form
        onSubmit={submit}
        className="flex w-full shrink-0 flex-col items-start gap-3 rounded-lg border border-brass bg-surface px-5 py-4"
      >
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            // Enter sends; Shift+Enter keeps the newline.
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void submit(event);
            }
          }}
          rows={2}
          placeholder="What do these papers say about chunk size and retrieval quality?"
          className="w-full resize-none bg-transparent font-ui text-[15px] text-primary placeholder:text-muted focus:outline-none"
        />
        <div className="flex w-full items-center gap-3">
          <p className="min-w-px flex-1 font-mono text-[10px] text-muted">
            {indexed} indexed paper{indexed === 1 ? "" : "s"} in{" "}
            {project?.name ?? "this project"}
          </p>
          <button
            type="submit"
            disabled={!projectId || pending || !question.trim()}
            className="shrink-0 rounded-md bg-oxblood px-[18px] py-[9px] font-ui text-[13px] font-semibold text-primary disabled:bg-surface-raised disabled:text-muted"
          >
            {pending ? "Thinking…" : "Ask"}
          </button>
        </div>
      </form>

      {pending && (
        <p className="font-ui text-[13px] text-muted">
          Retrieving, reranking and answering. The first question after an API
          restart also waits on the embedding and reranking models loading —
          around 25 seconds.
        </p>
      )}

      {error && (
        <div className="flex w-full flex-col items-start gap-3">
          <ApiErrorNotice message={error} />
          {needsKey && (
            <p className="font-ui text-xs text-muted">
              Answering needs an OpenRouter key. From{" "}
              <span className="font-mono text-secondary">backend/</span>, run{" "}
              <span className="font-mono text-secondary">
                ./scripts/set-openrouter-key.sh
              </span>{" "}
              and restart the API. Search and the library work without it.
            </p>
          )}
        </div>
      )}

      {asked && result && (
        <div className="flex w-full flex-col items-start gap-4">
          <p className="font-ui text-[15px] font-semibold text-primary">
            {asked}
          </p>
          <AnswerView result={result} />
        </div>
      )}

      {!asked && !pending && indexed === 0 && (
        <EmptyState
          title="Nothing indexed yet"
          description="Answers are built only from passages retrieved out of your own papers. Upload a PDF and let it finish processing first."
          actionLabel="Upload a paper"
          actionHref="/upload"
        />
      )}
    </div>
  );
}
