"use client";

import { motion } from "motion/react";

import type { RunStage } from "@/lib/api/run";
import { formatDuration, useElapsed } from "@/lib/hooks/useElapsed";

import { FileIcon } from "./Icons";
import { StageList } from "./StageList";

/**
 * Analysis — "Show work happening" (01-product-spec.md, Screens).
 *
 * There is no progress bar on this screen and that is the point. The gateway
 * reports no total to divide by, and 03-ux-spec.md is explicit that a
 * percentage is `completed / total` of real items or it is not shown. What is
 * shown instead is the list of stages resolving and the real elapsed time.
 *
 * Analysis of a 1.1 MB workbook takes about 25 ms, so this screen will often be
 * on-screen for less time than it takes to read. *"A conversion may complete in
 * under a second. That is not a reason to slow it down."* The recorded timeline
 * stays available on the results screen for anyone who wants to see what
 * happened.
 */
export function AnalysisScreen({
  filename,
  stages,
  startedAt,
}: {
  readonly filename: string;
  readonly stages: readonly RunStage[];
  /** `performance.now()` when the run began. Null before it does. */
  readonly startedAt: number | null;
}) {
  const elapsed = useElapsed(startedAt, true);
  const done = stages.filter((stage) => stage.phase === "done").length;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.24, ease: [0.22, 0.61, 0.36, 1] }}
    >
      <p className="eyebrow">Step 3 — reading the workbook</p>
      <h1 className="mt-3 text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
        Working through your workbook
      </h1>

      <p className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="flex items-center gap-2 text-sm text-ink-muted">
          <FileIcon className="h-4 w-4 shrink-0 text-source" />
          <span className="data break-all">{filename}</span>
        </span>
        {/* The real elapsed time, and the real count of steps that have
            actually finished. Neither is an estimate of what is left. */}
        <span
          className="numeral text-xs text-ink-faint"
          role="timer"
          aria-live="off"
        >
          {formatDuration(elapsed)} elapsed
        </span>
        <span className="numeral text-xs text-ink-faint">
          {done} of {stages.length} steps done
        </span>
      </p>

      <section aria-labelledby="stages-heading" className="panel mt-6 p-5 sm:p-6">
        <h2 id="stages-heading" className="eyebrow">
          What is happening
        </h2>
        <div className="mt-4">
          <StageList stages={stages} label="Analysis progress" />
        </div>
      </section>

      <p className="mt-6 max-w-prose text-xs leading-relaxed text-ink-faint">
        Each step above flips when a request actually returns, and each duration
        is measured across that request. Nothing here is a guess at how far along
        the work is, and nothing is slowed down so it can be watched.
      </p>
    </motion.div>
  );
}
