/**
 * The comparison explorer's data: source expression beside target expression,
 * one row per object, built from the contract and nothing else.
 *
 * 08-validation-engine.md, "Comparison explorer":
 *
 * > Unconverted items show the refusal reason in the same layout, because what
 * > did not convert is as much a result as what did.
 *
 * So an unconverted item is not filtered out and not moved to a second list. It
 * is the same row shape with `target: null` and a `refusal` — which is why the
 * type below has one row for both cases rather than a converted row and a
 * failure row.
 *
 * ## Where each half comes from
 *
 * * **Source** — `CanonicalModel.datasources[].tables[].columns[].expression`.
 *   `Column.id` is the deterministic name path `"<table>.<name>"`, which is
 *   also what a `ConversionFlag`'s `ref` and `item` carry, so the two join on a
 *   stable key rather than on a display string.
 * * **Target** — `Column.translation`, when the model carries one.
 * * **Refusal** — the conversion's flags, matched to the column by that key.
 *
 * ## Which model, and why it matters
 *
 * Two `CanonicalModel`s reach this screen and only one can answer the question.
 * `Analysis.model` is read before translation, so its `translation` is null in
 * every row by construction; `Conversion.model` is the same model after the
 * pipeline ran and is the one carrying DAX. `comparisonSource` below makes that
 * choice explicit, because comparing the wrong one does not merely empty the
 * right-hand column — it reports "converted, cannot show you" for objects that
 * converted cleanly.
 *
 * Where a target is genuinely absent, `targetAbsence` says *why* — refused, or
 * never returned. Those two are different facts and the screen must not blur
 * them into one, because "we refused this" and "we did this and cannot show
 * you" are opposite claims.
 *
 * Pure: no React, no fetch.
 */

import { actionabilityRank } from "@/lib/flags/ordering";
import type {
  Analysis,
  CanonicalModel,
  Column,
  Conversion,
  ConversionFlag,
  ConversionStatus,
  Translation,
  Validation,
} from "@/types/contracts";

/** Which model the explorer is comparing, and therefore what it may claim. */
export type ComparisonSourceKind =
  /** The model the conversion produced. Targets are present where they exist. */
  | "converted"
  /** The pre-conversion inventory: no target can be present, in any row. */
  | "analysed"
  /** Neither model crossed the API. */
  | "absent";

export interface ComparisonSource {
  readonly kind: ComparisonSourceKind;
  readonly model: CanonicalModel | null;
}

/**
 * Choose between the two models on the results screen.
 *
 * `Analysis.model` is read off the workbook *before* translation, so every
 * `Column.translation` in it is null by construction. `Conversion.model` is the
 * same model after the pipeline ran and is the only one that carries DAX.
 *
 * Comparing the analysed model does not merely leave the right-hand column
 * empty: every row reports `not_returned` — "we converted this and cannot show
 * you" — for objects that converted cleanly. That is the service accusing
 * itself of a defect it does not have, which is exactly the kind of false claim
 * this screen exists to prevent, so the choice is made here and tested rather
 * than settled by whichever prop a component is handed.
 *
 * The fallback is named rather than silent: a caller has to be able to say that
 * no target *could* be present, instead of implying the conversion produced
 * none.
 */
export function comparisonSource(
  conversion: Pick<Conversion, "model"> | null | undefined,
  analysis: Pick<Analysis, "model"> | null | undefined,
): ComparisonSource {
  const converted = conversion?.model ?? null;
  if (converted !== null) return { kind: "converted", model: converted };

  const analysed = analysis?.model ?? null;
  if (analysed !== null) return { kind: "analysed", model: analysed };

  return { kind: "absent", model: null };
}

/** Why the target half of a row is empty. Never merged into one message. */
export type TargetAbsence =
  /** A flag explains the refusal; `refusal` carries it. */
  | "refused"
  /** No refusal, and no translation either: the API returned neither. */
  | "not_returned";

/** What a row may honestly say where a per-pair check result would go. */
export type PairCheck =
  /** Validation has not run. Nothing has been checked, at any grain. */
  | "not_run"
  /** Validation ran; it scores the project by category and never names a pair. */
  | "not_per_pair";

/**
 * The line each row carries in place of a check result.
 *
 * It exists because a blank space where a PASS belongs reads as a PASS. It has
 * two shapes because there are two different truths: nothing has been checked,
 * or things were checked and none of them was about this expression. Saying the
 * first while the validation panel is on screen contradicts it.
 *
 * Neither wording implies a pass, which is what the tests hold it to.
 */
export const PAIR_CHECK_COPY: Record<PairCheck, string> = {
  not_run:
    "No check has been run against this pair. Structural, semantic and " +
    "visual validation are a separate step and have not happened.",
  not_per_pair:
    "The checks scored this conversion by category, not expression by " +
    "expression, so nothing above was verified about this pair in particular.",
};

/** Which of the two is true, from whether the checks have returned. */
export function pairCheck(validation: Validation | null | undefined): PairCheck {
  return validation === null || validation === undefined
    ? "not_run"
    : "not_per_pair";
}

export interface ComparisonRow {
  /** `"<table>.<name>"` — deterministic, stable across runs. */
  readonly id: string;
  readonly table: string;
  /** What the user calls it: the caption when there is one. */
  readonly label: string;
  readonly sourceLanguage: string;
  readonly sourceText: string;
  /** Present only when the model actually carried a translation. */
  readonly target: Translation | null;
  /** Present only when a flag actually explained this object. */
  readonly refusal: ConversionFlag | null;
  readonly targetAbsence: TargetAbsence | null;
  /** From the flag when there is one; `converted` when there is not. */
  readonly status: ConversionStatus;
}

/** Rows, plus the counts a heading needs so it can state a denominator. */
export interface Comparison {
  readonly rows: readonly ComparisonRow[];
  /** Rows whose target expression is actually present. */
  readonly crossed: number;
  /** Rows with a recorded refusal. */
  readonly refused: number;
  /** Rows with neither — the API returned no target and no reason. */
  readonly unaccounted: number;
}

function tableOf(id: string, fallback: string): string {
  const cut = id.lastIndexOf(".");
  return cut > 0 ? id.slice(0, cut) : fallback;
}

/**
 * Index the flags by the key they name.
 *
 * `ref` and `item` are both checked because the engine sets them to the same
 * value for column-level flags and to *different* values for sheet-level ones
 * (`item` is the shelf reference, `ref` the sheet). Matching on either is what
 * keeps a refusal attached to the object it refused.
 */
function indexFlags(
  flags: readonly ConversionFlag[],
): Map<string, ConversionFlag> {
  const byKey = new Map<string, ConversionFlag>();
  for (const flag of flags) {
    for (const key of [flag.ref, flag.item]) {
      if (key === undefined || key === "") continue;
      // First flag wins: two flags naming one object is a report about the
      // engine, and the flags panel shows both. Here, one row means one object.
      if (!byKey.has(key)) byKey.set(key, flag);
    }
  }
  return byKey;
}

function rowFor(
  column: Column,
  fallbackTable: string,
  flags: Map<string, ConversionFlag>,
): ComparisonRow | null {
  const expression = column.expression;
  // Only expression-bearing objects belong in an expression-by-expression
  // comparison. A plain column has no source text to put beside anything, and
  // padding the list with them would bury the calculations that need reading.
  if (expression === null || expression === undefined) return null;

  const translation = column.translation ?? null;
  const refusal = flags.get(column.id) ?? null;

  return {
    id: column.id,
    table: tableOf(column.id, fallbackTable),
    label: column.caption ?? column.name,
    sourceLanguage: expression.source_language,
    sourceText: expression.source_text,
    target: translation,
    refusal,
    targetAbsence:
      translation !== null ? null : refusal !== null ? "refused" : "not_returned",
    status: refusal?.status ?? "converted",
  };
}

/**
 * How a row is ordered: the same actionability rule the flags panel uses, so
 * one question has one answer on both halves of the screen
 * (03-ux-spec.md, "Ordering by actionability").
 *
 * Rows with no flag rank after every flagged row — there is nothing to do about
 * them — and ties break on the id, which makes the order deterministic.
 */
function rank(row: ComparisonRow): number {
  return row.refusal === null
    ? Number.MAX_SAFE_INTEGER
    : actionabilityRank(row.refusal);
}

/**
 * Build the comparison from the analysed model and the conversion's flags.
 *
 * `model` may be null: `Analysis.model` is optional in the contract, and a
 * screen must be able to say "the service did not return a model" rather than
 * render an empty explorer that looks like "there was nothing to compare".
 */
export function compare(
  model: CanonicalModel | null | undefined,
  flags: readonly ConversionFlag[],
): Comparison {
  const rows: ComparisonRow[] = [];
  if (model !== null && model !== undefined) {
    const byKey = indexFlags(flags);
    for (const datasource of model.datasources ?? []) {
      for (const table of datasource.tables ?? []) {
        for (const column of table.columns ?? []) {
          const row = rowFor(column, table.name, byKey);
          if (row !== null) rows.push(row);
        }
      }
    }
  }

  rows.sort((a, b) => {
    const byRank = rank(a) - rank(b);
    return byRank !== 0 ? byRank : a.id.localeCompare(b.id);
  });

  return {
    rows,
    crossed: rows.filter((row) => row.target !== null).length,
    refused: rows.filter((row) => row.targetAbsence === "refused").length,
    unaccounted: rows.filter((row) => row.targetAbsence === "not_returned")
      .length,
  };
}
