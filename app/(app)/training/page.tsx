import relevance from "@/backend/models/research/relevance/model.json";
import stance from "@/backend/models/research/stance/model.json";
import relevanceHistory from "@/backend/models/research/relevance/history.json";
import stanceHistory from "@/backend/models/research/stance/history.json";

const experiments = [
  { id: "relevance", title: "Evidence relevance", model: relevance, history: relevanceHistory, description: "Learns which passages answer a question, using SciQ and SQuAD." },
  { id: "stance", title: "Scientific claim stance", model: stance, history: stanceHistory, description: "Learns support versus contradiction from annotated SciFact abstracts." },
];

export default function TrainingPage() {
  return <div className="w-full space-y-8">
    <header className="space-y-2"><p className="font-mono text-xs uppercase tracking-widest text-brass">Models & evidence</p><h1 className="font-display text-3xl font-semibold">Training Lab</h1><p className="max-w-3xl text-sm leading-7 text-secondary">Two trained deep-learning classifiers, three public datasets, and reproducible Colab notebooks. Results below come from held-out examples. Both models are integrated as experimental diagnostics in research answers.</p></header>
    <div className="grid gap-5 lg:grid-cols-2">{experiments.map(({ id, title, model, history, description }) => {
      const ceiling = Math.max(1, ...history.flatMap(row => [row.train_loss, row.validation_loss]));
      const points = (field: "train_loss" | "validation_loss") => history.map((row, i) => `${40 + i * 480 / Math.max(history.length - 1, 1)},${190 - 150 * row[field] / ceiling}`).join(" ");
      return <section key={id} className="min-w-0 space-y-5 rounded-lg border border-hairline bg-surface p-6">
        <div><h2 className="font-display text-xl font-semibold">{title}</h2><p className="mt-2 text-sm leading-6 text-secondary">{description}</p></div>
        <div className="flex flex-wrap items-end gap-6"><div><p className="font-mono text-3xl text-brass">{(model.test.accuracy * 100).toFixed(2)}%</p><p className="mt-1 text-xs text-muted">Test accuracy</p></div><div><p className="font-mono text-xl">{model.test.macro_f1.toFixed(3)}</p><p className="mt-1 text-xs text-muted">Macro F1</p></div><div><p className="font-mono text-xl">{(model.baseline_test.accuracy * 100).toFixed(2)}%</p><p className="mt-1 text-xs text-muted">Baseline accuracy</p></div></div>
        <p className="text-sm italic text-secondary">{id === "stance" ? "Below the majority baseline on accuracy. Experimental only; do not use as a factual verdict." : "Outperformed a lexical overlap baseline on this dataset. Improvement over the production reranker has not been established."}</p>
        <figure><figcaption className="mb-2 text-sm font-semibold">Learning curves</figcaption><svg viewBox="0 0 560 230" role="img" aria-label={`${title}: training and validation loss across ${history.length} epochs`} className="w-full"><path d="M40 25V190H530" fill="none" stroke="currentColor" opacity="0.3"/><polyline fill="none" stroke="#b39a64" strokeWidth="3" points={points("train_loss")} /><polyline fill="none" stroke="#91a1ca" strokeWidth="3" points={points("validation_loss")} /><g fill="currentColor" fontSize="12"><text x="6" y="30">{ceiling.toFixed(1)}</text><text x="16" y="190">0</text><text x="40" y="217">Epoch 1</text><text x="455" y="217">Epoch {history.length}</text></g></svg><p className="text-xs text-muted">Gold: training loss · Blue: validation loss · Lower is better</p></figure>
        <div className="overflow-x-auto"><table className="w-full text-left text-xs"><caption className="mb-2 text-left font-semibold">Confusion matrix — actual rows, predicted columns</caption><thead><tr><th className="p-2">Actual</th>{model.labels.map(label => <th key={label} className="p-2">{label.replaceAll("_", " ")}</th>)}</tr></thead><tbody>{model.test.confusion_matrix.map((row, index) => <tr key={index} className="border-t border-hairline"><th className="p-2 font-normal">{model.labels[index].replaceAll("_", " ")}</th>{row.map((count, i) => <td key={i} className="p-2 font-mono">{count}</td>)}</tr>)}</tbody></table></div>
        <p className="text-xs text-muted">Architecture: {model.architecture.join(" → ")} · Seed {model.seed} · Validation-selected checkpoint</p>
        <a href={`/api/training/${id}`} className="inline-block rounded border border-brass px-4 py-2 text-sm font-semibold text-brass hover:bg-surface-raised">Download {id === "stance" ? "stance" : "relevance"} Colab notebook</a>
      </section>;
    })}</div>
    <section className="space-y-3 rounded-lg border border-hairline p-6"><h2 className="font-display text-xl font-semibold">Understand the data</h2><p className="text-sm leading-7 text-secondary"><strong>24,759 training and evaluation pairs</strong> across the two tasks. Shared questions and documents stay within one split; training fails if a normalized question or passage leaks between splits. Relevance negatives are sampled and may include incorrect labels. These are custom research splits, not official leaderboard results.</p><p className="text-sm leading-7 text-secondary"><a className="text-brass underline" href="https://huggingface.co/datasets/allenai/sciq">SciQ</a> · CC BY-NC 3.0; <a className="text-brass underline" href="https://rajpurkar.github.io/SQuAD-explorer/">SQuAD</a> · CC BY-SA 4.0; <a className="text-brass underline" href="https://github.com/allenai/scifact/blob/master/LICENSE.md">SciFact</a> · claims CC BY 4.0, abstracts ODC-By 1.0.</p><p className="text-sm italic text-secondary">Both notebooks were executed locally through all cells. A hosted Colab run has not been performed. Open a downloaded notebook in Colab and choose Run all; CPU is sufficient.</p></section>
  </div>;
}
