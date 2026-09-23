"""Headless tests for the desktop worker's pure job function (no Qt/display needed)."""

import pytest

from engines.t2pbi.core.extract import InvalidWorkbookError
from engines.t2pbi.desktop.worker import JobSummary, run_job


def test_run_job_converts_sample(sample_twb_path, tmp_path):
    summary = run_job(sample_twb_path, tmp_path, "Sales")
    assert isinstance(summary, JobSummary)
    assert summary.stats["tables"] == 1
    assert summary.stats["calculated_translated"] == 1
    assert "Sales.pbip" in summary.pbip_path
    assert "migration-report" in summary.report_path


def test_run_job_headline_text(sample_twb_path, tmp_path):
    summary = run_job(sample_twb_path, tmp_path, "Sales")
    text = summary.headline()
    assert "tables" in text and "DAX" in text


def test_run_job_raises_on_invalid(tmp_path):
    bad = tmp_path / "bad.twb"
    bad.write_text("nonsense")
    with pytest.raises(InvalidWorkbookError):
        run_job(bad, tmp_path / "out", "bad")
