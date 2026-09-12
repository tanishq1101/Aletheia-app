from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Paragraph
from reportlab.pdfgen import canvas

OUT = "/Users/pratyushsinha/Downloads/Aletheia/output/pdf/aletheia-project-summary.pdf"
W, H = A4
M = 16 * mm

INK = HexColor("#1E293B")
MUTED = HexColor("#64748B")
PAPER = HexColor("#F8FAFC")
PANEL = HexColor("#FFFFFF")
LINE = HexColor("#CBD5E1")
NAVY = HexColor("#173B64")
BLUE = HexColor("#2563EB")
TEAL = HexColor("#0F766E")
AMBER = HexColor("#B45309")
RED = HexColor("#B91C1C")
GREEN = HexColor("#15803D")
VIOLET = HexColor("#6D28D9")

styles = getSampleStyleSheet()
body = ParagraphStyle("body", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.8, leading=12, textColor=INK)
small = ParagraphStyle("small", parent=body, fontSize=7.3, leading=9.5, textColor=MUTED)
card_text = ParagraphStyle("card", parent=body, fontSize=8.2, leading=10.5)

def para(c, text, x, y_top, width, style=body):
    p = Paragraph(text, style)
    _, h = p.wrap(width, 200 * mm)
    p.drawOn(c, x, y_top - h)
    return h

def footer(c, page):
    c.setStrokeColor(LINE); c.line(M, 13*mm, W-M, 13*mm)
    c.setFont("Helvetica", 7.5); c.setFillColor(MUTED)
    c.drawString(M, 8.5*mm, "Aletheia - project brief")
    c.drawRightString(W-M, 8.5*mm, f"Page {page}")

def page_title(c, kicker, title, subtitle, page):
    c.setFillColor(PAPER); c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(NAVY); c.rect(0, H-34*mm, W, 34*mm, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 8); c.setFillColor(HexColor("#93C5FD")); c.drawString(M, H-12*mm, kicker.upper())
    c.setFont("Helvetica-Bold", 23); c.setFillColor(colors.white); c.drawString(M, H-22*mm, title)
    c.setFont("Helvetica", 8.5); c.setFillColor(HexColor("#DBEAFE")); c.drawString(M, H-29*mm, subtitle)
    footer(c, page)

def card(c, x, y, w, h, title, accent=BLUE):
    c.setFillColor(PANEL); c.setStrokeColor(LINE); c.roundRect(x, y-h, w, h, 3*mm, fill=1, stroke=1)
    c.setFillColor(accent); c.roundRect(x, y-h, 4, h, 2, fill=1, stroke=0)
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 9); c.drawString(x+10, y-14, title)

def pill(c, x, y, text, color):
    c.setFont("Helvetica-Bold", 7)
    w = stringWidth(text, "Helvetica-Bold", 7) + 12
    c.setFillColor(color); c.roundRect(x, y-12, w, 12, 6, fill=1, stroke=0)
    c.setFillColor(colors.white); c.drawCentredString(x+w/2, y-8.5, text)
    return w

def bullet(c, x, y, text, width, color=BLUE):
    c.setFillColor(color); c.circle(x+2, y-4, 2, fill=1, stroke=0)
    return para(c, text, x+10, y, width-10, card_text) + 4

def flow(c, labels, x, y, total_w):
    gap = 7
    bw = (total_w-gap*(len(labels)-1))/len(labels)
    for i, (label, color) in enumerate(labels):
        bx = x + i*(bw+gap)
        c.setFillColor(colors.white); c.setStrokeColor(color); c.roundRect(bx, y-24, bw, 24, 3, fill=1, stroke=1)
        c.setFillColor(color); c.setFont("Helvetica-Bold", 7.2)
        lines = label.split("\n")
        for j, line in enumerate(lines): c.drawCentredString(bx+bw/2, y-10-j*8, line)
        if i < len(labels)-1:
            c.setStrokeColor(MUTED); c.setLineWidth(1); c.line(bx+bw+1, y-12, bx+bw+gap-2, y-12)
            c.setFillColor(MUTED); c.circle(bx+bw+gap-2, y-12, 1.7, fill=1, stroke=0)

c = canvas.Canvas(OUT, pagesize=A4)
c.setTitle("Aletheia Project Summary")

# 1. Overview
page_title(c, "Project summary", "Aletheia", "Research intelligence workspace - implementation snapshot", 1)
c.setFont("Helvetica-Bold", 11); c.setFillColor(INK); c.drawString(M, H-47*mm, "1. Project Overview")
card(c, M, H-52*mm, W-2*M, 38*mm, "Mission", NAVY)
para(c, "<b>Turn a research library into auditable answers.</b><br/>Aletheia ingests project sources, extracts structured paper content, retrieves evidence semantically, reranks it, and returns grounded answers with traceable page and section citations.", M+12, H-59*mm, W-2*M-24, body)
c.setFont("Helvetica-Bold", 11); c.setFillColor(INK); c.drawString(M, H-101*mm, "Value proposition")
flow(c, [("Research\nsources", BLUE), ("Structured\nextraction", TEAL), ("Semantic\nretrieval", VIOLET), ("Evidence-led\nanswer", AMBER)], M, H-107*mm, W-2*M)
card(c, M, H-146*mm, 84*mm, 45*mm, "What it is", BLUE)
y = H-160*mm
for t in ["Research-paper library and reader", "Project-scoped semantic search", "Cited question answering and agent research"]:
    y -= bullet(c, M+11, y, t, 70*mm)
card(c, M+91*mm, H-146*mm, 87*mm, 45*mm, "What it is not", RED)
y = H-160*mm
for t in ["A generic chat-with-PDF demo", "An uncited answer generator", "A replacement for researcher judgement"]:
    y -= bullet(c, M+102*mm, y, t, 73*mm, RED)
c.setFont("Helvetica-Bold", 11); c.setFillColor(INK); c.drawString(M, H-202*mm, "2. Target Audience / Users")
for x, title, text, color in [(M, "Researchers", "Compare papers, inspect source passages, and synthesize evidence.", TEAL), (M+60*mm, "Students", "Read technical literature with visible provenance and page-level context.", BLUE), (M+120*mm, "Research teams", "Maintain project-specific libraries, questions, and documented findings.", VIOLET)]:
    card(c, x, H-207*mm, 55*mm, 31*mm, title, color); para(c, text, x+10, H-219*mm, 42*mm, small)
c.showPage()

# 2 Stack
page_title(c, "Architecture", "Technology map", "Frontend, backend, retrieval, storage, and model operations", 2)
c.setFont("Helvetica-Bold", 11); c.setFillColor(INK); c.drawString(M, H-47*mm, "3. Tech Stack & Tools")
layers = [
    ("Experience", "Next.js 16 - TypeScript - Tailwind CSS", BLUE),
    ("Application API", "FastAPI - Pydantic - Python", TEAL),
    ("Document intelligence", "PyMuPDF - normalization - section-aware chunking", VIOLET),
    ("Retrieval", "FastEmbed Jina embeddings - pgvector - local reranker", AMBER),
    ("Generation", "OpenRouter LLM for grounded answers, agent planning, figure interpretation", NAVY),
    ("Persistence", "Postgres 17 - local source storage - Chroma mirror where configured", GREEN),
]
y = H-55*mm
for name, detail, color in layers:
    c.setFillColor(PANEL); c.setStrokeColor(LINE); c.roundRect(M, y-17, W-2*M, 17, 3, fill=1, stroke=1)
    c.setFillColor(color); c.roundRect(M, y-17, 37*mm, 17, 3, fill=1, stroke=0)
    c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 7.7); c.drawCentredString(M+18.5*mm, y-10.5, name)
    c.setFillColor(INK); c.setFont("Helvetica", 8.5); c.drawString(M+41*mm, y-10.5, detail)
    y -= 21
c.setFont("Helvetica-Bold", 11); c.drawString(M, H-192*mm, "Evidence flow")
flow(c, [("Add\nsource", BLUE), ("Parse +\nchunk", TEAL), ("Embed +\nindex", VIOLET), ("Retrieve +\nrerank", AMBER), ("Cite\nanswer", NAVY)], M, H-199*mm, W-2*M)
card(c, M, H-239*mm, W-2*M, 30*mm, "Design controls", RED)
para(c, "<b>Grounding:</b> the backend issues evidence IDs and resolves citations; model-invented IDs are removed. &nbsp;&nbsp; <b>Resilience:</b> ingestion jobs expose stage, progress, failure, and retry state. &nbsp;&nbsp; <b>Security:</b> API keys remain server-side environment variables.", M+12, H-250*mm, W-2*M-24, small)
c.showPage()

# 3 features/status
page_title(c, "Delivery view", "Features and current status", "Implemented capabilities, preview surfaces, and operating constraints", 3)
c.setFont("Helvetica-Bold", 11); c.setFillColor(INK); c.drawString(M, H-47*mm, "4. Core Features")
features = [
    ("Project sources", "Projects, source inventory, upload, delete, processing status", "LIVE", GREEN),
    ("Reading workspace", "Library filters, extracted pages, section outline, figures/tables/assets", "LIVE", GREEN),
    ("Semantic retrieval", "Embedded chunks, project scope, page/section-aware results", "LIVE", GREEN),
    ("Ask and citations", "Retrieve -> rerank -> evidence context -> cited response", "LIVE", GREEN),
    ("Research Agent", "Bounded subquestions, source discovery, grounded synthesis", "LIVE - KEY REQUIRED", AMBER),
    ("Claim / cross-paper / reproducibility", "Verification and comparison workflows", "PREVIEW / IN PROGRESS", VIOLET),
]
y = H-55*mm
for name, desc, status, color in features:
    card(c, M, y, W-2*M, 21*mm, name, color)
    para(c, desc, M+12, y-18, 112*mm, small)
    pill(c, W-M-50*mm, y-10, status, color)
    y -= 24*mm
c.setFont("Helvetica-Bold", 11); c.setFillColor(INK); c.drawString(M, H-207*mm, "5. Current Status")
card(c, M, H-213*mm, W-2*M, 34*mm, "Snapshot", BLUE)
para(c, "<b>Core workspace:</b> operational locally - source ingestion, library, reader, semantic retrieval, Ask, and the bounded Research Agent are wired. <br/><b>Model operations:</b> local embeddings/reranking and research diagnostics are present; hosted-generation routes require an OpenRouter key. <br/><b>Product maturity:</b> active implementation - core RAG is usable; verification and reproducibility surfaces need completion and live-data hardening.", M+12, H-224*mm, W-2*M-24, small)
c.showPage()

# 4 notebooks
page_title(c, "Training assets", "Three Colab model-training notebooks", "Purpose, architecture, validation design, and production role", 4)
c.setFont("Helvetica-Bold", 11); c.setFillColor(INK); c.drawString(M, H-47*mm, "Colab notebook portfolio")
notebooks = [
    ("1. Neural Reranker", "Aletheia_Neural_Reranker_Colab.ipynb", "5 -> 16 -> 8 -> 1 PyTorch MLP", "Trains a compact query-passage relevance reranker over a pinned 10-paper arXiv corpus and 150 benchmark questions.", "Question-ID held-out split; MRR and Recall@6 versus cosine baseline; SHA-256 corpus validation.", "Candidate experiment - does not replace production cross-encoder.", BLUE),
    ("2. Multi-source Relevance", "Aletheia_Multisource_Relevance_Colab.ipynb", "516 -> 96 -> 32 -> 2 NumPy network", "Learns whether a query and passage are relevant using SciQ and SQuAD public pairs.", "70/15/15 connected-group split; leakage checks; weighted loss, early stopping, held-out macro F1.", "Integrated only as experimental answer diagnostics.", TEAL),
    ("3. Scientific Stance", "Aletheia_Scientific_Stance_Colab.ipynb", "516 -> 128 -> 48 -> 2 NumPy network", "Classifies support vs contradiction on annotated SciFact abstract pairs.", "Same split discipline; confusion matrix, class F1, validation-selected checkpoint.", "Experimental only - no neutral class and not a fact checker.", VIOLET),
]
y = H-55*mm
for title, file, arch, purpose, eval_text, role, color in notebooks:
    card(c, M, y, W-2*M, 53*mm, title, color)
    para(c, f"<b>File:</b> {file}<br/><b>Architecture:</b> {arch}<br/><b>Purpose:</b> {purpose}<br/><b>Evaluation:</b> {eval_text}<br/><b>Production role:</b> {role}", M+12, y-17, W-2*M-24, small)
    y -= 57*mm
c.showPage()

# 5 metrics + next steps
page_title(c, "Decision support", "Model signal and next priorities", "Measured outcomes, limitations, and a practical sequence to completion", 5)
c.setFont("Helvetica-Bold", 11); c.setFillColor(INK); c.drawString(M, H-47*mm, "Training results - experimental diagnostics")
rows = [("Relevance classifier", "89.87%", "0.8987", "84.96%", GREEN), ("Scientific stance", "54.00%", "0.4715", "63.00%", AMBER)]
headers = ["Model", "Test accuracy", "Test macro F1", "Baseline accuracy"]
xs = [M, M+65*mm, M+103*mm, M+140*mm]
c.setFillColor(NAVY); c.roundRect(M, H-61*mm, W-2*M, 10*mm, 3, fill=1, stroke=0)
c.setFont("Helvetica-Bold", 7.6); c.setFillColor(colors.white)
for x, h in zip(xs, headers): c.drawString(x+3, H-55*mm, h)
y = H-71*mm
for name, acc, f1, base, color in rows:
    c.setFillColor(PANEL); c.setStrokeColor(LINE); c.roundRect(M, y-9*mm, W-2*M, 11*mm, 2, fill=1, stroke=1)
    c.setFillColor(color); c.rect(M, y-9*mm, 4, 11*mm, fill=1, stroke=0)
    c.setFillColor(INK); c.setFont("Helvetica", 8.2)
    for x, val in zip(xs, [name, acc, f1, base]): c.drawString(x+5, y-4.5*mm, val)
    y -= 13*mm
card(c, M, H-106*mm, W-2*M, 31*mm, "Interpretation guardrails", RED)
para(c, "Relevance improves on its lexical baseline and is useful as a diagnostic signal. Stance accuracy trails its majority baseline; contradiction performance is weak. Neither model determines truth, replaces the Jina reranker, overrides LLM evidence, or supplies calibrated confidence.", M+12, H-118*mm, W-2*M-24, small)
c.setFont("Helvetica-Bold", 11); c.setFillColor(INK); c.drawString(M, H-149*mm, "6. Next Steps & Priorities")
priorities = [
    ("P0 - Stability", "Keep local API, database migrations, and source deletion reliable; add regression coverage for source types and lifecycle.", RED),
    ("P1 - Product completion", "Replace preview claim, cross-paper, and reproducibility pages with live API-backed workflows.", AMBER),
    ("P1 - Search quality", "Benchmark source-scoped retrieval, chunk settings, reranking, and failure fallback against a fixed question set.", BLUE),
    ("P2 - Research operations", "Run the Colabs in hosted Colab, retain artifacts, and only promote models after end-to-end evaluation.", TEAL),
    ("P2 - Deployment readiness", "Add authentication, production storage, observability, secrets management, and CI/CD checks.", VIOLET),
]
y = H-157*mm
for label, text, color in priorities:
    card(c, M, y, W-2*M, 18*mm, label, color)
    para(c, text, M+12, y-17, W-2*M-24, small)
    y -= 21*mm
c.showPage()

# 6 roadmap flow
page_title(c, "Execution plan", "Recommended delivery flow", "A concise operating roadmap for the next project cycle", 6)
c.setFont("Helvetica-Bold", 11); c.setFillColor(INK); c.drawString(M, H-47*mm, "From working prototype to research-ready platform")
steps = [
    ("1", "Stabilize", "Migrations, health, delete lifecycle, source-format tests", RED),
    ("2", "Complete live workflows", "Connect verification, cross-paper, reproducibility to real APIs", AMBER),
    ("3", "Measure retrieval", "Fixed evaluation set, source scope, chunk and reranker comparisons", BLUE),
    ("4", "Validate models", "Hosted Colab run, retained artifacts, end-to-end diagnostic assessment", TEAL),
    ("5", "Harden deployment", "Auth, managed storage, monitoring, CI/CD", VIOLET),
]
y = H-62*mm
for i, (n, title, detail, color) in enumerate(steps):
    cx = M+9*mm
    c.setFillColor(color); c.circle(cx, y-5*mm, 7*mm, fill=1, stroke=0)
    c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 12); c.drawCentredString(cx, y-8*mm, n)
    if i < len(steps)-1:
        c.setStrokeColor(LINE); c.setLineWidth(2); c.line(cx, y-13*mm, cx, y-34*mm)
    card(c, M+24*mm, y+2*mm, W-M-(M+24*mm), 25*mm, title, color)
    para(c, detail, M+36*mm, y-14*mm, W-M-(M+41*mm), small)
    y -= 34*mm
card(c, M, H-248*mm, W-2*M, 28*mm, "Success condition", GREEN)
para(c, "A researcher can add a source, see exactly what the system used, ask a question, inspect page-level citations, understand uncertainty, and reproduce the operational path without hidden model behavior or silent failure.", M+12, H-259*mm, W-2*M-24, small)
c.save()
print(OUT)
