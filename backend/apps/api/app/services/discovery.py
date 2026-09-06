"""Bounded public literature discovery. Abstracts are source data, not instructions."""
from concurrent.futures import ThreadPoolExecutor
import html
import re
from urllib.parse import quote

import httpx


def _plain(value):
    return html.unescape(re.sub(r'<[^>]+>', ' ', str(value or ''))).strip()[:8000]

def _search(provider, query):
    with httpx.Client(timeout=httpx.Timeout(12.0), follow_redirects=False) as client:
        if provider == 'Europe PMC':
            response = client.get('https://www.ebi.ac.uk/europepmc/webservices/rest/search', params={'query':query[:500], 'format':'json','pageSize':4,'resultType':'core'})
            response.raise_for_status()
            return [{'provider':provider, 'title':_plain(r.get('title')), 'url':f'https://europepmc.org/article/{quote(r.get("source","MED"),safe="")}/{quote(str(r["id"]),safe="")}', 'year':str(r.get('pubYear','')), 'abstract':_plain(r.get('abstractText')), 'evidence_scope':'abstract only; full text not reviewed'} for r in response.json().get('resultList',{}).get('result',[]) if r.get('id') and r.get('title')]
        response = client.get('https://api.crossref.org/works', params={'query.bibliographic':query[:500], 'rows':4}, headers={'User-Agent':'AletheiaResearch/1.0 (public literature discovery)'})
        response.raise_for_status()
        return [{'provider':provider,'title':_plain((r.get('title') or [''])[0]),'url':'https://doi.org/'+quote(r['DOI'],safe='/'), 'year':str((r.get('published',{}).get('date-parts') or [['']])[0][0]), 'abstract':_plain(r.get('abstract')), 'evidence_scope':'abstract only; full text not reviewed' if r.get('abstract') else 'metadata only; not used as answer evidence'} for r in response.json().get('message',{}).get('items',[]) if r.get('DOI') and r.get('title')]

def discover_literature(query):
    sources, errors = [], []
    with ThreadPoolExecutor(max_workers=2) as executor:
        jobs = {provider: executor.submit(_search, provider, query) for provider in ['Europe PMC','Crossref']}
        for provider, future in jobs.items():
            try:
                sources.extend(future.result())
            except Exception:
                errors.append(f'{provider} search is unavailable. Research continued with the other available sources.')
    return list({r['url']:r for r in sources}.values()), errors
