"use client";

import { motion } from "motion/react";

import type { RunStage } from "@/lib/api/run";
import { formatDuration, useElapsed } from "@/lib/hooks/useElapsed";
import type { ProgressEvent as JobProgressEvent } from "@/types/contracts";

import { FileIcon } from "./Icons";
import { StageList } from "./StageList";

/**
 * Conversion — "Show progress" (01-product-spec.md, Screens).
 *
 * There is no progress bar here unless the job reports one, and today it does
 * not. 03-ux-spec.md is unambiguous: *"A percentage is `completed / total` of
 * real items or it is not shown."* The gateway relays no per-item counters —
 * `GET /projects/{id}/events` (P3.4) does not exist and `Conversion` carries no
 * stage counts — so what is shown instead is the indeterminate indicator, the
 * stage that is actually running, and the real elapsed time.
 *
 * `progress` is wired through anyway, because the state machine already carries
 * a real `ProgressEvent` and the moment the stream exists this screen renders
 * `completed / total` from it without a line of it being invented. Until then
 * the prop is null and the ratio is simply absent.
 */
export function ConversionScreen({
  filename,
  stages,
  startedAt,
  progress,
}: {
  readonly filename: string;
  readonly stages: readonly RunStage[];
  /** `performance.now()` when the conversion was asked for. */
  readonly startedAt: number | null;
  /** The last real progress event, or null when none has been reported. */
  readonly progress: JobProgressEvent | null;
}) {
  const elapsed = useElapsed(startedAt, true);
  const done = stages.filter((stage) => stage.phase === "done").length;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.24, ease: [0.22, 0.61, 0.36, 1] }}
    >
      <p className="eyebrow">Step 6 — converting</p>
      <h1 className="mt-3 text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
        Converting your workbook
      </h1>

      <p className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="flex items-center gap-2 text-sm text-ink-muted">
          <FileIcon className="h-4 w-4 shrink-0 text-source" />
          <span className="data break-all">{filename}</span>
        </span>
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
        {/* Only ever `completed / total` of real items, never a percentage
            derived from a clock. Absent when the job reports nothing. */}
        {progress === null ? null : (
          <span className="numeral text-xs text-ink">
            {progress.stage}: {progress.completed} of {progress.total}
          </span>
        )}
      </p>

      <section aria-labelledby="converting-heading" className="panel mt-6 p-5 sm:p-6">
        <h2 id="converting-heading" className="eyebrow">
          What is happening
        </h2>
        <div className="mt-4">
          <StageList stages={stages} label="Conversion progress" />
        </div>
      </section>

      <p className="mt-6 max-w-prose text-xs leading-relaxed text-ink-faint">
        Each step flips when a request actually returns. The service does not
        report how many objects are left, so no proportion is shown — a bar
        creeping toward ninety per cent would be an estimate, and this screen
        does not make estimates. Nothing is being validated: that is a separate
        step, and it has not run.
      </p>
    </motion.div>
  );
}
