"""Storage seam.

Two backends implement `StorageBackend`:

  * `local` — a directory on disk. What development and any host with a
    persistent volume use.
  * `r2` — Cloudflare R2 through its S3-compatible API. Required on hosts with
    ephemeral disk: Cloudflare Containers hand a container a *fresh* disk every
    time it wakes from sleep, so a local-disk deployment there would leave the
    `papers` rows in Postgres pointing at files that no longer exist.

R2 is spoken to directly over `httpx` with SigV4 signing rather than through
boto3. botocore is ~50 MB for four verbs, and this API ships in a slim
container — the same reasoning already recorded for choosing reportlab over
WeasyPrint. The Supabase backend remains unwritten; it cannot be verified
against a project that does not exist.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx

from app.core.config import Settings


class StorageError(RuntimeError):
    """Raised when a storage backend fails. Never swallowed."""


class StorageBackend(Protocol):
    def store(self, *, key: str, data: bytes) -> str:
        """Persist bytes under key. Returns the storage path recorded on the paper."""

    def read(self, *, key: str) -> bytes: ...

    def exists(self, *, key: str) -> bool: ...

    def delete(self, *, key: str) -> None: ...


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

    def delete(self, *, key: str) -> None:
        try:
            self._resolve(key).unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError(f"Could not delete {key}: {exc}") from exc


_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _validate_key(key: str) -> str:
    """Reject keys that would address something other than what they name.

    S3 has no parent directory, so `..` cannot escape a bucket the way it can
    escape a directory — but a key containing it still *stores* under a
    literal `..` segment while `LocalStorage` would have refused outright. Both
    backends refusing the same keys is what lets the two be swapped without
    re-auditing every call site.
    """
    if not key or key.startswith("/") or "\\" in key:
        raise StorageError(f"Refusing malformed storage key: {key!r}")
    if any(segment in {"..", "."} for segment in key.split("/")):
        raise StorageError(f"Refusing storage key with relative segment: {key!r}")
    return key


def _sign(secret: str, date: str, region: str, service: str) -> bytes:
    """Derive a SigV4 signing key: date -> region -> service -> terminator."""
    mac = hmac.new(f"AWS4{secret}".encode(), date.encode(), hashlib.sha256).digest()
    for part in (region, service, "aws4_request"):
        mac = hmac.new(mac, part.encode(), hashlib.sha256).digest()
    return mac


class R2Storage:
    """Cloudflare R2 over the S3 REST API, signed with AWS SigV4."""

    _SERVICE = "s3"

    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        region: str = "auto",
        timeout: float = 30.0,
    ) -> None:
        missing = [
            name
            for name, value in (
                ("R2_ENDPOINT (or R2_ACCOUNT_ID)", endpoint),
                ("R2_BUCKET", bucket),
                ("R2_ACCESS_KEY_ID", access_key_id),
                ("R2_SECRET_ACCESS_KEY", secret_access_key),
            )
            if not value
        ]
        if missing:
            # Named, not "misconfigured": a deploy that is one variable short
            # should say which one rather than fail on the first upload.
            raise StorageError(
                "STORAGE_BACKEND=r2 requires " + ", ".join(missing)
            )
        self._endpoint = endpoint.rstrip("/")
        # SigV4 signs the Host header exactly as it goes on the wire, and an
        # HTTP client includes a non-default port there. Signing the bare
        # hostname would still work against R2 on 443 and break against any
        # endpoint carrying a port, which is precisely what the tests use.
        parsed = httpx.URL(self._endpoint)
        self._host = (
            f"{parsed.host}:{parsed.port}" if parsed.port is not None else parsed.host
        )
        self._bucket = bucket
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._region = region
        self._timeout = timeout

    def _canonical_path(self, key: str) -> str:
        # Each segment encoded once. S3 signs the un-normalised path, so the
        # separators must survive encoding while the segments are escaped.
        segments = [quote(part, safe="") for part in key.split("/")]
        return "/" + quote(self._bucket, safe="") + "/" + "/".join(segments)

    def _request(
        self, method: str, key: str, *, data: bytes | None = None
    ) -> httpx.Response:
        path = self._canonical_path(_validate_key(key))
        payload = data if data is not None else b""
        payload_hash = hashlib.sha256(payload).hexdigest() if data is not None else _EMPTY_SHA256

        now = _dt.datetime.now(_dt.timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")

        headers = {
            "host": self._host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        signed_headers = ";".join(sorted(headers))
        canonical_headers = "".join(
            f"{name}:{headers[name]}\n" for name in sorted(headers)
        )
        canonical_request = "\n".join(
            [method, path, "", canonical_headers, signed_headers, payload_hash]
        )

        scope = f"{date_stamp}/{self._region}/{self._SERVICE}/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                scope,
                hashlib.sha256(canonical_request.encode()).hexdigest(),
            ]
        )
        signature = hmac.new(
            _sign(self._secret_access_key, date_stamp, self._region, self._SERVICE),
            string_to_sign.encode(),
            hashlib.sha256,
        ).hexdigest()

        headers["authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self._access_key_id}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )

        try:
            return httpx.request(
                method,
                f"{self._endpoint}{path}",
                headers=headers,
                content=payload if data is not None else None,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise StorageError(f"R2 {method} {key} failed: {exc}") from exc

    def store(self, *, key: str, data: bytes) -> str:
        response = self._request("PUT", key, data=data)
        if response.status_code not in (200, 201):
            raise StorageError(
                f"Could not write {key}: R2 returned {response.status_code} "
                f"{response.text[:200]}"
            )
        return key

    def read(self, *, key: str) -> bytes:
        response = self._request("GET", key)
        if response.status_code == 404:
            raise StorageError(f"Could not read {key}: not found in R2")
        if response.status_code != 200:
            raise StorageError(
                f"Could not read {key}: R2 returned {response.status_code} "
                f"{response.text[:200]}"
            )
        return response.content

    def exists(self, *, key: str) -> bool:
        response = self._request("HEAD", key)
        if response.status_code == 200:
            return True
        if response.status_code == 404:
            return False
        raise StorageError(
            f"Could not stat {key}: R2 returned {response.status_code}"
        )

    def delete(self, *, key: str) -> None:
        response = self._request("DELETE", key)
        # S3 delete is idempotent: a missing key is a successful delete, and
        # `LocalStorage.delete` uses missing_ok=True for the same reason.
        if response.status_code not in (200, 204, 404):
            raise StorageError(
                f"Could not delete {key}: R2 returned {response.status_code} "
                f"{response.text[:200]}"
            )


def build_storage(settings: Settings) -> StorageBackend:
    backend = settings.storage_backend.lower()
    if backend == "local":
        return LocalStorage(settings.storage_root)
    if backend == "r2":
        return R2Storage(
            endpoint=settings.r2_endpoint,
            bucket=settings.r2_bucket,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
            region=settings.r2_region,
        )
    if backend == "supabase":
        raise StorageError(
            "STORAGE_BACKEND=supabase is not implemented yet. Use 'r2' for "
            "object storage, or 'local' where the disk survives a restart."
        )
    raise StorageError(f"Unknown STORAGE_BACKEND: {settings.storage_backend!r}")
