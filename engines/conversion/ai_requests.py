"""Turn a refused calculation into the least a model needs (`P4.5`).

07-ai-engine.md §29. `LLMRequest` has nowhere to put a workbook, which stops the
worst version of this. It cannot stop a caller putting every column in the
workbook into `fields` - that would be minimisation in shape only - so the
extraction is here, and it sends the fields the expression actually names.

**This lives outside `engines/ai` on purpose.** Pulling the pieces out needs the
canonical model, and the AI layer is not allowed to import it; a boundary test
enforces that. The seam is exactly the point: everything the model may see
crosses it as plain strings, and the crossing is one function that can be read
in full.

`policy_for` is the other half - the names `P4.4` checks a proposal against.
Also flat strings, for the same reason.
"""

from __future__ import annotations

from dashboardbridge_contracts import CanonicalModel

from engines.ai import FieldSchema, LLMRequest
from engines.ai.proposal import Policy


def _columns(model: CanonicalModel):
    for datasource in model.datasources or []:
        for table in datasource.tables or []:
            for column in table.columns or []:
                yield table, column


def request_for(
    model: CanonicalModel,
    column_id: str,
    refusal_reason: str,
    *,
    operation: str = "translate_calculation",
) -> LLMRequest:
    """The request for one refused calculation, and nothing more.

    Raises `KeyError` rather than returning an empty request for a column that
    is not there: an empty request would be sent, answered, and the answer would
    be about nothing.
    """
    found = next(
        ((table, column) for table, column in _columns(model) if column.id == column_id),
        None,
    )
    if found is None:
        raise KeyError(f"no column {column_id!r} in this model")
    table, column = found
    if column.expression is None:
        raise KeyError(f"{column_id!r} carries no expression to translate")

    return LLMRequest(
        operation=operation,
        source_platform=model.source_platform.value
        if hasattr(model.source_platform, "value")
        else str(model.source_platform),
        target_platform="powerbi",
        expression=column.expression.source_text,
        fields=_referenced_fields(model, table.name, column.expression.source_text),
        rule_ids=tuple(column.translation.rule_ids) if column.translation else (),
        refusal_reason=refusal_reason,
    )


def _referenced_fields(
    model: CanonicalModel, from_table: str, expression: str
) -> tuple[FieldSchema, ...]:
    """The schema of the fields this expression names. Its own table first.

    The same scoping rule the converter uses (`P3.2`): two tables can both hold
    something called `Quantity`, and sending the wrong one's schema would have
    the model translate against a column the expression does not mean.
    """
    local: dict[str, tuple[str, str]] = {}
    everywhere: dict[str, tuple[str, str]] = {}
    for table, column in _columns(model):
        datatype = (
            column.datatype.value
            if hasattr(column.datatype, "value")
            else str(column.datatype)
        )
        for alias in {column.name.lower(), (column.caption or column.name).lower()}:
            everywhere.setdefault(alias, (table.name, datatype))
            if table.name == from_table:
                local.setdefault(alias, (table.name, datatype))

    seen: dict[str, FieldSchema] = {}
    from t2pbi.core.dax.refs import REF_RE  # noqa: PLC0415 - Tableau engine, optional

    for match in REF_RE.finditer(expression or ""):
        raw = match.group(1)
        found = local.get(raw.lower()) or everywhere.get(raw.lower())
        if found is None:
            continue
        owner, datatype = found
        key = f"{owner}.{raw}"
        seen.setdefault(key, FieldSchema(table=owner, name=raw, datatype=datatype))
    return tuple(seen.values())


def policy_for(model: CanonicalModel, **thresholds: float) -> Policy:
    """What a proposal for this model is allowed to say.

    Flat sets of names, never the model itself, so the AI layer stays unable to
    see a workbook. The function set is the rule pack's - what the converter
    knows to be equivalent - plus the tokens the translator legitimately emits
    on its own.
    """
    from t2pbi.core.dax.functions import (  # noqa: PLC0415 - Tableau engine, optional
        ALLOWED_DAX_FUNCS,
        SUPPORTED_FUNCS,
    )

    references = {
        f"{table.name}[{column.caption or column.name}]"
        for table, column in _columns(model)
    } | {table.name for table, _ in _columns(model)}

    return Policy(
        allowed_references=frozenset(references),
        allowed_functions=frozenset(
            {name.upper() for name in SUPPORTED_FUNCS.values()}
            | {name.upper() for name in ALLOWED_DAX_FUNCS}
        ),
        **thresholds,
    )
