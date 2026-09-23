"""What the XML parser will accept, and what it refuses (`P7.4`).

The parser was built as `XMLParser(recover=True, huge_tree=True)`, and every
security-relevant property of it came from lxml's defaults rather than being
stated. Three things came out of measuring that rather than reading it, and one
of them contradicted the first draft of this file.

## `huge_tree=True` was the only deliberate weakening, and it bought nothing

It turns off libxml2's own resource limits. Measured: 100,000 levels of nesting
parse happily with it and stop at 256 without it. The whole suite passes without
it, and so does a 9 MB text node - the shape a real workbook's embedded
thumbnail takes, and the plausible reason someone reached for the flag. Past
10 MB, libxml2 2.14 truncates a text node and 2.11 does not, so the parser
refuses one itself rather than let the answer depend on the platform.

## The error type moved, and the guard went quiet

libxml2 2.14 files the depth limit and the entity guard under
`ERR_RESOURCE_LIMIT`, where 2.11 used `ERR_INTERNAL_ERROR` and `ERR_ENTITY_LOOP`.
The limits held; the refusal did not, because it matched on the old types. lxml
6.1.3's Linux wheel ships 2.14 and its Windows wheel 2.11, so this surfaced
only in CI.

## The safe setting was silently lossy, which is why it could not just be set

With `recover=True`, hitting a limit does not raise. It returns a **truncated
tree**: 257 elements out of 20,001, no exception, no flag. Silent truncation is
the one thing this project does not do, so turning the limits back on and
leaving it there would have traded a bounded attack for lost data.

The first fix drafted was "refuse whenever recovery reported a FATAL", and it
was wrong. libxml2 marks nearly every real-world malformation FATAL - including
the unescaped `&` that `recover=True` was added for - so that rule would have
rejected exactly the workbooks the flag exists to tolerate. Content loss is
distinguishable by error *type* instead, not by severity.

## Entities do expand, and the first version of this file said they did not

An entity in an **attribute value** is always substituted, whatever
`resolve_entities` says - that setting governs text nodes. Measured, a ~400-byte
document expands an attribute to 300,000 characters before libxml2's own guard
stops it: real, bounded, about 750-fold. Not a memory-exhaustion vector.

What it *is* is a second route to the same silent drop. Past the guard, the
parse does not fail; the element that used the entity is discarded and parsing
continues. A `<datasource>` vanishing without a word is the same defect as the
truncated tree.

External entities are genuinely not resolved, and only because of a default -
lxml 4.x resolved them. A version bump was all that stood between this and XXE,
with nothing failing. The settings are stated explicitly now, and asserted here.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from lxml import etree

from engines.t2pbi.core.parse import ParseLimitExceeded, _parser, parse_workbook

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _doc(depth: int) -> bytes:
    return b"<workbook version='18.1'>" + b"<a>" * depth + b"</a>" * depth + b"</workbook>"


# --- what must keep working -----------------------------------------------------


@pytest.mark.parametrize(
    "name", ["sample.twb", "clashes.twb", "federated.twb", "shelves.twb", "hostile.twb"]
)
def test_every_fixture_still_parses(name):
    """A limit that costs the product its own corpus is not a fix."""
    workbook = parse_workbook((FIXTURES / name).read_bytes())
    assert workbook.all_tables()


def test_a_recoverable_malformation_still_parses():
    """Why `recover=True` is there at all.

    An unescaped `&` is common in workbooks people actually have, and libxml2
    reports it as FATAL. The first version of this fix refused on any FATAL and
    would have rejected them all.
    """
    workbook = parse_workbook(
        b"<workbook version='18.1'><datasources>"
        b"<datasource caption='Sales &amp Marketing' name='ds'/>"
        b"</datasources></workbook>"
    )
    assert workbook is not None


def _thumbnail_doc(size: int) -> bytes:
    return (
        b"<workbook version='18.1'><thumbnails><thumbnail>"
        + b"x" * size
        + b"</thumbnail></thumbnails></workbook>"
    )


def test_a_large_text_node_still_parses():
    """The plausible reason someone reached for `huge_tree` in the first place.

    A real `.twb` carries base64 thumbnails. This is bigger than any of them and
    is read whole, so the flag was not buying this either.

    This used to be 11 MB, and passed on libxml2 2.14 while the text came back
    cut to 9,999,952 characters: asserting "a workbook came back" cannot see a
    truncation. So the size is under the limit, and the text is measured.
    """
    size = 9 * 1024 * 1024
    parser = _parser()
    root = etree.fromstring(_thumbnail_doc(size), parser=parser)
    assert len(root.find(".//thumbnail").text) == size
    assert parse_workbook(_thumbnail_doc(size)) is not None


def test_a_text_node_past_the_limit_is_refused_on_every_libxml2():
    """libxml2 2.14 truncates this; 2.11 reads it whole. Neither is acceptable
    as a platform difference - the same workbook must not convert on the Windows
    desktop app and be cut short on a Linux server - so both refuse it."""
    with pytest.raises(ParseLimitExceeded) as raised:
        parse_workbook(_thumbnail_doc(11 * 1024 * 1024))

    assert "text" in str(raised.value).lower()


# --- the limit ------------------------------------------------------------------


def test_excessive_nesting_is_refused_rather_than_silently_truncated():
    """The defect this exists for.

    Before: 20,001 elements in, 257 elements out, no exception. A workbook
    silently missing everything below level 256 is indistinguishable from one
    that never had it.
    """
    with pytest.raises(ParseLimitExceeded):
        parse_workbook(_doc(10_000))


def test_the_refusal_names_the_limit_rather_than_calling_the_file_corrupt():
    """Different problems, different actions. "Corrupt" sends someone to
    re-save a workbook that is fine."""
    with pytest.raises(ParseLimitExceeded) as raised:
        parse_workbook(_doc(10_000))

    message = str(raised.value).lower()
    assert "nest" in message or "depth" in message
    assert "corrupt" not in message


def test_a_document_within_the_limit_is_untouched():
    """The bound is libxml2's, and 256 levels is far past anything Tableau
    writes - so this must not be a limit anyone meets by accident."""
    workbook = parse_workbook(_doc(100))
    assert workbook is not None


# --- entities -------------------------------------------------------------------


def test_an_external_entity_is_not_resolved():
    """XXE. Not exploitable today, and only because of a default.

    lxml 4.x resolved entities by default; a version bump would have opened
    this with nothing failing. The setting is explicit now, and this is what
    would notice if it stopped being.
    """
    secret = Path(tempfile.mkdtemp()) / "secret.txt"
    secret.write_text("TOP-SECRET-CONTENTS", encoding="utf-8")

    workbook = parse_workbook(
        f"""<?xml version="1.0"?>
        <!DOCTYPE workbook [ <!ENTITY xxe SYSTEM "file:///{secret.as_posix()}"> ]>
        <workbook version="18.1"><datasources>
        <datasource caption="&xxe;" name="ds"/>
        </datasources></workbook>""".encode()
    )

    assert "TOP-SECRET" not in repr(workbook)


#: One newline, spelled this way because the byte literals below are built
#: by concatenation and an escape in the wrong place is a silent syntax change.
_NL = chr(10).encode()


def _entity_bomb(levels: int) -> bytes:
    """`levels` of tenfold entity nesting: 30 * 10 ** (levels - 1) characters."""
    lines = [b'<!ENTITY e0 "' + b"A" * 30 + b'">']
    for index in range(1, levels):
        lines.append(b'<!ENTITY e%d "' % index + (b"&e%d;" % (index - 1)) * 10 + b'">')
    return (
        b'<?xml version="1.0"?>' + _NL
        + b"<!DOCTYPE workbook [" + _NL
        + _NL.join(lines) + _NL
        + b"]>" + _NL
        + b'<workbook version="18.1"><datasources>'
        + b'<datasource caption="&e%d;" name="ds"/>' % (levels - 1)
        + b"</datasources></workbook>"
    )


def test_a_modest_entity_expansion_does_expand():
    """Stated because the first draft of this file claimed the opposite.

    An entity in an *attribute value* is always substituted, whatever
    `resolve_entities` says - that setting governs text nodes. Measured, a
    ~400-byte document expands an attribute to 300,000 characters before
    libxml2's own guard stops it: real, bounded, and about 750-fold.

    That is not a memory-exhaustion vector, and saying so is the point. Writing
    "entities are not resolved" would have been a comfortable claim that the
    measurement does not support.
    """
    workbook = parse_workbook(_entity_bomb(5))
    assert "AAAAAAAAAA" in repr(workbook)


def test_an_entity_expanding_past_the_guard_is_refused_not_silently_dropped():
    """The real defect on this path.

    Past libxml2's amplification guard the parse does not fail - it drops the
    element that used the entity and carries on. A `<datasource>` vanishing
    without a word is the same failure as the truncated tree, arriving by a
    different route.
    """
    with pytest.raises(ParseLimitExceeded):
        parse_workbook(_entity_bomb(7))


# --- the settings themselves -----------------------------------------------------


def test_the_security_settings_are_stated_not_inherited():
    """Every one of these is lxml's current default, and that is the point.

    A default is a decision someone else makes and can change in a minor
    release - lxml 4.x resolved entities by default. Read from the source
    rather than from the parser object, because `XMLParser` exposes none of
    these as attributes; a source check is blunt, and it is what there is.

    **Read from the call, not from the text.** Two earlier versions of this
    test searched the source as a string and both passed while a setting was
    deleted: first because the docstring mentions the settings, so prose
    describing the code satisfied a check meant for the code, and then because
    the attempt to strip the docstring silently did nothing - the working tree
    is CRLF, and on Python 3.13+ `__doc__` is dedented at compile time, so a
    docstring is not found in its own source by either comparison.

    The call's keyword arguments are the thing being asserted, so this reads
    them.
    """
    import ast
    import inspect
    import textwrap

    from engines.t2pbi.core import parse as module

    tree = ast.parse(textwrap.dedent(inspect.getsource(module._parser)))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "XMLParser"
    ]
    assert len(calls) == 1, "expected exactly one parser construction"
    settings = {
        keyword.arg: keyword.value.value
        for keyword in calls[0].keywords
        if isinstance(keyword.value, ast.Constant)
    }

    assert settings == {
        "recover": True,
        "huge_tree": False,
        "resolve_entities": False,
        "load_dtd": False,
        "dtd_validation": False,
        "no_network": True,
    }


def test_the_parser_is_built_in_one_place():
    """Two parsers is two configurations, and only one of them gets hardened."""
    import inspect

    from engines.t2pbi.core import parse as module

    assert inspect.getsource(module).count("XMLParser(") == 1
