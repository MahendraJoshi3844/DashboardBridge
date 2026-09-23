# Module Specs

Each pipeline module has a focused mini-spec here (Purpose / Inputs / Outputs /
Behaviour / Edge cases / Acceptance). They refine the top-level
[`SPEC-tableau-to-powerbi-migration.md`](../SPEC-tableau-to-powerbi-migration.md)
and follow the [`TECHNICAL-DESIGN.md`](../../design/TECHNICAL-DESIGN.md) pipeline.

| Module | Spec | Code |
|---|---|---|
| IR model | [ir.md](ir.md) | `engines/t2pbi/ir/model.py` |
| Extract | [extract.md](extract.md) | `engines/t2pbi/core/extract.py` |
| Parse | [parse.md](parse.md) | `engines/t2pbi/core/parse/` |
| DAX translator | [dax.md](dax.md) | `engines/t2pbi/core/dax/` |
| Emit (TMDL/PBIP) | [emit.md](emit.md) | `engines/t2pbi/core/emit/` |
| Report + Pipeline + CLI | [pipeline.md](pipeline.md) | `engines/t2pbi/{report.py,pipeline.py,cli.py}` |
| Visual mapping + PBIR | [visual.md](visual.md) | `engines/t2pbi/core/mapping/`, `engines/t2pbi/core/emit/pbir.py` |
| Desktop app | [desktop.md](desktop.md) | `engines/t2pbi/desktop/` |
| Packaging (.exe) | [packaging.md](packaging.md) | `packaging/` |
