import { paperTitle } from "@/lib/display";
import type { AnswerResponse, Paper } from "@/types/api";

/** A question the composer will offer to complete, and why it is being
 *  offered. The reason is shown to the reader — a suggestion whose provenance
 *  is not visible is indistinguishable from an invented one, which is the
 *  thing this whole application exists to avoid. */
export type Suggestion = {
  text: string;
  reason: string;
};

const MAX_SUGGESTIONS = 4;

/** Titles get long, and a question is unusable once the title eats the line. */
function short(title: string, limit = 58): string {
  const clean = title.replace(/\s+/g, " ").trim();
  if (clean.length <= limit) return clean;
  return `${clean.slice(0, limit - 1).trimEnd()}…`;
}

function lower(first: string): string {
  // "Retrieval" → "retrieval", but leave "RAG" and "BM25" alone.
  return /^[A-Z][a-z]/.test(first) ? first[0].toLowerCase() + first.slice(1) : first;
}

function dedupe(suggestions: Suggestion[]): Suggestion[] {
  const seen = new Set<string>();
  const kept: Suggestion[] = [];
  for (const suggestion of suggestions) {
    const key = suggestion.text.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    kept.push(suggestion);
    if (kept.length === MAX_SUGGESTIONS) break;
  }
  return kept;
}

/** Where to start, before anything has been asked.
 *
 * Built from the papers actually in the project, so the offer is always one
 * the corpus can attempt — a generic "summarise the literature" prompt on an
 * empty library is a guaranteed "insufficient evidence". */
export function openingQuestions(papers: Paper[]): Suggestion[] {
  const ready = papers.filter((paper) => paper.status === "ready");
  if (ready.length === 0) return [];

  const named = ready.slice(0, 2).map((paper) => short(paperTitle(paper), 44));

  const suggestions: Suggestion[] = [
    {
      text: `What question does ${named[0]} set out to answer, and what did it find?`,
      reason: "a source in this project",
    },
  ];

  if (ready.length > 1) {
    suggestions.push({
      text: `Where do ${named[0]} and ${named[1]} agree, and where do they disagree?`,
      reason: `${ready.length} sources indexed`,
    });
  }

  suggestions.push(
    {
      text: "What method does each paper evaluate, and on which datasets?",
      reason: "across the whole project",
    },
    {
      text: "What limitations do these papers state about their own results?",
      reason: "across the whole project",
    },
  );

  return dedupe(suggestions);
}

/** What to ask next, given the answer just returned.
 *
 * The API writes these itself when it can: `follow_ups` comes from a model
 * that was shown the answer and every passage behind it, so it wins outright.
 * What follows is the fallback for when it cannot — the feature switched off,
 * the extra call failed, or a reply that did not meet the contract — and for
 * threads answered before the API did this.
 *
 * The fallback is anchored in what the backend actually returned: a paper it
 * retrieved from, a section it read, evidence it pulled and did not use.
 * Nothing here invents a topic the corpus has not been shown to contain. */
export function followUpQuestions(
  result: AnswerResponse,
  papers: Paper[],
): Suggestion[] {
  if (result.follow_ups?.length) {
    return dedupe(
      result.follow_ups.map((text) => ({ text, reason: "suggested by the model" })),
    );
  }

  const suggestions: Suggestion[] = [];
  const citedPaperIds = new Set(result.citations.map((c) => c.paper_id));

  const titleFor = (paperId: string, fallback: string | null) => {
    const paper = papers.find((candidate) => candidate.id === paperId);
    return short(paper ? paperTitle(paper) : (fallback ?? "that paper"), 44);
  };

  // The answer could not be supported. The useful next move is narrowing, not
  // another broad question that will fail the same way.
  if (!result.sufficient_evidence) {
    const nearest = result.evidence[0];
    if (nearest) {
      suggestions.push({
        text: `What does ${titleFor(nearest.paper_id, nearest.paper_title)} actually cover on this topic?`,
        reason: "closest passage retrieved",
      });
    }
    suggestions.push({
      text: "Which of my sources comes closest to addressing this, and what does it stop short of saying?",
      reason: "evidence was insufficient",
    });
  }

  // Passages the retriever found and the answer never used. These are the
  // most defensible leads on the page: real text, already in the context, and
  // demonstrably not yet accounted for.
  const uncited = result.evidence.filter(
    (item) => !result.citations.some((c) => c.evidence_id === item.evidence_id),
  );
  for (const item of uncited.slice(0, 2)) {
    const section = item.section?.trim();
    suggestions.push({
      text: section
        ? `What does ${titleFor(item.paper_id, item.paper_title)} say in ${lower(section)}?`
        : `What does ${titleFor(item.paper_id, item.paper_title)} add on ${item.location}?`,
      reason: "retrieved but not cited",
    });
  }

  // Two or more papers were cited, so a comparison is a question the corpus
  // has already proved it can source.
  const citedTitles = [...citedPaperIds].map((paperId) => {
    const citation = result.citations.find((c) => c.paper_id === paperId)!;
    return titleFor(paperId, citation.paper_title);
  });
  if (citedTitles.length > 1) {
    suggestions.push({
      text: `Where do ${citedTitles[0]} and ${citedTitles[1]} disagree on this?`,
      reason: "both cited above",
    });
  }

  // A cited section is a heading the model read. Asking for its evidence is
  // the natural "show your working" follow-up.
  const citedSection = result.citations.find((c) => c.section?.trim());
  if (citedSection?.section) {
    suggestions.push({
      text: `What evidence in ${lower(citedSection.section.trim())} supports that?`,
      reason: `cited from ${citedSection.location}`,
    });
  }

  suggestions.push({
    text: "What would have to be true for this conclusion to be wrong?",
    reason: "a check on the answer above",
  });

  return dedupe(suggestions);
}
