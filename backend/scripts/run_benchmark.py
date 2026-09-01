#!/usr/bin/env python3
"""Run the Sprint 6 evaluation benchmark and record the result.

Measures what PRD Section 12 asks for, and keeps the two halves separate:

    retrieval  -- recall@k, MRR, and the lift reranking actually contributes
    answering  -- correctness, citation accuracy, faithfulness, refusals
    latency    -- per stage, not one opaque total

**Retrieval metrics never need an LLM and always run.** Answer metrics need
one, and skip with a stated reason when no key is configured rather than
reporting zeros that look like failures. Sprint 4 deliberately kept `/search`
and `/answer` as separate endpoints so exactly this split is possible.

    python scripts/run_benchmark.py                 # everything available
    python scripts/run_benchmark.py --retrieval-only
    python scripts/run_benchmark.py --limit 20      # smoke run
    python scripts/run_benchmark.py --paper bert
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

RESULTS_DIR = REPO_ROOT / "datasets" / "benchmark" / "results"
PROJECT_NAME = "Sprint 6 Benchmark Corpus"


def _now() -> float:
    return time.perf_counter() * 1000.0


def resolve_project_and_papers() -> tuple[str, dict[str, str]]:
    """Returns (project_id, {paper_id: manifest_key})."""
    from app.db.session import get_connection

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE name = %s", (PROJECT_NAME,))
        row = cur.fetchone()
        if row is None:
            raise SystemExit(
                f"No project {PROJECT_NAME!r}. Run scripts/ingest_corpus.py first."
            )
        project_id = str(row["id"])
        cur.execute(
            "SELECT id::text AS id, filename FROM papers WHERE project_id = %s",
            (project_id,),
        )
        papers = {r["id"]: r["filename"].removesuffix(".pdf") for r in cur.fetchall()}
    return project_id, papers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--limit", type=int, help="run only the first N questions")
    parser.add_argument("--paper", help="restrict to one manifest key")
    parser.add_argument("--top-k", type=int, help="override candidate count")
    parser.add_argument("--rerank-top-k", type=int, help="override evidence count")
    parser.add_argument("--label", default="", help="short name for this run")
    args = parser.parse_args()

    from app.core.config import get_settings
    from app.services.answering import answer_question
    from app.services.benchmark import load_benchmark
    from app.services.evaluation import (
        CitationCheck,
        LatencyBreakdown,
        MetricAccumulator,
        PageRef,
        answer_correctness,
        citation_accuracy,
        evidence_sufficiency,
        handled_unanswerable,
        hit_at_k,
        percentile,
        recall_at_k,
        reciprocal_rank,
        rerank_lift,
        uncited_claim_ratio,
    )
    from app.services.llm import LLMConfigurationError, LLMError, build_llm_provider
    from app.services.reranking import build_reranker
    from app.services.retrieval import retrieve_candidates

    settings = get_settings()
    candidate_k = args.top_k or settings.search_top_k
    evidence_k = args.rerank_top_k or settings.rerank_top_k

    questions = load_benchmark()
    if args.paper:
        questions = [q for q in questions if q.paper == args.paper]
    if args.limit:
        questions = questions[: args.limit]
    if not questions:
        raise SystemExit("No questions selected.")

    # --- decide up front whether answer metrics can run, and say why ---------
    llm = None
    llm_skip_reason = ""
    if args.retrieval_only:
        llm_skip_reason = "--retrieval-only was passed"
    else:
        try:
            llm = build_llm_provider()
        except LLMConfigurationError as exc:
            # Stated, not silently reported as zeros: a 0% correctness score
            # and an unrun correctness score are completely different facts.
            llm_skip_reason = str(exc)

    project_id, paper_by_id = resolve_project_and_papers()
    reranker = build_reranker()

    print(f"Benchmark: {len(questions)} question(s)")
    print(f"  candidates k={candidate_k}, evidence k={evidence_k}")
    print(f"  answer metrics: {'ON' if llm else 'SKIPPED — ' + llm_skip_reason}\n")

    acc = {
        name: MetricAccumulator(name)
        for name in (
            "recall_at_k",
            "hit_at_k",
            "mrr",
            "recall_before_rerank",
            "mrr_before_rerank",
            "recall_lift",
            "mrr_lift",
            "evidence_sufficiency",
            "answer_correct",
            "keyword_recall",
            "citation_precision",
            "citations_resolvable",
            "uncited_claim_ratio",
            "declined_correctly",
        )
    }
    latencies: list[LatencyBreakdown] = []
    fabricated_total = 0
    per_question: list[dict] = []
    errors: list[str] = []

    for index, q in enumerate(questions, 1):
        record: dict = {
            "id": q.id,
            "paper": q.paper,
            "category": q.category,
            "answerable": q.answerable,
            "question": q.question,
            "expected_pages": q.expected_pages,
        }
        timing = LatencyBreakdown()
        started = _now()

        # --- retrieval (always) ---------------------------------------------
        try:
            t0 = _now()
            candidates = retrieve_candidates(
                project_id=project_id, query=q.question, top_k=candidate_k
            )
            timing.retrieve_ms = _now() - t0
        except Exception as exc:
            errors.append(f"{q.id}: retrieval failed: {exc}")
            record["error"] = f"retrieval: {exc}"
            per_question.append(record)
            continue

        before = [
            PageRef(paper=paper_by_id.get(str(c.paper_id), "?"), page=c.page_number)
            for c in candidates
        ]

        # --- reranking (always) ---------------------------------------------
        try:
            t0 = _now()
            by_id = {str(c.chunk_id): c for c in candidates}
            scored = reranker.rerank(
                query=q.question,
                chunks=[(str(c.chunk_id), c.content) for c in candidates],
                top_k=evidence_k,
            )
            timing.rerank_ms = _now() - t0
        except Exception as exc:
            errors.append(f"{q.id}: reranking failed: {exc}")
            record["error"] = f"rerank: {exc}"
            per_question.append(record)
            continue

        ranked = [(by_id[s.chunk_id], s.score) for s in scored]
        after = [
            PageRef(paper=paper_by_id.get(str(c.paper_id), "?"), page=c.page_number)
            for c, _ in ranked
        ]

        # Retrieval quality is only meaningful where gold exists. An
        # unanswerable question has none by construction, so it is excluded
        # rather than scored 0 and dragged through the average.
        if q.answerable:
            gold = q.gold
            lift = rerank_lift(before=before, after=after, gold=gold, k=evidence_k)
            record["retrieval"] = {
                "recall_at_k": recall_at_k(after, gold, evidence_k),
                "hit_at_k": hit_at_k(after, gold, evidence_k),
                "mrr": reciprocal_rank(after, gold),
                **lift,
                "retrieved_pages": [str(r) for r in after],
            }
            acc["recall_at_k"].add(record["retrieval"]["recall_at_k"])
            acc["hit_at_k"].add(record["retrieval"]["hit_at_k"])
            acc["mrr"].add(record["retrieval"]["mrr"])
            acc["recall_before_rerank"].add(lift["recall_before"])
            acc["mrr_before_rerank"].add(lift["mrr_before"])
            acc["recall_lift"].add(lift["recall_lift"])
            acc["mrr_lift"].add(lift["mrr_lift"])

            # Needs no LLM, so it runs even in retrieval-only mode. This is
            # the ceiling on answer correctness: the model cannot ground an
            # answer in evidence it was never handed.
            sufficient = evidence_sufficiency(
                evidence_text="\n".join(c.content for c, _ in ranked),
                must_contain=q.must_contain,
            )
            record["retrieval"]["evidence_sufficiency"] = sufficient
            acc["evidence_sufficiency"].add(1.0 if sufficient else 0.0)

        # --- answering (only with a provider) --------------------------------
        if llm is not None:
            try:
                t0 = _now()
                result = answer_question(
                    project_id=project_id,
                    question=q.question,
                    llm=llm,
                    top_k=candidate_k,
                    rerank_top_k=evidence_k,
                )
                # Retrieval and reranking are re-done inside answer_question, so
                # subtract them to isolate the model's own round trip.
                timing.llm_ms = max(
                    0.0, (_now() - t0) - timing.retrieve_ms - timing.rerank_ms
                )
            except (LLMError, Exception) as exc:
                errors.append(f"{q.id}: answering failed: {exc}")
                record["error"] = f"answer: {exc}"
                timing.total_ms = _now() - started
                record["latency"] = timing.as_dict()
                per_question.append(record)
                continue

            fabricated_total += result.fabricated_citations_removed
            answer_record: dict = {
                "answer": result.answer,
                "sufficient_evidence": result.sufficient_evidence,
                "fabricated_citations_removed": result.fabricated_citations_removed,
                "citations": [
                    {
                        "evidence_id": c.evidence_id,
                        "paper": paper_by_id.get(c.paper_id, "?"),
                        "page": c.page_number,
                        "section": c.section,
                    }
                    for c in result.citations
                ],
            }

            if q.answerable:
                correctness = answer_correctness(
                    answer=result.answer,
                    must_contain=q.must_contain,
                    must_not_contain=q.must_not_contain,
                )
                checks = [
                    CitationCheck(
                        paper=paper_by_id.get(c.paper_id),
                        page=c.page_number,
                        resolves=bool(c.chunk_id and c.paper_id),
                    )
                    for c in result.citations
                ]
                cites = citation_accuracy(
                    citations=checks,
                    gold=q.gold,
                    fabricated_removed=result.fabricated_citations_removed,
                )
                uncited = uncited_claim_ratio(result.answer)
                answer_record.update(
                    {
                        "correct": correctness.correct,
                        "keyword_recall": correctness.keyword_recall,
                        "missing_terms": correctness.missing,
                        "citation_precision": cites.precision,
                        "citations_on_gold_page": cites.on_gold_page,
                        "uncited_claim_ratio": uncited,
                    }
                )
                acc["answer_correct"].add(1.0 if correctness.correct else 0.0)
                acc["keyword_recall"].add(correctness.keyword_recall)
                if cites.total:
                    acc["citation_precision"].add(cites.precision)
                    acc["citations_resolvable"].add(cites.resolvable / cites.total)
                acc["uncited_claim_ratio"].add(uncited)
            else:
                declined = handled_unanswerable(
                    sufficient_evidence=result.sufficient_evidence
                )
                answer_record["declined_correctly"] = declined
                acc["declined_correctly"].add(1.0 if declined else 0.0)

            record["answer"] = answer_record

        timing.total_ms = _now() - started
        record["latency"] = timing.as_dict()
        latencies.append(timing)
        per_question.append(record)

        mark = "."
        if "error" in record:
            mark = "E"
        elif q.answerable and record.get("retrieval", {}).get("hit_at_k") == 0.0:
            mark = "r"  # retrieval missed every gold page
        print(mark, end="", flush=True)
        if index % 50 == 0:
            print(f"  {index}/{len(questions)}")

    print("\n")

    # --- summary -------------------------------------------------------------
    answerable = [q for q in questions if q.answerable]
    unanswerable = [q for q in questions if not q.answerable]
    totals = [lat.total_ms for lat in latencies]
    llm_times = [lat.llm_ms for lat in latencies if lat.llm_ms > 0]

    summary = {
        "questions": len(questions),
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
        "errors": len(errors),
        "config": {
            "candidate_k": candidate_k,
            "evidence_k": evidence_k,
            "chunk_max_tokens": settings.chunk_max_tokens,
            "chunk_overlap_tokens": settings.chunk_overlap_tokens,
            "embedding_context_max_tokens": settings.context_max_tokens,
            "rerank_model": settings.rerank_model,
            "llm_model": settings.openrouter_model if llm else None,
        },
        "retrieval": {
            f"recall_at_{evidence_k}": acc["recall_at_k"].mean,
            f"hit_at_{evidence_k}": acc["hit_at_k"].mean,
            "mrr": acc["mrr"].mean,
            "recall_before_rerank": acc["recall_before_rerank"].mean,
            "mrr_before_rerank": acc["mrr_before_rerank"].mean,
            "recall_lift": acc["recall_lift"].mean,
            "mrr_lift": acc["mrr_lift"].mean,
            "evidence_sufficiency": acc["evidence_sufficiency"].mean,
            "scored_questions": acc["recall_at_k"].count,
        },
        "answering": (
            {
                "correctness": acc["answer_correct"].mean,
                "keyword_recall": acc["keyword_recall"].mean,
                "scored_questions": acc["answer_correct"].count,
            }
            if llm
            else {"skipped": llm_skip_reason}
        ),
        "citations": (
            {
                "precision_on_gold_page": acc["citation_precision"].mean,
                "resolvable": acc["citations_resolvable"].mean,
                "fabricated_total": fabricated_total,
                "zero_fabricated": fabricated_total == 0,
            }
            if llm
            else {"skipped": llm_skip_reason}
        ),
        "faithfulness": (
            {
                "uncited_claim_ratio": acc["uncited_claim_ratio"].mean,
                "unanswerable_declined": acc["declined_correctly"].mean,
                "unanswerable_scored": acc["declined_correctly"].count,
            }
            if llm
            else {"skipped": llm_skip_reason}
        ),
        "latency": {
            "total_p50_ms": percentile(totals, 50),
            "total_p95_ms": percentile(totals, 95),
            "retrieve_p50_ms": percentile([x.retrieve_ms for x in latencies], 50),
            "rerank_p50_ms": percentile([x.rerank_ms for x in latencies], 50),
            "llm_p50_ms": percentile(llm_times, 50),
            "llm_p95_ms": percentile(llm_times, 95),
        },
    }

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = f"{stamp}{'-' + args.label if args.label else ''}"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "run": name,
        "timestamp": datetime.now(UTC).isoformat(),
        "summary": summary,
        "errors": errors,
        "questions": per_question,
    }
    json_path = RESULTS_DIR / f"{name}.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    md_path = RESULTS_DIR / f"{name}.md"
    md_path.write_text(render_report(payload))

    print(render_report(payload))
    print(f"\nWrote {json_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {md_path.relative_to(REPO_ROOT)}")
    return 1 if errors else 0


def render_report(payload: dict) -> str:
    """Markdown report. Kept next to the JSON so a run is readable without a
    parser, and comparable to the previous run without re-running anything."""
    s = payload["summary"]
    cfg = s["config"]
    ev_k = cfg["evidence_k"]
    lines = [
        f"# Benchmark run {payload['run']}",
        "",
        f"{s['questions']} questions ({s['answerable']} answerable, "
        f"{s['unanswerable']} unanswerable) · {s['errors']} error(s)",
        "",
        "## Configuration",
        "",
        "| Setting | Value |",
        "|---|---|",
        f"| candidate k (pre-rerank) | {cfg['candidate_k']} |",
        f"| evidence k (post-rerank) | {ev_k} |",
        f"| chunk size / overlap | {cfg['chunk_max_tokens']} / "
        f"{cfg['chunk_overlap_tokens']} tokens |",
        f"| reranker | `{cfg['rerank_model']}` |",
        f"| LLM | {'`' + cfg['llm_model'] + '`' if cfg['llm_model'] else '_not run_'} |",
        "",
        "## Retrieval",
        "",
        "Gold labels are page-level. \"Before\" is the raw semantic candidate order,",
        f"\"after\" is post-rerank, both measured at k={ev_k}.",
        "",
        "| Metric | Before rerank | After rerank | Lift |",
        "|---|---|---|---|",
    ]
    r = s["retrieval"]
    lines += [
        f"| recall@{ev_k} | {r['recall_before_rerank']:.3f} | "
        f"{r[f'recall_at_{ev_k}']:.3f} | {r['recall_lift']:+.3f} |",
        f"| MRR | {r['mrr_before_rerank']:.3f} | {r['mrr']:.3f} | "
        f"{r['mrr_lift']:+.3f} |",
        "",
        f"hit@{ev_k} (any gold page retrieved): **{r[f'hit_at_{ev_k}']:.3f}** "
        f"over {r['scored_questions']} answerable questions.",
        "",
        f"**Evidence sufficiency: {r['evidence_sufficiency']:.3f}** — the fraction of "
        "questions whose assembled evidence blocks actually contain every required",
        "answer term. This is the ceiling on answer correctness: no model can ground an "
        "answer in evidence it was never handed, so the gap between this and",
        "correctness below is the model's own contribution, and the gap between this and "
        "1.0 is retrieval's.",
        "",
    ]

    for title, block, rows in (
        (
            "Answering",
            s["answering"],
            [
                ("correctness (all required terms present)", "correctness"),
                ("keyword recall (partial credit)", "keyword_recall"),
            ],
        ),
        (
            "Citations",
            s["citations"],
            [
                ("precision (cited page is a gold page)", "precision_on_gold_page"),
                ("resolvable to chunk -> page -> paper", "resolvable"),
            ],
        ),
        (
            "Faithfulness",
            s["faithfulness"],
            [
                ("uncited claim ratio (lower is better)", "uncited_claim_ratio"),
                ("unanswerable questions declined", "unanswerable_declined"),
            ],
        ),
    ):
        lines += [f"## {title}", ""]
        if "skipped" in block:
            lines += [f"_Not measured: {block['skipped']}_", ""]
            continue
        lines += ["| Metric | Value |", "|---|---|"]
        for label, key in rows:
            lines.append(f"| {label} | {block[key]:.3f} |")
        if title == "Citations":
            lines.append(
                f"| **fabricated citation IDs (PRD 12: must be 0)** | "
                f"**{block['fabricated_total']}** |"
            )
        lines.append("")

    lat = s["latency"]
    lines += [
        "## Latency",
        "",
        "| Stage | p50 | p95 |",
        "|---|---|---|",
        f"| retrieve | {lat['retrieve_p50_ms']:.0f} ms | — |",
        f"| rerank | {lat['rerank_p50_ms']:.0f} ms | — |",
        f"| LLM | {lat['llm_p50_ms']:.0f} ms | {lat['llm_p95_ms']:.0f} ms |",
        f"| **end to end** | **{lat['total_p50_ms']:.0f} ms** | "
        f"**{lat['total_p95_ms']:.0f} ms** |",
        "",
    ]

    if payload["errors"]:
        lines += ["## Errors", ""]
        lines += [f"- {e}" for e in payload["errors"][:20]]
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
