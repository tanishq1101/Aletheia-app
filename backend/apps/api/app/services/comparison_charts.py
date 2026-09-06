"""Conservative plots from cited comparison tables; no generated graph numbers."""
from collections import defaultdict
import math
import re

HEADERS = ['method', 'metric', 'value', 'unit', 'dataset', 'conditions', 'evidence']
NUMBER = re.compile(r'(?<![\w.])\d+(?:\.\d+)?(?![\w.])')

def extract_comparison_charts(answer, evidence):
    """Accept only comparable rows with literal numeric/source support.

    This checks provenance and grouping, not scientific correctness. The UI
    retains source buttons and the original table for human interpretation.
    """
    supplied = {item.evidence_id:item for item in evidence}
    groups = defaultdict(list)
    in_table = False
    for line in answer.splitlines():
        if not line.strip().startswith('|'):
            in_table = False
            continue
        cells = [cell.strip().strip('*') for cell in line.strip().strip('|').split('|')]
        if [cell.lower() for cell in cells] == HEADERS:
            in_table = True
            continue
        if not in_table or len(cells) != 7 or all(re.fullmatch(r':?-+:?',cell.replace(' ','')) for cell in cells):
            continue
        method, metric, value, unit, dataset, conditions, refs = cells
        if not re.fullmatch(r'\d+(?:\.\d+)?', value):
            continue
        numeric = float(value)
        if not math.isfinite(numeric) or not all([method,metric,unit,dataset,conditions]):
            continue
        if unit == '%' and numeric > 100:
            continue
        ids = list(dict.fromkeys(re.findall(r'\bE\d+\b',refs)))
        supporting = []
        for eid in ids:
            if eid not in supplied: continue
            text = supplied[eid].content.lower()
            if numeric not in {float(n) for n in NUMBER.findall(text)}: continue
            if not all(term.lower() in text for term in [method, metric, dataset, unit, conditions]): continue
            supporting.append(eid)
        if not supporting:
            continue
        key = (metric.lower(),unit.lower(),dataset.lower(),conditions.lower())
        groups[key].append({'label':method, 'value':numeric, 'evidence_ids':supporting})
    charts = []
    for (metric,unit,dataset,conditions),rows in groups.items():
        if 2 <= len(rows) <= 12 and len({r['label'].lower() for r in rows}) == len(rows):
            charts.append({'title':f'{metric} on {dataset}', 'unit':unit,'conditions':conditions,'points':rows,
                           'note':'Reported values from cited passages. Matching labels and conditions do not establish study equivalence; review the source context.'})
    return charts[:3]
