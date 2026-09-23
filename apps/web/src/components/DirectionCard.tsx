"use client";

import { motion } from "motion/react";
import type { ReactNode } from "react";

import type { Platform } from "@/types/contracts";

import { ArrowRightIcon, BlockedIcon, CheckIcon } from "./Icons";

const PLATFORM_LABEL: Record<Platform, string> = {
  tableau: "Tableau",
  powerbi: "Power BI",
};

export type Availability = "available" | "not_yet";

export interface DirectionCardProps {
  readonly source: Platform;
  readonly target: Platform;
  readonly blurb: string;
  /** What the run actually produces. Concrete, in a monospace face. */
  readonly produces: readonly string[];
  readonly availability: Availability;
  /** Why it is not available. Required when `availability` is "not_yet". */
  readonly reason?: string;
  readonly selected: boolean;
  readonly onSelect: () => void;
  readonly index: number;
}

const card = {
  hidden: { opacity: 0, y: 18, scale: 0.985 },
  visible: { opacity: 1, y: 0, scale: 1 },
};

/**
 * One direction, stated in the user's terms: which tool the work is in now,
 * and which tool it is going to.
 *
 * A direction we cannot do is shown, not hidden — the asymmetry between the
 * two directions is a fact about the product (ADR-005) and concealing it would
 * make the landing screen a promise the engine cannot keep. It is rendered as
 * a plain region with no control in it, so there is nothing to click, nothing
 * to tab to, and nowhere for it to lead.
 */
export function DirectionCard(props: DirectionCardProps) {
  const {
    source,
    target,
    blurb,
    produces,
    availability,
    reason,
    selected,
    onSelect,
    index,
  } = props;

  const title = `${PLATFORM_LABEL[source]} → ${PLATFORM_LABEL[target]}`;
  const headingId = `direction-${source}-${target}`;
  const available = availability === "available";

  const body = (
    <>
      <div className="flex items-center gap-2.5">
        <span className="data rounded-control border border-line px-2.5 py-1 text-xs text-source">
          {PLATFORM_LABEL[source]}
        </span>
        <ArrowRightIcon
          className={
            available ? "h-4 w-4 text-ink-muted" : "h-4 w-4 text-ink-faint"
          }
        />
        <span className="data rounded-control border border-line px-2.5 py-1 text-xs text-target">
          {PLATFORM_LABEL[target]}
        </span>
      </div>

      <h3
        id={headingId}
        className="mt-5 text-2xl font-semibold tracking-tight text-ink sm:text-[1.75rem]"
      >
        {title}
      </h3>

      <p className="mt-2.5 max-w-prose text-sm leading-relaxed text-ink-muted">
        {blurb}
      </p>

      {available ? (
        <ul className="mt-5 space-y-1.5">
          {produces.map((item) => (
            <li
              key={item}
              className="data flex items-start gap-2 text-xs text-ink-muted"
            >
              <CheckIcon className="mt-px h-3.5 w-3.5 shrink-0 text-good" />
              {item}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-5 max-w-prose text-sm leading-relaxed text-ink-faint">
          {reason}
        </p>
      )}

      <div className="mt-6 flex items-center justify-between border-t border-line pt-4">
        {available ? (
          <StatusChip tone="good" icon={<CheckIcon className="h-3.5 w-3.5" />}>
            {selected ? "Direction selected" : "Available"}
          </StatusChip>
        ) : (
          <StatusChip
            tone="faint"
            icon={<BlockedIcon className="h-3.5 w-3.5" />}
          >
            Not yet available
          </StatusChip>
        )}

        {available ? (
          <span className="text-sm font-medium text-ink">
            {selected ? "Selected" : "Choose"}
          </span>
        ) : null}
      </div>
    </>
  );

  const shared = "w-full text-left p-6 sm:p-7 h-full flex flex-col justify-start";

  if (!available) {
    // Not a panel. The two directions were identical cards separated only by a
    // badge, so the page read as offering two things and quietly withdrawing
    // one - a stakeholder scanning it sees two products. A dashed outline on
    // the page ground says "planned" before anyone reads a word, and 90%
    // opacity never did: the difference between an offer and a note about a
    // future offer is a difference in kind, so it is a difference in form.
    return (
      <motion.div
        variants={card}
        custom={index}
        role="group"
        aria-labelledby={headingId}
        className={`${shared} rounded-card border border-dashed border-line`}
      >
        {body}
      </motion.div>
    );
  }

  return (
    <motion.button
      type="button"
      variants={card}
      custom={index}
      onClick={onSelect}
      aria-pressed={selected}
      whileHover={{ y: -4 }}
      whileTap={{ scale: 0.994 }}
      transition={{ type: "spring", stiffness: 320, damping: 30 }}
      className={`panel ${shared} cursor-pointer hover:border-line-strong ${
        selected ? "border-line-strong shadow-lift" : ""
      }`}
    >
      {body}
    </motion.button>
  );
}

/** Status is never colour alone: every chip carries an icon and a word. */
function StatusChip({
  tone,
  icon,
  children,
}: {
  tone: "good" | "faint";
  icon: ReactNode;
  children: ReactNode;
}) {
  const colour = tone === "good" ? "text-good" : "text-ink-faint";
  return (
    <span
      className={`tag flex items-center gap-1.5 text-xs ${colour}`}
    >
      {icon}
      {children}
    </span>
  );
}
