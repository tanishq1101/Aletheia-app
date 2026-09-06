#!/usr/bin/env python3
"""Build two standalone Colab notebooks with the exact runtime feature contract."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def md(text):
    return {'cell_type':'markdown','metadata':{},'source':text.splitlines(True)}

def code(text):
    return {'cell_type':'code','metadata':{},'source':text.splitlines(True),'execution_count':None,'outputs':[]}

def build(task, title, filename):
    files = {str(path.relative_to(ROOT / 'backend')):path.read_text() for path in [ROOT/'backend/scripts/prepare_research_data.py',ROOT/'backend/scripts/train_research_models.py',ROOT/'backend/apps/api/app/services/research_models.py']}
    cells = [md(f'''# Aletheia — {title}

A standalone, executable **deep-learning experiment** with public data collection, leakage checks, training, held-out evaluation, loss graphs and project-compatible export. No repository URL, secret or GPU is required. Select **Runtime → Run all**. CPU is intentional for these compact NumPy networks; this does not fine-tune the chat language model.

**Task:** {'Learn query–passage relevance from SciQ and SQuAD, using a 516 → 96 → 32 → 2 network.' if task=='relevance' else 'Learn supports/contradicts on annotated SciFact abstracts, using a 516 → 128 → 48 → 2 network. This is binary stance classification, not a general fact checker; no neutral class is trained.'}

The feature representation uses normalized hashed words, pair interactions and overlap features. It loses word order. Treat performance as experimental; a high retrieval score does not prove truth.
'''), code('''import importlib.util, os, subprocess, sys
from pathlib import Path
if importlib.util.find_spec("numpy") is None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "numpy>=2.0,<3"])
ROOT = Path.cwd() / "aletheia-colab" / "backend"
ROOT.mkdir(parents=True, exist_ok=True)
'''), code('embedded_files = '+repr(files)+'''\nfor name, source in embedded_files.items():
    path = ROOT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
sys.path.insert(0, str(ROOT / "apps/api"))
'''), md('''## Collect and audit data

Sources: [SciQ](https://huggingface.co/datasets/allenai/sciq) (**CC BY-NC 3.0**), [SciFact](https://github.com/allenai/scifact/blob/master/LICENSE.md) (claims **CC BY 4.0**, abstracts **ODC-By 1.0**) and [SQuAD](https://rajpurkar.github.io/SQuAD-explorer/) (**CC BY-SA 4.0**). Retain attribution and review dataset terms before redistribution or commercial use. Data and derived models may carry restrictions.

The collector records SHA-256 checksums and download URLs. Stable sampling caps QA at 6,000 questions per source. Shared questions/documents form connected groups assigned to 70% train, 15% validation, 15% test. SciFact's public annotated train/dev are regrouped; these are **not official leaderboard splits**. Relevance negatives are sampled from another document with no literal answer match; these are weak labels and may be wrong. Train/validation/test share neither normalized questions nor passages; execution fails if they do.
'''), code('''DATA = Path(os.environ.get("ALETHEIA_DATA_DIR", str(ROOT / "datasets/research")))
subprocess.check_call([sys.executable, str(ROOT / "scripts/prepare_research_data.py"), "--output", str(DATA)])
import json
print(json.dumps(json.loads((DATA / "sources.json").read_text()), indent=2))
'''), md('''## Train and evaluate

Adam optimization, balanced class weights, L2 regularization, gradient clipping and early stopping on validation macro F1. The test set is evaluated only after checkpoint selection. The relevance baseline threshold is selected on validation; stance uses the training majority class. Both accuracy and macro F1 are reported so class imbalance stays visible.
'''), code(f'''TASK = {task!r}
OUTPUT = ROOT / "models/research"
subprocess.check_call([sys.executable, str(ROOT / "scripts/train_research_models.py"), "--task", TASK, "--data-dir", str(DATA), "--output", str(OUTPUT), "--epochs", "60"])
metadata = json.loads((OUTPUT / TASK / "model.json").read_text())
print(json.dumps(metadata, indent=2))
'''), md('''## Explain the results

Purple is training loss; ochre is validation loss. A widening gap suggests overfitting. Class F1 is measured on the held-out test set. Inspect the confusion matrix (rows: actual, columns: predicted), per-source metrics, and test predictions before deciding whether the model is useful. Model scores are **not calibrated confidence**. No improvement over the production Jina reranker or end-to-end chat is established by this experiment.
'''), code('''svg = (OUTPUT / TASK / "training.svg").read_text()
try:
    from IPython.display import SVG, display
    display(SVG(svg))
except ImportError:
    print("Graph saved at", OUTPUT / TASK / "training.svg")
print("Labels:", metadata["labels"])
print("Confusion matrix:", metadata["test"]["confusion_matrix"])
print("Test macro F1:", metadata["test"]["macro_f1"])
print("Baseline macro F1:", metadata["baseline_test"]["macro_f1"])
print(metadata["limitations"])
'''), md('''## Verify inference and export to Aletheia

The export uses `.npz` numeric arrays with pickle disabled, a versioned feature contract, and checksums. It is the same inference code as the backend. The project shows both models in **Experimental model analysis**; their outputs do not override citations or decide factual sufficiency.

Extract the archive at the project's `backend/` directory, so files land in `models/research/<task>/`. Keep `RESEARCH_MODELS_ENABLED=true` and `RESEARCH_MODELS_DIR=models/research`. Restart the API after replacing artifacts because loaded models are cached. Do not promote a model based on training loss alone.
'''), code('''from app.services.research_models import PairClassifier, pair_features
import numpy as np
classifier = PairClassifier.load(OUTPUT / TASK)
example = next(json.loads(line) for line in (DATA / f"{TASK}.jsonl").read_text().splitlines() if json.loads(line)["split"] == "test")
scores = classifier.predict(pair_features([(example["query"], example["passage"])]))[0]
assert np.isfinite(scores).all() and np.isclose(scores.sum(), 1)
print("Example:", example["query"])
print("Actual label:", metadata["labels"][example["label"]])
print("Predicted scores:", dict(zip(metadata["labels"], map(float, scores))))
import zipfile
archive = ROOT / f"aletheia-{TASK}-model.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
    for path in (OUTPUT / TASK).iterdir():
        bundle.write(path, path.relative_to(ROOT))
    bundle.write(DATA / "sources.json", "datasets/research/sources.json")
print("Export:", archive)
try:
    from google.colab import files
    files.download(str(archive))
except ImportError:
    pass
''')]
    notebook = {'nbformat':4,'nbformat_minor':5,'metadata':{'colab':{'name':filename},'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},'language_info':{'name':'python','version':'3.11'}},'cells':cells}
    for i, cell in enumerate(cells): cell['id']=f'{task}-{i:02d}'
    (ROOT/'colab'/filename).write_text(json.dumps(notebook,indent=2)+'\n')

if __name__ == '__main__':
    build('relevance','Multi-source Evidence Relevance','Aletheia_Multisource_Relevance_Colab.ipynb')
    build('stance','Scientific Claim Stance','Aletheia_Scientific_Stance_Colab.ipynb')
