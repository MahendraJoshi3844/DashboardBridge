"use client";

import { motion, useReducedMotion } from "motion/react";

import type { Complexity } from "@/types/contracts";

import { InfoIcon } from "./Icons";

/**
 * The complexity score, and the arithmetic that produced it.
 *
 * `formula` is rendered, not hidden behind a tooltip and not summarised. The
 * API returns it *precisely so the derivation is visible* (05-api-spec.md:
 * "A score without it is decoration"), and 01-product-spec.md repeats the
 * point: the formula is published next to the number.
 *
 * The meter animates to the measured score and never past it (03-ux-spec.md,
 * Motion). Its width is `score`, full stop — there is no easing overshoot,
 * because an overshoot would draw, however briefly, a number that was not
 * measured.
 */
const BAND_COPY: Record<string, { readonly tone: string; readonly meaning: string }> = {
  low: {
    tone: "text-good",
    meaning:
      "Mostly plain columns and straightforward visuals. The mechanical work dominates.",
  },
  moderate: {
    tone: "text-warning",
    meaning:
      "Enough calculated logic that some of it will need reading by a person before it is trusted.",
  },
  high: {
    tone: "text-serious",
    meaning:
      "The workbook is mostly expressions and custom visuals. Expect hand work, and scope for it.",
  },
};

export function ComplexityPanel({
  complexity,
}: {
  readonly complexity: Complexity;
}) {
  const reduced = useReducedMotion();
  const band = BAND_COPY[complexity.band] ?? {
    tone: "text-ink-muted",
    meaning: "",
  };
  const percent = Math.max(0, Math.min(1, complexity.score)) * 100;

  return (
    <section aria-labelledby="complexity-heading" className="panel p-5 sm:p-6">
      <h2 id="complexity-heading" className="eyebrow">
        Complexity
      </h2>

      <div className="mt-3 flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <p className="numeral text-4xl font-semibold tracking-tight text-ink">
          {complexity.score.toFixed(2)}
        </p>
        <p
          className={`tag text-sm ${band.tone}`}
          // The band is a word, so the score is not carried by colour alone.
        >
          {complexity.band}
        </p>
        <p className="data text-xs text-ink-faint">of a possible 1.00</p>
      </div>

      <div
        role="meter"
        aria-valuenow={complexity.score}
        aria-valuemin={0}
        aria-valuemax={1}
        aria-label="Complexity score"
        className="mt-4 h-2 w-full overflow-hidden rounded-control border border-line bg-raised"
      >
        {reduced ? (
          <div
            className="h-full rounded-control bg-source"
            style={{ width: `${percent}%` }}
          />
        ) : (
          <motion.div
            className="h-full rounded-control bg-source"
            initial={{ width: 0 }}
            animate={{ width: `${percent}%` }}
            transition={{ duration: 0.9, ease: [0.22, 0.61, 0.36, 1] }}
          />
        )}
      </div>

      {band.meaning ? (
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-muted">
          {band.meaning}
        </p>
      ) : null}

      <details className="mt-4" open>
        <summary className="flex cursor-pointer items-center gap-2 text-xs text-ink-faint underline-offset-4 hover:underline">
          <InfoIcon className="h-3.5 w-3.5" />
          How this score is derived
        </summary>
        <p className="data mt-2 break-words rounded-control border border-line bg-raised px-3 py-2.5 text-xs leading-relaxed text-ink-muted">
          {complexity.formula}
        </p>
        <p className="mt-2 max-w-prose text-xs leading-relaxed text-ink-faint">
          The weights are stated judgement, published with every score so you can
          disagree with them specifically rather than distrust the number.
        </p>
      </details>
    </section>
  );
}
