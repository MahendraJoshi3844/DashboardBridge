"""A packaged workbook (.twbx) is analysed and converted over the API.

Found by a person uploading Superstore_V1.twbx: every .twbx failed analysis
with "We could not read that workbook", because the adapter handed the zip
itself to the XML parser. The API tests only ever sent plain .twb files, so
nothing noticed. A .twbx is the form most real workbooks arrive in.
"""

from __future__ import annotations

import io
import zipfile

from tests.dashboardbridge.test_conversion import FIXTURES
from tests.support.engines import needs_tableau

pytestmark = needs_tableau

PREFIX = "/api/v1"


def _packaged(name: str = "clashes.twb") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, (FIXTURES / name).read_bytes())
        archive.writestr("Data/extract.hyper", b"\x00" * 64)
    return buffer.getvalue()


def test_a_packaged_workbook_is_analysed_and_converted(api):
    client = api.client
    project_id = client.post(
        f"{PREFIX}/projects",
        json={"source_platform": "tableau", "target_platform": "powerbi", "name": "Packaged"},
    ).json()["project_id"]
    upload = client.post(
        f"{PREFIX}/projects/{project_id}/artifacts",
        files={"file": ("Packaged.twbx", _packaged(), "application/zip")},
    )
    assert upload.status_code in {200, 201}, upload.text

    analysis = client.post(f"{PREFIX}/projects/{project_id}/analysis")
    assert analysis.status_code == 202, analysis.text
    inventory = client.get(f"{PREFIX}/projects/{project_id}/analysis").json()["inventory"]
    assert inventory["tables"] >= 1

    conversion = client.post(f"{PREFIX}/projects/{project_id}/conversion", json={"ai_enabled": False})
    assert conversion.status_code == 202, conversion.text


def test_the_adapter_reads_a_packaged_workbook_directly():
    from engines.adapters.tableau import TableauAdapter

    adapter = TableauAdapter()
    model = adapter.normalize(adapter.parse(_packaged()))
    assert model.visuals
