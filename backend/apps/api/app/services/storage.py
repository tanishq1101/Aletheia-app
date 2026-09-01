"""Storage seam.

Sprint 1 runs on local Postgres and local disk (see PROGRESS.md). A Supabase
Storage backend is intentionally NOT written yet: it cannot be verified against
a project that does not exist, and shipping an untested implementation would
break the "never claim done without verification" principle. This protocol is
the seam it will slot into.
"""

from pathlib import Path
from typing import Protocol

from app.core.config import Settings


class StorageError(RuntimeError):
    """Raised when a storage backend fails. Never swallowed."""


class StorageBackend(Protocol):
    def store(self, *, key: str, data: bytes) -> str:
        """Persist bytes under key. Returns the storage path recorded on the paper."""

    def read(self, *, key: str) -> bytes: ...

    def exists(self, *, key: str) -> bool: ...


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _resolve(self, key: str) -> Path:
        # Keys are built server-side from UUIDs, but resolve and re-check anyway
        # so a malformed key can never escape the storage root.
        target = (self._root / key).resolve()
        if not target.is_relative_to(self._root.resolve()):
            raise StorageError(f"Refusing to access path outside storage root: {key}")
        return target

    def store(self, *, key: str, data: bytes) -> str:
        target = self._resolve(key)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        except OSError as exc:
            raise StorageError(f"Could not write {key}: {exc}") from exc
        return key

    def read(self, *, key: str) -> bytes:
        target = self._resolve(key)
        try:
            return target.read_bytes()
        except OSError as exc:
            raise StorageError(f"Could not read {key}: {exc}") from exc

    def exists(self, *, key: str) -> bool:
        return self._resolve(key).is_file()


def build_storage(settings: Settings) -> StorageBackend:
    backend = settings.storage_backend.lower()
    if backend == "local":
        return LocalStorage(settings.storage_root)
    if backend == "supabase":
        raise StorageError(
            "STORAGE_BACKEND=supabase is not implemented yet. Sprint 1 runs on "
            "local storage by decision (see PROGRESS.md); the Supabase backend "
            "lands once a project is provisioned."
        )
    raise StorageError(f"Unknown STORAGE_BACKEND: {settings.storage_backend!r}")
