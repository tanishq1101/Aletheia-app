"""Reproducibility disclosure audit (PRD Section 3.2, Phase 6).

What this measures, precisely: **whether the paper discloses what someone would
need to reproduce it** — code, data, hyperparameters, seeds, environment, and
evaluation protocol. It does not run the code and does not claim the results
reproduce. That distinction is the difference between a defensible score and a
misleading one, and it is stated on the report itself.

Each dimension is retrieved for separately (scoped to the one paper), then
judged against that evidence with citations, using the same evidence-ID
discipline as answering and verification.

Links are extracted from the paper's real text with no model involved at all.
When a GitHub repository is linked, its public metadata is fetched — and when
GitHub is unreachable or rate-limited, that is reported as unavailable rather
than silently omitted.
"""

import re
from dataclasses import dataclass, field
from uuid import UUID

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.answering import (
    Citation,
    extract_cited_ids,
    resolve_citations,
    strip_fabricated_citations,
)
from app.services.context import assign_evidence_ids, build_context
from app.services.embedding import build_token_counter
from app.services.providers import LLMProvider
from app.services.reranking import build_reranker
from app.services.retrieval import retrieve_candidates
from app.services.settings_store import get_effective_settings

log = get_logger(__name__)

DISCLOSED = "disclosed"
PARTIAL = "partial"
MISSING = "missing"

# Weight reflects how much each item actually blocks a reproduction attempt:
# without code or data you cannot start; without seeds you can still get close.
DIMENSIONS: list[dict] = [
    {
        "key": "code",
        "label": "Source code is available",
        "query": "code available at github repository implementation released open source",
        "weight": 1.0,
    },
    {
        "key": "data",
        "label": "Datasets are identified and obtainable",
        "query": "dataset used for training and evaluation, data source, benchmark splits",
        "weight": 1.0,
    },
    {
        "key": "hyperparameters",
        "label": "Training hyperparameters are reported",
        "query": "learning rate, batch size, optimizer, epochs, weight decay, hyperparameters",
        "weight": 1.0,
    },
    {
        "key": "seeds",
        "label": "Random seeds or run variance are reported",
        "query": "random seed, number of runs, standard deviation across seeds, variance",
        "weight": 0.5,
    },
    {
        "key": "environment",
        "label": "Compute environment is described",
        "query": "hardware, GPUs, TPUs, training time, software framework versions",
        "weight": 0.75,
    },
    {
        "key": "evaluation",
        "label": "Evaluation protocol and metrics are specified",
        "query": "evaluation metric, test set, evaluation protocol, how results are measured",
        "weight": 1.0,
    },
]

STATUS_CREDIT = {DISCLOSED: 1.0, PARTIAL: 0.5, MISSING: 0.0}

_STATUS_LINE = re.compile(
    r"^\s*STATUS\s*:\s*(DISCLOSED|PARTIAL|MISSING)\b", re.IGNORECASE | re.MULTILINE
)
_FINDING_LINE = re.compile(
    r"^\s*FINDING\s*:\s*(.*)\Z", re.IGNORECASE | re.MULTILINE | re.DOTALL
)

# Links are read straight out of the paper's text — no model, no cost, no
# hallucination surface.
_GITHUB_URL = re.compile(
    r"https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", re.IGNORECASE
)
_GITLAB_URL = re.compile(
    r"https?://(?:www\.)?gitlab\.com/[A-Za-z0-9_./-]+", re.IGNORECASE
)
_DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")

AUDIT_SYSTEM_PROMPT = """\
You audit whether a scientific paper discloses enough for someone else to \
reproduce its results.

You are given one reproducibility requirement and numbered <EVIDENCE> blocks \
from the paper. Judge only whether the paper DISCLOSES this information — not \
whether the work is good, and not whether the results would replicate.

Rules, all of which are enforced:
1. Judge ONLY from the supplied evidence. Absence of evidence is MISSING, not \
an assumption that the paper probably says it somewhere.
2. DISCLOSED means the evidence gives the specifics someone would need. \
PARTIAL means it is mentioned but underspecified. MISSING means the evidence \
does not address it.
3. Cite evidence IDs in square brackets, like [E2]. You may ONLY cite an ID \
present in the evidence you were given.

Reply in exactly this format and nothing else:
STATUS: DISCLOSED|PARTIAL|MISSING
FINDING: <one or two sentences, citing evidence IDs>
"""

AUDIT_USER_PROMPT = """\
Requirement:
{requirement}

Evidence:
{evidence}

Judge whether the paper discloses this, in the required format.
"""

GITHUB_TIMEOUT_SECONDS = 8.0


@dataclass
class DimensionResult:
    key: str
    label: str
    status: str
    rationale: str
    citations: list[Citation] = field(default_factory=list)


@dataclass
class ReproducibilityResult:
    score: float
    checks: list[DimensionResult]
    links: list[dict]
    repo_metadata: dict | None
    model: str


def extract_links(text: str) -> list[dict]:
    """Code, repository and DOI links present in the paper's own text."""
    links: list[dict] = []
    seen: set[str] = set()

    for match in _GITHUB_URL.finditer(text):
        owner, repo = match.group(1), match.group(2).rstrip(".,);")
        url = f"https://github.com/{owner}/{repo}"
        if url.lower() in seen:
            continue
        seen.add(url.lower())
        links.append({"kind": "github", "url": url, "owner": owner, "repo": repo})

    for match in _GITLAB_URL.finditer(text):
        url = match.group(0).rstrip(".,);")
        if url.lower() not in seen:
            seen.add(url.lower())
            links.append({"kind": "gitlab", "url": url})

    for match in _DOI.finditer(text):
        doi = match.group(0).rstrip(".,);")
        if doi.lower() not in seen:
            seen.add(doi.lower())
            links.append({"kind": "doi", "url": f"https://doi.org/{doi}", "doi": doi})

    return links


def fetch_github_metadata(owner: str, repo: str) -> dict:
    """Public repo facts. Never raises: an unreachable GitHub is a finding."""
    url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {"Accept": "application/vnd.github+json"}
    token = get_settings().github_token
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = httpx.get(
            url,
            timeout=GITHUB_TIMEOUT_SECONDS,
            headers=headers,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        log.warning("GitHub lookup for %s/%s failed: %s", owner, repo, exc)
        return {"repository": f"{owner}/{repo}", "status": "unavailable", "detail": str(exc)}

    if response.status_code == 404:
        return {"repository": f"{owner}/{repo}", "status": "not_found"}
    if response.status_code == 403:
        # Unauthenticated GitHub allows 60 requests/hour per IP.
        return {"repository": f"{owner}/{repo}", "status": "rate_limited"}
    if response.status_code >= 400:
        return {
            "repository": f"{owner}/{repo}",
            "status": "unavailable",
            "detail": f"HTTP {response.status_code}",
        }

    data = response.json()
    return {
        "repository": data.get("full_name") or f"{owner}/{repo}",
        "status": "ok",
        "url": data.get("html_url"),
        "description": data.get("description"),
        "stars": data.get("stargazers_count"),
        "forks": data.get("forks_count"),
        "license": (data.get("license") or {}).get("spdx_id"),
        "language": data.get("language"),
        "last_pushed_at": data.get("pushed_at"),
        "archived": data.get("archived"),
        "open_issues": data.get("open_issues_count"),
    }


def parse_audit(raw: str) -> tuple[str, str]:
    """An unreadable reply is MISSING, never an assumed pass."""
    match = _STATUS_LINE.search(raw)
    if match is None:
        log.warning("Reproducibility audit reply had no STATUS line; recording missing.")
        return MISSING, raw.strip()[:600]

    status = match.group(1).lower()
    finding = _FINDING_LINE.search(raw)
    rationale = (
        finding.group(1).strip() if finding else raw[match.end() :].strip()
    )
    return status, rationale


def _judge_dimension(
    *, project_id: UUID, paper_id: UUID, dimension: dict, llm: LLMProvider
) -> DimensionResult:
    settings = get_effective_settings()
    candidates = retrieve_candidates(
        project_id=project_id,
        query=dimension["query"],
        top_k=settings.search_top_k,
        paper_ids=[paper_id],
    )
    if not candidates:
        return DimensionResult(
            key=dimension["key"],
            label=dimension["label"],
            status=MISSING,
            rationale="No indexed content from this paper addressed this.",
        )

    reranker = build_reranker()
    by_id = {str(chunk.chunk_id): chunk for chunk in candidates}
    scored = reranker.rerank(
        query=dimension["query"],
        chunks=[(str(c.chunk_id), c.content) for c in candidates],
        top_k=settings.rerank_top_k,
    )
    ranked = [(by_id[item.chunk_id], item.score) for item in scored]

    context = build_context(
        ranked=assign_evidence_ids(ranked),
        counter=build_token_counter(),
        max_tokens=settings.context_max_tokens,
    )

    raw = llm.complete(
        system=AUDIT_SYSTEM_PROMPT,
        prompt=AUDIT_USER_PROMPT.format(
            requirement=dimension["label"], evidence=context.text
        ),
    )

    status, rationale = parse_audit(raw)
    rationale, fabricated = strip_fabricated_citations(rationale, context.evidence_ids)
    if fabricated:
        log.warning(
            "Removed %d fabricated citation ID(s) from a %s audit.",
            fabricated,
            dimension["key"],
        )

    return DimensionResult(
        key=dimension["key"],
        label=dimension["label"],
        status=status,
        rationale=rationale,
        citations=resolve_citations(extract_cited_ids(rationale), context.evidence),
    )


def audit_paper(
    *,
    project_id: UUID,
    paper_id: UUID,
    paper_text: str,
    llm: LLMProvider,
    check_github: bool = True,
) -> ReproducibilityResult:
    """Audit one paper's reproducibility disclosure across every dimension."""
    links = extract_links(paper_text)

    repo_metadata: dict | None = None
    if check_github:
        github = next((link for link in links if link["kind"] == "github"), None)
        if github is not None:
            repo_metadata = fetch_github_metadata(github["owner"], github["repo"])

    checks = [
        _judge_dimension(
            project_id=project_id, paper_id=paper_id, dimension=dimension, llm=llm
        )
        for dimension in DIMENSIONS
    ]

    weights = {d["key"]: d["weight"] for d in DIMENSIONS}
    earned = sum(STATUS_CREDIT[c.status] * weights[c.key] for c in checks)
    total = sum(weights.values())
    score = earned / total if total else 0.0

    log.info(
        "Reproducibility audit for paper %s: score %.2f, %d link(s) found",
        paper_id,
        score,
        len(links),
    )
    return ReproducibilityResult(
        score=score,
        checks=checks,
        links=links,
        repo_metadata=repo_metadata,
        model=getattr(llm, "name", type(llm).__name__),
    )


__all__ = [
    "DIMENSIONS",
    "DISCLOSED",
    "MISSING",
    "PARTIAL",
    "DimensionResult",
    "ReproducibilityResult",
    "audit_paper",
    "extract_links",
    "fetch_github_metadata",
    "parse_audit",
]
