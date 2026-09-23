"use client";

import { motion, useReducedMotion } from "motion/react";

import { formatDuration } from "@/lib/hooks/useElapsed";
import {
  RUN_STAGE_LABELS,
  type RunStage,
} from "@/lib/api/run";

import { CheckIcon, DotIcon, RunningIcon } from "./Icons";

/**
 * The real stages of a real run.
 *
 * Each row flips because a request returned, and each duration was measured
 * across that request. There is no percentage here because the server reports
 * no total to divide by — 03-ux-spec.md: *"When the backend has no measurable
 * total, show an indeterminate indicator and the current stage name — not a bar
 * creeping toward 90%."*
 *
 * The list is a live region, so a screen-reader user hears each stage resolve
 * rather than discovering afterwards that it did.
 */
export function StageList({
  stages,
  label = "Progress",
}: {
  readonly stages: readonly RunStage[];
  readonly label?: string;
}) {
  return (
    <ol
      aria-label={label}
      role="list"
      aria-live="polite"
      className="space-y-2.5"
    >
      {stages.map((stage) => (
        <StageRow key={stage.id} stage={stage} />
      ))}
    </ol>
  );
}

function StageRow({ stage }: { readonly stage: RunStage }) {
  const reduced = useReducedMotion();
  const label = RUN_STAGE_LABELS[stage.id];

  const tone =
    stage.phase === "done"
      ? "text-ink"
      : stage.phase === "active"
        ? "text-ink"
        : "text-ink-faint";

  return (
    <li className="flex items-start gap-3">
      <span className={`mt-px shrink-0 ${markTone(stage.phase)}`}>
        <StageMark phase={stage.phase} reduced={reduced === true} />
      </span>

      <span className="min-w-0 flex-1">
        <span className={`text-sm ${tone}`}>{label}</span>
        {/* The state in words as well as a mark: motion and colour are never
            the only carriers of information. */}
        <span className="sr-only">
          {stage.phase === "done"
            ? " — done"
            : stage.phase === "active"
              ? " — in progress"
              : " — not started"}
        </span>
        {stage.note ? (
          <span className="data ml-2 break-all text-xs text-ink-faint">
            {stage.note}
          </span>
        ) : null}
      </span>

      {stage.elapsedMs === null ? null : (
        <span className="numeral shrink-0 text-xs text-ink-faint">
          {formatDuration(stage.elapsedMs)}
        </span>
      )}
    </li>
  );
}

function markTone(phase: RunStage["phase"]): string {
  if (phase === "done") return "text-good";
  if (phase === "active") return "text-source";
  return "text-ink-faint";
}

/**
 * The indeterminate indicator the spec asks for: it says *something is
 * happening*, and claims nothing about how far along it is.
 */
function StageMark({
  phase,
  reduced,
}: {
  readonly phase: RunStage["phase"];
  readonly reduced: boolean;
}) {
  if (phase === "done") return <CheckIcon className="h-4 w-4" />;
  if (phase === "pending") return <DotIcon className="h-4 w-4" />;
  if (reduced) return <RunningIcon className="h-4 w-4" />;
  return (
    <motion.span
      className="block"
      animate={{ rotate: 360 }}
      transition={{ duration: 1.1, repeat: Infinity, ease: "linear" }}
    >
      <RunningIcon className="h-4 w-4" />
    </motion.span>
  );
}
