# Dataset References

Compiled during Cowork planning. Match the source to the actual need — do not pull all of these indiscriminately.

## Ingestion corpus (Sprint 1–5 — real PDFs to feed the pipeline)
- arXiv Bulk Data Access: https://info.arxiv.org/help/bulk_data.html
- arXiv S3 bulk data: https://info.arxiv.org/help/bulk_data_s3.html
- kermitt2/arxiv_harvester (simpler scripted harvester): https://github.com/kermitt2/arxiv_harvester
- arxiv-community/arxiv_dataset on Hugging Face: https://huggingface.co/datasets/arxiv-community/arxiv_dataset
  — check the dataset card before use: confirm raw PDFs vs. pre-extracted text. Pre-extracted text defeats the point of testing the PyMuPDF extraction step (PRD Section 6).

## Metadata / paper discovery only (not the PDFs themselves)
- arXiv Dataset on Kaggle (Cornell-University): https://www.kaggle.com/datasets/Cornell-University/arxiv
- mattbierbaum/arxiv-public-datasets (metadata + full text at scale): https://github.com/mattbierbaum/arxiv-public-datasets

## LitQA2 / PaperQA2 — reference/comparison only (PRD Section 3), NOT the Sprint 6 benchmark
- Future-House/LitQA (the actual question set): https://github.com/Future-House/LitQA
- Future-House/paper-qa (their implementation): https://github.com/Future-House/paper-qa
- Future-House/LAB-Bench (broader eval suite LitQA2 sits inside): https://github.com/Future-House/LAB-Bench
- futurehouse/lab-bench on Hugging Face: https://huggingface.co/datasets/futurehouse/lab-bench

Do not reuse this as the Sprint 6 benchmark — it undercuts the PRD's own framing (Section 3.2) of extending PaperQA2 rather than just running their eval.

## Sprint 6 benchmark (~10 papers × 15 questions)
Hand-built by the team from the ingestion corpus above, per PRD Section 11. No external dataset substitutes for this — it has to match your own corpus and your own evidence-ID citation design (Section 5.3).

## Only relevant if Phase 6 needs actual model training (unresolved — see PROGRESS.md)
- allenai/s2orc on Hugging Face: https://huggingface.co/datasets/allenai/s2orc
- allenai/s2orc on GitHub: https://github.com/allenai/s2orc
- PMC Open Access FTP Service: https://pmc.ncbi.nlm.nih.gov/tools/ftp/
- Europe PMC bulk downloads: https://europepmc.org/downloads

Do not start pulling from this tier until the Phase 6 training-vs-heuristic question is answered (see PROGRESS.md open decisions).
