import json

from engines.t2pbi.pipeline import run


def test_end_to_end_creates_pbip_and_report(sample_twb_path, tmp_path):
    result = run(sample_twb_path, tmp_path, "Sales")

    # PBIP scaffold exists.
    assert result.pbip_path.exists()
    model_dir = tmp_path / "Sales.SemanticModel"
    assert (model_dir / "definition" / "model.tmdl").exists()
    assert (model_dir / "definition" / "tables" / "federated.sales.tmdl").exists() or any(
        (model_dir / "definition" / "tables").glob("*.tmdl")
    )

    # Supported calc translated; unsupported one flagged MANUAL.
    s = result.stats
    assert s["calculated_fields"] == 2
    assert s["calculated_translated"] == 1
    assert s["manual_flags"] >= 1

    # Report json is present and lists the manual flag.
    data = json.loads((tmp_path / "migration-report.json").read_text())
    assert any(f["severity"] == "manual" for f in data["flags"])


def test_determinism(sample_twb_path, tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    run(sample_twb_path, a, "Sales")
    run(sample_twb_path, b, "Sales")
    fa = (a / "Sales.SemanticModel" / "definition" / "model.tmdl").read_text()
    fb = (b / "Sales.SemanticModel" / "definition" / "model.tmdl").read_text()
    assert fa == fb


def test_invalid_input_raises(tmp_path):
    from engines.t2pbi.core.extract import InvalidWorkbookError

    bad = tmp_path / "bad.twb"
    bad.write_text("not a workbook")
    try:
        run(bad, tmp_path / "out", "bad")
        assert False, "expected InvalidWorkbookError"
    except InvalidWorkbookError:
        pass
