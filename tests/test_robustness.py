"""Robustness of extraction, output regeneration, and stage reporting."""

import zipfile

import pytest

from t2pbi.core.extract import InvalidWorkbookError, extract
from t2pbi.pipeline import run

MINIMAL_TWB = b"""<?xml version='1.0' encoding='utf-8' ?>
<workbook version='2021.4'>
  <datasources>
    <datasource name='federated.abc' caption='Orders'>
      <connection class='sqlserver' />
      <column name='[Sales]' datatype='real' role='measure' />
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name='Sheet 1'>
      <table><view><rows>[federated.abc].[sum:Sales:qk]</rows></view>
      <panes><pane><mark class='Bar' /></pane></panes></table>
    </worksheet>
  </worksheets>
</workbook>
"""

OTHER_TWB = MINIMAL_TWB.replace(b"[Sales]", b"[Revenue]").replace(
    b"caption='Orders'", b"caption='Billing'"
)


def _twbx(path, members: dict[str, bytes]):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def test_twbx_with_a_backup_copy_prefers_the_top_level_workbook(tmp_path):
    archive = _twbx(
        tmp_path / "wb.twbx",
        {"wb.twb": MINIMAL_TWB, "Backup/wb.twb": OTHER_TWB, "data.hyper": b"xx"},
    )
    result = extract(archive)
    assert b"[Sales]" in result.twb_bytes


def test_ambiguous_top_level_workbooks_are_still_rejected(tmp_path):
    archive = _twbx(tmp_path / "wb.twbx", {"a.twb": MINIMAL_TWB, "b.twb": OTHER_TWB})
    with pytest.raises(InvalidWorkbookError):
        extract(archive)


def test_extract_never_reads_data_extract_members(tmp_path):
    archive = _twbx(
        tmp_path / "wb.twbx", {"wb.twb": MINIMAL_TWB, "Data/big.hyper": b"y" * 5000}
    )
    result = extract(archive)
    assert result.resources["Data/big.hyper"] == 5000


def test_reconverting_into_the_same_folder_removes_the_previous_tables(tmp_path):
    first = tmp_path / "first.twb"
    first.write_bytes(MINIMAL_TWB)
    second = tmp_path / "second.twb"
    second.write_bytes(OTHER_TWB)
    out = tmp_path / "out"

    run(first, out, "Project")
    run(second, out, "Project")

    tables = {p.name for p in (out / "Project.SemanticModel" / "definition" / "tables").iterdir()}
    assert "Orders.tmdl" not in tables, "stale table from the previous conversion"
    assert "Billing.tmdl" in tables


def test_map_stage_is_reported_while_mapping_actually_happens(tmp_path):
    src = tmp_path / "wb.twb"
    src.write_bytes(MINIMAL_TWB)
    seen: list[str] = []

    def progress(label: str, _pct: int) -> None:
        seen.append(label)

    result = run(src, tmp_path / "out", "P", progress_cb=progress)
    stages = {name: i for i, name in enumerate(seen)}
    flag_stages = {f.stage for f in result.workbook.flags}
    # If visual mapping runs inside Generate, the tracer misreports which stage
    # is doing the work.
    assert "visual_map" in flag_stages
    assert stages["Map"] < stages["Generate"]
