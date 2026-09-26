"""The rule pack: translation rules as reviewable data, not Python literals.

`P3.1`. 06-conversion-engine.md, "Rule engine":

    > Data-driven and versioned. Rules are YAML ..., not Python literals, so
    > they can be reviewed, diffed, and eventually shipped as rule packs.

What these tests protect is not the file format. It is that a rule pack fails
*loudly*. A Python dict cannot lose an entry between two runs; a file can - by
a bad merge, a truncated write, a duplicate key that shadows its twin - and a
lost rule does not raise. It converts one fewer formula, reports that formula
as needing a person, and looks exactly like a workbook that was always going
to need one.

The existing DAX suite is the parity net: if a mapping is lost in the move,
those tests fail. These cover what they cannot see.
"""

from __future__ import annotations

import pytest

from t2pbi.core.dax.rules import (
    RulePackError,
    function_rules,
    load_pack,
    refusal_rules,
)


def test_every_rule_is_identified_and_no_two_share_an_id():
    """A duplicate id shadows a mapping, and shadowing is silent."""
    ids = [rule.rule_id for rule in (*function_rules(), *refusal_rules())]
    assert ids, "the pack is empty"
    assert all(ids), "a rule with no id cannot be cited by a translation"
    assert len(ids) == len(set(ids)), "two rules share an id"


def test_the_pack_loads_in_the_same_order_every_time():
    """Determinism: same input, same output, including the order rules fire in."""
    first = [rule.rule_id for rule in function_rules()]
    second = [rule.rule_id for rule in function_rules()]
    assert first == second
    assert first == sorted(first), "order is content, not filesystem order"


def test_a_rule_naming_no_target_is_refused_at_load(tmp_path):
    """A half-written rule must not load as a rule that maps to nothing.

    Silently skipping it removes a function from the supported set, and the
    only visible effect is a formula that quietly stops converting.
    """
    bad = tmp_path / "functions.yaml"
    bad.write_text(
        "functions:\n"
        "  - rule_id: TABLEAU_SUM_TO_PBI_SUM\n"
        "    version: 1\n"
        "    source: SUM\n",
        encoding="utf-8",
    )
    with pytest.raises(RulePackError) as caught:
        load_pack(tmp_path)
    assert "TABLEAU_SUM_TO_PBI_SUM" in str(caught.value)


def test_a_duplicated_rule_id_is_refused_at_load(tmp_path):
    (tmp_path / "functions.yaml").write_text(
        "functions:\n"
        "  - rule_id: DUPE\n    version: 1\n    source: SUM\n    target: SUM\n"
        "  - rule_id: DUPE\n    version: 1\n    source: MIN\n    target: MIN\n",
        encoding="utf-8",
    )
    # Both halves of a pack must be present before the id check is reachable;
    # a missing file is the earlier and louder failure.
    (tmp_path / "refusals.yaml").write_text("refusals: []\n", encoding="utf-8")
    with pytest.raises(RulePackError) as caught:
        load_pack(tmp_path)
    assert "DUPE" in str(caught.value)


def test_a_missing_pack_is_refused_rather_than_treated_as_no_rules(tmp_path):
    """No rules and no pack are different facts.

    An empty supported set converts nothing and reports every calculation as
    needing a person - a plausible-looking result produced by a missing file.
    """
    with pytest.raises(RulePackError):
        load_pack(tmp_path / "nowhere")


def test_the_function_rules_cover_what_the_translator_advertises():
    """The pack is the source of truth for the supported set."""
    from t2pbi.core.dax.functions import SUPPORTED_FUNCS

    assert SUPPORTED_FUNCS == {
        rule.source_function: rule.target_function for rule in function_rules()
    }


def test_every_refusal_says_why_in_words_a_person_can_act_on():
    """A refusal marker without a reason becomes an unexplained rejection."""
    for rule in refusal_rules():
        assert rule.marker, rule.rule_id
        assert len(rule.reason) > 20, f"{rule.rule_id} has no usable reason"


def test_the_markers_still_disqualify_the_constructs_the_spec_names():
    """Table calculations and every LOD form, including the simple ones."""
    markers = {rule.marker for rule in refusal_rules()}
    for named in ("WINDOW_", "RUNNING_", "INDEX(", "RANK(", "FIXED", "INCLUDE",
                  "EXCLUDE", "SCRIPT_", "RAWSQL"):
        assert named in markers, f"{named} is no longer refused"


def test_the_pack_is_shipped_with_the_package():
    """YAML beside a module is data, and data is not installed by default.

    Left undeclared, `pip install t2pbi` produces a package whose loader
    refuses its own pack: the engine converts nothing, and only in the built
    artifact, never in the checkout it was tested in.
    """
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    package_data = config["tool"]["setuptools"].get("package-data", {})
    # Keyed by the *import* path, which moved with `P2.1`.
    patterns = package_data.get("t2pbi", [])
    assert any("dax/rules" in pattern for pattern in patterns), (
        "the rule pack is not declared as package data, so an installed "
        "t2pbi would have no rules"
    )
    assert any(
        dep.lower().startswith("pyyaml") for dep in config["project"]["dependencies"]
    ), "the pack is YAML but PyYAML is not a declared dependency"


# --- what produced this DAX (P3.2) ----------------------------------------


def test_a_translation_names_every_rule_that_produced_it():
    """The audit trail's answer to "why is this DAX what it is".

    A formula can fire several mappings, so the citation is plural. Recording
    only one of two would name an arbitrary half of the reason.
    """
    from t2pbi.core.dax import translate_formula

    result = translate_formula("Sum([Profit])/countD([Order ID])", "Orders")
    assert result.dax is not None
    assert set(result.rule_ids) == {
        "TABLEAU_SUM_TO_PBI_SUM",
        "TABLEAU_COUNTD_TO_PBI_DISTINCTCOUNT",
    }


def test_a_translation_the_rules_did_not_touch_cites_none():
    """Empty is a fact, not a gap.

    A control-flow rewrite is the translator's own work; no function mapping
    fired. Citing a rule anyway would credit the pack for something it did not
    do, and 10 of Superstore's 21 calculations are in this case.
    """
    from t2pbi.core.dax import translate_formula

    result = translate_formula('IF [x] THEN "a" ELSE "b" END', "Orders")
    assert result.dax is not None
    assert result.rule_ids == ()


def test_the_cited_rules_are_ordered_so_two_runs_agree():
    from t2pbi.core.dax import translate_formula

    first = translate_formula("Sum([Profit])/countD([Order ID])", "Orders")
    second = translate_formula("Sum([Profit])/countD([Order ID])", "Orders")
    assert first.rule_ids == second.rule_ids
    assert list(first.rule_ids) == sorted(first.rule_ids)
