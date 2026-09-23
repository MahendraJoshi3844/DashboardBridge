/**
 * What the product is allowed to claim about a conversion, and the numbers it
 * is allowed to claim it with.
 *
 * This module exists because the results screen is the one place where an
 * interface is most tempted to lie, and the rule it would break is the rule the
 * validation engine exists to protect (08-validation-engine.md):
 *
 * > The system never reports success it did not verify.
 *
 * Two consequences are encoded here rather than left to a component:
 *
 * 1. **Every count travels with its denominator.** `summarise()` returns the
 *    parts *and* the total *and* whether they sum, so a screen can print
 *    "132 of 143 objects converted · 8 need review · 3 unsupported" and never
 *    a bare percentage. A percentage is the number people quote and cannot
 *    defend.
 *
 * 2. **Conversion alone never produces a verdict above `unverified`.** A file
 *    being produced is not evidence that it is correct. `verdictOf()` will only
 *    return `verified` / `partially_verified` when a `Validation` is passed in
 *    and says so. The verdict is read off that report and never recomputed
 *    here: a second opinion assembled in the browser is one the engine
 *    never gave.
 *
 * Pure: no React, no fetch, no clock.
 */

import type {
  Compatibility,
  Conversion,
  Validation,
  Verdict,
} from "@/types/contracts";

/**
 * The counts a results screen may print, each one a field of the contract or a
 * sum of fields of the contract.
 */
export interface ResultSummary {
  /** Objects the engine considered. The denominator, always shown with it. */
  readonly total: number;
  readonly converted: number;
  /** Crossed but imperfect, plus held for a person. Work, not failure. */
  readonly needReview: number;
  /** No Power BI equivalent. A design decision, not a defect. */
  readonly unsupported: number;
  /** The engine could not process it. Ours to fix, not the user's. */
  readonly failed: number;
  /** converted + needReview + unsupported + failed. */
  readonly accountedFor: number;
  /**
   * Whether the parts sum to the whole.
   *
   * False means the gateway sent counts that do not reconcile, and a screen
   * must say so rather than print a total the parts contradict. Quietly
   * rendering it anyway is how a number nobody can defend reaches a
   * stakeholder.
   */
  readonly balances: boolean;
}

function countOf(compatibility: Compatibility, key: keyof Compatibility): number {
  const value = compatibility[key];
  return typeof value === "number" ? value : 0;
}

/** Reduce a `Compatibility` to what may be printed, with its denominator. */
export function summarise(
  compatibility: Compatibility | undefined,
): ResultSummary {
  const source: Compatibility = compatibility ?? {};
  const converted = countOf(source, "converted");
  const needReview =
    countOf(source, "partial") + countOf(source, "ai_required");
  const unsupported = countOf(source, "unsupported");
  const failed = countOf(source, "failed");
  const total = countOf(source, "total");
  const accountedFor = converted + needReview + unsupported + failed;

  return {
    total,
    converted,
    needReview,
    unsupported,
    failed,
    accountedFor,
    balances: accountedFor === total,
  };
}

/**
 * The four words, and nothing outside them (§63).
 *
 * `validation` is `null` whenever validation has not run, or has not
 * returned yet. A completed conversion with no validation is `unverified`:
 * files exist, nothing has been checked. A conversion that did not complete
 * is `failed`, because there is no output to be unverified about.
 */
export function verdictOf(
  conversion: Conversion,
  validation: Validation | null,
): Verdict {
  if (validation !== null && validation.verdict !== undefined) {
    return validation.verdict;
  }
  if (conversion.status === "failed" || conversion.status === "cancelled") {
    return "failed";
  }
  return "unverified";
}

export interface VerdictCopy {
  /** The word itself. It is one of exactly four. */
  readonly label: string;
  /** What the word means, in the user's terms. */
  readonly meaning: string;
}

/**
 * The vocabulary, written out. Kept beside `verdictOf` so the word and its
 * meaning cannot drift apart in two different components.
 */
export const VERDICT_COPY: Record<Verdict, VerdictCopy> = {
  verified: {
    label: "Verified",
    meaning:
      "Every applicable check ran against the produced project and passed.",
  },
  partially_verified: {
    label: "Partially verified",
    meaning:
      "The checks ran and some did not pass. The report names which, and why.",
  },
  unverified: {
    label: "Unverified",
    meaning:
      "Files were produced and nothing has been checked against the workbook they came from.",
  },
  failed: {
    label: "Failed",
    meaning: "The conversion did not finish, so there is no output to judge.",
  },
};

/**
 * Why this conversion is unverified, in one sentence a person can act on.
 *
 * Returns null for a verdict that came from a real validation — at that point
 * the reason is the validation's own report, not a sentence written here.
 */
export function unverifiedBecause(verdict: Verdict): string | null {
  if (verdict !== "unverified") return null;
  return (
    "The structural, semantic and visual checks have not returned, so " +
    "nothing on this page has yet been checked against the workbook it " +
    "came from. The produced project is unaffected either way: it is the " +
    "claim about it that is missing, not the file."
  );
}
