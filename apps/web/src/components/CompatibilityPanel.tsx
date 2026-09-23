"use client";

import { motion, useReducedMotion } from "motion/react";

import type { Compatibility, ConversionStatus } from "@/types/contracts";

import { AnimatedNumber } from "./AnimatedNumber";
import { AlertIcon, BlockedIcon, CheckIcon, HandIcon, SparkIcon } from "./Icons";

/**
 * What will become of each object, on the status axis of ADR-004.
 *
 * The verdict leads, with its denominator: *"132 of 143 objects converted · 8
 * need review · 3 unsupported"* (03-ux-spec.md, Results). There is no bare
 * percentage anywhere in this component, because a percentage without its
 * denominator is the number people quote and cannot defend.
 *
 * Held items are named as held, never as failed: they are the product working,
 * not failing.
 */
type StatusKey = Exclude<keyof Compatibility, "total">;

interface StatusSpec {
  readonly key: StatusKey;
  readonly status: ConversionStatus;
  readonly label: string;
  readonly meaning: string;
  readonly ink: string;
  readonly fill: string;
  readonly Icon: typeof CheckIcon;
}

const STATUSES: readonly StatusSpec[] = [
  {
    key: "converted",
    status: "converted",
    label: "Converted",
    meaning: "Crossed by a deterministic rule, with the rule recorded.",
    ink: "text-good",
    fill: "bg-good",
    Icon: CheckIcon,
  },
  {
    key: "partial",
    status: "partial",
    label: "Partly converted",
    meaning: "Crossed, but something about it did not survive intact.",
    ink: "text-warning",
    fill: "bg-warning",
    Icon: AlertIcon,
  },
  {
    key: "ai_required",
    status: "ai_required",
    label: "Held for you",
    meaning:
      "No deterministic equivalent. A model can draft it for your review, or you can write it.",
    ink: "text-held",
    fill: "bg-held",
    Icon: SparkIcon,
  },
  {
    key: "unsupported",
    status: "unsupported",
    label: "Not supported",
    meaning: "Power BI has no equivalent. Rebuilding it is a design decision.",
    ink: "text-serious",
    fill: "bg-serious",
    Icon: BlockedIcon,
  },
  {
    key: "failed",
    status: "failed",
    label: "Failed",
    meaning: "The engine could not process it. This is ours to fix, not yours.",
    ink: "text-critical",
    fill: "bg-critical",
    Icon: HandIcon,
  },
];

function countOf(compatibility: Compatibility, key: StatusKey): number {
  return compatibility[key] ?? 0;
}

export function CompatibilityPanel({
  compatibility,
}: {
  readonly compatibility: Compatibility;
}) {
  const reduced = useReducedMotion();
  const total = compatibility.total ?? 0;
  const converted = countOf(compatibility, "converted");
  const held =
    countOf(compatibility, "partial") + countOf(compatibility, "ai_required");
  const unsupported =
    countOf(compatibility, "unsupported") + countOf(compatibility, "failed");

  return (
    <section aria-labelledby="compatibility-heading" className="panel p-5 sm:p-6">
      <h2 id="compatibility-heading" className="eyebrow">
        Expected outcome — before anything is converted
      </h2>

      {/* Lead with the verdict and its denominator. */}
      <p className="mt-3 text-lg leading-relaxed text-ink sm:text-xl">
        <span className="numeral font-semibold">
          <AnimatedNumber value={converted} />
        </span>{" "}
        of <span className="numeral font-semibold">{total.toLocaleString()}</span>{" "}
        objects are expected to convert
        {held > 0 ? (
          <>
            {" · "}
            <span className="numeral font-semibold text-held">
              {held.toLocaleString()}
            </span>{" "}
            need you
          </>
        ) : null}
        {unsupported > 0 ? (
          <>
            {" · "}
            <span className="numeral font-semibold text-serious">
              {unsupported.toLocaleString()}
            </span>{" "}
            will not cross
          </>
        ) : null}
      </p>

      <p className="mt-2 max-w-prose text-sm leading-relaxed text-ink-muted">
        Counted from the flags the parse raised, not from a conversion — nothing
        has been converted yet. The parts sum to the whole so you can check the
        arithmetic.
      </p>

      {total > 0 ? (
        <div
          className="mt-5 flex h-3 w-full overflow-hidden rounded-control border border-line bg-raised"
          role="img"
          aria-label={STATUSES.map(
            (spec) =>
              `${countOf(compatibility, spec.key)} ${spec.label.toLowerCase()}`,
          ).join(", ")}
        >
          {STATUSES.map((spec) => {
            const count = countOf(compatibility, spec.key);
            if (count === 0) return null;
            const width = `${(count / total) * 100}%`;
            return reduced ? (
              <div key={spec.key} className={spec.fill} style={{ width }} />
            ) : (
              <motion.div
                key={spec.key}
                className={spec.fill}
                initial={{ width: 0 }}
                animate={{ width }}
                transition={{ duration: 0.8, ease: [0.22, 0.61, 0.36, 1] }}
              />
            );
          })}
        </div>
      ) : null}

      <dl className="mt-5 grid gap-x-6 gap-y-3 sm:grid-cols-2">
        {STATUSES.map((spec) => {
          const count = countOf(compatibility, spec.key);
          return (
            <div key={spec.key} className="flex items-start gap-2.5">
              {/* Status is never colour alone: icon, word and number together. */}
              <spec.Icon className={`mt-0.5 h-4 w-4 shrink-0 ${spec.ink}`} />
              <div className="min-w-0 flex-1">
                <dt className="flex items-baseline justify-between gap-3">
                  <span className={`text-sm font-medium ${spec.ink}`}>
                    {spec.label}
                  </span>
                  <span className="numeral text-sm text-ink">
                    {count.toLocaleString()}
                  </span>
                </dt>
                <dd className="mt-0.5 text-xs leading-relaxed text-ink-faint">
                  {spec.meaning}
                </dd>
              </div>
            </div>
          );
        })}
      </dl>
    </section>
  );
}
