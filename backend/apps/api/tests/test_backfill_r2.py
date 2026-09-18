"""The local-disk -> R2 backfill.

The script exists because switching STORAGE_BACKEND moves where the API looks
for bytes, not the bytes themselves. Its failure modes matter more than its
happy path: a file silently skipped, or wrong bytes written under a right key,
would leave a library that looks complete and is not.
"""

from __future__ import annotations

import hashlib
import importlib.util
from argparse import Namespace
from pathlib import Path

import pytest

from app.services.storage import LocalStorage
from tests.test_storage_r2 import fake_r2  # noqa: F401  (pytest fixture)

REPO_ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "backfill_r2", REPO_ROOT / "scripts" / "backfill_r2.py"
)
backfill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill)


def row(key: str, label: str = "paper.pdf", sha256: str | None = None) -> dict:
    return {"row_id": "r1", "key": key, "label": label, "sha256": sha256}


def args(**overrides) -> Namespace:
    base = dict(force=False, dry_run=False, verify=False)
    base.update(overrides)
    return Namespace(**base)


@pytest.fixture
def local(tmp_path):
    return LocalStorage(tmp_path)


def test_copies_a_file_that_r2_does_not_have(local, fake_r2):
    data = b"%PDF-1.7 body"
    local.store(key="proj/a.pdf", data=data)
    tally = backfill.Tally()

    backfill.transfer(row("proj/a.pdf"), local, fake_r2, args(), tally)

    assert len(tally.copied) == 1
    assert fake_r2.read(key="proj/a.pdf") == data


def test_skips_a_key_r2_already_holds(local, fake_r2):
    fake_r2.store(key="proj/a.pdf", data=b"already there")
    local.store(key="proj/a.pdf", data=b"different local bytes")
    tally = backfill.Tally()

    backfill.transfer(row("proj/a.pdf"), local, fake_r2, args(), tally)

    assert tally.already and not tally.copied
    # Untouched: skipping must not overwrite.
    assert fake_r2.read(key="proj/a.pdf") == b"already there"


def test_force_overwrites_an_existing_key(local, fake_r2):
    fake_r2.store(key="proj/a.pdf", data=b"stale")
    local.store(key="proj/a.pdf", data=b"fresh")
    tally = backfill.Tally()

    backfill.transfer(row("proj/a.pdf"), local, fake_r2, args(force=True), tally)

    assert fake_r2.read(key="proj/a.pdf") == b"fresh"


def test_records_a_file_that_is_not_on_this_machine(local, fake_r2):
    """The paused deployment's disk is gone; these need re-uploading."""
    tally = backfill.Tally()

    backfill.transfer(row("proj/gone.pdf", "gone.pdf"), local, fake_r2, args(), tally)

    assert tally.missing == ["gone.pdf (proj/gone.pdf)"]
    assert tally.unrecoverable  # so the run exits non-zero
    assert not fake_r2.exists(key="proj/gone.pdf")


def test_refuses_to_upload_bytes_that_contradict_the_recorded_digest(local, fake_r2):
    """Wrong bytes under a right key is worse than a missing file: nothing
    downstream would ever notice."""
    local.store(key="proj/a.pdf", data=b"not the file that was uploaded")
    recorded = hashlib.sha256(b"the file that was uploaded").hexdigest()
    tally = backfill.Tally()

    backfill.transfer(row("proj/a.pdf", sha256=recorded), local, fake_r2, args(), tally)

    assert len(tally.mismatched) == 1
    assert not tally.copied
    assert fake_r2.exists(key="proj/a.pdf") is False


def test_matching_digest_is_uploaded(local, fake_r2):
    data = b"the file that was uploaded"
    local.store(key="proj/a.pdf", data=data)
    tally = backfill.Tally()

    backfill.transfer(
        row("proj/a.pdf", sha256=hashlib.sha256(data).hexdigest()),
        local,
        fake_r2,
        args(),
        tally,
    )

    assert len(tally.copied) == 1
    assert fake_r2.read(key="proj/a.pdf") == data


def test_verify_reads_the_object_back(local, fake_r2):
    data = b"round trip me"
    local.store(key="proj/a.pdf", data=data)
    tally = backfill.Tally()

    backfill.transfer(row("proj/a.pdf"), local, fake_r2, args(verify=True), tally)

    assert len(tally.copied) == 1 and not tally.failed


def test_dry_run_writes_nothing(local, fake_r2):
    local.store(key="proj/a.pdf", data=b"x")
    tally = backfill.Tally()

    backfill.transfer(row("proj/a.pdf"), local, fake_r2, args(dry_run=True), tally)

    assert len(tally.copied) == 1
    assert fake_r2.exists(key="proj/a.pdf") is False


def test_assets_without_a_digest_still_copy(local, fake_r2):
    """paper_assets has no sha256 column, so sha256 is None for every asset."""
    local.store(key="assets/p/figure-0.png", data=b"\x89PNG fake")
    tally = backfill.Tally()

    backfill.transfer(
        row("assets/p/figure-0.png", "figure #0", sha256=None),
        local,
        fake_r2,
        args(),
        tally,
    )

    assert len(tally.copied) == 1
    assert fake_r2.read(key="assets/p/figure-0.png") == b"\x89PNG fake"
