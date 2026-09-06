"""Offline integration checks without a database, API key or model download."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'apps/api'))
sys.path.insert(0, str(ROOT/'scripts'))
from app.services.research_models import PairClassifier, pair_features, INPUT_DIM
from app.services.context import Evidence, BuiltContext
from app.services.answering import AnswerResult, answer_from_context
from app.services.agent import AgentExecutionStep, synthesize_research, run_research_agent
from train_research_models import audit

@pytest.mark.parametrize('task',['relevance','stance'])
def test_real_artifact_and_heldout_data(task):
    data_path = ROOT / f"datasets/research/{task}.jsonl"
    if not data_path.exists():
        pytest.skip("Run prepare_research_data.py to reproduce the local dataset snapshot")
    rows=[json.loads(line) for line in data_path.read_text().splitlines()]
    audit(rows)
    model=PairClassifier.load(ROOT/f'models/research/{task}')
    x=pair_features([(rows[0]['query'],rows[0]['passage']),('','')])
    assert x.shape==(2,INPUT_DIM)
    scores=model.predict(x)
    assert scores.shape==(2,2) and np.isfinite(scores).all()
    np.testing.assert_allclose(scores.sum(axis=1),1,rtol=1e-6)

def test_corrupt_artifact_rejected(tmp_path):
    model=PairClassifier.load(ROOT/'models/research/stance')
    model.save(tmp_path)
    with (tmp_path/'weights.npz').open('ab') as out: out.write(b'corrupt')
    with pytest.raises(ValueError,match='checksum'): PairClassifier.load(tmp_path)

def test_audit_rejects_passage_leakage():
    rows=[{'query':f'{s}{i}','passage':'shared' if i==0 else s,'split':s,'label':i} for s in ['train','validation','test'] for i in [0,1]]
    with pytest.raises(ValueError,match='Leakage'): audit(rows)

class LLM:
    name='scripted-test'
    def __init__(self, reply): self.reply=reply; self.prompts=[]
    def complete(self, **kwargs): self.prompts.append(kwargs); return self.reply

def item(content='Measured accuracy is 82%.', title='Paper', url=None):
    return Evidence('E1',str(uuid4()),str(uuid4()),title,content,'Results',1,.8,1.2,url)

@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setenv('DATABASE_URL','postgresql://unused:unused@localhost/unused')
    from app.core.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

@pytest.mark.parametrize('reply',['', 'Uncited assertion.', 'Claim [E999].'])
def test_uncited_or_empty_answer_is_not_sufficient(reply):
    evidence=item()
    result=answer_from_context(question='accuracy?',context=BuiltContext([evidence],'evidence',0,3),llm=LLM(reply),candidates_considered=1)
    assert not result.sufficient_evidence
    assert 'E999' not in result.answer

def test_synthesis_remaps_step_ids_and_resolves_public_sources(monkeypatch):
    import app.services.embedding as embeddings
    monkeypatch.setattr(embeddings,'build_token_counter',lambda:SimpleNamespace(count=lambda text:len(text.split())))
    # Inspect token-counter contract below; fixtures mimic the production counter.
    a,b=item(),item('Other method achieved 79%.','Other')
    steps=[AgentExecutionStep('q','succeeded',AnswerResult('claim [E1]',True,[],[e],0,1,0,'test')) for e in [a,b]]
    llm=LLM('First 82% [E1]. Public abstract [E2]. Other 79% [E3].')
    result=synthesize_research('Compare',steps,[{'title':'Public','url':'https://doi.org/10.1/test','abstract':'A third method is evaluated.'}],llm)
    assert [c.paper_title for c in result.citations]==['Paper','Public','Other']
    assert result.citations[1].source_url=='https://doi.org/10.1/test'
    assert len(result.model_diagnostics)==2
    assert len({e.evidence_id for e in result.evidence})==3

def test_discovery_partial_failure(monkeypatch):
    from app.services import discovery
    def search(provider, query):
        if provider=='Crossref': raise RuntimeError('offline')
        return [{'url':'https://europepmc.org/article/MED/1','title':'Example'}]
    monkeypatch.setattr(discovery,'_search',search)
    sources,errors=discovery.discover_literature('test')
    assert len(sources)==1 and len(errors)==1

def test_agent_preserves_steps_if_synthesis_fails(monkeypatch):
    from app.services import agent
    monkeypatch.setattr(agent,'answer_question',lambda **kwargs: AnswerResult('No evidence',False,[],[],0,0,0,'test'))
    monkeypatch.setattr(agent,'synthesize_research',lambda *args: (_ for _ in ()).throw(RuntimeError('failure')))
    run=run_research_agent(project_id=uuid4(),goal='test',llm=LLM('{"questions":["test?"]}'),max_steps=1,synthesize=True)
    assert len(run.steps)==1 and run.synthesis_error and run.synthesis is None

def test_charts_require_matching_literal_values_and_conditions():
    from app.services.comparison_charts import extract_comparison_charts
    a=item('Alpha accuracy 82 % on SciQ held-out. Beta accuracy 79 % on SciQ held-out.')
    table='| Method | Metric | Value | Unit | Dataset | Conditions | Evidence |\n|---|---|---|---|---|---|---|\n| Alpha | accuracy | 82 | % | SciQ | held-out | [E1] |\n| Beta | accuracy | 79 | % | SciQ | held-out | [E1] |'
    charts=extract_comparison_charts(table,[a])
    assert len(charts)==1 and charts[0]['points'][1]['value']==79
    assert extract_comparison_charts(table.replace('79','99'),[a])==[]
    assert extract_comparison_charts(table.replace('| Beta | accuracy','| Beta | recall'),[a])==[]
    assert extract_comparison_charts(table.replace('[E1]','[E99]'),[a])==[]

def test_truncated_response_is_explicit_and_not_sufficient():
    from app.services.llm import CompletionText
    evidence=item()
    result=answer_from_context(question='test',context=BuiltContext([evidence],'evidence',0,3),llm=LLM(CompletionText('Claim [E1]. Unfinished',truncated=True)),candidates_considered=1)
    assert result.truncated and not result.sufficient_evidence and not result.charts

def test_provider_preserves_length_finish_reason(monkeypatch):
    import httpx
    from app.services.llm import OpenRouterProvider
    monkeypatch.setattr('app.services.llm.httpx.post', lambda *args, **kwargs: httpx.Response(200,json={'choices':[{'message':{'content':'Partial text'},'finish_reason':'length'}]}))
    provider=OpenRouterProvider(api_key='test',model='test',base_url='https://example.test',temperature=0,max_output_tokens=5,timeout=1)
    result=provider.complete(system='s',prompt='q')
    assert result == 'Partial text' and result.truncated
