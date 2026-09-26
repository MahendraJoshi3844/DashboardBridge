"""Where the data came from, and that the model has none of it.

Power BI Desktop opens a generated project and says "some of the tables have
incomplete or no data". That is true, expected, and by design - `CLAUDE.md` is
explicit that a full data extract is never read, only its schema - and until
now the product said nothing about it at all.

Two silent drops caused that, and both break the promise the product is built
on:

* **The parser kept the wrapper and discarded the connection.** A Tableau
  `<datasource>` for a file is a `federated` shell around a
  `<named-connection>` that holds the real thing: `excel-direct` with a
  filename, `textscan` with a directory and a filename, `sqlserver` with a
  server and a database. `connection` on the IR read `federated` for all three
  of Superstore's sources - the wrapper, which says nothing.
* **Nothing was flagged.** 185 flags, and not one mentioned data, refreshing, or
  a source. So the one thing the user has to do to make the converted model
  useful - point it at their copy of the data - was the one thing the migration
  report did not tell them.

An empty model is the correct output. An empty model that does not say what it
is missing, or where it was, is not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from t2pbi.core.parse import parse_workbook

FIXTURES = Path(__file__).resolve().parent / "fixtures"

FILE_SOURCES = b"""<?xml version='1.0' encoding='utf-8' ?>
<workbook version='2021.4'>
  <datasources>
    <datasource name='federated.abc' caption='Sample - Superstore'>
      <connection class='federated'>
        <named-connections>
          <named-connection caption='Sample - Superstore'>
            <connection class='excel-direct' filename='C:/data/Sample - Superstore.xls' server='' />
          </named-connection>
        </named-connections>
        <relation name='Orders' table='[Orders$]' type='table' />
      </connection>
      <column name='[Sales]' datatype='real' role='measure' />
    </datasource>
    <datasource name='federated.def' caption='Commission'>
      <connection class='federated'>
        <named-connections>
          <named-connection caption='Commission'>
            <connection class='textscan' directory='C:/data' filename='Commission.csv' server='' />
          </named-connection>
        </named-connections>
        <relation name='Commission' table='[Commission#csv]' type='table' />
      </connection>
      <column name='[Rate]' datatype='real' role='measure' />
    </datasource>
    <datasource name='federated.ghi' caption='Warehouse'>
      <connection class='federated'>
        <named-connections>
          <named-connection caption='Warehouse'>
            <connection class='sqlserver' server='sql01' dbname='Sales' />
          </named-connection>
        </named-connections>
        <relation name='Fact' table='[dbo].[Fact]' type='table' />
      </connection>
      <column name='[Amount]' datatype='real' role='measure' />
    </datasource>
  </datasources>
  <worksheets />
  <dashboards />
</workbook>
"""


@pytest.fixture(scope="module")
def workbook():
    return parse_workbook(FILE_SOURCES)


def _by_name(workbook, name: str):
    return next(ds for ds in workbook.datasources if ds.name == name)


# --- the connection the workbook actually names -----------------------------------


def test_a_file_source_is_read_as_the_file_and_not_as_federated(workbook):
    """`federated` is the wrapper Tableau puts around every source.

    Reporting it is like reporting that a parcel arrived in a box: true, and not
    what anyone needed to know.
    """
    assert _by_name(workbook, "Sample - Superstore").connection != "federated"


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Sample - Superstore", "excel-direct"),
        ("Commission", "textscan"),
        ("Warehouse", "sqlserver"),
    ],
)
def test_each_source_keeps_its_own_kind(workbook, name, expected):
    assert _by_name(workbook, name).connection == expected


def test_a_file_source_keeps_the_path_it_named(workbook):
    """The user has to find their copy of this file. Naming it is the
    difference between an instruction and a puzzle."""
    where = _by_name(workbook, "Sample - Superstore").source_location
    assert where and "Sample - Superstore.xls" in where


def test_a_directory_and_filename_are_joined_into_one_location(workbook):
    """`textscan` splits them across two attributes; a person wants one path."""
    where = _by_name(workbook, "Commission").source_location
    assert where and where.endswith("Commission.csv")
    assert "C:/data" in where


def test_a_server_source_names_the_server_and_database(workbook):
    where = _by_name(workbook, "Warehouse").source_location
    assert where and "sql01" in where and "Sales" in where


def test_a_source_with_nothing_to_say_says_nothing(workbook):
    """`None`, not a guess and not an empty string dressed as a location."""
    minimal = parse_workbook(
        b"<workbook version='2021.4'><datasources>"
        b"<datasource name='ds' caption='Bare'><connection class='sqlproxy' /></datasource>"
        b"</datasources><worksheets /><dashboards /></workbook>"
    )
    assert _by_name(minimal, "Bare").source_location is None


# --- and that it is reported ------------------------------------------------------


def test_every_source_is_flagged_with_where_its_data_was(workbook):
    """The one action the user must take to make the model useful.

    The converted model carries schema and no rows - deliberately, because a
    converter that read a full extract would be a different and much worse
    tool. Saying so is what turns Desktop's "incomplete or no data" from a
    mystery into a next step.
    """
    reported = {
        flag.item
        for flag in workbook.flags
        if "data" in flag.reason.lower() and flag.stage == "parse"
    }
    for name in ("Sample - Superstore", "Commission", "Warehouse"):
        assert name in reported, f"{name} never had its data source reported"


def test_the_flag_names_the_location_so_it_can_be_acted_on(workbook):
    flag = next(
        f
        for f in workbook.flags
        if f.item == "Sample - Superstore" and "data" in f.reason.lower()
    )
    assert "Sample - Superstore.xls" in flag.reason


def test_the_flag_says_the_model_has_no_rows_rather_than_that_something_failed(
    workbook,
):
    """This is a designed limit, not a failure, and the wording decides whether
    the user goes looking for a bug or goes and connects their data."""
    flag = next(
        f for f in workbook.flags if f.item == "Commission" and "data" in f.reason.lower()
    )
    lowered = flag.reason.lower()
    assert "no rows" in lowered or "schema" in lowered
    assert "error" not in lowered and "failed" not in lowered


def test_the_real_superstore_workbook_reports_all_three_of_its_sources():
    """The workbook that produced the Desktop warning, if it is present.

    `testing_content/` is gitignored, so this skips rather than fails on a
    clean clone - the fixture above is what runs everywhere.
    """
    real = Path(__file__).resolve().parents[1] / "testing_content" / "Superstore.twb"
    if not real.is_file():
        pytest.skip("Superstore.twb is not in this checkout")
    wb = parse_workbook(real.read_bytes())
    kinds = {ds.connection for ds in wb.datasources}
    assert kinds and kinds != {"federated"}, kinds
    reported = {f.item for f in wb.flags if "data" in f.reason.lower()}
    for ds in wb.datasources:
        assert ds.name in reported


# --- how it is said ---------------------------------------------------------------


@pytest.mark.parametrize(
    "kind, words",
    [
        ("excel-direct", "an Excel file"),
        ("textscan", "a text or CSV file"),
        ("sqlserver", "a SQL Server database"),
        ("hyper", "a Tableau extract"),
    ],
)
def test_the_connection_kind_is_said_in_words_a_person_uses(kind, words):
    """`excel-direct` is how Tableau names it internally. Nobody calls a
    spreadsheet an excel-direct, and this text goes in a migration report a
    consultant hands to a stakeholder."""
    from t2pbi.core.parse.datasources import _kind_in_words

    assert _kind_in_words(kind) == words


def test_an_unmapped_kind_keeps_its_own_name_rather_than_going_vague():
    """An unmapped class is still a fact about the workbook. Replacing it with
    "a data source" would lose information to look tidy - and it reads wrong
    besides, which is how "a excel-direct source" got shipped for one run."""
    from t2pbi.core.parse.datasources import _kind_in_words

    assert _kind_in_words("teradata") == "a teradata source"
    assert _kind_in_words("odbc") == "an odbc source"


def test_no_flag_says_a_before_a_vowel(workbook):
    """The first version wrote "It was a excel-direct source"."""
    import re

    for flag in workbook.flags:
        assert not re.search(r"\ba [aeiou]", flag.reason), flag.reason
