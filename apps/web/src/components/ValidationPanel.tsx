"use client";

import { motion } from "motion/react";
import { useState } from "react";

import type { Validation, ValidationRuleResult } from "@/types/contracts";

import { AlertIcon, InfoIcon, PendingIcon, ShieldIcon } from "./Icons";

/**
 * What the checks found — the evidence behind the verdict.
 *
 * The panel is arranged so the least flattering things are the hardest to
 * miss. Failures come first, then warnings, then everything that passed
 * collapsed behind a disclosure, because a list that opens on 40 green rows
 * buries the three that matter (03-ux-spec.md, Results).
 *
 * Three rules are structural here rather than left to copy:
 *
 * 1. **The score never appears without its formula.** The formula the engine
 *    published is rendered directly beneath it. A score whose derivation a
 *    reader cannot follow is decoration (08-validation-engine.md).
 *
 * 2. **Every category shows `passed / checks`, not a percentage.** The
 *    percentage is the number that gets quoted in a meeting and cannot be
 *    defended; the fraction carries its own denominator.
 *
 * 3. **`numerical` is stated as unmeasured, with its reason.** Its absence is
 *    the point: comparing results means executing both dashboards against live
 *    data, which we do not do (ADR-003). Leaving the row out entirely would let
 *    a reader assume it had been checked.
 */

const CATEGORY_COPY: Record<string, string> = {
  structural: "Does the produced model hold together, and does every object that did not cross say so?",
  semantic: "Does each translated expression mean what the original meant?",
  visual: "Did each worksheet reach the report as a page, with its fields bound?",
};

/** FAIL first, then WARNING; PASS and NOT_APPLICABLE keep engine order. */
const SEVERITY: Record<string, number> = {
  FAIL: 0,
  WARNING: 1,
  PASS: 2,
  NOT_APPLICABLE: 3,
};

function ordered(rules: readonly ValidationRuleResult[]): ValidationRuleResult[] {
  return [...rules].sort(
    (a, b) => (SEVERITY[a.status] ?? 9) - (SEVERITY[b.status] ?? 9),
  );
}

export function ValidationPanel({
  validation,
  validating,
}: {
  readonly validation: Validation | null;
  /** The checks are running. Distinct from having run and found nothing. */
  readonly validating: boolean;
}) {
  const [showPassed, setShowPassed] = useState(false);

  if (validation === null) {
    return (
      <section aria-labelledby="validation-heading" className="panel p-5 sm:p-6">
        <h2 id="validation-heading" className="eyebrow">
          What the checks found
        </h2>
        <p className="mt-3 flex items-start gap-2 max-w-prose text-sm leading-relaxed text-ink-muted">
          <PendingIcon className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
          <span>
            {validating
              ? "Running the structural, semantic and visual checks against the project that was produced. Nothing above has been verified yet."
              : "The checks have not run, so nothing above has been checked against the workbook it came from."}
          </span>
        </p>
      </section>
    );
  }

  const rules = validation.rules ?? [];
  const notable = ordered(rules).filter(
    (rule) => rule.status === "FAIL" || rule.status === "WARNING",
  );
  const rest = ordered(rules).filter(
    (rule) => rule.status !== "FAIL" && rule.status !== "WARNING",
  );
  const categories = Object.entries(validation.categories ?? {});

  return (
    <motion.section
      aria-labelledby="validation-heading"
      className="panel p-5 sm:p-6"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2 }}
    >
      <h2 id="validation-heading" className="eyebrow">
        What the checks found
      </h2>

      {categories.length === 0 ? (
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-muted">
          No category had a check that applied to this workbook, so there is no
          score. That is the honest answer; a score of 1.0 over nothing would
          not be.
        </p>
      ) : (
        <>
          <dl className="mt-4 grid gap-3 sm:grid-cols-3">
            {categories.map(([name, category]) => (
              <div key={name} className="rounded-control border border-line p-3">
                <dt className="text-xs uppercase tracking-wide text-ink-faint">
                  {name}
                </dt>
                <dd className="numeral mt-1 text-lg font-semibold text-ink">
                  {category.passed} / {category.checks}
                  <span className="ml-1.5 text-xs font-normal text-ink-faint">
                    checks passed
                  </span>
                </dd>
                <dd className="mt-1.5 text-xs leading-relaxed text-ink-muted">
                  {CATEGORY_COPY[name] ?? ""}
                </dd>
              </div>
            ))}
          </dl>

          {/* The score is never shown without the derivation beneath it. */}
          {validation.formula ? (
            <p className="data mt-4 rounded-control bg-surface px-3 py-2 text-xs leading-relaxed text-ink-muted">
              {validation.formula}
            </p>
          ) : null}
        </>
      )}

      {notable.length > 0 ? (
        <ul className="mt-5 space-y-2.5">
          {notable.map((rule) => (
            <Rule key={`${rule.rule_id}-${rule.note}`} rule={rule} />
          ))}
        </ul>
      ) : (
        <p className="mt-5 flex items-start gap-2 text-sm text-ink-muted">
          <ShieldIcon className="mt-0.5 h-4 w-4 shrink-0 text-good" />
          <span>No check failed and none returned a warning.</span>
        </p>
      )}

      {rest.length > 0 ? (
        <div className="mt-4">
          <button
            type="button"
            onClick={() => setShowPassed((open) => !open)}
            className="text-xs text-ink-muted underline underline-offset-4 hover:text-ink"
            aria-expanded={showPassed}
          >
            {showPassed ? "Hide" : "Show"} the {rest.length} checks that passed
            or did not apply
          </button>
          {showPassed ? (
            <ul className="mt-3 space-y-2.5">
              {rest.map((rule) => (
                <Rule key={`${rule.rule_id}-${rule.note}`} rule={rule} />
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {/* ADR-003. Stated, never omitted: an omitted row reads as a passed one. */}
      <p className="mt-5 flex items-start gap-2 border-t border-line pt-4 text-xs leading-relaxed text-ink-faint">
        <InfoIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>
          Numerical equivalence: not measured.{" "}
          {validation.numerical?.reason ?? ""}
        </span>
      </p>
    </motion.section>
  );
}

const STATUS_STYLE: Record<string, { readonly tone: string; readonly label: string }> = {
  FAIL: { tone: "text-critical", label: "Failed" },
  WARNING: { tone: "text-held", label: "Warning" },
  PASS: { tone: "text-good", label: "Passed" },
  NOT_APPLICABLE: { tone: "text-ink-faint", label: "Did not apply" },
};

function Rule({ rule }: { readonly rule: ValidationRuleResult }) {
  const style = STATUS_STYLE[rule.status] ?? {
    tone: "text-ink-muted",
    label: rule.status,
  };
  const Icon = rule.status === "PASS" ? ShieldIcon : AlertIcon;

  return (
    <li className="flex items-start gap-2.5">
      <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${style.tone}`} />
      <div className="min-w-0">
        <p className="text-sm text-ink">
          <span className="data">{rule.rule_id}</span>
          <span className={`ml-2 text-xs ${style.tone}`}>{style.label}</span>
        </p>
        {/* The note carries the denominator and the names. It is the finding. */}
        {rule.note ? (
          <p className="mt-0.5 text-xs leading-relaxed text-ink-muted">
            {rule.note}
          </p>
        ) : null}
      </div>
    </li>
  );
}
