#!/usr/bin/env python3
"""Build the self-contained Google Colab notebook for the neural reranker.

The benchmark is embedded (compressed) in the resulting notebook so it can be
opened in Colab without a GitHub repository or a separate dataset upload.
Run this script from the repository root after changing the benchmark.
"""

from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path
from textwrap import dedent


ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "backend" / "datasets" / "benchmark" / "questions.json"
OUTPUT = ROOT / "colab" / "Aletheia_Neural_Reranker_Colab.ipynb"


def markdown(source: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": dedent(source).lstrip().splitlines(True)}


def code(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": dedent(source).lstrip().splitlines(True),
    }


def main() -> None:
    encoded_questions = base64.b64encode(
        gzip.compress(QUESTIONS.read_bytes(), mtime=0)
    ).decode("ascii")

    cells = [
        markdown(
            """
            # Aletheia — Neural Relevance Reranker

            This Colab notebook reproduces Aletheia's compact deep-learning
            experiment for research-paper retrieval. It downloads the pinned
            open-access arXiv corpus, extracts and chunks the papers, creates
            labelled query–passage candidates from the project benchmark, and
            trains a **5 → 16 → 8 → 1** PyTorch MLP to predict relevance.

            The comparison is intentionally honest: the held-out split is by
            question ID, so passages from a question cannot leak into both
            training and validation. The neural model is compared with the
            cosine-similarity retrieval baseline using MRR and Recall@6.

            **Runtime:** choose a standard CPU or GPU Colab runtime. A GPU is
            optional—the MLP is small; downloads and PDF extraction dominate.
            Expect roughly 5–15 minutes on a first run, depending on arXiv and
            model-cache speed.
            """
        ),
        markdown(
            """
            ## What makes this reproducible

            - The benchmark (150 questions over 10 papers) is embedded in this
              notebook, so there is no separate label-file upload.
            - The corpus is fetched directly from arXiv and each PDF is checked
              against its pinned SHA-256 hash.
            - Positive labels require both the expected paper and a labelled
              physical PDF page; labels are never inferred from the model.
            - The deterministic SHA-256 question split keeps evaluation separate
              from training.

            This is a feature-based neural reranker, not a transformer fine-tune.
            It is deliberately scoped to the model shipped by Aletheia and is
            evaluated before any production promotion decision is made.
            """
        ),
        code(
            """
            # Install only the dependency that is not guaranteed by Colab.
            !pip -q install pymupdf==1.28.2

            import base64
            import gzip
            import hashlib
            import json
            import math
            import random
            import re
            import time
            from pathlib import Path

            import fitz  # PyMuPDF
            import matplotlib.pyplot as plt
            import numpy as np
            import pandas as pd
            import requests
            import scipy.sparse as sp
            import torch
            from sklearn.feature_extraction.text import TfidfVectorizer

            SEED = 42
            random.seed(SEED)
            np.random.seed(SEED)
            torch.manual_seed(SEED)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(SEED)

            DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            WORKDIR = Path("/content/aletheia_neural_reranker")
            PDF_DIR = WORKDIR / "pdfs"
            OUTPUT_DIR = WORKDIR / "outputs"
            PDF_DIR.mkdir(parents=True, exist_ok=True)
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            print(f"Using {DEVICE}; artifacts will be saved to {OUTPUT_DIR}")
            """
        ),
        code(
            f"""
            # The checked-in Aletheia benchmark is embedded, compressed, below.
            # It contains 150 hand-written questions and page-level gold labels.
            ENCODED_BENCHMARK = "{encoded_questions}"
            benchmark = json.loads(gzip.decompress(base64.b64decode(ENCODED_BENCHMARK)))
            questions = benchmark["questions"]
            answerable_questions = [q for q in questions if q["answerable"]]
            print(f"Loaded {{len(questions)}} questions; {{len(answerable_questions)}} are answerable.")
            print(benchmark["description"])
            """
        ),
        code(
            """
            # Pinned Aletheia benchmark corpus: ten open-access arXiv PDFs.
            # The hashes make accidental corpus drift a hard failure.
            PAPERS = [
                ("attention", "1706.03762", "bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697"),
                ("resnet", "1512.03385", "1e0651b6810ecba34a3dbc5b5b0209226f889004607c1f203540a48d64e5a93a"),
                ("bert", "1810.04805", "5692a5514787a8c6727b4ff3b726a3385798bc68e12138d1d4af83947e2acf6e"),
                ("adam", "1412.6980", "eab9c73ae2ceda884b94830bda99312254bac4806f6c9f045cbab90721ecda31"),
                ("vgg", "1409.1556", "83728f9efc21081792902b4c17a4657022d1e4a92ec81655c2427f4ef0755e50"),
                ("batchnorm", "1502.03167", "bdc69e0b568f41d8d3181cc9077a461f58fcdd1c70c9f49efe60a05ee6109655"),
                ("rag", "2005.11401", "23e3249e9a1e75418d82efecab0ea8c4d033b89c93742f63208d47ce01f21233"),
                ("gpt3", "2005.14165", "97fd272f1fdfc18677462d0292f5fbf26ca86b4d1b485c2dba03269b643a0e83"),
                ("word2vec", "1301.3781", "a44d7e22d2005752271c9cc1929c6462d4c8270916b063977992a883e3a54362"),
                ("gan", "1406.2661", "ff5819e3a7b713c3bd3107b7de3d51fe0a347aa5d8444f0efdcf2345ef0a8b63"),
            ]

            def sha256(path):
                digest = hashlib.sha256()
                with open(path, "rb") as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(block)
                return digest.hexdigest()

            session = requests.Session()
            session.headers["User-Agent"] = "Aletheia-Colab-Reproducibility-Notebook/1.0"
            for index, (key, arxiv_id, expected_hash) in enumerate(PAPERS):
                destination = PDF_DIR / f"{key}.pdf"
                if not destination.exists():
                    print(f"Downloading {{key}} (arXiv:{{arxiv_id}})...")
                    response = session.get(f"https://arxiv.org/pdf/{{arxiv_id}}", timeout=180)
                    response.raise_for_status()
                    if not response.content.startswith(b"%PDF"):
                        raise RuntimeError(f"arXiv did not return a PDF for {{arxiv_id}}")
                    destination.write_bytes(response.content)
                    # Respect arXiv's guidance for automated clients.
                    if index < len(PAPERS) - 1:
                        time.sleep(3)
                actual_hash = sha256(destination)
                if actual_hash != expected_hash:
                    raise RuntimeError(
                        f"SHA-256 mismatch for {{destination.name}}: expected {{expected_hash}}, got {{actual_hash}}"
                    )
                print(f"✓ {{destination.name}} verified ({{destination.stat().st_size / 1_000_000:.1f}} MB)")
            """
        ),
        code(
            """
            # Extract page-aware chunks. Keeping page numbers is vital because
            # benchmark labels are tied to physical PDF pages, not volatile IDs.
            WORD_RE = re.compile(r"[A-Za-z0-9]+(?:\\.[0-9]+)?")
            HEADING_RE = re.compile(r"^(?:\\d+(?:\\.\\d+)*\\s+)?[A-Z][A-Za-z ,:/&()\\-]{3,80}$")

            def tokens(text):
                return set(WORD_RE.findall(text.lower()))

            def likely_heading(line):
                cleaned = " ".join(line.split())
                return bool(HEADING_RE.match(cleaned)) and len(cleaned.split()) <= 12

            def make_chunks(key, pdf_path, max_words=300, overlap=40):
                chunks = []
                document = fitz.open(pdf_path)
                active_section = "Unknown"
                for page_number, page in enumerate(document, start=1):
                    text = page.get_text("text")
                    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
                    for line in lines:
                        if likely_heading(line):
                            active_section = line
                    words = text.split()
                    start = 0
                    while start < len(words):
                        window = words[start : start + max_words]
                        content = " ".join(window).strip()
                        if len(content) > 80:
                            chunks.append({
                                "paper": key,
                                "page": page_number,
                                "section": active_section,
                                "content": content,
                            })
                        if start + max_words >= len(words):
                            break
                        start += max_words - overlap
                document.close()
                return chunks

            chunks = []
            for key, _, _ in PAPERS:
                chunks.extend(make_chunks(key, PDF_DIR / f"{key}.pdf"))

            chunks_frame = pd.DataFrame(chunks)
            print(f"Created {{len(chunks_frame):,}} chunks across {{chunks_frame.paper.nunique()}} papers.")
            display(chunks_frame.groupby("paper").size().rename("chunks").to_frame())
            """
        ),
        code(
            """
            # Build retrieval candidates using TF-IDF cosine similarity. The MLP
            # never sees the gold page during inference; pages only define labels.
            vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=2, max_features=60_000)
            chunk_matrix = vectorizer.fit_transform(chunks_frame.content)
            query_matrix = vectorizer.transform([q["question"] for q in answerable_questions])
            similarities = (query_matrix @ chunk_matrix.T).toarray()

            def candidate_features(query, row, cosine_similarity):
                query_tokens = tokens(query)
                content_tokens = tokens(row.content)
                union = query_tokens | content_tokens
                jaccard = len(query_tokens & content_tokens) / len(union) if union else 0.0
                numbers = {{token for token in query_tokens if any(char.isdigit() for char in token)}}
                numeric_coverage = len(numbers & content_tokens) / len(numbers) if numbers else 0.0
                section_overlap = len(query_tokens & tokens(row.section)) / len(query_tokens) if query_tokens else 0.0
                content_length_log = math.log1p(len(content_tokens)) / 10.0
                return [cosine_similarity, jaccard, numeric_coverage, section_overlap, content_length_log]

            TOP_K = 20
            examples = []
            for question_index, question in enumerate(answerable_questions):
                top_indexes = np.argsort(similarities[question_index])[-TOP_K:][::-1]
                for chunk_index in top_indexes:
                    row = chunks_frame.iloc[chunk_index]
                    examples.append({
                        "question_id": question["id"],
                        "paper": row.paper,
                        "page": int(row.page),
                        "cosine": float(similarities[question_index, chunk_index]),
                        "label": int(row.paper == question["paper"] and int(row.page) in question["expected_pages"]),
                        "features": candidate_features(question["question"], row, float(similarities[question_index, chunk_index])),
                    })

            examples_frame = pd.DataFrame(examples)
            print(f"Built {{len(examples_frame):,}} candidates with {{examples_frame.label.sum():,}} positives.")
            if examples_frame.label.sum() == 0:
                raise RuntimeError("No positive candidates were retrieved. Check corpus extraction or increase TOP_K.")
            """
        ),
        code(
            """
            # Split by question—not individual passages—to prevent leakage.
            def is_validation_question(question_id):
                return int(hashlib.sha256(question_id.encode()).hexdigest()[:8], 16) % 5 == 0

            examples_frame["validation"] = examples_frame.question_id.map(is_validation_question)
            train_frame = examples_frame[~examples_frame.validation].reset_index(drop=True)
            validation_frame = examples_frame[examples_frame.validation].reset_index(drop=True)
            assert train_frame.label.sum() > 0 and validation_frame.label.sum() > 0

            feature_columns = ["cosine", "jaccard", "numeric_coverage", "section_overlap", "content_length_log"]
            # Expand named feature columns from the compact list generated above.
            examples_frame[feature_columns] = pd.DataFrame(examples_frame.features.tolist(), index=examples_frame.index)
            train_frame = examples_frame[~examples_frame.validation].reset_index(drop=True)
            validation_frame = examples_frame[examples_frame.validation].reset_index(drop=True)

            mean = train_frame[feature_columns].mean().to_numpy(dtype=np.float32)
            scale = train_frame[feature_columns].std().to_numpy(dtype=np.float32)
            scale[scale < 1e-8] = 1.0
            x_train = ((train_frame[feature_columns].to_numpy(np.float32) - mean) / scale)
            x_validation = ((validation_frame[feature_columns].to_numpy(np.float32) - mean) / scale)
            y_train = train_frame.label.to_numpy(np.float32).reshape(-1, 1)
            y_validation = validation_frame.label.to_numpy(np.float32).reshape(-1, 1)

            print(f"Train: {{len(train_frame)}} candidates, {{int(y_train.sum())}} positive")
            print(f"Validation: {{len(validation_frame)}} candidates, {{int(y_validation.sum())}} positive")
            """
        ),
        code(
            """
            # Aletheia's compact neural relevance model: 5 → 16 → 8 → 1.
            class NeuralRelevanceMLP(torch.nn.Module):
                def __init__(self):
                    super().__init__()
                    self.network = torch.nn.Sequential(
                        torch.nn.Linear(5, 16), torch.nn.ReLU(),
                        torch.nn.Linear(16, 8), torch.nn.ReLU(),
                        torch.nn.Linear(8, 1),
                    )
                def forward(self, x):
                    return self.network(x)

            model = NeuralRelevanceMLP().to(DEVICE)
            x_train_t = torch.tensor(x_train, device=DEVICE)
            y_train_t = torch.tensor(y_train, device=DEVICE)
            x_validation_t = torch.tensor(x_validation, device=DEVICE)
            positive_weight = torch.tensor([(len(y_train) - y_train.sum()) / max(y_train.sum(), 1)], device=DEVICE)
            loss_function = torch.nn.BCEWithLogitsLoss(pos_weight=positive_weight)
            optimizer = torch.optim.Adam(model.parameters(), lr=0.01, weight_decay=1e-4)

            EPOCHS = 300
            loss_history = []
            for epoch in range(EPOCHS):
                model.train()
                optimizer.zero_grad()
                loss = loss_function(model(x_train_t), y_train_t)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)
                optimizer.step()
                loss_history.append(float(loss.item()))
                if (epoch + 1) % 50 == 0:
                    print(f"Epoch {{epoch + 1:3d}}/{{EPOCHS}} — weighted BCE: {{loss.item():.4f}}")

            model.eval()
            with torch.no_grad():
                neural_scores = torch.sigmoid(model(x_validation_t)).cpu().numpy().ravel()
            print("Training complete.")
            """
        ),
        code(
            """
            # Evaluate neural reranking against the original cosine baseline.
            def mean_reciprocal_rank(frame, score_column):
                reciprocal_ranks = []
                for _, group in frame.groupby("question_id", sort=False):
                    ranked = group.sort_values(score_column, ascending=False)
                    positive_positions = np.flatnonzero(ranked.label.to_numpy() == 1)
                    reciprocal_ranks.append(1 / (positive_positions[0] + 1) if len(positive_positions) else 0.0)
                return float(np.mean(reciprocal_ranks))

            def recall_at_k(frame, score_column, k=6):
                recalls = []
                for _, group in frame.groupby("question_id", sort=False):
                    total_positives = int(group.label.sum())
                    if total_positives:
                        recalls.append(group.nlargest(k, score_column).label.sum() / total_positives)
                return float(np.mean(recalls)) if recalls else 0.0

            evaluation = validation_frame.copy()
            evaluation["neural"] = neural_scores
            cosine_mrr = mean_reciprocal_rank(evaluation, "cosine")
            neural_mrr = mean_reciprocal_rank(evaluation, "neural")
            cosine_recall = recall_at_k(evaluation, "cosine")
            neural_recall = recall_at_k(evaluation, "neural")
            accuracy = float(((neural_scores >= 0.5) == y_validation.ravel()).mean())

            results = {
                "architecture": "5 -> 16 -> 8 -> 1 (ReLU, ReLU, sigmoid)",
                "feature_names": feature_columns,
                "seed": SEED,
                "candidate_top_k": TOP_K,
                "train_examples": int(len(train_frame)),
                "validation_examples": int(len(validation_frame)),
                "train_positive": int(train_frame.label.sum()),
                "validation_positive": int(validation_frame.label.sum()),
                "final_weighted_bce": loss_history[-1],
                "validation_accuracy": accuracy,
                "cosine_mrr": cosine_mrr,
                "neural_mrr": neural_mrr,
                "mrr_lift": neural_mrr - cosine_mrr,
                "cosine_recall_at_6": cosine_recall,
                "neural_recall_at_6": neural_recall,
                "recall_at_6_lift": neural_recall - cosine_recall,
            }
            results["recommended_for_future_blended_experiment"] = bool(
                results["mrr_lift"] > 0 and results["recall_at_6_lift"] >= 0
            )
            display(pd.DataFrame([
                ["MRR", cosine_mrr, neural_mrr, neural_mrr - cosine_mrr],
                ["Recall@6", cosine_recall, neural_recall, neural_recall - cosine_recall],
            ], columns=["Metric", "Cosine baseline", "Neural MLP", "Lift"]))
            print("Decision:", "eligible for a later blended-reranker experiment" if results["recommended_for_future_blended_experiment"] else "not promoted; keep the production reranker unchanged")
            """
        ),
        code(
            """
            # Save the trained model, normalisation statistics, metrics, and plots.
            model_path = OUTPUT_DIR / "neural_relevance_mlp.pt"
            torch.save({
                "state_dict": model.state_dict(),
                "architecture": [5, 16, 8, 1],
                "feature_names": feature_columns,
                "normalisation_mean": mean.tolist(),
                "normalisation_scale": scale.tolist(),
                "metrics": results,
            }, model_path)
            (OUTPUT_DIR / "metrics.json").write_text(json.dumps(results, indent=2) + "\\n")
            evaluation.drop(columns=["features"], errors="ignore").to_csv(OUTPUT_DIR / "held_out_predictions.csv", index=False)

            plt.figure(figsize=(8, 4))
            plt.plot(loss_history, color="#2563eb")
            plt.title("Neural relevance MLP training loss")
            plt.xlabel("Epoch")
            plt.ylabel("Weighted binary cross-entropy")
            plt.grid(alpha=0.25)
            plt.tight_layout()
            plt.savefig(OUTPUT_DIR / "training_loss.png", dpi=160)
            plt.show()

            print("Saved:")
            for artifact in sorted(OUTPUT_DIR.iterdir()):
                print(" -", artifact.name)

            # Optional: download all reproducibility artifacts to your computer.
            # from google.colab import files
            # files.download(str(OUTPUT_DIR / "metrics.json"))
            """
        ),
        markdown(
            """
            ## How to report this experiment

            Report the held-out MRR and Recall@6 against the cosine baseline,
            state the question-level split and the class imbalance, and retain
            `metrics.json`, `held_out_predictions.csv`, and the model checkpoint
            as your reproducibility artifacts. A gain here means the MLP is a
            candidate for a later blended-reranker experiment—it does **not**
            automatically replace Aletheia's production cross-encoder.
            """
        ),
    ]

    notebook = {
        "cells": cells,
        "metadata": {
            "colab": {"name": "Aletheia_Neural_Reranker_Colab.ipynb", "provenance": []},
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python"},
            "accelerator": "GPU",
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(notebook, indent=2) + "\n")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
