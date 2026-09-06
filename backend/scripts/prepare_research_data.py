#!/usr/bin/env python3
"""Download attributed public datasets and build document-disjoint research tasks."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tarfile
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    'sciq': ('https://s3-us-west-2.amazonaws.com/ai2-website/data/SciQ.zip', 'CC BY-NC 3.0', 'https://huggingface.co/datasets/allenai/sciq'),
    'scifact': ('https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz', 'Claims: CC BY 4.0; abstracts: ODC-By 1.0', 'https://github.com/allenai/scifact/blob/master/LICENSE.md'),
    'squad': ('https://rajpurkar.github.io/SQuAD-explorer/dataset/train-v1.1.json', 'CC BY-SA 4.0', 'https://rajpurkar.github.io/SQuAD-explorer/'),
}

def digest(text):
    return hashlib.sha256(' '.join(text.lower().split()).encode()).hexdigest()

def download(name, directory):
    url, license_name, attribution = SOURCES[name]
    target = directory / name
    if not target.exists():
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=90) as response:
                    data = response.read(80 * 1024 * 1024 + 1)
                if len(data) > 80 * 1024 * 1024:
                    raise ValueError('Dataset exceeds download budget')
                target.with_suffix('.part').write_bytes(data)
                target.with_suffix('.part').replace(target)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
    data = target.read_bytes()
    return data, {'url': url, 'license': license_name, 'attribution': attribution,
                  'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}

def split_records(rows):
    """Connected components keep shared documents AND duplicate queries together."""
    parents = {}
    def root(key):
        parents.setdefault(key, key)
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key
    for row in rows:
        a, b = root('q:' + digest(row['query'])), root('d:' + row['group'])
        parents[max(a, b)] = min(a, b)
    for row in rows:
        group = root('d:' + row['group'])
        bucket = int(digest(group)[:8], 16) % 100
        row['split'] = 'train' if bucket < 70 else 'validation' if bucket < 85 else 'test'
    return rows

def prepare(output, max_qa=6000):
    raw = output / 'raw'
    raw.mkdir(parents=True, exist_ok=True)
    payloads, manifest = {}, {}
    for name in SOURCES:
        payloads[name], manifest[name] = download(name, raw)
        print(f'Downloaded {name}: {manifest[name]["bytes"]:,} bytes', flush=True)
    previous = output / 'sources.json'
    if previous.exists():
        old = json.loads(previous.read_text())['sources']
        for name in manifest:
            if old[name]['sha256'] != manifest[name]['sha256']:
                raise ValueError(f'{name} changed upstream; use a new output directory to review a new snapshot')
    qa, stance = [], []
    with zipfile.ZipFile(io.BytesIO(payloads['sciq'])) as archive:
        for name in sorted(archive.namelist()):
            if name.endswith(('.json',)) and Path(name).name in {'train.json', 'valid.json', 'test.json'}:
                for i, row in enumerate(json.loads(archive.read(name))):
                    if row.get('support', '').strip():
                        qa.append(dict(id=f'sciq:{name}:{i}', source='sciq', query=row['question'], passage=row['support'], answer=row['correct_answer'], group=digest(row['support']), label=1))
    # Stable hash sampling, not the first articles/questions in file order.
    squad = []
    for article in json.loads(payloads['squad'])['data']:
        for paragraph in article['paragraphs']:
            for row in paragraph['qas']:
                squad.append(dict(id='squad:' + row['id'], source='squad', query=row['question'], passage=paragraph['context'], answer=row['answers'][0]['text'], group='squad:' + article['title'], label=1))
    qa = sorted(qa, key=lambda r: digest(r['id']))[:max_qa] + sorted(squad, key=lambda r: digest(r['id']))[:max_qa]
    with tarfile.open(fileobj=io.BytesIO(payloads['scifact']), mode='r:gz') as archive:
        # Read named members only; never extract archive paths onto the filesystem.
        files = {Path(m.name).name: archive.extractfile(m).read().decode() for m in archive.getmembers() if m.isfile() and Path(m.name).name in {'corpus.jsonl', 'claims_train.jsonl', 'claims_dev.jsonl'}}
    corpus = {str(row['doc_id']): row for row in map(json.loads, files['corpus.jsonl'].splitlines())}
    for filename in ['claims_train.jsonl', 'claims_dev.jsonl']:
        for claim in map(json.loads, files[filename].splitlines()):
            for doc_id, annotations in claim['evidence'].items():
                labels = {item['label'] for item in annotations}
                if len(labels) != 1 or not labels <= {'SUPPORT', 'CONTRADICT'}:
                    continue
                stance.append(dict(id=f'scifact:{claim["id"]}:{doc_id}', source='scifact', query=claim['claim'], passage=' '.join(corpus[doc_id]['abstract']), group=digest(' '.join(corpus[doc_id]['abstract'])), label=int(next(iter(labels)) == 'SUPPORT')))
    # Collapse exact pairs before assigning splits.
    rows = list({(digest(r['query']), digest(r['passage'])): r for r in qa + stance}.values())
    split_records(rows)
    relevance = [r for r in rows if r['source'] != 'scifact']
    stance = [r for r in rows if r['source'] == 'scifact']
    negatives = []
    for split in ['train', 'validation', 'test']:
        pool = [r for r in relevance if r['split'] == split]
        for index, row in enumerate(pool):
            choices = [pool[(index + offset) % len(pool)] for offset in range(1, min(33, len(pool)))]
            qtokens = set(row['query'].lower().split())
            choices = [c for c in choices if c['source'] == row['source'] and c['group'] != row['group'] and row['answer'].lower() not in c['passage'].lower() and digest(c['query']) != digest(row['query'])]
            if not choices:
                continue
            candidate = max(choices, key=lambda c: len(qtokens & set(c['passage'].lower().split())))
            negatives.append({**row, 'id': row['id'] + ':negative', 'passage': candidate['passage'], 'group': candidate['group'], 'label': 0, 'label_origin': 'sampled_nonanswer_passage'})
    for task, records in [('relevance', relevance + negatives), ('stance', stance)]:
        path = output / f'{task}.jsonl'
        path.write_text(''.join(json.dumps(r) + '\n' for r in records))
        print(task, dict(Counter((r['split'], r['label']) for r in records)), flush=True)
    previous.write_text(json.dumps({'created_at': datetime.now(timezone.utc).isoformat(), 'sources': manifest, 'max_qa_per_source': max_qa, 'split_policy': '70/15/15 hash of connected document/query groups; official SciFact train+dev regrouped; no official leaderboard claim', 'negative_policy': 'Weak relevance negatives: same-source passage with lexical overlap, different document, no answer substring; may contain false negatives.'}, indent=2) + '\n')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'datasets/research')
    parser.add_argument('--max-qa', type=int, default=6000)
    args = parser.parse_args()
    if args.max_qa < 100:
        parser.error('--max-qa must be at least 100')
    prepare(args.output, args.max_qa)
