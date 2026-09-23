/**
 * Order flags by what a person must do about them.
 *
 * 03-ux-spec.md, "Ordering by actionability": *"A calculation needing
 * hand-written DAX outranks a field-well needing a click. Timeline order once
 * buried all six actionable calculations beneath forty field-well notices,
 * where nobody would ever see them."*
 *
 * So the engine's discovery order is deliberately discarded here. The sort is
 * total and deterministic — the last key is the item name — because two runs of
 * the same workbook must produce the same list in the same order (§78,
 * determinism).
 *
 * ## Why the stage, and not just the status
 *
 * The first version of this file ranked on the three ADR-004 axes alone:
 * severity, then status, then method. Run against the real Superstore
 * workbook it put eleven `unsupported` field wells *above* five `ai_required`
 * calculations — precisely the inversion the spec names, arrived at from the
 * other direction. The status axis answers *what became of it*, which is not
 * the same question as *how much work is it, and of what kind*.
 *
 * The **stage** is what distinguishes the kinds of work, so it ranks above the
 * status:
 *
 * | Stage | The work it implies |
 * |---|---|
 * | `translate` | Write an expression by hand and convince yourself it is right |
 * | `extract` / `parse` | The source could not be read; something is missing |
 * | `map` | Re-bind a field — a decision, then a click |
 * | `generate` | Layout and formatting |
 * | `validate` / `report` | Reading, not doing |
 *
 * A `failed` item jumps all of it. That is the engine failing rather than the
 * user's workbook being hard, and it is the one row a person should see first.
 */

import type {
  ConversionFlag,
  ConversionMethod1 as ConversionMethod,
  ConversionStatus,
  Severity,
  Stage,
} from "@/types/contracts";

/** Lower sorts first. Does this need a person at all? */
const SEVERITY_RANK: Record<Severity, number> = {
  manual: 0,
  warning: 1,
  info: 2,
};

/** What kind of work, and how much of it. */
const STAGE_RANK: Record<Stage, number> = {
  translate: 0,
  extract: 1,
  parse: 1,
  map: 2,
  generate: 3,
  validate: 4,
  report: 5,
};

/** What became of it, within one kind of work. */
const STATUS_RANK: Record<ConversionStatus, number> = {
  failed: 0,
  unsupported: 1,
  ai_required: 2,
  partial: 3,
  converted: 4,
};

const METHOD_RANK: Record<ConversionMethod, number> = {
  manual: 0,
  ai_assisted: 1,
  rule: 2,
  deterministic: 3,
};

/** Contract fields are optional; a missing axis is treated as its mildest value. */
function severityOf(flag: ConversionFlag): Severity {
  return flag.severity ?? "info";
}

function statusOf(flag: ConversionFlag): ConversionStatus {
  return flag.status ?? "converted";
}

function methodOf(flag: ConversionFlag): ConversionMethod {
  return flag.method ?? "deterministic";
}

/**
 * How much of a person's attention this item needs; lower is more.
 *
 * Exported so a caller can group or filter on the same number the sort used —
 * two orderings of the same list would be two answers to one question.
 */
export function actionabilityRank(flag: ConversionFlag): number {
  const failedFirst = statusOf(flag) === "failed" ? 0 : 1;
  return (
    SEVERITY_RANK[severityOf(flag)] * 10_000 +
    failedFirst * 1_000 +
    STAGE_RANK[flag.stage] * 100 +
    STATUS_RANK[statusOf(flag)] * 10 +
    METHOD_RANK[methodOf(flag)]
  );
}

/** True when the flag is something a person has to pick up. */
export function needsAPerson(flag: ConversionFlag): boolean {
  const status = statusOf(flag);
  return (
    severityOf(flag) === "manual" ||
    status === "failed" ||
    status === "unsupported" ||
    status === "ai_required"
  );
}

/** A new array, ordered by actionability. The input is never mutated. */
export function byActionability(
  flags: readonly ConversionFlag[],
): ConversionFlag[] {
  return [...flags].sort((a, b) => {
    const rank = actionabilityRank(a) - actionabilityRank(b);
    if (rank !== 0) return rank;
    return a.item.localeCompare(b.item);
  });
}
