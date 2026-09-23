"use client";

import { motion } from "motion/react";
import { useMemo, useState, type ReactNode } from "react";

import {
  compare,
  pairCheck,
  PAIR_CHECK_COPY,
  type ComparisonRow,
  type ComparisonSource,
  type PairCheck,
} from "@/lib/comparison/pairs";
import type {
  ConversionFlag,
  ConversionMethod1 as ConversionMethod,
  ConversionStatus,
  Validation,
} from "@/types/contracts";

import { ArrowRightIcon, HandIcon, InfoIcon } from "./Icons";

/**
 * The comparison explorer (P5.5): source expression beside target expression,
 * one row per object, with the method and any rule id.
 *
 * 08-validation-engine.md calls this "the user-facing half of validation" and
 * requires one thing above all: *"Unconverted items show the refusal reason in
 * the same layout, because what did not convert is as much a result as what
 * did."* So a refused item is not filtered out, not collapsed into a count, and
 * not moved to a second list — it is the same row with the reason where the
 * target expression would have been, and it sorts to the top, because it is the
 * part that needs a person.
 *
 * A per-pair check result is **not** shown, and its absence is stated rather
 * than left blank, because a blank where a PASS belongs reads as a PASS to
 * anyone skimming. The validation engine scores the project by category and
 * never names an individual expression, so no row can carry one — which is a
 * different sentence from "validation has not run", and `pairCheck` picks
 * between them rather than letting the row assert the stronger claim.
 *
 * All ordering and shaping is in `@/lib/comparison/pairs`, which is pure and
 * tested away from the DOM.
 */
const STATUS_COPY: Record<ConversionStatus, { label: string; ink: string }> = {
  converted: { label: "Converted", ink: "text-good" },
  partial: { label: "Partly converted", ink: "text-warning" },
  ai_required: { label: "Held for you", ink: "text-held" },
  unsupported: { label: "Not supported", ink: "text-serious" },
  failed: { label: "Failed", ink: "text-critical" },
};

const METHOD_COPY: Record<ConversionMethod, string> = {
  deterministic: "Deterministic",
  rule: "Rule",
  ai_assisted: "AI-assisted",
  manual: "By hand",
};

/** How many rows are shown before the list asks to be opened. */
const PREVIEW = 8;

export function ComparisonPanel({
  source,
  flags,
  validation,
}: {
  /** Which model is being compared — see `comparisonSource`. */
  readonly source: ComparisonSource;
  readonly flags: readonly ConversionFlag[];
  /** The checks, once they have returned. Null before that, never a stand-in. */
  readonly validation: Validation | null;
}) {
  const model = source.model;
  const check = pairCheck(validation);
  const comparison = useMemo(() => compare(model, flags), [model, flags]);
  const [expanded, setExpanded] = useState(false);
  const shown = expanded
    ? comparison.rows
    : comparison.rows.slice(0, PREVIEW);

  if (model === null) {
    return (
      <section aria-labelledby="comparison-heading" className="panel p-5 sm:p-6">
        <h2 id="comparison-heading" className="eyebrow">
          Source beside target
        </h2>
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-muted">
          The service returned neither the converted model nor the analysed one,
          so there is nothing to put side by side. Nothing has been
          reconstructed in its place.
        </p>
      </section>
    );
  }

  if (comparison.rows.length === 0) {
    return (
      <section aria-labelledby="comparison-heading" className="panel p-5 sm:p-6">
        <h2 id="comparison-heading" className="eyebrow">
          Source beside target
        </h2>
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-muted">
          This workbook has no calculated fields, so there are no expressions to
          compare. The objects it does have are counted above.
        </p>
      </section>
    );
  }

  return (
    <section aria-labelledby="comparison-heading">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="comparison-heading" className="eyebrow">
          Source beside target
        </h2>
        {/* The parts sum to the whole, so a reader can check the arithmetic
            (03-ux-spec.md, Results). `unaccounted` is shown when it is not
            zero rather than folded into either of the other two. */}
        <p className="text-sm text-ink-muted">
          <span className="numeral text-ink">
            {comparison.rows.length.toLocaleString()}
          </span>{" "}
          expressions ·{" "}
          <span className="numeral text-ink">
            {comparison.crossed.toLocaleString()}
          </span>{" "}
          translated ·{" "}
          <span className="numeral text-ink">
            {comparison.refused.toLocaleString()}
          </span>{" "}
          refused
          {comparison.unaccounted === 0 ? null : (
            <>
              {" · "}
              <span className="numeral text-ink">
                {comparison.unaccounted.toLocaleString()}
              </span>{" "}
              unaccounted for
            </>
          )}
        </p>
      </div>

      <p className="mt-2 flex items-start gap-2 text-xs leading-relaxed text-ink-faint">
        <InfoIcon className="mt-px h-3.5 w-3.5 shrink-0" />
        Expression by expression, refusals first. What did not convert appears in
        the same layout as what did, with the reason in place of the result.
      </p>

      {/* Two different silences, never merged. "The conversion produced no DAX"
          and "the conversion's model never reached us" are opposite claims
          about the run, and only the first is a statement about the workbook. */}
      {source.kind === "analysed" ? (
        <p
          className="panel mt-3 border-line-strong p-4 text-sm leading-relaxed text-ink-muted"
          role="note"
        >
          <strong className="font-medium text-warning">
            No target expression can be shown for any row.
          </strong>{" "}
          The conversion did not return the model it produced, so the right-hand
          column is reading the workbook as it was uploaded, before anything was
          translated. An empty target here means <em>not shown</em>, not{" "}
          <em>not converted</em>, and nothing has been reconstructed to fill it.
        </p>
      ) : comparison.crossed === 0 ? (
        <p
          className="panel mt-3 border-line-strong p-4 text-sm leading-relaxed text-ink-muted"
          role="note"
        >
          <strong className="font-medium text-warning">
            No target expression was produced for any row.
          </strong>{" "}
          The conversion returned its model and not one expression in it carries
          DAX. Nothing has been reconstructed to fill the column — a
          plausible-looking DAX expression nobody generated is precisely what
          this product refuses to print.
        </p>
      ) : null}

      <motion.ul
        initial="hidden"
        animate="visible"
        variants={{ hidden: {}, visible: { transition: { staggerChildren: 0.03 } } }}
        className="mt-4 space-y-2.5"
      >
        {shown.map((row) => (
          <Row key={row.id} row={row} check={check} />
        ))}
      </motion.ul>

      {comparison.rows.length > PREVIEW ? (
        <button
          type="button"
          className="btn btn-quiet mt-4"
          aria-expanded={expanded}
          onClick={() => setExpanded((open) => !open)}
        >
          {expanded
            ? `Show the first ${PREVIEW}`
            : `Show all ${comparison.rows.length} expressions`}
        </button>
      ) : null}
    </section>
  );
}

function Row({
  row,
  check,
}: {
  readonly row: ComparisonRow;
  readonly check: PairCheck;
}) {
  const status = STATUS_COPY[row.status];

  return (
    <motion.li
      variants={{ hidden: { opacity: 0, y: 8 }, visible: { opacity: 1, y: 0 } }}
      className="panel p-4"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="data min-w-0 break-all text-sm text-ink">{row.id}</h3>
        <span className={`data text-xs ${status.ink}`}>{status.label}</span>
      </div>

      {/* Side by side where there is room; stacked where there is not. The
          arrow is decorative — the column headings carry the direction. */}
      <div className="mt-3 grid gap-3 lg:grid-cols-[1fr_auto_1fr] lg:items-stretch">
        <Side heading="Tableau" ink="text-source">
          <Expression text={row.sourceText} language={row.sourceLanguage} />
        </Side>

        <span
          className="hidden items-center text-ink-faint lg:flex"
          aria-hidden="true"
        >
          <ArrowRightIcon className="h-4 w-4" />
        </span>

        <Side heading="Power BI" ink="text-target">
          {row.target !== null ? (
            <>
              <Expression
                text={row.target.target_text}
                language={row.target.target_language}
              />
              <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
                <Fact term="Method" value={METHOD_COPY[row.target.method]} />
                {/* Plural: one expression can fire several mappings, and
                    citing one of two names an arbitrary half of the reason.
                    Absent rather than empty when none fired - a control-flow
                    rewrite is the translator's own work, not a rule's. */}
                {row.target.rule_ids && row.target.rule_ids.length > 0 ? (
                  <Fact
                    term={row.target.rule_ids.length === 1 ? "Rule" : "Rules"}
                    value={row.target.rule_ids.join(", ")}
                  />
                ) : null}
                {row.target.proposal_id ? (
                  <Fact term="Proposal" value={row.target.proposal_id} />
                ) : null}
              </dl>
            </>
          ) : row.targetAbsence === "refused" && row.refusal ? (
            <Refusal reason={row.refusal.reason ?? ""} method={row.refusal.method} />
          ) : (
            <p className="text-sm leading-relaxed text-ink-muted">
              No expression was returned for this object, and no refusal was
              recorded either. Neither fact is invented here.
            </p>
          )}
        </Side>
      </div>

      {/* A blank space where a check result belongs reads as a pass; saying so
          does not. Which of the two sentences is true is decided in
          `pairCheck`, because "nothing was checked" and "the checks were not
          about this" are different claims and the wrong one contradicts the
          validation panel on the same screen. */}
      <p className="mt-3 text-xs leading-relaxed text-ink-faint">
        {PAIR_CHECK_COPY[check]}
      </p>
    </motion.li>
  );
}

function Side({
  heading,
  ink,
  children,
}: {
  readonly heading: string;
  readonly ink: string;
  readonly children: ReactNode;
}) {
  return (
    <div className="min-w-0">
      <p className={`tag text-xs ${ink}`}>
        {heading}
      </p>
      <div className="mt-1.5">{children}</div>
    </div>
  );
}

/**
 * An expression, verbatim.
 *
 * `overflow-x-auto` on the block rather than wrapping mid-token: an expression
 * broken at an arbitrary character is an expression a reader can misread, and
 * the page must never scroll sideways as a whole (03-ux-spec.md, responsive).
 */
function Expression({
  text,
  language,
}: {
  readonly text: string;
  readonly language: string;
}) {
  return (
    <>
      <pre className="overflow-x-auto rounded-control border border-line bg-raised px-3 py-2 text-xs leading-relaxed text-ink">
        <code>{text}</code>
      </pre>
      <p className="tag mt-1 text-xs text-ink-faint">
        <span className="sr-only">Language: </span>
        {language}
      </p>
    </>
  );
}

function Refusal({
  reason,
  method,
}: {
  readonly reason: string;
  readonly method: ConversionMethod | undefined;
}) {
  return (
    <div className="rounded-control border border-line bg-raised px-3 py-2">
      <p className="flex items-start gap-2 text-sm leading-relaxed text-ink-muted">
        <HandIcon className="mt-0.5 h-4 w-4 shrink-0 text-held" />
        <span className="min-w-0 break-words">
          {reason === "" ? "No expression was produced for this object." : reason}
        </span>
      </p>
      {method === undefined ? null : (
        <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
          <Fact term="Next" value={METHOD_COPY[method]} />
        </dl>
      )}
    </div>
  );
}

function Fact({
  term,
  value,
}: {
  readonly term: string;
  readonly value: string;
}) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className="tag text-xs text-ink-faint">
        {term}
      </dt>
      <dd className="data break-all text-xs text-ink-muted">{value}</dd>
    </div>
  );
}
