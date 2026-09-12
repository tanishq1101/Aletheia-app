#!/usr/bin/env python3
"""Train and evaluate Aletheia's local neural relevance experiment.

Examples are the real semantic candidates retrieved for answerable benchmark
questions. A candidate is positive only when its paper and physical PDF page
match a gold label. The held-out split is by question ID, so chunks from one
question cannot leak into both train and validation.

No API key is used. The embedding model and training both run locally.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

PROJECT_NAME = "Sprint 6 Benchmark Corpus"
MODEL_PATH = REPO_ROOT / "models" / "neural_relevance_model.json"
RESULTS_DIR = REPO_ROOT / "datasets" / "training" / "results"
# The Training Lab reads every experiment from models/research/<task>/. The
# reranker's weights stay in MODEL_PATH — this directory holds only what the
# page renders, so a UI import never drags a weight matrix into the bundle.
REPORT_DIR = REPO_ROOT / "models" / "research" / "reranker"


def _validation_question(question_id: str) -> bool:
    digest = hashlib.sha256(question_id.encode()).hexdigest()
    return int(digest[:8], 16) % 5 == 0


def _recall_at_k(
    question_ids: list[str], labels: np.ndarray, scores: np.ndarray, k: int
) -> float:
    values: list[float] = []
    for question_id in dict.fromkeys(question_ids):
        indexes = [i for i, value in enumerate(question_ids) if value == question_id]
        positives = sum(int(labels[index]) for index in indexes)
        if not positives:
            continue
        ranked = sorted(indexes, key=lambda index: float(scores[index]), reverse=True)[:k]
        values.append(sum(int(labels[index]) for index in ranked) / positives)
    return float(np.mean(values)) if values else 0.0


def _project() -> tuple[str, dict[str, str]]:
    from app.db.session import get_connection

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE name = %s", (PROJECT_NAME,))
        row = cur.fetchone()
        if row is None:
            raise SystemExit(
                f"No {PROJECT_NAME!r} project. Run scripts/ingest_corpus.py first."
            )
        project_id = str(row["id"])
        cur.execute(
            "SELECT id::text AS id, filename FROM papers WHERE project_id = %s",
            (project_id,),
        )
        papers = {
            paper["id"]: paper["filename"].removesuffix(".pdf")
            for paper in cur.fetchall()
        }
    return project_id, papers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epochs", type=int, default=500)
    parser.add_argument("--learning-rate", type=float, default=0.02)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    from app.services.benchmark import load_benchmark
    from app.services.retrieval import retrieve_candidates
    from app.services.training import (
        FEATURE_NAMES,
        binary_log_loss,
        candidate_features,
        mean_reciprocal_rank,
        train_neural_relevance_model,
    )
    from app.db.session import close_pool

    questions = [question for question in load_benchmark() if question.answerable]
    if args.limit:
        questions = questions[: args.limit]
    project_id, paper_by_id = _project()

    features: list[np.ndarray] = []
    labels: list[int] = []
    question_ids: list[str] = []
    cosine_scores: list[float] = []

    print(f"Building examples from {len(questions)} benchmark questions...")
    for index, question in enumerate(questions, 1):
        candidates = retrieve_candidates(
            project_id=project_id,
            query=question.question,
            top_k=args.top_k,
        )
        for candidate in candidates:
            features.append(candidate_features(question.question, candidate))
            labels.append(
                int(
                    paper_by_id.get(str(candidate.paper_id)) == question.paper
                    and candidate.page_number in question.expected_pages
                )
            )
            question_ids.append(question.id)
            cosine_scores.append(candidate.similarity)
        print("." if index % 40 else f" {index}/{len(questions)}")

    x = np.asarray(features, dtype=np.float64)
    y = np.asarray(labels, dtype=np.int64)
    cosine = np.asarray(cosine_scores, dtype=np.float64)
    validation = np.asarray([_validation_question(qid) for qid in question_ids])
    train = ~validation
    if not train.any() or not validation.any():
        raise SystemExit("The selected question set is too small for the stable split.")
    if y[train].sum() == 0 or y[validation].sum() == 0:
        raise SystemExit("Train and validation splits both need positive examples.")

    print(
        f"Training {len(FEATURE_NAMES)}→16→8→1 MLP on {train.sum()} examples "
        f"({int(y[train].sum())} positive); validating on {validation.sum()}."
    )
    model, history = train_neural_relevance_model(
        x[train],
        y[train],
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        seed=args.seed,
        validation=(x[validation], y[validation]),
    )
    probabilities = model.predict_proba(x[validation]).reshape(-1)
    val_labels = y[validation]
    val_question_ids = [
        question_id for question_id, held_out in zip(question_ids, validation, strict=True)
        if held_out
    ]
    baseline = cosine[validation]

    metrics = {
        "train_examples": int(train.sum()),
        "validation_examples": int(validation.sum()),
        "train_positive": int(y[train].sum()),
        "validation_positive": int(val_labels.sum()),
        "initial_train_loss": history.initial_loss,
        "final_train_loss": history.final_loss,
        "validation_log_loss": binary_log_loss(val_labels, probabilities),
        "validation_accuracy": float(np.mean((probabilities >= 0.5) == val_labels)),
        "cosine_mrr": mean_reciprocal_rank(val_question_ids, val_labels, baseline),
        "neural_mrr": mean_reciprocal_rank(val_question_ids, val_labels, probabilities),
        "cosine_recall_at_6": _recall_at_k(val_question_ids, val_labels, baseline, 6),
        "neural_recall_at_6": _recall_at_k(
            val_question_ids, val_labels, probabilities, 6
        ),
    }
    metrics["mrr_lift"] = metrics["neural_mrr"] - metrics["cosine_mrr"]
    metrics["recall_at_6_lift"] = (
        metrics["neural_recall_at_6"] - metrics["cosine_recall_at_6"]
    )
    recommended = metrics["mrr_lift"] > 0 and metrics["recall_at_6_lift"] >= 0

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    metadata = {
        "trained_at": timestamp,
        "dataset": "datasets/benchmark/questions.json",
        "project": PROJECT_NAME,
        "split": "sha256(question_id) modulo 5",
        "seed": args.seed,
        "epochs": args.epochs,
        "learning_rate": args.learning_rate,
        "candidate_top_k": args.top_k,
        "metrics": metrics,
        "recommended_for_production": recommended,
        "production_note": (
            "Candidate for a later blended reranker experiment."
            if recommended
            else "Does not beat the held-out cosine baseline; keep production reranker unchanged."
        ),
    }
    model.save(MODEL_PATH, metadata=metadata)
    _write_report(metadata, history.snapshots)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS_DIR / f"{timestamp}-neural-relevance.json"
    json_path.write_text(json.dumps(metadata, indent=2) + "\n")
    md_path = RESULTS_DIR / f"{timestamp}-neural-relevance.md"
    md_path.write_text(_report(metadata))

    print(_report(metadata))
    print(f"\nModel: {MODEL_PATH.relative_to(REPO_ROOT)}")
    print(f"Report: {md_path.relative_to(REPO_ROOT)}")
    close_pool()
    return 0


def _write_report(metadata: dict, snapshots: list[dict]) -> None:
    """Persist what the Training Lab renders, in the shape the other two use.

    Without this the learning curve simply does not exist: the per-epoch losses
    were computed and discarded, so the page had nothing to draw and the model
    was left off it entirely.
    """
    from app.services.training import FEATURE_NAMES

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    metrics = metadata["metrics"]
    (REPORT_DIR / "model.json").write_text(
        json.dumps(
            {
                "task": "reranker",
                "kind": "ranking",
                "architecture": [len(FEATURE_NAMES), 16, 8, 1],
                "seed": metadata["seed"],
                "epochs": metadata["epochs"],
                "learning_rate": metadata["learning_rate"],
                "trained_at": metadata["trained_at"],
                "dataset": metadata["dataset"],
                "split": metadata["split"],
                "feature_names": list(FEATURE_NAMES),
                "candidate_top_k": metadata["candidate_top_k"],
                "counts": {
                    "train": metrics["train_examples"],
                    "train_positive": metrics["train_positive"],
                    "validation": metrics["validation_examples"],
                    "validation_positive": metrics["validation_positive"],
                },
                "ranking": {
                    "mrr": metrics["neural_mrr"],
                    "recall_at_6": metrics["neural_recall_at_6"],
                    "log_loss": metrics["validation_log_loss"],
                    "accuracy": metrics["validation_accuracy"],
                },
                "baseline_ranking": {
                    "mrr": metrics["cosine_mrr"],
                    "recall_at_6": metrics["cosine_recall_at_6"],
                },
                "lift": {
                    "mrr": metrics["mrr_lift"],
                    "recall_at_6": metrics["recall_at_6_lift"],
                },
                "status": "experimental_advisory",
                "limitations": (
                    "Five hand-built features over retrieval candidates, not an "
                    "end-to-end fine-tune. The held-out set is 500 candidates from "
                    f"{metrics['validation_positive']} positives, so the ranking "
                    "gains carry wide error bars. Positives require both the "
                    "expected paper and the labelled physical page, so a correct "
                    "passage on an unlabelled page counts as a negative. Not "
                    "promoted over the production cross-encoder."
                ),
            },
            indent=2,
        )
        + "\n"
    )
    (REPORT_DIR / "history.json").write_text(json.dumps(snapshots, indent=2) + "\n")


def _report(metadata: dict) -> str:
    metrics = metadata["metrics"]
    recommendation = (
        "Eligible for a later blended-reranker experiment."
        if metadata["recommended_for_production"]
        else "Not promoted; the existing production cross-encoder remains unchanged."
    )
    return "\n".join([
        f"# Neural relevance training — {metadata['trained_at']}",
        "",
        "A locally trained NumPy MLP over real benchmark retrieval candidates. No hosted AI API was used.",
        "",
        "## Data and configuration",
        "",
        f"- train examples: {metrics['train_examples']} ({metrics['train_positive']} positive)",
        f"- validation examples: {metrics['validation_examples']} ({metrics['validation_positive']} positive)",
        f"- architecture: 5 → 16 → 8 → 1",
        f"- split: {metadata['split']}",
        f"- epochs / learning rate / seed: {metadata['epochs']} / {metadata['learning_rate']} / {metadata['seed']}",
        "",
        "## Held-out results",
        "",
        "| Metric | Cosine baseline | Neural model | Lift |",
        "|---|---:|---:|---:|",
        f"| MRR | {metrics['cosine_mrr']:.3f} | {metrics['neural_mrr']:.3f} | {metrics['mrr_lift']:+.3f} |",
        f"| Recall@6 | {metrics['cosine_recall_at_6']:.3f} | {metrics['neural_recall_at_6']:.3f} | {metrics['recall_at_6_lift']:+.3f} |",
        "",
        f"Validation log loss: {metrics['validation_log_loss']:.4f} · accuracy: {metrics['validation_accuracy']:.3f}",
        f"Training loss: {metrics['initial_train_loss']:.4f} → {metrics['final_train_loss']:.4f}",
        "",
        f"**Decision:** {recommendation}",
        "",
        "This is a compact feature-based neural experiment, not an end-to-end transformer fine-tune. A GPU-scale fine-tune needs a larger labelled query/passage dataset and a separately approved compute budget.",
        "",
    ])


if __name__ == "__main__":
    raise SystemExit(main())
