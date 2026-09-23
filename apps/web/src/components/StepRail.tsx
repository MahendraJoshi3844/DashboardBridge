"use client";

import { motion } from "motion/react";
import type { ReactNode } from "react";

import type { MachineState, MachineStateName } from "@/lib/state/machine";

import { CheckIcon, PendingIcon } from "./Icons";

interface Step {
  readonly label: string;
  /** The machine states during which this step is the one being done. */
  readonly during: readonly MachineStateName[];
}

/**
 * Named for what the user does, not for what the engine calls it — and mapped
 * to the states during which they are *doing* it. `SOURCE_SELECTED` is not
 * "choosing a direction": the direction is chosen, and the person is now
 * looking for a workbook. Marking the step by the state you arrived from puts
 * the rail one step behind the heading, which is a small lie about where you
 * are.
 */
const STEPS: readonly Step[] = [
  { label: "Choose direction", during: ["IDLE"] },
  { label: "Open workbook", during: ["SOURCE_SELECTED", "UPLOADING"] },
  { label: "Analyse", during: ["ANALYZING"] },
  { label: "Review what converts", during: ["ANALYSIS_READY"] },
  { label: "Convert", during: ["CONFIGURING", "CONVERTING"] },
  { label: "Results", during: ["CONVERTED"] },
  // Validate sits after Results because that is the order this product does
  // them in, and it is never reached today: validation is Phase 5. A step that
  // stays "not started" is a true statement about where the work stopped —
  // which is more use than removing it and implying there is nothing left.
  { label: "Validate", during: ["VALIDATING", "COMPLETED"] },
];

/**
 * `ERROR` is not a place on this rail. It retains the state it came from, so
 * the rail keeps showing where the user actually is — which is the state they
 * will resume into.
 */
function currentIndex(state: MachineState): number {
  const name = state.name === "ERROR" ? state.origin.name : state.name;
  return STEPS.findIndex((step) => step.during.includes(name));
}

/**
 * "Where am I?" answered without a number that was not measured. Steps behind
 * the current one are done; the current one is marked with a word as well as a
 * mark, so the state survives greyscale, colour-vision deficiency and reduced
 * motion alike.
 */
export function StepRail({
  state,
  children,
}: {
  readonly state: MachineState;
  /** The status line beneath the rail: what is true right now. */
  readonly children?: ReactNode;
}) {
  const index = currentIndex(state);

  return (
    <motion.nav
      aria-label="Migration progress"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ delay: 0.15 }}
    >
      <ol className="flex flex-wrap items-center gap-x-2 gap-y-2">
        {STEPS.map((step, i) => {
          const done = index > i;
          const here = index === i;
          return (
            <li key={step.label} className="flex items-center gap-2">
              <span
                className={[
                  "tag flex items-center gap-1.5 rounded-control border px-2.5 py-1 text-xs",
                  here
                    ? "border-line-strong text-ink"
                    : done
                      ? "border-line text-good"
                      : "border-line text-ink-faint",
                ].join(" ")}
                aria-current={here ? "step" : undefined}
              >
                {done ? (
                  <CheckIcon className="h-3 w-3" />
                ) : (
                  <PendingIcon className="h-3 w-3" />
                )}
                {step.label}
                {here ? <span className="sr-only"> — you are here</span> : null}
                {!done && !here ? (
                  <span className="sr-only"> — not started</span>
                ) : null}
              </span>
              {i < STEPS.length - 1 ? (
                <span className="h-px w-4 bg-line-strong" aria-hidden="true" />
              ) : null}
            </li>
          );
        })}
      </ol>

      {children ? (
        <p
          className="mt-4 text-sm text-ink-muted"
          role="status"
          aria-live="polite"
        >
          {children}
        </p>
      ) : null}
    </motion.nav>
  );
}
