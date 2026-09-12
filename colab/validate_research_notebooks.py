#!/usr/bin/env python3
"""Execute every research notebook locally and keep the outputs in the file.

A notebook with empty `outputs` has never been run, whatever its prose claims.
Two of the three were validated here and the third was simply absent from the
list, so it shipped with nine code cells and no evidence that any of them
worked. The list is now derived from the directory, which is what stops that
happening again.

Two of the notebooks are self-contained and run as written. The Colab-native
reranker notebook needs three substitutions to run off a laptop, all of them
recorded in the notebook's own metadata so a reader can see exactly what was
changed:

  * `!pip install` lines are dropped — the packages are already present, and
    an IPython shell escape is not Python and will not compile.
  * Colab's `/content` is redirected into a scratch directory.
  * The pinned arXiv PDFs are seeded from the checked-out corpus instead of
    downloaded. The notebook still verifies every SHA-256 itself, so this
    skips the network, not the check.

This does not claim a hosted Colab run, and says so in the metadata.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_DIR = ROOT / "colab"
CORPUS_PDFS = ROOT / "backend/datasets/corpus/pdfs"

os.environ["ALETHEIA_DATA_DIR"] = str(ROOT / "backend/datasets/research")
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
# Headless: the reranker notebook calls plt.show().
os.environ.setdefault("MPLBACKEND", "Agg")

COLAB_ROOT = "/content/aletheia_neural_reranker"
SHELL_ESCAPE = re.compile(r"^\s*[!%]")


def strip_shell_escapes(source: str) -> tuple[str, int]:
    """Drop IPython shell/magic lines, which are not valid Python."""
    kept = [line for line in source.splitlines(True) if not SHELL_ESCAPE.match(line)]
    return "".join(kept), source.count("\n") + 1 - len(kept)


def seed_corpus(workdir: Path) -> None:
    """Put the verified PDFs where the notebook expects to download them."""
    destination = workdir / "pdfs"
    destination.mkdir(parents=True, exist_ok=True)
    for pdf in sorted(CORPUS_PDFS.glob("*.pdf")):
        shutil.copy2(pdf, destination / pdf.name)


NOTEBOOKS = [
    {
        "file": "Aletheia_Multisource_Relevance_Colab.ipynb",
        "done": lambda context: context["archive"].exists(),
    },
    {
        "file": "Aletheia_Scientific_Stance_Colab.ipynb",
        "done": lambda context: context["archive"].exists(),
    },
    {
        "file": "Aletheia_Neural_Reranker_Colab.ipynb",
        "colab_native": True,
        "done": lambda context: (context["OUTPUT_DIR"] / "metrics.json").exists(),
    },
]


def run(spec: dict) -> dict:
    filename = spec["file"]
    path = NOTEBOOK_DIR / filename
    notebook = json.loads(path.read_text())
    colab_native = spec.get("colab_native", False)

    context: dict = {"__name__": "__main__"}
    if colab_native:
        # `display` is an IPython builtin that Colab injects into every cell.
        # Providing the real one keeps the notebook source unmodified; without
        # it the notebook is not wrong, only unrunnable outside a kernel.
        from IPython.display import display

        context["display"] = display
    count = 0
    stripped_lines = 0
    started = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="aletheia-notebook-") as directory:
        workdir = Path(directory)
        if colab_native:
            seed_corpus(workdir)
        previous = Path.cwd()
        try:
            os.chdir(workdir)
            for cell in notebook["cells"]:
                if cell["cell_type"] != "code":
                    continue
                count += 1
                source = "".join(cell["source"])
                if colab_native:
                    source, dropped = strip_shell_escapes(source)
                    stripped_lines += dropped
                    source = source.replace(COLAB_ROOT, str(workdir))

                stdout = io.StringIO()
                with (
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stdout),
                ):
                    exec(  # noqa: S102 — executing the notebook is the point
                        compile(source, f"{filename}:cell-{count}", "exec"),
                        context,
                    )
                cell["execution_count"] = count
                cell["outputs"] = [
                    {
                        "output_type": "stream",
                        "name": "stdout",
                        "text": stdout.getvalue().splitlines(True),
                    }
                ]
                if "svg" in context and "svg =" in "".join(cell["source"]):
                    cell["outputs"].append(
                        {
                            "output_type": "display_data",
                            "metadata": {},
                            "data": {"image/svg+xml": context["svg"]},
                        }
                    )
            if not spec["done"](context):
                raise AssertionError(f"{filename} finished without its output artifact")
        finally:
            os.chdir(previous)

    environment = (
        "local Python; all code cells executed against downloaded snapshot; "
        "not hosted Colab"
    )
    validation = {"environment": environment, "code_cells": count}
    if colab_native:
        validation["environment"] = (
            "local Python; all code cells executed; not hosted Colab. "
            f"{stripped_lines} IPython shell-escape line(s) dropped (packages "
            "pre-installed), Colab's /content redirected to a scratch "
            "directory, and the pinned arXiv PDFs seeded from "
            "backend/datasets/corpus/pdfs — the notebook still verified every "
            "SHA-256 itself."
        )
        validation["substitutions"] = {
            "shell_escape_lines_dropped": stripped_lines,
            "content_root_redirected": True,
            "pdfs_seeded_from_local_corpus": True,
            "sha256_verification_performed_by_notebook": True,
        }

    notebook["metadata"]["aletheia_validation"] = validation
    path.write_text(json.dumps(notebook, indent=2) + "\n")

    return {
        "notebook": filename,
        "code_cells": count,
        "seconds": round(time.monotonic() - started, 2),
        "status": "passed",
    }


def main() -> None:
    known = {spec["file"] for spec in NOTEBOOKS}
    found = {path.name for path in NOTEBOOK_DIR.glob("*.ipynb")}
    if missing := sorted(found - known):
        # The exact failure this file exists to prevent: a notebook that is in
        # the repository and not in the list is a notebook nobody has run.
        raise SystemExit(
            "Notebooks present but not validated: "
            + ", ".join(missing)
            + ". Add them to NOTEBOOKS."
        )

    report = []
    for spec in NOTEBOOKS:
        report.append(run(spec))
        print(report[-1], flush=True)
    (NOTEBOOK_DIR / "validation-results.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
