#!/usr/bin/env python3
"""Store an OpenRouter key in backend/.env without echoing it."""

from __future__ import annotations

from getpass import getpass
import os
from pathlib import Path
import tempfile


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = BACKEND_ROOT / ".env"
ENV_NAME = "OPENROUTER_API_KEY"


def main() -> int:
    key = getpass("Enter OPENROUTER_API_KEY (input is hidden): ").strip()
    if not key:
        print("No key entered; nothing changed.")
        return 1
    if not key.startswith("sk-or-v1-"):
        print(
            "That is not an OpenRouter inference key (expected prefix: sk-or-v1-); "
            "nothing changed."
        )
        return 2

    existing = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    replacement = f"{ENV_NAME}={key}"
    updated: list[str] = []
    replaced = False
    for line in existing:
        if line.startswith(f"{ENV_NAME}="):
            if not replaced:
                updated.append(replacement)
                replaced = True
            continue
        updated.append(line)
    if not replaced:
        updated.append(replacement)

    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".env.", dir=ENV_PATH.parent, text=True
    )
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write("\n".join(updated).rstrip() + "\n")
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, ENV_PATH)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)

    print(f"Saved {ENV_NAME} to backend/.env (value not displayed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
