"use client";

import { motion } from "motion/react";
import { useCallback, useState } from "react";
import type { CSSProperties } from "react";

import { downloadArtifact, toApiError } from "@/lib/api/client";
import { comparisonSource } from "@/lib/comparison/pairs";
import type { RunStage } from "@/lib/api/run";
import { producedName, saveBlob } from "@/lib/download";
import { formatDuration } from "@/lib/hooks/useElapsed";
import {
  summarise,
  unverifiedBecause,
  verdictOf,
  VERDICT_COPY,
} from "@/lib/results/verdict";
import type {
  ApiError,
  Analysis,
  Conversion,
  Validation,
} from "@/types/contracts";

import { AnimatedNumber } from "./AnimatedNumber";
import { ComparisonPanel } from "./ComparisonPanel";
import { ProposalsPanel } from "./ProposalsPanel";
import { FlagsPanel } from "./FlagsPanel";
import {
  AlertIcon,
  DownloadIcon,
  FileIcon,
  InfoIcon,
  PendingIcon,
  ShieldIcon,
} from "./Icons";
import { StageList } from "./StageList";
import { ValidationPanel } from "./ValidationPanel";

/**
 * Results — "Deliver the verdict" (01-product-spec.md, Screens).
 *
 * This screen is where the product is most tempted to lie, so three rules are
 * enforced structurally rather than trusted to copy review:
 *
 * 1. **The verdict leads, with its denominator.** *"132 of 143 objects
 *    converted · 8 need review · 3 unsupported"*. There is no bare percentage
 *    anywhere in this file, and the parts are shown summing to the whole so a
 *    reader can check the arithmetic (03-ux-spec.md, Results).
 *
 * 2. **The output is Unverified, and the screen says why.** Conversion produced
 *    files; that is not evidence they are correct. The four words are
 *    `Verified · Partially verified · Unverified · Failed`
 *    (08-validation-engine.md), validation is Phase 5 and has not run, so the
 *    only word available is `Unverified`. The wording is not softened, because
 *    the softening is the failure.
 *
 * 3. **Numerical equivalence is never mentioned as a figure.** It would require
 *    executing both dashboards against live data (ADR-003). Its absence is
 *    stated explicitly, which is the whole reason `numerical.measured` exists
 *    in the contract.
 *
 * The verdict itself is computed in `@/lib/results/verdict`, which is pure and
 * cannot be persuaded by a component to return a better word.
 */
type Download =
  | { readonly phase: "idle" }
  | { readonly phase: "working" }
  | { readonly phase: "failed"; readonly error: ApiError };

export function ResultsScreen({
  conversion,
  analysis,
  filename,
  projectId,
  stages,
  totalElapsedMs,
  validation,
  validating,
  aiAvailable = false,
}: {
  readonly conversion: Conversion;
  readonly analysis: Analysis;
  readonly filename: string;
  readonly projectId: string;
  readonly stages: readonly RunStage[];
  readonly totalElapsedMs: number | null;
  /** The checks, once they have returned. Null before that, never a stand-in. */
  readonly validation: Validation | null;
  readonly validating: boolean;
  /** From `/settings/ai`. False until it says otherwise. */
  readonly aiAvailable?: boolean;
}) {
  const summary = summarise(conversion.compatibility);
  // The verdict is whatever the validation reported, or `unverified` while
  // there is no report. It is never computed from the conversion's own counts:
  // a conversion cannot grade itself.
  const verdict = verdictOf(conversion, validation);
  const flags = conversion.flags ?? [];

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.26, ease: [0.22, 0.61, 0.36, 1] }}
      className="space-y-10"
    >
      <header>
        <p className="eyebrow">{validation === null ? "Conversion complete" : "Conversion complete and checked"}</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
          What came across
        </h1>
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
          <span className="flex items-center gap-2 text-sm text-ink-muted">
            <FileIcon className="h-4 w-4 shrink-0 text-source" />
            <span className="data break-all">{filename}</span>
          </span>
          {totalElapsedMs === null ? null : (
            <span className="numeral text-xs text-ink-faint">
              converted in {formatDuration(totalElapsedMs)}
            </span>
          )}
          <span className="data break-all text-xs text-ink-faint">
            <span className="sr-only">Conversion id </span>
            {conversion.conversion_id}
          </span>
        </div>
      </header>

      <Verdict summary={summary} verdict={verdict} />

      <ValidationPanel validation={validation} validating={validating} />

      <ArtifactSection
        projectId={projectId}
        filename={filename}
        artifactId={conversion.artifact_id ?? null}
      />

      <FlagsPanel flags={flags} />

      {/* After the flags, because a draft is only interesting once you know
          what was held and why. Renders nothing when nothing was held. */}
      <ProposalsPanel
        projectId={projectId}
        held={heldExpressions(conversion)}
        aiAvailable={aiAvailable}
      />

      {/* The converted model, not the analysed one: only the former carries
          the DAX. See `comparisonSource` for why the choice is not a detail. */}
      <ComparisonPanel
        source={comparisonSource(conversion, analysis)}
        flags={flags}
        validation={validation}
      />

      <section aria-labelledby="conversion-timeline" className="panel p-5 sm:p-6">
        <h2 id="conversion-timeline" className="eyebrow">
          How this was produced
        </h2>
        <p className="mt-2 max-w-prose text-sm leading-relaxed text-ink-muted">
          Every step below flips because a request returned, and every duration
          is measured across it. The service relays no per-object progress while
          it converts, so none is shown.
        </p>
        <div className="mt-4">
          <StageList stages={stages} label="Conversion timeline" />
        </div>
      </section>
    </motion.div>
  );
}

/* ---------------------------------------------------------------------- */


/**
 * The light behind the verdict pane, in the verdict's own colour.
 *
 * The screen glows the colour of its own conclusion. It is the one decorative
 * decision on this screen, and it earns its place by being *information*: a
 * consultant who has run this twice knows the answer from across the room
 * before reading a word.
 *
 * Low alpha on purpose. The bloom sits behind the glass and never under the
 * text, so it changes what the pane looks like without changing what any ink
 * is measured against - `npm run check:contrast` composites over the page
 * ground, and a bright field under a paragraph would make that measurement a
 * number nobody sees.
 */
const VERDICT_GLOW: Record<keyof typeof VERDICT_COPY, string> = {
  verified: "rgba(86, 214, 160, 0.20)",
  partially_verified: "rgba(232, 185, 63, 0.18)",
  // Not a failure colour. Unverified means nothing has been checked yet, and
  // the held ink is the one this product already uses for "waiting on a
  // person" rather than "something went wrong".
  unverified: "rgba(195, 177, 255, 0.18)",
  failed: "rgba(255, 143, 140, 0.20)",
};

/** The lead line and the verdict, which are read together or not at all. */
function Verdict({
  summary,
  verdict,
}: {
  readonly summary: ReturnType<typeof summarise>;
  readonly verdict: keyof typeof VERDICT_COPY;
}) {
  const copy = VERDICT_COPY[verdict];
  const because = unverifiedBecause(verdict);

  return (
    <section
      aria-labelledby="verdict-heading"
      className="panel verdict p-6 sm:p-8"
      style={{ "--dbb-verdict-glow": VERDICT_GLOW[verdict] } as CSSProperties}
    >
      <h2 id="verdict-heading" className="eyebrow">
        The verdict, with its denominator
      </h2>

      {/* Never a bare percentage. Never "100% successfully converted". */}
      <p className="verdict__count mt-3 text-2xl leading-[1.25] text-ink sm:text-[2rem]">
        <span className="numeral font-semibold">
          <AnimatedNumber value={summary.converted} />
        </span>{" "}
        of{" "}
        <span className="numeral font-semibold">
          {summary.total.toLocaleString()}
        </span>{" "}
        objects converted
        {summary.needReview > 0 ? (
          <>
            {" · "}
            <span className="numeral font-semibold text-held">
              {summary.needReview.toLocaleString()}
            </span>{" "}
            need review
          </>
        ) : null}
        {summary.unsupported > 0 ? (
          <>
            {" · "}
            <span className="numeral font-semibold text-serious">
              {summary.unsupported.toLocaleString()}
            </span>{" "}
            unsupported
          </>
        ) : null}
        {summary.failed > 0 ? (
          <>
            {" · "}
            <span className="numeral font-semibold text-critical">
              {summary.failed.toLocaleString()}
            </span>{" "}
            failed
          </>
        ) : null}
      </p>

      {summary.balances ? (
        <p className="mt-2 text-xs leading-relaxed text-ink-faint">
          The parts sum to{" "}
          <span className="numeral">{summary.accountedFor.toLocaleString()}</span>
          , which is the whole. Every object is accounted for.
        </p>
      ) : (
        <p className="mt-2 flex items-start gap-2 text-xs leading-relaxed text-warning">
          <AlertIcon className="mt-px h-3.5 w-3.5 shrink-0" />
          The parts sum to{" "}
          <span className="numeral">{summary.accountedFor.toLocaleString()}</span>{" "}
          and the total says{" "}
          <span className="numeral">{summary.total.toLocaleString()}</span>. They
          do not reconcile, so treat both with suspicion until they do.
        </p>
      )}

      {/* Status is never colour alone: icon, word and explanation together. */}
      {/*
        A rule and space, not a second card. This was a bordered, filled box
        inside a bordered, filled pane - the same radius and the same hairline
        twice, which reads as two things when it is one: the verdict *is* the
        content of this pane, not an aside within it. The shield and the
        heading already say where it starts.
      */}
      <div className="mt-6 border-t border-line pt-5">
        <p className="flex items-center gap-2.5">
          <ShieldIcon className="h-5 w-5 shrink-0 text-warning" />
          <span className="text-base font-semibold tracking-tight text-ink">
            {copy.label}
          </span>
        </p>
        <p className="mt-2 max-w-prose text-sm leading-relaxed text-ink-muted">
          {copy.meaning}
        </p>
        {because === null ? null : (
          <p className="mt-2 max-w-prose text-sm leading-relaxed text-ink-muted">
            {because}
          </p>
        )}
        <p className="mt-2 max-w-prose text-sm leading-relaxed text-ink-muted">
          Numerical equivalence is <strong className="text-ink">not</strong>{" "}
          claimed and never will be by this tool: comparing results means running
          both dashboards against live data, which needs a Tableau engine, a
          Power BI engine and warehouse credentials.
        </p>

        <Vocabulary current={verdict} />
      </div>
    </section>
  );
}

/**
 * The four words the product is allowed to use, with the current one marked.
 *
 * Showing the scale rather than only the reading is what makes the reading
 * meaningful: "Unverified" says much more when a reader can see it is the
 * second-weakest of four, and not a synonym for "fine".
 */
function Vocabulary({
  current,
}: {
  readonly current: keyof typeof VERDICT_COPY;
}) {
  const order: readonly (keyof typeof VERDICT_COPY)[] = [
    "verified",
    "partially_verified",
    "unverified",
    "failed",
  ];

  return (
    <ol className="mt-4 flex flex-wrap items-center gap-2" aria-label="Verdict scale">
      {order.map((key) => {
        const here = key === current;
        return (
          <li key={key}>
            <span
              className={[
                "tag flex items-center gap-1.5 rounded-control border px-2.5 py-1 text-xs",
                here
                  ? "border-line-strong text-ink"
                  : "border-line text-ink-faint",
              ].join(" ")}
              aria-current={here ? "true" : undefined}
            >
              {here ? (
                <ShieldIcon className="h-3 w-3" />
              ) : (
                <PendingIcon className="h-3 w-3" />
              )}
              {VERDICT_COPY[key].label}
              {here ? <span className="sr-only"> — this result</span> : null}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/**
 * Downloading what was produced.
 *
 * A failure here is shown *in place*: the migration did not move, so pushing
 * the user to the error screen would report a state transition that did not
 * happen. The error still renders in the contract shape, with `detail` behind a
 * disclosure, so there is no second, weaker error path.
 */
function ArtifactSection({
  projectId,
  filename,
  artifactId,
}: {
  readonly projectId: string;
  readonly filename: string;
  readonly artifactId: string | null;
}) {
  const [state, setState] = useState<Download>({ phase: "idle" });

  const download = useCallback(() => {
    setState({ phase: "working" });
    downloadArtifact(projectId, producedName(filename))
      .then((file) => {
        saveBlob(file.blob, file.filename);
        setState({ phase: "idle" });
      })
      .catch((cause: unknown) => {
        setState({ phase: "failed", error: toApiError(cause) });
      });
  }, [filename, projectId]);

  return (
    <section aria-labelledby="artifact-heading" className="panel p-5 sm:p-6">
      <h2 id="artifact-heading" className="eyebrow">
        What you can take away
      </h2>

      {artifactId === null ? (
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-muted">
          The conversion reported no produced artifact, so there is nothing to
          download. That is what the service said; nothing has been assumed in
          its place.
        </p>
      ) : (
        <>
          <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-muted">
            A Power BI project — TMDL semantic model and PBIR report — delivered
            as an archive, because a PBIP is a folder rather than a single file.
          </p>
          <p className="data mt-2 break-all text-xs text-ink-faint">
            <span className="sr-only">Artifact id </span>
            {artifactId}
          </p>

          <div className="mt-5 flex flex-wrap items-center gap-3">
            <button
              type="button"
              className="btn"
              onClick={download}
              disabled={state.phase === "working"}
            >
              <DownloadIcon className="h-4 w-4" />
              {state.phase === "working"
                ? "Preparing the download…"
                : "Download the Power BI project"}
            </button>
            <span className="data text-xs text-ink-faint">
              {producedName(filename)}
            </span>
          </div>

          <p className="mt-4 flex items-start gap-2 text-xs leading-relaxed text-ink-faint">
            <InfoIcon className="mt-px h-3.5 w-3.5 shrink-0" />
            No generated project has yet been opened in Power BI Desktop. The
            output satisfies what we know of the TMDL and PBIR formats by
            reasoning, not by observation, and until it has been opened that is
            all this can claim.
          </p>
        </>
      )}

      {state.phase === "failed" ? (
        <div role="alert" className="mt-4 rounded-control border border-line-strong bg-raised p-4">
          <p className="flex items-start gap-2.5 text-sm text-ink">
            <AlertIcon className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <span className="min-w-0 break-words">{state.error.message}</span>
          </p>
          {state.error.detail ? (
            <details className="ml-7 mt-2">
              <summary className="cursor-pointer text-xs text-ink-faint underline-offset-4 hover:underline">
                View technical details
              </summary>
              <p className="data mt-2 break-words rounded-control border border-line bg-base px-3 py-2 text-xs text-ink-muted">
                {state.error.detail}
              </p>
            </details>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

/**
 * Expressions the converter held back - the only things a model can draft.
 *
 * A worksheet filter or a dashboard layout also needs a person, but it needs
 * one to rebuild it, which is not something a model can propose. Counting
 * those here would offer drafts for items no draft can exist for.
 */
function heldExpressions(conversion: Conversion): number {
  let held = 0;
  for (const datasource of conversion.model?.datasources ?? []) {
    for (const table of datasource.tables ?? []) {
      for (const column of table.columns ?? []) {
        if (column.expression && !column.translation) held += 1;
      }
    }
  }
  return held;
}
