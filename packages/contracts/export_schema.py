"""Export every contract as one JSON Schema document.

This is the single source of truth crossing the language boundary: the Pydantic
models are authored once, and the TypeScript types the web app uses are generated
from this file. A backend change that breaks the frontend therefore fails at
build time rather than at runtime in a browser.

    python packages/contracts/export_schema.py [output_path]

Deterministic: models are emitted in sorted order so the output only changes when
a contract actually changes, and drift is a reviewable diff.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "src"))

from dashboardbridge_contracts import api, canonical  # noqa: E402
from pydantic import BaseModel  # noqa: E402

OUT = HERE / "schema.json"


def _models() -> dict[str, type[BaseModel]]:
    found: dict[str, type[BaseModel]] = {}
    for module in (canonical, api):
        for name in dir(module):
            value = getattr(module, name)
            if (
                isinstance(value, type)
                and issubclass(value, BaseModel)
                and value.__module__ == module.__name__
                and not name.startswith("_")
                # Base classes carry no contract of their own.
                and name not in {"ApiModel", "CanonicalBase"}
            ):
                found[name] = value
    return found


def build() -> dict:
    definitions: dict[str, dict] = {}
    for name, model in sorted(_models().items()):
        schema = model.model_json_schema(ref_template="#/definitions/{model}")
        definitions.update(schema.pop("$defs", {}))
        definitions[name] = schema
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "DashboardBridgeContracts",
        "definitions": dict(sorted(definitions.items())),
    }


def main() -> int:
    OUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(build()['definitions'])} definitions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
