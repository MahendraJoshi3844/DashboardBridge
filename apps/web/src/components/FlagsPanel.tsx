"use client";

import { motion } from "motion/react";
import { useMemo, useState } from "react";

import { byActionability, needsAPerson } from "@/lib/flags/ordering";
import type {
  ConversionFlag,
  ConversionMethod1 as ConversionMethod,
  ConversionStatus,
  Severity,
} from "@/types/contracts";

import { InfoIcon } from "./Icons";

/**
 * Everything the parse could not do cleanly, ordered by what you must do about
 * it.
 *
 * The engine's discovery order is thrown away here on purpose. 03-ux-spec.md:
 * *"Timeline order once buried all six actionable calculations beneath forty
 * field-well notices, where nobody would ever see them."* The sort key is in
 * `@/lib/flags/ordering`, tested separately from this component.
 *
 * Every row shows **all three axes** — method, status, severity. They answer
 * three different questions (*how was it done*, *what became of it*, *how
 * loudly does the report say so*) and ADR-004 exists because collapsing them
 * into one enum makes the audit trail unable to answer "what did the AI
 * actually do".
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

const SEVERITY_COPY: Record<Severity, { label: string; ink: string }> = {
  manual: { label: "Needs a person", ink: "text-held" },
  warning: { label: "Worth reading", ink: "text-warning" },
  info: { label: "For the record", ink: "text-ink-faint" },
};

const row = {
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0 },
};

const list = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.03 } },
};

/** How many rows are shown before the list asks to be opened. */
const PREVIEW = 12;

export function FlagsPanel({
  flags,
}: {
  readonly flags: readonly ConversionFlag[];
}) {
  const ordered = useMemo(() => byActionability(flags), [flags]);
  const actionable = useMemo(
    () => ordered.filter(needsAPerson).length,
    [ordered],
  );
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? ordered : ordered.slice(0, PREVIEW);

  if (ordered.length === 0) {
    return (
      <section aria-labelledby="flags-heading" className="panel p-5 sm:p-6">
        <h2 id="flags-heading" className="eyebrow">
          What needs your attention
        </h2>
        <p className="mt-3 text-sm leading-relaxed text-ink-muted">
          The parse raised nothing. That means nothing was dropped silently — not
          that every object is guaranteed to convert; that is what the conversion
          and validation steps establish.
        </p>
      </section>
    );
  }

  return (
    <section aria-labelledby="flags-heading">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="flags-heading" className="eyebrow">
          What needs your attention
        </h2>
        <p className="text-sm text-ink-muted">
          <span className="numeral text-ink">{actionable}</span> of{" "}
          <span className="numeral text-ink">{ordered.length}</span> items need a
          person
        </p>
      </div>

      <p className="mt-2 flex items-start gap-2 text-xs leading-relaxed text-ink-faint">
        <InfoIcon className="mt-px h-3.5 w-3.5 shrink-0" />
        Ordered by what you must do, not by when the engine found it. A
        calculation needing hand-written DAX comes before a field well needing a
        click.
      </p>

      <motion.ul
        variants={list}
        initial="hidden"
        animate="visible"
        className="mt-4 space-y-2.5"
      >
        {shown.map((flag, index) => (
          <FlagRow key={`${flag.stage}-${flag.item}-${index}`} flag={flag} />
        ))}
      </motion.ul>

      {ordered.length > PREVIEW ? (
        <button
          type="button"
          className="btn btn-quiet mt-4"
          aria-expanded={expanded}
          onClick={() => setExpanded((open) => !open)}
        >
          {expanded
            ? `Show the first ${PREVIEW}`
            : `Show all ${ordered.length} items`}
        </button>
      ) : null}
    </section>
  );
}

function FlagRow({ flag }: { readonly flag: ConversionFlag }) {
  const status = STATUS_COPY[flag.status ?? "converted"];
  const severity = SEVERITY_COPY[flag.severity ?? "info"];
  const method = METHOD_COPY[flag.method ?? "deterministic"];

  return (
    <motion.li variants={row} className="panel p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="data min-w-0 break-all text-sm text-ink">{flag.item}</h3>
        <span className="tag text-xs text-ink-faint">
          {flag.stage}
        </span>
      </div>

      {/* `break-words`: a reason often quotes an encoded Tableau shelf
          reference, which is one 90-character word and will otherwise push the
          whole page sideways on a phone. */}
      {flag.reason ? (
        <p className="mt-1.5 max-w-prose break-words text-sm leading-relaxed text-ink-muted">
          {flag.reason}
        </p>
      ) : null}

      {flag.ref ? (
        <p className="data mt-1.5 break-all text-xs text-ink-faint">
          <span className="sr-only">Reference: </span>
          {flag.ref}
        </p>
      ) : null}

      {/* Three axes, three chips, each labelled with the question it answers. */}
      <dl className="mt-3 flex flex-wrap gap-x-4 gap-y-2">
        <Axis question="What became of it" value={status.label} ink={status.ink} />
        <Axis question="How" value={method} ink="text-ink-muted" />
        <Axis
          question="Attention"
          value={severity.label}
          ink={severity.ink}
        />
      </dl>
    </motion.li>
  );
}

function Axis({
  question,
  value,
  ink,
}: {
  readonly question: string;
  readonly value: string;
  readonly ink: string;
}) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className="tag text-xs text-ink-faint">
        {question}
      </dt>
      <dd className={`data text-xs ${ink}`}>{value}</dd>
    </div>
  );
}
