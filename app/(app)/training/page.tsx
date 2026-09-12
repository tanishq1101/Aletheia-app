import type { EpochPoint, Experiment } from "@/lib/experiments";
import { experiments } from "@/lib/experiments";

/** Learning curve. Both lines are the same weighted loss on different splits,
 *  so they share one scale — the gap between them is the whole point, and
 *  normalising them separately would hide it. */
function LearningCurve({ title, history }: { title: string; history: EpochPoint[] }) {
  const values = history.flatMap(point =>
    point.validation_loss === undefined
      ? [point.train_loss]
      : [point.train_loss, point.validation_loss],
  );
  const ceiling = Math.max(...values, 0.1) * 1.05;
  const span = Math.max(history.length - 1, 1);
  const line = (pick: (point: EpochPoint) => number | undefined) => {
    const points = history
      .map((point, index) => [index, pick(point)] as const)
      .filter((pair): pair is readonly [number, number] => pair[1] !== undefined)
      .map(([index, value]) => `${40 + (index * 480) / span},${190 - (150 * value) / ceiling}`);
    return points.length ? points.join(" ") : undefined;
  };

  const validation = line(point => point.validation_loss);

  return (
    <figure>
      <figcaption className="mb-2 text-sm font-semibold">Learning curves</figcaption>
      <svg
        viewBox="0 0 560 230"
        role="img"
        aria-label={`${title}: training${validation ? " and validation" : ""} loss over ${history.at(-1)?.epoch ?? history.length} epochs`}
        className="w-full"
      >
        <path d="M40 25V190H530" fill="none" stroke="currentColor" opacity="0.3" />
        <polyline fill="none" stroke="#b39a64" strokeWidth="3" points={line(point => point.train_loss)} />
        {validation ? (
          <polyline fill="none" stroke="#91a1ca" strokeWidth="3" points={validation} />
        ) : null}
        <g fill="currentColor" fontSize="12">
          <text x="6" y="30">{ceiling.toFixed(1)}</text>
          <text x="16" y="190">0</text>
          <text x="40" y="217">Epoch {history[0]?.epoch ?? 1}</text>
          <text x="455" y="217">Epoch {history.at(-1)?.epoch ?? history.length}</text>
        </g>
      </svg>
      <p className="text-xs text-muted">
        Gold: training loss{validation ? " · Blue: validation loss" : ""} · Lower is better
      </p>
    </figure>
  );
}

function Metric({ value, label, large = false }: { value: string; label: string; large?: boolean }) {
  return (
    <div>
      <p className={large ? "font-mono text-3xl text-brass" : "font-mono text-xl"}>{value}</p>
      <p className="mt-1 text-xs text-muted">{label}</p>
    </div>
  );
}

const percent = (value: number) => `${(value * 100).toFixed(2)}%`;

/** Headline numbers. A ranking model has no meaningful accuracy and a
 *  classifier has no MRR, so each is shown on the metrics it is actually
 *  judged by rather than forced into a shared row. */
function Headline({ experiment }: { experiment: Experiment }) {
  if (experiment.kind === "classification") {
    return (
      <div className="flex flex-wrap items-end gap-6">
        <Metric large value={percent(experiment.accuracy)} label="Test accuracy" />
        <Metric value={experiment.macroF1.toFixed(3)} label="Macro F1" />
        <Metric value={percent(experiment.baselineAccuracy)} label="Baseline accuracy" />
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-end gap-6">
      <Metric large value={experiment.mrr.toFixed(3)} label="Held-out MRR" />
      <Metric value={experiment.recallAt6.toFixed(3)} label="Recall@6" />
      <Metric value={experiment.baselineMrr.toFixed(3)} label="Baseline MRR" />
    </div>
  );
}

function ConfusionMatrix({ labels, matrix }: { labels: string[]; matrix: number[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <caption className="mb-2 text-left font-semibold">
          Confusion matrix — actual rows, predicted columns
        </caption>
        <thead>
          <tr>
            <th className="p-2">Actual</th>
            {labels.map(label => (
              <th key={label} className="p-2">{label.replaceAll("_", " ")}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, index) => (
            <tr key={index} className="border-t border-hairline">
              <th className="p-2 font-normal">{labels[index].replaceAll("_", " ")}</th>
              {row.map((count, column) => (
                <td key={column} className="p-2 font-mono">{count}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The ranking equivalent of a confusion matrix: what the model must beat, by
 *  how much, on the two metrics that decide whether reordering helped. */
function RankingComparison({ experiment }: { experiment: Extract<Experiment, { kind: "ranking" }> }) {
  const rows = [
    { metric: "MRR", baseline: experiment.baselineMrr, model: experiment.mrr },
    { metric: "Recall@6", baseline: experiment.baselineRecallAt6, model: experiment.recallAt6 },
  ];
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <caption className="mb-2 text-left font-semibold">
          Held-out ranking vs the cosine retrieval baseline
        </caption>
        <thead>
          <tr>
            <th className="p-2">Metric</th>
            <th className="p-2">Cosine baseline</th>
            <th className="p-2">Neural model</th>
            <th className="p-2">Lift</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ metric, baseline, model }) => (
            <tr key={metric} className="border-t border-hairline">
              <th className="p-2 font-normal">{metric}</th>
              <td className="p-2 font-mono">{baseline.toFixed(3)}</td>
              <td className="p-2 font-mono">{model.toFixed(3)}</td>
              <td className="p-2 font-mono text-brass">{(model - baseline >= 0 ? "+" : "") + (model - baseline).toFixed(3)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-muted">
        {experiment.trainExamples.toLocaleString()} training candidates ({experiment.trainPositive} positive) ·{" "}
        {experiment.validationExamples.toLocaleString()} held out ({experiment.validationPositive} positive) ·
        validation accuracy {percent(experiment.validationAccuracy)}
      </p>
    </div>
  );
}

export default function TrainingPage() {
  return (
    <div className="w-full space-y-8">
      <header className="space-y-2">
        <p className="font-mono text-xs uppercase tracking-widest text-brass">Models &amp; evidence</p>
        <h1 className="font-display text-3xl font-semibold">Training Lab</h1>
        <p className="max-w-3xl text-sm leading-7 text-secondary">
          {experiments.length} trained models, four public and in-house datasets, and a reproducible
          Colab notebook for each. Every number below comes from held-out examples. The two
          classifiers run as experimental diagnostics inside research answers; the reranker is an
          offline experiment and does not touch live retrieval. None of them is a verdict.
        </p>
      </header>

      <div className="grid gap-5 lg:grid-cols-2">
        {experiments.map(experiment => (
          <section
            key={experiment.id}
            className="min-w-0 space-y-5 rounded-lg border border-hairline bg-surface p-6"
          >
            <div>
              <h2 className="font-display text-xl font-semibold">{experiment.title}</h2>
              <p className="mt-2 text-sm leading-6 text-secondary">{experiment.description}</p>
            </div>

            <Headline experiment={experiment} />

            <p className="text-sm italic text-secondary">{experiment.caveat}</p>

            <LearningCurve title={experiment.title} history={experiment.history} />

            {experiment.kind === "classification" ? (
              <ConfusionMatrix labels={experiment.labels} matrix={experiment.confusionMatrix} />
            ) : (
              <RankingComparison experiment={experiment} />
            )}

            <p className="text-xs text-muted">
              Architecture: {experiment.architecture.join(" → ")} · Seed {experiment.seed} ·{" "}
              {experiment.kind === "classification"
                ? "Validation-selected checkpoint"
                : "Question-level split, so no passage leaks across it"}
            </p>

            <a
              href={`/api/training/${experiment.id}`}
              className="inline-block rounded border border-brass px-4 py-2 text-sm font-semibold text-brass hover:bg-surface-raised"
            >
              Download {experiment.title.toLowerCase()} Colab notebook
            </a>
          </section>
        ))}
      </div>

      <section className="space-y-3 rounded-lg border border-hairline p-6">
        <h2 className="font-display text-xl font-semibold">Understand the data</h2>
        <p className="text-sm leading-7 text-secondary">
          <strong>24,759 training and evaluation pairs</strong> across the two classification tasks,
          plus <strong>2,420 retrieval candidates</strong> from this project&apos;s own 150-question
          benchmark for the reranker. Shared questions and documents stay within one split; training
          fails if a normalized question or passage leaks between splits, and the reranker splits by
          question ID so no passage from a question can appear on both sides. Relevance negatives are
          sampled and may include incorrect labels. These are custom research splits, not official
          leaderboard results.
        </p>
        <p className="text-sm leading-7 text-secondary">
          <a className="text-brass underline" href="https://huggingface.co/datasets/allenai/sciq">SciQ</a> · CC BY-NC 3.0;{" "}
          <a className="text-brass underline" href="https://rajpurkar.github.io/SQuAD-explorer/">SQuAD</a> · CC BY-SA 4.0;{" "}
          <a className="text-brass underline" href="https://github.com/allenai/scifact/blob/master/LICENSE.md">SciFact</a> · claims CC BY 4.0, abstracts ODC-By 1.0; reranker benchmark: ten open-access arXiv papers, pinned by SHA-256.
        </p>
        <p className="text-sm italic text-secondary">
          All three notebooks were executed locally through every cell. A hosted Colab run has not
          been performed. Open a downloaded notebook in Colab and choose Run all; CPU is sufficient.
        </p>
      </section>
    </div>
  );
}
