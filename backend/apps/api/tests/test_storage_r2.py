"""R2 storage backend.

The signature is checked three ways, because a storage backend that silently
fails to authenticate is the failure that loses a user's library:

  * against AWS's own published signing-key vector, so the HMAC chain is not
    merely self-consistent;
  * against a fake S3 server that re-derives the signature from the raw request
    it received, which is what catches a wrong canonical request;
  * against the real bucket, when credentials are configured (see the end).
"""

from __future__ import annotations

import hashlib
import hmac
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.services.storage import (
    LocalStorage,
    R2Storage,
    StorageError,
    _sign,
    build_storage,
)


def test_signing_key_matches_aws_published_vector():
    """AWS SigV4 documentation, 'Examples of how to derive a signing key'."""
    key = _sign(
        "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", "20150830", "us-east-1", "iam"
    )
    assert (
        key.hex()
        == "c4afb1cc5771d871763a393e44b703571b55cc28424d1a5e86da6ed3c154a4b9"
    )


# --- a fake S3 that verifies signatures ------------------------------------

ACCESS_KEY = "test-access-key"
SECRET_KEY = "test-secret-key"
BUCKET = "scratch"


class _FakeS3(BaseHTTPRequestHandler):
    objects: dict[str, bytes] = {}
    reject_with: int | None = None

    def log_message(self, *args):  # keep pytest output clean
        pass

    def _verify(self, body: bytes) -> bool:
        """Re-derive the signature from what actually arrived on the wire."""
        auth = self.headers.get("authorization", "")
        if not auth.startswith("AWS4-HMAC-SHA256 "):
            return False
        parts = dict(
            piece.strip().split("=", 1)
            for piece in auth[len("AWS4-HMAC-SHA256 ") :].split(",")
        )
        credential = parts["Credential"]
        signed_headers = parts["SignedHeaders"]
        given = parts["Signature"]
        _, date_stamp, region, service, _ = credential.split("/")

        payload_hash = self.headers["x-amz-content-sha256"]
        canonical_headers = "".join(
            f"{name}:{self.headers[name]}\n" for name in signed_headers.split(";")
        )
        canonical_request = "\n".join(
            [
                self.command,
                self.path,
                "",
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )
        scope = f"{date_stamp}/{region}/{service}/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                self.headers["x-amz-date"],
                scope,
                hashlib.sha256(canonical_request.encode()).hexdigest(),
            ]
        )
        expected = hmac.new(
            _sign(SECRET_KEY, date_stamp, region, service),
            string_to_sign.encode(),
            hashlib.sha256,
        ).hexdigest()
        # The client must also have hashed the body it really sent.
        if payload_hash != hashlib.sha256(body).hexdigest():
            return False
        return hmac.compare_digest(expected, given)

    def _handle(self, body: bytes = b""):
        if type(self).reject_with is not None:
            self.send_response(type(self).reject_with)
            self.end_headers()
            self.wfile.write(b"rejected")
            return None
        if not self._verify(body):
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"SignatureDoesNotMatch")
            return None
        return self.path

    def do_PUT(self):
        length = int(self.headers.get("content-length", 0))
        body = self.rfile.read(length)
        path = self._handle(body)
        if path is None:
            return
        type(self).objects[path] = body
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        path = self._handle()
        if path is None:
            return
        if path not in type(self).objects:
            self.send_response(404)
            self.end_headers()
            return
        payload = type(self).objects[path]
        self.send_response(200)
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_HEAD(self):
        path = self._handle()
        if path is None:
            return
        self.send_response(200 if path in type(self).objects else 404)
        self.end_headers()

    def do_DELETE(self):
        path = self._handle()
        if path is None:
            return
        type(self).objects.pop(path, None)
        self.send_response(204)
        self.end_headers()


@pytest.fixture
def fake_r2():
    _FakeS3.objects = {}
    _FakeS3.reject_with = None
    server = HTTPServer(("127.0.0.1", 0), _FakeS3)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    yield R2Storage(
        endpoint=f"http://{host}:{port}",
        bucket=BUCKET,
        access_key_id=ACCESS_KEY,
        secret_access_key=SECRET_KEY,
    )
    server.shutdown()
    server.server_close()


def test_round_trip(fake_r2):
    """The signature is accepted and the exact bytes come back."""
    data = b"%PDF-1.7 not really a pdf \x00\xff binary"
    assert fake_r2.store(key="proj/paper.pdf", data=data) == "proj/paper.pdf"
    assert fake_r2.read(key="proj/paper.pdf") == data


def test_overwrite_replaces_content(fake_r2):
    fake_r2.store(key="a/b.bin", data=b"first")
    fake_r2.store(key="a/b.bin", data=b"second")
    assert fake_r2.read(key="a/b.bin") == b"second"


def test_exists_reports_presence(fake_r2):
    assert fake_r2.exists(key="a/b.bin") is False
    fake_r2.store(key="a/b.bin", data=b"x")
    assert fake_r2.exists(key="a/b.bin") is True


def test_delete_is_idempotent(fake_r2):
    fake_r2.store(key="a/b.bin", data=b"x")
    fake_r2.delete(key="a/b.bin")
    assert fake_r2.exists(key="a/b.bin") is False
    fake_r2.delete(key="a/b.bin")  # must not raise


def test_read_missing_key_raises(fake_r2):
    with pytest.raises(StorageError, match="not found"):
        fake_r2.read(key="nope/missing.pdf")


def test_rejected_credentials_surface_as_storage_error(fake_r2):
    _FakeS3.reject_with = 403
    with pytest.raises(StorageError) as excinfo:
        fake_r2.store(key="a/b.bin", data=b"x")
    assert "403" in str(excinfo.value)


def test_empty_object_round_trips(fake_r2):
    """A zero-byte body must hash as the empty-payload digest, not be skipped."""
    fake_r2.store(key="a/empty.bin", data=b"")
    assert fake_r2.read(key="a/empty.bin") == b""


# --- key discipline, shared with LocalStorage -------------------------------


@pytest.mark.parametrize("key", ["../escape.pdf", "a/../../etc/passwd", "/abs.pdf", "a\\b.pdf", ""])
def test_r2_refuses_unsafe_keys(fake_r2, key):
    with pytest.raises(StorageError):
        fake_r2.store(key=key, data=b"x")


@pytest.mark.parametrize("key", ["../escape.pdf", "a/../../etc/passwd"])
def test_local_refuses_the_same_traversal_keys(tmp_path, key):
    """Both backends refuse the same keys, so swapping one for the other
    cannot widen what a key is allowed to address."""
    with pytest.raises(StorageError):
        LocalStorage(tmp_path).store(key=key, data=b"x")


# --- configuration ----------------------------------------------------------


def test_missing_credentials_name_the_variable():
    with pytest.raises(StorageError) as excinfo:
        R2Storage(
            endpoint="https://acct.r2.cloudflarestorage.com",
            bucket="",
            access_key_id="",
            secret_access_key="secret",
        )
    message = str(excinfo.value)
    assert "R2_BUCKET" in message and "R2_ACCESS_KEY_ID" in message


def test_build_storage_dispatches_to_r2():
    class _Settings:
        storage_backend = "r2"
        r2_endpoint = "https://acct.r2.cloudflarestorage.com"
        r2_bucket = "papers"
        r2_access_key_id = "id"
        r2_secret_access_key = "secret"
        r2_region = "auto"

    assert isinstance(build_storage(_Settings()), R2Storage)


def test_unknown_backend_names_the_value():
    class _Settings:
        storage_backend = "s4"

    with pytest.raises(StorageError, match="s4"):
        build_storage(_Settings())


# --- against the real bucket ------------------------------------------------
#
# Skipped unless R2 credentials are present, so the suite still runs offline
# and in CI. This is the test that proves the signature is accepted by R2
# itself rather than by a fake that agrees with us — run it once after
# `gcloud secrets create`, with the same values, before trusting a deploy:
#
#   R2_ENDPOINT_URL=... R2_BUCKET=aletheia-papers R2_ACCESS_KEY_ID=... \
#   R2_SECRET_ACCESS_KEY=... pytest apps/api/tests/test_storage_r2.py -k real_r2

import os
import uuid

_r2_env = {
    "endpoint": os.environ.get("R2_ENDPOINT_URL", ""),
    "bucket": os.environ.get("R2_BUCKET", ""),
    "access_key_id": os.environ.get("R2_ACCESS_KEY_ID", ""),
    "secret_access_key": os.environ.get("R2_SECRET_ACCESS_KEY", ""),
}


@pytest.mark.skipif(
    not all(_r2_env.values()), reason="R2 credentials not configured"
)
def test_real_r2_round_trip_and_cleanup():
    storage = R2Storage(**_r2_env, region=os.environ.get("R2_REGION", "auto"))
    key = f"_test/{uuid.uuid4()}.bin"
    payload = b"aletheia round trip \x00\x01\x02"
    try:
        storage.store(key=key, data=payload)
        assert storage.exists(key=key) is True
        assert storage.read(key=key) == payload
    finally:
        storage.delete(key=key)
    assert storage.exists(key=key) is False
