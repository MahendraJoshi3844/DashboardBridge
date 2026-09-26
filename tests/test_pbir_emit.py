import json

from t2pbi.pipeline import run


def test_pbir_pages_and_visuals_generated(sample_twb_path, tmp_path):
    run(sample_twb_path, tmp_path, "Sales")
    definition = tmp_path / "Sales.Report" / "definition"

    pages = json.loads((definition / "pages" / "pages.json").read_text())
    assert len(pages["pageOrder"]) == 1
    assert pages["activePageName"] == pages["pageOrder"][0]

    page_id = pages["pageOrder"][0]
    page = json.loads((definition / "pages" / page_id / "page.json").read_text())
    assert page["displayName"] == "Sales by Date"

    visual_files = list((definition / "pages" / page_id / "visuals").glob("*/visual.json"))
    assert len(visual_files) == 1
    visual = json.loads(visual_files[0].read_text())
    assert visual["visual"]["visualType"] == "clusteredBarChart"
    wells = visual["visual"]["query"]["queryState"]
    assert "Category" in wells and "Y" in wells


def test_pbir_is_deterministic(sample_twb_path, tmp_path):
    run(sample_twb_path, tmp_path / "a", "Sales")
    run(sample_twb_path, tmp_path / "b", "Sales")
    a = (tmp_path / "a" / "Sales.Report" / "definition" / "pages" / "pages.json").read_text()
    b = (tmp_path / "b" / "Sales.Report" / "definition" / "pages" / "pages.json").read_text()
    assert a == b
