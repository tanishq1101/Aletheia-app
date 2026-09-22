"""Decoding JSON out of a model that was asked for JSON only.

"Return JSON only" is a request, not a parser contract. Providers wrap it in a
fence, and some prepend a sentence of explanation however plainly they were
told not to. This accepts exactly those two wrappers and nothing looser — the
caller's own schema checks and caps stay authoritative, so a reply that decodes
but means something else is still rejected downstream.
"""

import json

__all__ = ["decode_model_json"]


def decode_model_json(raw: str) -> object:
    """Decode strict JSON, a fenced JSON block, or one embedded JSON object.

    Raises `json.JSONDecodeError` when none of those are present.
    """
    candidate = raw.strip()

    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[-1].strip() == "```":
            candidate = "\n".join(lines[1:-1]).strip()

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # Some providers add one short sentence despite a JSON-only request.
        # Take exactly one outer object; anything else is still a failure.
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(candidate[start : end + 1])
