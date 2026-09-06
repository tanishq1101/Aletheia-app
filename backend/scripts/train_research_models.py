#!/usr/bin/env python3
"""Train/evaluate two text-pair MLPs, export portable artifacts and SVG reports."""
import argparse
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import sys

import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/api'))
from app.services.research_models import INPUT_DIM, PairClassifier, pair_features, softmax

def metrics(y, probability):
    pred = probability.argmax(axis=1)
    confusion = np.zeros((2, 2), dtype=int)
    np.add.at(confusion, (y, pred), 1)
    f1 = [2 * confusion[i,i] / max(int(confusion[i,:].sum() + confusion[:,i].sum()), 1) for i in range(2)]
    return {'accuracy': float(np.mean(y == pred)), 'macro_f1': float(np.mean(f1)), 'per_class_f1': f1, 'confusion_matrix': confusion.tolist(), 'log_loss': float(-np.log(np.clip(probability[np.arange(len(y)), y], 1e-7, 1)).mean())}

def audit(rows):
    for a, b in [('train','validation'), ('train','test'), ('validation','test')]:
        for field in ['query', 'passage']:
            values = [{hashlib.sha256(' '.join(r[field].lower().split()).encode()).hexdigest() for r in rows if r['split'] == split} for split in [a,b]]
            if values[0] & values[1]:
                raise ValueError(f'Leakage: shared {field} between {a} and {b}')
    for split in ['train','validation','test']:
        if {r['label'] for r in rows if r['split'] == split} != {0,1}:
            raise ValueError(f'{split} must contain both classes')

def train(x, y, vx, vy, hidden, epochs=60, seed=42):
    rng = np.random.default_rng(seed)
    dims = [INPUT_DIM, *hidden, 2]
    w = {}
    for i in range(1, 4):
        w[f'w{i}'] = (rng.normal(size=(dims[i-1],dims[i])) * np.sqrt(2 / dims[i-1])).astype(np.float32)
        w[f'b{i}'] = np.zeros(dims[i], dtype=np.float32)
    m, v = {k: np.zeros_like(a) for k,a in w.items()}, {k: np.zeros_like(a) for k,a in w.items()}
    class_weights = len(y) / (2 * np.bincount(y, minlength=2))
    best, best_score, stale, history, step = None, -1.0, 0, [], 0
    for epoch in range(epochs):
        order = rng.permutation(len(x))
        for start in range(0, len(order), 128):
            step += 1
            ids = order[start:start+128]
            bx, by = x[ids], y[ids]
            h1 = np.maximum(0, bx @ w['w1'] + w['b1'])
            h2 = np.maximum(0, h1 @ w['w2'] + w['b2'])
            delta = softmax(h2 @ w['w3'] + w['b3'])
            delta[np.arange(len(by)),by] -= 1
            delta *= class_weights[by,None] / len(by)
            g = {'w3': h2.T @ delta, 'b3': delta.sum(axis=0)}
            d2 = (delta @ w['w3'].T) * (h2 > 0)
            g.update(w2=h1.T @ d2, b2=d2.sum(axis=0))
            d1 = (d2 @ w['w2'].T) * (h1 > 0)
            g.update(w1=bx.T @ d1, b1=d1.sum(axis=0))
            for key in w:
                grad = np.clip(g[key] + (1e-4*w[key] if key.startswith('w') else 0), -5, 5)
                m[key] = .9*m[key] + .1*grad
                v[key] = .999*v[key] + .001*grad*grad
                w[key] -= .001 * (m[key]/(1-.9**step)) / (np.sqrt(v[key]/(1-.999**step)) + 1e-8)
        model = PairClassifier(w, {})
        validation = metrics(vy, model.predict(vx))
        history.append({'epoch': epoch+1, 'train_loss': metrics(y, model.predict(x))['log_loss'], 'validation_loss': validation['log_loss'], 'validation_macro_f1': validation['macro_f1']})
        if validation['macro_f1'] > best_score + .0001:
            best_score, best, stale = validation['macro_f1'], {k:a.copy() for k,a in w.items()}, 0
        else:
            stale += 1
        if stale >= 10:
            break
    return PairClassifier(best, {}), history

def report_svg(history, result, labels):
    points = []
    ceiling = max(1.0, max(max(r['train_loss'],r['validation_loss']) for r in history))
    for field, color in [('train_loss','#7255c4'),('validation_loss','#b57224')]:
        coordinates = ' '.join(f'{55+i*480/max(len(history)-1,1):.1f},{245-r[field]/ceiling*180:.1f}' for i,r in enumerate(history))
        points.append(f'<polyline fill="none" stroke="{color}" stroke-width="3" points="{coordinates}"/>')
    texts = ''.join(f'<text x="580" y="{110+i*28}">{html.escape(label)}: {result["per_class_f1"][i]:.3f} F1</text>' for i,label in enumerate(labels))
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="320" role="img"><title>Training and validation loss; held-out class F1</title><rect width="900" height="320" fill="#faf8f2"/><g font-family="sans-serif" fill="#25232a"><text x="30" y="30">Training loss (purple) / validation loss (ochre)</text><path d="M55 60V245H535" fill="none" stroke="#777"/><text x="15" y="65">{ceiling:.1f}</text><text x="30" y="245">0</text><text x="55" y="270">Epoch 1</text><text x="470" y="270">Epoch {len(history)}</text>{"".join(points)}<text x="580" y="65">Held-out test (not selection data)</text>{texts}<text x="580" y="190">Macro F1: {result["macro_f1"]:.3f}</text></g></svg>'

def run(task, data_dir, output, epochs):
    path = data_dir / f'{task}.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    audit(rows)
    data = {}
    for split in ['train','validation','test']:
        selected = [r for r in rows if r['split'] == split]
        data[split] = (pair_features([(r['query'],r['passage']) for r in selected]), np.array([r['label'] for r in selected]), selected)
    x,y,_ = data['train']; vx,vy,_ = data['validation']; tx,ty,test_rows = data['test']
    hidden = [96,32] if task == 'relevance' else [128,48]
    model, history = train(x,y,vx,vy,hidden,epochs)
    probability = model.predict(tx)
    test = metrics(ty,probability)
    # Tune lexical relevance threshold on validation only; fixed majority stance baseline.
    if task == 'relevance':
        thresholds = np.linspace(0,1,101)
        threshold = max(thresholds, key=lambda t: metrics(vy, np.column_stack([vx[:,-4]<t, vx[:,-4]>=t]))['macro_f1'])
        baseline = metrics(ty,np.column_stack([tx[:,-4]<threshold, tx[:,-4]>=threshold]))
    else:
        majority = int(np.bincount(y).argmax())
        baseline = metrics(ty,np.tile(np.eye(2)[majority],(len(ty),1)))
    labels = ['not_relevant','relevant'] if task == 'relevance' else ['contradicts','supports']
    model.metadata = {'task':task,'labels':labels,'architecture':[INPUT_DIM,*hidden,2], 'seed':42,
        'validation':metrics(vy,model.predict(vx)), 'test':test, 'baseline_test':baseline,
        'counts':{split:dict(Counter(map(str,data[split][1]))) for split in data},
        'dataset_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'status':'experimental_advisory', 'limitations':'Hashed lexical features lose word order. Scores are not calibrated. Sampled relevance negatives are weak labels. Stance is binary on annotated SciFact abstracts; no neutral detection. No demonstrated improvement over production Jina or end-to-end answer quality.',
        'source_test_metrics':{source: metrics(ty[[i for i,r in enumerate(test_rows) if r['source']==source]],probability[[i for i,r in enumerate(test_rows) if r['source']==source]]) for source in sorted({r['source'] for r in test_rows})}}
    directory = output / task
    model.save(directory)
    (directory/'history.json').write_text(json.dumps(history,indent=2)+'\n')
    (directory/'training.svg').write_text(report_svg(history,test,labels))
    (directory/'test_predictions.jsonl').write_text(''.join(json.dumps({'id':r['id'],'source':r['source'],'label':int(label),'scores':score.tolist()})+'\n' for r,label,score in zip(test_rows,ty,probability)))
    loaded = PairClassifier.load(directory)
    np.testing.assert_allclose(loaded.predict(tx),probability)
    print(json.dumps({'task':task,'epochs':len(history),'test':test,'baseline':baseline,'counts':model.metadata['counts']},indent=2),flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', choices=['relevance','stance','both'],default='both')
    parser.add_argument('--data-dir',type=Path,default=ROOT/'datasets/research')
    parser.add_argument('--output',type=Path,default=ROOT/'models/research')
    parser.add_argument('--epochs',type=int,default=60)
    args = parser.parse_args()
    if args.epochs < 1:
        parser.error('epochs must be positive')
    for task in ['relevance','stance'] if args.task=='both' else [args.task]:
        run(task,args.data_dir,args.output,args.epochs)
