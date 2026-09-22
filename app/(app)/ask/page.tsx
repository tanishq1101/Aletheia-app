"use client";

import { useEffect, useMemo, useState } from "react";
import ApiErrorNotice from "@/components/ApiErrorNotice";
import AnswerView from "@/components/AnswerView";
import DownloadReportButton from "@/components/DownloadReportButton";
import EmptyState from "@/components/EmptyState";
import ProjectSources from "@/components/ProjectSources";
import QuestionComposer from "@/components/QuestionComposer";
import {
  ApiError,
  createConversation,
  downloadAnswerPdf,
  listConversations,
  listMessages,
  sendMessage,
} from "@/lib/api";
import { followUpQuestions, openingQuestions } from "@/lib/suggestions";
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
    // Answers stored before this was recorded carry no flag. Assume
    // reproducible rather than accusing an old answer of something unproven.
    reproducible: metadata?.reproducible ?? true,
    // Stored with the answer, so a reopened thread offers the same next
    // questions rather than a fresh set derived from a partial record.
    follow_ups: metadata?.follow_ups,
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

  /** What to offer as the next question.
   *
   * After an answer, the offers are built from that answer's own evidence —
   * see `lib/suggestions`. Before one, they are built from the papers in the
   * project. Either way every suggestion names something this corpus holds,
   * rather than a topic it might not cover. */
  const suggestions = useMemo(() => {
    const lastAnswer = [...messages]
      .reverse()
      .find((message) => message.role === "assistant");
    return lastAnswer
      ? followUpQuestions(answerFromMessage(lastAnswer), papers)
      : openingQuestions(papers);
  }, [messages, papers]);

  const startNewThread = () => {
    setConversationId(null);
    setMessages([]);
    setError(null);
    setNeedsKey(false);
  };

  const submit = async () => {
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

      <QuestionComposer
        value={question}
        onChange={setQuestion}
        onSubmit={() => void submit()}
        suggestions={suggestions}
        disabled={!projectId}
        pending={pending}
        placeholder="What do these papers say about chunk size and retrieval quality?"
        footer={`${indexed} indexed paper${indexed === 1 ? "" : "s"} in ${project?.name ?? "this project"}`}
      />

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
              Answering needs a key for the enabled provider. In{" "}
              <span className="font-mono text-secondary">backend/.env</span>,
              enable exactly one of{" "}
              <span className="font-mono text-secondary">OPENAI_ENABLED</span>{" "}
              or{" "}
              <span className="font-mono text-secondary">GEMINI_ENABLED</span>,
              set its matching key, and restart the API. Search and the library
              work without it.
            </p>
          )}
        </div>
      )}

      <ProjectSources />

      {messages.length > 0 && (
        <div className="flex w-full flex-col items-start gap-8">
          {messages.map((message, index) => {
            if (message.role === "user") {
              return (
                <p
                  key={message.id}
                  className="font-ui text-[15px] font-semibold text-primary"
                >
                  {message.content}
                </p>
              );
            }
            const result = answerFromMessage(message);
            // The question this answered is the turn before it. A report
            // titled by its own answer would be unidentifiable in a folder.
            const asked =
              [...messages.slice(0, index)].reverse().find((m) => m.role === "user")
                ?.content ?? "";
            return (
              <div key={message.id} className="flex w-full flex-col items-start gap-3">
                <div className="flex w-full items-start justify-between gap-4">
                  {result.reproducible === false ? (
                    <p className="min-w-px flex-1 font-ui text-xs text-warning">
                      Not reproducible: {result.model} answers at its own sampling
                      setting rather than the deterministic one this app requests,
                      so the same question may be worded differently next time. The
                      cited passages are exact either way.
                    </p>
                  ) : (
                    <span className="min-w-px flex-1" />
                  )}
                  {projectId && (
                    <DownloadReportButton
                      title="This answer and every cited passage, as a PDF."
                      download={() =>
                        downloadAnswerPdf(projectId, asked, result, project?.name ?? "")
                      }
                    />
                  )}
                </div>
                <AnswerView result={result} />
              </div>
            );
          })}
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
