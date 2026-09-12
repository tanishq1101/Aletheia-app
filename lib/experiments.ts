/** The Training Lab's single source of truth for which models exist.
 *
 * The page used to inline this list, and the third model — the neural
 * relevance reranker — was simply never added to it: trained, evaluated and
 * invisible. The registry exists so "which experiments are there" is one
 * declaration that the page and the notebook download route both read,
 * instead of two hardcoded lists that drifted apart.
 *
 * Adding a fourth model means adding one entry here. `npm run typecheck`
 * fails if its artifacts are missing, so a half-added model cannot ship
 * looking complete. */

import relevanceModel from "@/backend/models/research/relevance/model.json";
import relevanceHistory from "@/backend/models/research/relevance/history.json";
import stanceModel from "@/backend/models/research/stance/model.json";
import stanceHistory from "@/backend/models/research/stance/history.json";
import rerankerModel from "@/backend/models/research/reranker/model.json";
import rerankerHistory from "@/backend/models/research/reranker/history.json";

/** One sampled epoch. `validation_loss` is absent only for a run trained with
 *  no held-out set — which none of the shipped models are. */
export type EpochPoint = {
  epoch: number;
  train_loss: number;
  validation_loss?: number;
};

type Common = {
  id: string;
  title: string;
  description: string;
  /** Filename under `colab/`, served by `/api/training/[task]`. */
  notebook: string;
  history: EpochPoint[];
  architecture: number[];
  seed: number;
  /** Shown verbatim. Every model here is advisory; none is a verdict. */
  caveat: string;
};

/** Predicts a label per example: judged by accuracy, macro F1 and a confusion
 *  matrix against a lexical baseline. */
export type ClassificationExperiment = Common & {
  kind: "classification";
  labels: string[];
  accuracy: number;
  macroF1: number;
  baselineAccuracy: number;
  confusionMatrix: number[][];
};

/** Orders candidates for one query: accuracy is close to meaningless, so it is
 *  judged by MRR and Recall@6 against the retrieval baseline it must beat. */
export type RankingExperiment = Common & {
  kind: "ranking";
  mrr: number;
  recallAt6: number;
  baselineMrr: number;
  baselineRecallAt6: number;
  validationAccuracy: number;
  trainExamples: number;
  validationExamples: number;
  trainPositive: number;
  validationPositive: number;
};

export type Experiment = ClassificationExperiment | RankingExperiment;

export const experiments: Experiment[] = [
  {
    kind: "classification",
    id: "relevance",
    title: "Evidence relevance",
    description:
      "Learns which passages answer a question, using SciQ and SQuAD.",
    notebook: "Aletheia_Multisource_Relevance_Colab.ipynb",
    history: relevanceHistory,
    architecture: relevanceModel.architecture,
    seed: relevanceModel.seed,
    labels: relevanceModel.labels,
    accuracy: relevanceModel.test.accuracy,
    macroF1: relevanceModel.test.macro_f1,
    baselineAccuracy: relevanceModel.baseline_test.accuracy,
    confusionMatrix: relevanceModel.test.confusion_matrix,
    caveat:
      "Outperformed a lexical overlap baseline on this dataset. Improvement over the production reranker has not been established.",
  },
  {
    kind: "classification",
    id: "stance",
    title: "Scientific claim stance",
    description:
      "Learns support versus contradiction from annotated SciFact abstracts.",
    notebook: "Aletheia_Scientific_Stance_Colab.ipynb",
    history: stanceHistory,
    architecture: stanceModel.architecture,
    seed: stanceModel.seed,
    labels: stanceModel.labels,
    accuracy: stanceModel.test.accuracy,
    macroF1: stanceModel.test.macro_f1,
    baselineAccuracy: stanceModel.baseline_test.accuracy,
    confusionMatrix: stanceModel.test.confusion_matrix,
    caveat:
      "Below the majority baseline on accuracy. Experimental only; do not use as a factual verdict.",
  },
  {
    kind: "ranking",
    id: "reranker",
    title: "Neural relevance reranker",
    description:
      "Reorders retrieved passages from five signals — cosine similarity, term overlap, numeric coverage, section match and passage length — trained on this project's own 150-question benchmark.",
    notebook: "Aletheia_Neural_Reranker_Colab.ipynb",
    history: rerankerHistory,
    architecture: rerankerModel.architecture,
    seed: rerankerModel.seed,
    mrr: rerankerModel.ranking.mrr,
    recallAt6: rerankerModel.ranking.recall_at_6,
    baselineMrr: rerankerModel.baseline_ranking.mrr,
    baselineRecallAt6: rerankerModel.baseline_ranking.recall_at_6,
    validationAccuracy: rerankerModel.ranking.accuracy,
    trainExamples: rerankerModel.counts.train,
    validationExamples: rerankerModel.counts.validation,
    trainPositive: rerankerModel.counts.train_positive,
    validationPositive: rerankerModel.counts.validation_positive,
    caveat:
      "Beat the cosine retrieval baseline on both ranking metrics, but on 41 held-out positives — the error bars are wide. Offline only: live retrieval still uses the production cross-encoder.",
  },
];

/** Notebook filenames keyed by experiment id, for the download route. */
export const notebooksByExperiment: Record<string, string> =
  Object.fromEntries(experiments.map(({ id, notebook }) => [id, notebook]));
