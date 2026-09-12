"use client";

import { useEffect, useState, type FormEvent } from "react";
import ApiErrorNotice from "@/components/ApiErrorNotice";
import AnswerView from "@/components/AnswerView";
import EmptyState from "@/components/EmptyState";
import ProjectSources from "@/components/ProjectSources";
import {
  ApiError,
  createConversation,
  listConversations,
  listMessages,
  sendMessage,
} from "@/lib/api";
import { useWorkspace } from "@/lib/workspace";
import type { AnswerResponse, Message } from "@/types/api";

/** A stored `Message` only carries citations, not full evidence blocks or
 *  diagnostics — those are not persisted. `AnswerView` renders fine from a
 *  partial `AnswerResponse`; the sections it has no data for just stay empty. */
function answerFromMessage(message: Message): AnswerResponse {
  const metadata = message.metadata;
  return {
    answer: message.content,
    sufficient_evidence: metadata?.sufficient_evidence ?? true,
    citations: message.citations,
    evidence: [],
    fabricated_citations_removed: metadata?.fabricated_citations_removed ?? 0,
    candidates_considered: metadata?.candidates_considered ?? 0,
    evidence_dropped_for_budget: metadata?.evidence_dropped_for_budget ?? 0,
    model: metadata?.model ?? "",
  };
}

export default function AskPage() {
  const { projectId, project, papers } = useWorkspace();
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [pending, setPending] = useState(false);
  const [loadingThread, setLoadingThread] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [needsKey, setNeedsKey] = useState(false);

  const indexed = papers.filter((p) => p.status === "ready").length;

  // Resume the most recent thread in this project, if there is one.
  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;

    listConversations(projectId)
      .then((threads) => {
        if (cancelled) return;
        const latest = threads[0];
        if (!latest) {
          setConversationId(null);
          setMessages([]);
          return Promise.resolve();
        }
        setConversationId(latest.id);
        return listMessages(latest.id).then((loaded) => {
          if (!cancelled) setMessages(loaded);
        });
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(
            cause instanceof Error ? cause.message : "Could not load conversations.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingThread(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const startNewThread = () => {
    setConversationId(null);
    setMessages([]);
    setError(null);
    setNeedsKey(false);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || !projectId) return;

    setPending(true);
    setError(null);
    setNeedsKey(false);
    setQuestion("");
    try {
      const activeConversationId =
        conversationId ?? (await createConversation(projectId)).id;
      setConversationId(activeConversationId);
      const exchange = await sendMessage(activeConversationId, trimmed);
      setMessages((current) => [
        ...current,
        exchange.user_message,
        exchange.assistant_message,
      ]);
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
      <div className="flex w-full items-center gap-4">
        <div className="flex min-w-px flex-1 flex-col items-start gap-2">
          <h1 className="font-display text-3xl font-semibold text-primary">
            Ask your library
          </h1>
          <p className="font-ui text-[13px] text-secondary">
            Retrieve, rerank, then answer — every claim cited back to a passage the
            backend resolved itself.
          </p>
        </div>
        {messages.length > 0 && (
          <button
            type="button"
            onClick={startNewThread}
            className="shrink-0 rounded-md border border-hairline px-[14px] py-[9px] font-ui text-xs font-medium text-secondary hover:text-primary"
          >
            New thread
          </button>
        )}
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

      <ProjectSources />

      {messages.length > 0 && (
        <div className="flex w-full flex-col items-start gap-8">
          {messages.map((message) =>
            message.role === "user" ? (
              <p
                key={message.id}
                className="font-ui text-[15px] font-semibold text-primary"
              >
                {message.content}
              </p>
            ) : (
              <AnswerView key={message.id} result={answerFromMessage(message)} />
            ),
          )}
        </div>
      )}

      {!loadingThread &&
        messages.length === 0 &&
        !pending &&
        indexed === 0 && (
          <EmptyState
            title="Nothing indexed yet"
            description="Answers are built only from passages retrieved from your project sources. Add a file and let its text finish processing first."
            actionLabel="Add a source"
            actionHref="/upload"
          />
        )}
    </div>
  );
}
