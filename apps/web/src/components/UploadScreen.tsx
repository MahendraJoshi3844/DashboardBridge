"use client";

import { motion } from "motion/react";

import { PLATFORM_NAMES } from "@/lib/platforms";
import type { ApiError, Platform } from "@/types/contracts";

import { ChosenFile, Dropzone } from "./Dropzone";
import { AlertIcon, ArrowRightIcon, CloseIcon } from "./Icons";

const PLATFORM_LABEL: Record<Platform, string> = PLATFORM_NAMES;

/**
 * Upload (P1.2) — "Accept an artifact" (01-product-spec.md, Screens).
 *
 * The screen answers the five questions: where you are (the heading and the
 * direction), what is happening (nothing yet — nothing has left the machine),
 * why (the empty state says what this step is for), what next (one control),
 * and what needs attention (a refused file, stated inline).
 *
 * A pre-check refusal is shown **here** rather than pushed through the state
 * machine's `ERROR`. The file never left the browser, so nothing about where
 * the user is in the migration has changed; moving them to an error screen
 * would report a state transition that did not happen. The error still renders
 * as the contract shape, with `detail` behind a disclosure, so there is no
 * second, weaker error path.
 */
export function UploadScreen({
  source,
  target,
  file,
  refusal,
  onAccepted,
  onRefused,
  onCleared,
  onStart,
}: {
  readonly source: Platform;
  readonly target: Platform;
  readonly file: File | null;
  readonly refusal: ApiError | null;
  readonly onAccepted: (file: File) => void;
  readonly onRefused: (error: ApiError) => void;
  readonly onCleared: () => void;
  readonly onStart: () => void;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.24, ease: [0.22, 0.61, 0.36, 1] }}
    >
      <p className="eyebrow">Step 2 — open a workbook</p>
      <h1 className="mt-3 text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
        Open the workbook you want to migrate
      </h1>
      <p className="mt-3 flex flex-wrap items-center gap-2 text-sm text-ink-muted">
        <span className="data rounded-control border border-line px-2.5 py-1 text-xs text-source">
          {PLATFORM_LABEL[source]}
        </span>
        <ArrowRightIcon className="h-4 w-4 text-ink-faint" />
        <span className="data rounded-control border border-line px-2.5 py-1 text-xs text-target">
          {PLATFORM_LABEL[target]}
        </span>
        <span className="ml-1">
          It is read here, and analysed before anything is converted.
        </span>
      </p>

      {refusal ? (
        <div
          role="alert"
          className="panel mt-6 border-line-strong p-4 sm:p-5"
        >
          <p className="flex items-start gap-2.5 text-sm text-ink">
            <AlertIcon className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <span className="min-w-0 break-words">{refusal.message}</span>
          </p>
          {refusal.detail ? (
            <details className="ml-7 mt-2">
              <summary className="cursor-pointer text-xs text-ink-faint underline-offset-4 hover:underline">
                View technical details
              </summary>
              <p className="data mt-2 break-words rounded-control border border-line bg-raised px-3 py-2 text-xs text-ink-muted">
                {refusal.detail}
              </p>
            </details>
          ) : null}
        </div>
      ) : null}

      <div className="mt-6">
        {file === null ? (
          <Dropzone onAccepted={onAccepted} onRefused={onRefused} />
        ) : (
          <section
            aria-labelledby="chosen-heading"
            className="panel p-5 sm:p-6"
          >
            <h2 id="chosen-heading" className="eyebrow">
              Ready to analyse
            </h2>
            <div className="mt-3">
              <ChosenFile file={file} />
            </div>
            <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-muted">
              Nothing has been sent yet. Analysing reads the workbook and reports
              what is in it — it converts nothing and changes nothing.
            </p>
            <div className="mt-5 flex flex-wrap items-center gap-3">
              <button type="button" className="btn" onClick={onStart}>
                Analyse this workbook
                <ArrowRightIcon className="h-4 w-4" />
              </button>
              <button
                type="button"
                className="btn btn-quiet"
                onClick={onCleared}
              >
                <CloseIcon className="h-4 w-4" />
                Choose a different one
              </button>
            </div>
          </section>
        )}
      </div>

      <p className="mt-6 max-w-prose text-xs leading-relaxed text-ink-faint">
        The checks in this browser — file type, size — are a courtesy that saves
        you a doomed upload. The service checks the same things again, plus the
        bytes themselves, and its answer is the one that counts.
      </p>
    </motion.div>
  );
}
