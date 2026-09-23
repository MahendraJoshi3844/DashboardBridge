"use client";

import { motion } from "motion/react";

import type { RunStage } from "@/lib/api/run";
import { formatDuration } from "@/lib/hooks/useElapsed";
import type { Analysis } from "@/types/contracts";

import { CompatibilityPanel } from "./CompatibilityPanel";
import { ComplexityPanel } from "./ComplexityPanel";
import { FlagsPanel } from "./FlagsPanel";
import { ArrowRightIcon, FileIcon } from "./Icons";
import { InventoryGrid } from "./InventoryGrid";
import { StageList } from "./StageList";

/**
 * The metadata dashboard (P1.4 + P2.6): what is in the workbook, how hard it
 * will be, what will happen to it, and what needs a person — all read from a
 * real `Analysis`.
 *
 * Nothing on this screen is computed here. The counts, the score, the formula
 * and the flags are all fields of the contract; this component's whole job is
 * to decide what a person reads first. Deriving a number in a React component
 * would put conversion logic in the UI (AGENTS.md rule 8) and would produce a
 * figure the report could not reproduce.
 *
 * The timeline of the run stays on the page, collapsed. A conversion may finish
 * in under a second, and 03-ux-spec.md asks for the recorded event timeline to
 * be replayable rather than for the run to be slowed down so it can be watched.
 */
export function MetadataDashboard({
  analysis,
  filename,
  stages,
  totalElapsedMs,
  onConvert,
}: {
  readonly analysis: Analysis;
  readonly filename: string;
  readonly stages: readonly RunStage[];
  readonly totalElapsedMs: number | null;
  /** Opens the AI decision (§24). The conversion itself starts from there. */
  readonly onConvert: () => void;
}) {
  const inventory = analysis.inventory;
  const complexity = analysis.complexity;
  const compatibility = analysis.compatibility;
  const flags = analysis.flags ?? [];

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.26, ease: [0.22, 0.61, 0.36, 1] }}
      className="space-y-10"
    >
      <header>
        <p className="eyebrow">Analysis complete</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
          What is in this workbook
        </h1>
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
          <span className="flex items-center gap-2 text-sm text-ink-muted">
            <FileIcon className="h-4 w-4 shrink-0 text-source" />
            <span className="data break-all">{filename}</span>
          </span>
          {totalElapsedMs === null ? null : (
            <span className="numeral text-xs text-ink-faint">
              read in {formatDuration(totalElapsedMs)}
            </span>
          )}
          <span className="data break-all text-xs text-ink-faint">
            <span className="sr-only">Analysis id </span>
            {analysis.analysis_id}
          </span>
        </div>
      </header>

      {inventory === undefined ? (
        <Missing what="an inventory" />
      ) : (
        <InventoryGrid inventory={inventory} />
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        {complexity === null || complexity === undefined ? (
          <Missing what="a complexity score" />
        ) : (
          <ComplexityPanel complexity={complexity} />
        )}

        {compatibility === undefined ? (
          <Missing what="a compatibility breakdown" />
        ) : (
          <CompatibilityPanel compatibility={compatibility} />
        )}
      </div>

      <FlagsPanel flags={flags} />

      <section aria-labelledby="timeline-heading" className="panel p-5 sm:p-6">
        <h2 id="timeline-heading" className="eyebrow">
          How this was produced
        </h2>
        <p className="mt-2 max-w-prose text-sm leading-relaxed text-ink-muted">
          Every step below is a request that returned, timed across the request.
          None of it was estimated, and the run was not slowed down so it could
          be watched.
        </p>
        <div className="mt-4">
          <StageList stages={stages} label="Run timeline" />
        </div>
      </section>

      <section aria-labelledby="next-heading" className="panel p-5 sm:p-6">
        <h2 id="next-heading" className="eyebrow">
          What next
        </h2>
        <p className="mt-2 max-w-prose text-sm leading-relaxed text-ink-muted">
          Everything above is measured and final: re-running the same workbook
          produces the same numbers. Converting writes a Power BI project from
          it. You will be asked how it should be done before anything is
          produced, and nothing here is changed by it.
        </p>
        <div className="mt-5">
          <button type="button" className="btn" onClick={onConvert}>
            Convert this workbook
            <ArrowRightIcon className="h-4 w-4" />
          </button>
        </div>
      </section>
    </motion.div>
  );
}

/**
 * A field the contract allows to be absent. Saying so is not a failure state —
 * it is the difference between "the service did not send this" and a zero we
 * invented to fill the space.
 */
function Missing({ what }: { readonly what: string }) {
  return (
    <section className="panel p-5 text-sm leading-relaxed text-ink-muted sm:p-6">
      The service did not return {what} for this analysis, so there is nothing to
      show here. Nothing has been guessed in its place.
    </section>
  );
}
