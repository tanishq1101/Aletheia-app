"""The reranker notebook and the script that generates it must not diverge.

They already did once, in both directions at the same time. The notebook was
ahead — it carried the pypdf parser, the arXiv download retry loop and the fix
for a `NameError` that hit anyone who chose "Run all" — while the generator
still emitted the old PyMuPDF version and twelve `{key}` sites that reached the
reader as literal braces. Running the generator would have silently reverted
all of it.

Nothing failed while they disagreed, which is the point of asserting it here:
this is the only check that runs without someone deciding to run it.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
COLAB = ROOT / "colab"
GENERATORS = sorted(COLAB.glob("build_*_notebook.py")) if COLAB.is_dir() else []


@pytest.mark.skipif(not GENERATORS, reason="no notebook generators in this checkout")
@pytest.mark.parametrize("generator", GENERATORS, ids=lambda path: path.name)
def test_notebook_matches_its_generator(generator: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(generator), "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, (
        f"{generator.name} and the notebook it generates have diverged. "
        "Port the notebook's changes into the generator, then rerun it with "
        f"--force.\n{result.stdout}{result.stderr}"
    )
