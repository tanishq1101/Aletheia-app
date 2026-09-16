"""What a downloadable report contains, independent of how it is rendered.

A plain description of a document — headings, prose, tables, provenance — built
from a run the user has already seen. Two properties matter:

**It is built from the result, never from a re-run.** Answers here are not
reproducible (the models this ships against refuse `temperature=0`; see
`llm.OpenAICompatibleProvider.deterministic`), so regenerating the report would
produce a *different* document from the one on screen and quietly present it as
the same thing. The export therefore takes the finished result as input.

**Evidence travels with it.** A cited claim whose passage stays behind in the
browser is a claim the reader cannot check, which is the one thing this
application exists to prevent. Every cited passage is in the PDF.

Rendering lives in `pdf.py`, so this module stays testable without a PDF engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re

# Long enough to verify a claim against, short enough that the appendix stays a
# reference rather than a reprint of the library.
_SNIPPET_CHARS = 600


@dataclass(frozen=True)
class ReportTable:
    columns: list[str]
    rows: list[list[str]]
    caption: str = ""
    #: Column widths as fractions of the text width. None spaces them evenly.
    widths: list[float] | None = None


@dataclass(frozen=True)
class ReportSection:
    heading: str = ""
    #: A line under the heading explaining what the reader is looking at.
    note: str = ""
    #: Markdown — the answering prompt asks the model for it, so the renderer
    #: understands the subset it requests.
    body: str = ""
    tables: list[ReportTable] = field(default_factory=list)
    children: list[ReportSection] = field(default_factory=list)
    page_break_before: bool = False


@dataclass(frozen=True)
class ReportDocument:
    title: str
    subtitle: str = ""
    #: Repeated at the foot of every page.
    footer: str = "Aletheia"
    #: Key/value provenance shown under the title: model, date, counts.
    provenance: list[tuple[str, str]] = field(default_factory=list)
    #: Things the reader must know before trusting the contents.
    caveats: list[str] = field(default_factory=list)
    sections: list[ReportSection] = field(default_factory=list)
    filename: str = "aletheia-report.pdf"


# --- helpers ----------------------------------------------------------------

def _slug(text: str, *, limit: int = 48) -> str:
    """A filename fragment: lowercase words, hyphens, nothing else."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (cleaned[:limit].rstrip("-")) or "report"


def _timestamp() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d %H:%M UTC"), now.strftime("%Y%m%d-%H%M")


def _location(citation) -> str:
    parts = [citation.section or "", f"p. {citation.page_number}"
             if citation.page_number else ""]
    return " · ".join(p for p in parts if p) or (citation.location or "—")


def _citation_table(citations, *, caption: str) -> list[ReportTable]:
    """Cited passages in full, so every claim can be checked from the PDF."""
    if not citations:
        return []
    rows = []
    for citation in citations:
        snippet = (citation.snippet or "").strip().replace("\n", " ")
        if len(snippet) > _SNIPPET_CHARS:
            snippet = snippet[:_SNIPPET_CHARS].rsplit(" ", 1)[0] + " …"
        rows.append([
            citation.evidence_id,
            citation.paper_title or "Untitled source",
            _location(citation),
            snippet or "—",
        ])
    return [ReportTable(
        columns=["ID", "Source", "Location", "Cited passage"],
        rows=rows, caption=caption, widths=[0.06, 0.22, 0.14, 0.58],
    )]


def _answer_provenance(answer, *, include_model: bool = True) -> list[tuple[str, str]]:
    return [
        *([("Model", answer.model or "—")] if include_model else []),
        ("Evidence", f"{len(answer.citations)} cited of "
                     f"{len(answer.evidence)} supplied · "
                     f"{answer.candidates_considered} candidates considered"),
        ("Integrity", f"{answer.fabricated_citations_removed} fabricated "
                      "citation(s) removed · "
                      f"{answer.evidence_dropped_for_budget} passage(s) "
                      "dropped for context budget"),
    ]


def _answer_caveats(answer) -> list[str]:
    caveats: list[str] = []
    if not getattr(answer, "reproducible", True):
        caveats.append(
            "This answer is not reproducible. The model refused the "
            "configured temperature of 0 and answered at its own sampling "
            "setting, so asking the same question again may produce a "
            "different answer. Cited passages remain exact."
        )
    if not answer.sufficient_evidence:
        caveats.append(
            "The model reported the supplied evidence was insufficient to "
            "answer fully. That is a reported outcome, not a failure — treat "
            "the text below as a statement about the library's coverage."
        )
    if answer.truncated:
        caveats.append(
            "The answer reached the model's output limit and is cut off."
        )
    if answer.fabricated_citations_removed:
        caveats.append(
            f"{answer.fabricated_citations_removed} citation ID(s) the model "
            "invented were removed before this report was written."
        )
    return caveats


def _answer_sections(answer, *, heading: str, note: str = "") -> list[ReportSection]:
    return [ReportSection(
        heading=heading, note=note, body=answer.answer,
        tables=_citation_table(answer.citations, caption="Evidence cited above"),
    )]


# --- builders ---------------------------------------------------------------

def answer_document(*, question: str, answer, project_name: str = "") -> ReportDocument:
    """One grounded answer from the Ask page."""
    shown, stamp = _timestamp()
    return ReportDocument(
        title="Grounded Answer",
        subtitle=question,
        footer=f"Aletheia · {project_name or 'library'} · generated {shown}",
        provenance=[("Generated", shown), *_answer_provenance(answer)],
        caveats=_answer_caveats(answer),
        sections=_answer_sections(
            answer, heading="Answer",
            note="Each claim cites the passage it rests on; the passages "
                 "themselves are reproduced below.",
        ),
        filename=f"aletheia-answer-{_slug(question)}-{stamp}.pdf",
    )


def agent_document(*, run, project_name: str = "") -> ReportDocument:
    """A complete research brief, including how it was built."""
    shown, stamp = _timestamp()
    answered = sum(1 for step in run.steps if step.status == "succeeded")
    synthesis = run.synthesis

    provenance = [
        ("Generated", shown),
        ("Model", run.model or "—"),
        ("Coverage", f"{answered} of {len(run.steps)} research question(s) "
                     f"answered · {len(run.discoveries or [])} public source(s) "
                     "checked"),
    ]
    caveats: list[str] = []
    if run.planner_fallback_used:
        caveats.append(
            "The planner could not produce a usable set of sub-questions, so "
            "this brief answers the original goal directly as a single check."
        )
    if synthesis:
        provenance.extend(_answer_provenance(synthesis, include_model=False))
        caveats.extend(_answer_caveats(synthesis))
    if run.synthesis_error:
        caveats.append(run.synthesis_error)

    sections: list[ReportSection] = []
    if synthesis:
        sections.extend(_answer_sections(
            synthesis, heading="What the evidence says",
            note="The combined finding across every research question below.",
        ))
    else:
        sections.append(ReportSection(
            heading="What the evidence says",
            body="_No combined report was produced for this run._ The "
                 "per-question findings below are complete and were not "
                 "affected.",
        ))

    steps = ReportSection(
        heading="How this brief was built",
        note="Each research question, its grounded answer, and the passages "
             "that answer rests on.",
        page_break_before=bool(sections),
    )
    children: list[ReportSection] = []
    for index, step in enumerate(run.steps, 1):
        if step.answer:
            children.append(ReportSection(
                heading=f"{index}. {step.question}",
                body=step.answer.answer,
                tables=_citation_table(step.answer.citations,
                                       caption="Evidence cited above"),
            ))
        else:
            children.append(ReportSection(
                heading=f"{index}. {step.question}",
                body=f"**This question was not answered.** {step.error or ''}".strip(),
            ))
    sections.append(ReportSection(
        heading=steps.heading, note=steps.note,
        page_break_before=steps.page_break_before, children=children,
    ))

    if run.discoveries:
        sections.append(ReportSection(
            heading="Public sources considered",
            note="Discovery leads, not automatically trusted evidence. "
                 "Abstract-only sources are labelled as such and were never "
                 "read in full.",
            tables=[ReportTable(
                columns=["Title", "Provider", "Year", "Scope", "URL"],
                rows=[[s.get("title", "—"), s.get("provider", "—"),
                       str(s.get("year", "—")), s.get("evidence_scope", "—"),
                       s.get("url", "—")] for s in run.discoveries],
                widths=[0.34, 0.12, 0.07, 0.15, 0.32],
            )],
        ))
    for message in run.discovery_errors or []:
        caveats.append(message)

    return ReportDocument(
        title="Research Brief",
        subtitle=run.goal,
        footer=f"Aletheia · {project_name or 'library'} · generated {shown}",
        provenance=provenance, caveats=caveats, sections=sections,
        filename=f"aletheia-brief-{_slug(run.goal)}-{stamp}.pdf",
    )


def reproducibility_document(*, report, paper_title: str = "") -> ReportDocument:
    """A disclosure audit for one paper."""
    shown, stamp = _timestamp()
    title = paper_title or f"Paper {report.paper_id}"
    repo = report.repo_metadata or {}

    sections = [ReportSection(
        heading="Disclosure checks",
        note="Each dimension is judged only on what the paper discloses. "
             "Nothing here runs the paper's code or reproduces its results.",
        tables=[ReportTable(
            columns=["Dimension", "Status", "Rationale", "Evidence"],
            rows=[[check.dimension, check.status.replace("_", " ").title(),
                   check.rationale,
                   ", ".join(c.evidence_id for c in check.citations) or "—"]
                  for check in report.checks],
            widths=[0.18, 0.11, 0.57, 0.14],
        )],
    )]

    cited = [c for check in report.checks for c in check.citations]
    if cited:
        sections.append(ReportSection(
            heading="Cited passages",
            note="The disclosure text each judgement above rests on.",
            page_break_before=True,
            tables=_citation_table(cited, caption=""),
        ))
    if report.links:
        sections.append(ReportSection(
            heading="Artefact links found in the paper",
            tables=[ReportTable(
                columns=["Kind", "URL", "Reachable"],
                rows=[[link.get("kind", "—"), link.get("url", "—"),
                       str(link.get("reachable", "not checked"))]
                      for link in report.links],
                widths=[0.16, 0.64, 0.20],
            )],
        ))
    if repo:
        sections.append(ReportSection(
            heading="Repository metadata",
            tables=[ReportTable(
                columns=["Field", "Value"],
                rows=[[k.replace("_", " ").title(), str(v)]
                      for k, v in repo.items()],
                widths=[0.28, 0.72],
            )],
        ))

    return ReportDocument(
        title="Reproducibility Audit",
        subtitle=title,
        footer=f"Aletheia · reproducibility audit · generated {shown}",
        provenance=[
            ("Paper", title),
            ("Generated", shown),
            ("Model", report.model or "—"),
            ("Disclosure score", f"{report.score:.0%} across "
                                 f"{len(report.checks)} dimension(s)"),
        ],
        caveats=[
            "This score measures what the paper *discloses*, not whether its "
            "results reproduce. Nothing here executed the paper's code."
        ],
        sections=sections,
        filename=f"aletheia-reproducibility-{_slug(title)}-{stamp}.pdf",
    )


__all__ = [
    "ReportDocument",
    "ReportSection",
    "ReportTable",
    "agent_document",
    "answer_document",
    "reproducibility_document",
]
