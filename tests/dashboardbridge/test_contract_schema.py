"""The exported schema is the language boundary, so it is guarded like one.

The web app's TypeScript types are generated from packages/contracts/schema.json.
If a Pydantic model changes and that file is not regenerated, the frontend keeps
compiling against a contract the backend no longer honours - and the failure
appears at runtime in a browser instead of in CI.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EXPORTER = REPO / "packages" / "contracts" / "export_schema.py"
SCHEMA = REPO / "packages" / "contracts" / "schema.json"


def _regenerate() -> dict:
    """Build the schema in-process, without writing over the committed file."""
    sys.path.insert(0, str(EXPORTER.parent))
    import export_schema  # noqa: PLC0415

    return export_schema.build()


def test_the_committed_schema_matches_the_models():
    """The drift gate. Regenerate with:

        python packages/contracts/export_schema.py
    """
    committed = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert committed == _regenerate(), (
        "packages/contracts/schema.json is stale. A contract changed without "
        "regenerating it, so the web app's generated types are now wrong. "
        "Run: python packages/contracts/export_schema.py"
    )


def test_export_is_deterministic():
    """Same models, same bytes - otherwise the drift gate cries wolf every run."""
    assert _regenerate() == _regenerate()


def test_every_contract_is_exported():
    names = set(_regenerate()["definitions"])
    # One representative from each layer; a missing layer means the exporter
    # stopped walking a module and the gate silently covers less than it claims.
    assert {"CanonicalModel", "Column", "VisualBinding"} <= names, "canonical layer"
    assert {"ConversionRequest", "Validation", "ApiError"} <= names, "api layer"
    assert {"Platform", "ConversionStatus", "PrivacyMode"} <= names, "enums"


def test_the_exporter_runs_as_a_script(tmp_path):
    """CI invokes it as a subprocess; an import-only test would not catch a
    broken __main__ path. Written to tmp so the test never touches the
    committed schema."""
    result = subprocess.run(
        [sys.executable, str(EXPORTER), str(tmp_path / "schema.json")],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stderr
    assert "definitions" in result.stdout


def test_numerical_validation_absence_survives_the_boundary():
    """ADR-003 must reach the frontend as a typed field, not a convention."""
    numerical = _regenerate()["definitions"]["NumericalValidation"]
    assert numerical["properties"]["measured"]["default"] is False
