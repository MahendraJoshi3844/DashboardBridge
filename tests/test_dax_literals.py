"""String-literal and keyword-detection correctness in the DAX translator.

DAX reads 'single quotes' as a table reference, so a Tableau string literal that
survives unconverted produces DAX that silently fails to validate. Keyword and
marker scans must likewise ignore text inside literals and field names.
"""

from t2pbi.core.dax import translate_formula


def test_single_quoted_literal_becomes_a_dax_string():
    r = translate_formula("IF [Region] = 'West' THEN 1 ELSE 0 END", "T")
    assert r.dax == 'IF(\'T\'[Region] = "West", 1, 0)'


def test_single_quoted_literal_containing_an_apostrophe_word_is_preserved():
    r = translate_formula("IF [City] = 'O''Fallon' THEN 1 ELSE 0 END", "T")
    assert r.dax is not None
    assert "O'Fallon" in r.dax


def test_no_emitted_dax_contains_a_single_quoted_literal():
    r = translate_formula("IF [Region] = 'West' THEN 'a' ELSE 'b' END", "T")
    assert r.dax is not None
    assert "'West'" not in r.dax
    assert "'a'" not in r.dax


def test_keyword_inside_a_string_does_not_break_conditional_parsing():
    r = translate_formula('IF CONTAINS([Name],"END") THEN 1 ELSE 0 END', "T")
    assert r.dax == 'IF(CONTAINSSTRING(\'T\'[Name],"END"), 1, 0)'


def test_field_named_like_an_unsupported_construct_is_still_converted():
    r = translate_formula("[Fixed Cost] + 1", "T")
    assert r.dax == "'T'[Fixed Cost] + 1"


def test_genuine_lod_expression_is_still_refused():
    r = translate_formula("{FIXED [Order ID]: SUM([Profit])} > 0", "T")
    assert r.dax is None
    assert "FIXED" in r.reason


def test_genuine_table_calc_is_still_refused():
    r = translate_formula("RUNNING_SUM(SUM([Sales]))", "T")
    assert r.dax is None


def test_bracket_text_inside_a_string_literal_is_not_rewritten_as_a_column():
    r = translate_formula('IF [Region] = "West" THEN "[Sales] total" ELSE "" END', "T")
    assert r.dax is not None
    assert '"[Sales] total"' in r.dax
