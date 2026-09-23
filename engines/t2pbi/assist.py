"""Local AI assist: draft DAX for held items, entirely on this machine.

Held items are exactly what a language model is good at, but this product's first
promise is that workbook content never leaves the machine. So assist talks only
to a model runtime running on loopback (Ollama's default port). There is no cloud
path and no API key, and if no local runtime is listening the feature is simply
absent - never a silent fallback to a remote call.

A suggestion is always a proposal. It is labelled as drafted, and nothing is
written into the model until a human accepts it, so an accepted suggestion is
never mistaken for a deterministic conversion.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass

# Loopback only. This constant is the offline guarantee in code: a hostname that
# is not the local machine must never appear here - and `_endpoint` below
# *enforces* that rather than trusting this comment, because a comment does not
# run and an invariant nothing checks is one that erodes without anyone noticing.
_HOST = "127.0.0.1"
_PORT = 11434
_MODEL = "llama3.1"
_TIMEOUT_S = 45

_SYSTEM = (
    "You translate Tableau calculated fields into Power BI DAX. "
    "The deterministic converter refused this one and explained why. "
    "Return only a DAX expression, no prose, no code fences, no measure name. "
    "If you cannot produce correct DAX, return exactly: UNKNOWN"
)


@dataclass(frozen=True)
class Suggestion:
    dax: str
    note: str

    def to_dict(self) -> dict:
        return {"dax": self.dax, "note": self.note}


def _endpoint() -> tuple[str, int]:
    """The runtime's address, checked to be this machine before it is used.

    `require_loopback` reads a literal address with `ipaddress` rather than
    comparing strings, because `localhost.evil.example` defeats a prefix test
    and the whole of `127.0.0.0/8` is loopback while looking nothing like
    `127.0.0.1`. Raising here is deliberate: a misconfigured host is not a
    runtime that happens to be absent, and reporting it as absence would hide
    the one failure that matters.
    """
    from engines.ai.provider import require_loopback  # noqa: PLC0415

    return require_loopback(_HOST), _PORT


def runtime_available(timeout_s: float = 0.4) -> bool:
    """Is a local model runtime listening? Never probes anything but loopback."""
    address = _endpoint()
    try:
        with socket.create_connection(address, timeout=timeout_s):
            return True
    except OSError:
        return False


def build_prompt(name: str, formula: str, reason: str, table: str) -> str:
    """Assemble the request. Kept pure so its content is testable and reviewable.

    Only the single field's own formula is included - never the whole workbook.
    """
    return (
        f"{_SYSTEM}\n\n"
        f"Table: {table}\n"
        f"Field name: {name}\n"
        f"Tableau formula:\n{formula}\n\n"
        f"Why the converter refused it:\n{reason}\n\n"
        "DAX:"
    )


def _clean(raw: str) -> str:
    """Strip the wrappers models add even when told not to."""
    text = raw.strip()
    if text.startswith("```"):
        lines = [ln for ln in text.splitlines() if not ln.startswith("```")]
        text = "\n".join(lines).strip()
    if text.lower().startswith("dax:"):
        text = text[4:].strip()
    return text


def suggest_for(
    name: str, formula: str, reason: str, table: str, model: str = _MODEL
) -> Suggestion | None:
    """Ask the local runtime to draft DAX. Returns None when it cannot help."""
    if not runtime_available():
        return None

    payload = json.dumps(
        {
            "model": model,
            "prompt": build_prompt(name, formula, reason, table),
            "stream": False,
            "options": {"temperature": 0.1},
        }
    ).encode("utf-8")

    host, port = _endpoint()
    request = urllib.request.Request(
        f"http://{host}:{port}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None

    dax = _clean(body.get("response", ""))
    if not dax or dax.upper() == "UNKNOWN":
        return None
    return Suggestion(
        dax=dax,
        note=f"Drafted on this machine by {model}. Review before accepting.",
    )
