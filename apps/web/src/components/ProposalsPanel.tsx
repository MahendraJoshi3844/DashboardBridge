"use client";

import { motion } from "motion/react";
import { useCallback, useState } from "react";

import { createProposals, decideProposal, toApiError } from "@/lib/api/client";
import { describeOutcome, splitOutcomes } from "@/lib/proposals/outcomes";
import type { ApiError, ProposalReview, ProposalSet } from "@/types/contracts";

import { AlertIcon, HandIcon, InfoIcon, SparkIcon } from "./Icons";

/**
 * Human-in-the-loop review (`P4.6`, ADR-007).
 *
 * The rule this screen exists to keep is that **nothing here has been applied**.
 * A proposal is a draft to read. Accepting one records a decision, and the
 * decision takes effect the next time the workbook is converted — which is said
 * in as many words, because a button labelled *Accept* on a screen showing an
 * expression invites the reading that the expression is now in the output.
 *
 * Three things are on the row for a reason:
 *
 * * **the reason the converter refused** — without it a reviewer is judging an
 *   answer to a question they cannot see;
 * * **the assumptions the model declared** — the part most likely to be wrong
 *   and the part a reader can actually check;
 * * **what was sent to the model**, verbatim and collapsed. It is the only way
 *   a person can satisfy themselves that the workbook was not sent, rather than
 *   taking our word for it.
 *
 * Confidence is shown and never acts. A high number pre-selects; a person still
 * presses the button.
 */
type Phase =
  | { readonly kind: "idle" }
  | { readonly kind: "asking" }
  | { readonly kind: "ready"; readonly set: ProposalSet }
  | { readonly kind: "failed"; readonly error: ApiError };

export function ProposalsPanel({
  projectId,
  held,
  aiAvailable,
}: {
  readonly projectId: string;
  /** How many objects the converter held back. Zero means nothing to ask about. */
  readonly held: number;
  readonly aiAvailable: boolean;
}) {
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [deciding, setDeciding] = useState<string | null>(null);

  const ask = useCallback(async () => {
    setPhase({ kind: "asking" });
    try {
      setPhase({ kind: "ready", set: await createProposals(projectId) });
    } catch (cause) {
      setPhase({ kind: "failed", error: toApiError(cause) });
    }
  }, [projectId]);

  const decide = useCallback(
    async (review: ProposalReview, decision: "accepted" | "rejected") => {
      const id = review.proposal.proposal_id;
      setDeciding(id);
      try {
        const updated = await decideProposal(projectId, id, decision);
        setPhase((current) =>
          current.kind === "ready"
            ? {
                kind: "ready",
                set: {
                  ...current.set,
                  reviews: current.set.reviews?.map((row) =>
                    row.proposal.proposal_id === id ? updated : row,
                  ),
                },
              }
            : current,
        );
      } catch (cause) {
        setPhase({ kind: "failed", error: toApiError(cause) });
      } finally {
        setDeciding(null);
      }
    },
    [projectId],
  );

  if (held === 0) return null;

  return (
    <section aria-labelledby="proposals-heading" className="panel p-5 sm:p-6">
      <h2 id="proposals-heading" className="eyebrow">
        What a model could draft
      </h2>

      <p className="mt-3 flex items-start gap-2.5 max-w-prose text-sm leading-relaxed text-ink-muted">
        <SparkIcon className="mt-0.5 h-4 w-4 shrink-0 text-held" />
        <span>
          <span className="numeral text-ink">{held.toLocaleString()}</span>{" "}
          {held === 1 ? "expression was" : "expressions were"} held back. A model
          can draft {held === 1 ? "it" : "them"} for you to read. It sees the
          expression and the schema of the fields it names — never the workbook.
        </span>
      </p>

      {phase.kind === "idle" ? (
        <button
          type="button"
          className="btn btn-quiet mt-4"
          onClick={ask}
          disabled={!aiAvailable}
        >
          {aiAvailable ? "Ask for drafts" : "No model is configured"}
        </button>
      ) : null}

      {phase.kind === "asking" ? (
        <p className="mt-4 text-sm text-ink-muted">Asking the model…</p>
      ) : null}

      {phase.kind === "failed" ? (
        <p className="mt-4 flex items-start gap-2 text-sm text-critical" role="alert">
          <AlertIcon className="mt-0.5 h-4 w-4 shrink-0" />
          {phase.error.message}
        </p>
      ) : null}

      {phase.kind === "ready" ? (
        <Results set={phase.set} deciding={deciding} onDecide={decide} />
      ) : null}
    </section>
  );
}

function Results({
  set,
  deciding,
  onDecide,
}: {
  readonly set: ProposalSet;
  readonly deciding: string | null;
  readonly onDecide: (
    review: ProposalReview,
    decision: "accepted" | "rejected",
  ) => void;
}) {
  const reviews = set.reviews ?? [];
  const skipped = set.skipped ?? [];
  const counts = splitOutcomes(skipped.map((item) => item.outcome));

  return (
    <div className="mt-4 space-y-4">
      <p className="text-sm leading-relaxed text-ink-muted">{set.summary}</p>

      {reviews.length === 0 ? null : (
        <p className="flex items-start gap-2 text-xs leading-relaxed text-ink-faint">
          <InfoIcon className="mt-px h-3.5 w-3.5 shrink-0" />
          Nothing below has been applied. Accepting one records your decision;
          it takes effect the next time this workbook is converted.
        </p>
      )}

      <motion.ul
        initial="hidden"
        animate="visible"
        variants={{ hidden: {}, visible: { transition: { staggerChildren: 0.04 } } }}
        className="space-y-3"
      >
        {reviews.map((review) => (
          <Row
            key={review.proposal.proposal_id}
            review={review}
            busy={deciding === review.proposal.proposal_id}
            onDecide={onDecide}
          />
        ))}
      </motion.ul>

      {skipped.length === 0 ? null : (
        <div>
          {/* Two different silences. "Nothing was asked" is about this machine;
              "the answer was discarded" is about the answer. Only the second
              says anything about the model. */}
          <h3 className="eyebrow mt-6">Without a draft</h3>
          <p className="mt-2 text-sm text-ink-muted">
            <span className="numeral text-ink">{counts.notAsked}</span> never
            sent to a model ·{" "}
            <span className="numeral text-ink">{counts.rejected}</span> answered
            and discarded before you saw it
          </p>
          <ul className="mt-3 space-y-2">
            {skipped.map((item) => {
              const copy = describeOutcome(item.outcome);
              return (
                <li key={`${item.item}-${item.outcome}`} className="panel p-3">
                  <p className="data break-all text-xs text-ink">{item.item}</p>
                  <p className="mt-1 text-xs text-ink-muted">
                    <span
                      className={
                        copy.kind === "answer_rejected"
                          ? "text-warning"
                          : "text-ink-faint"
                      }
                    >
                      {copy.label}
                    </span>{" "}
                    — {copy.next}
                  </p>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

function Row({
  review,
  busy,
  onDecide,
}: {
  readonly review: ProposalReview;
  readonly busy: boolean;
  readonly onDecide: (
    review: ProposalReview,
    decision: "accepted" | "rejected",
  ) => void;
}) {
  const [showPrompt, setShowPrompt] = useState(false);
  const proposal = review.proposal;
  const decided = review.decision !== "pending";

  return (
    <motion.li
      variants={{ hidden: { opacity: 0, y: 8 }, visible: { opacity: 1, y: 0 } }}
      className="panel p-4"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h4 className="data min-w-0 break-all text-sm text-ink">{review.item}</h4>
        <span className="data text-xs text-ink-faint">
          <span className="sr-only">Model confidence </span>
          {/* Shown, and doing nothing. Models are not calibrated. */}
          confidence {proposal.confidence.toFixed(2)}
          {proposal.preselected ? " · pre-selected" : ""}
        </span>
      </div>

      <p className="mt-2 flex items-start gap-2 text-xs leading-relaxed text-ink-muted">
        <HandIcon className="mt-px h-3.5 w-3.5 shrink-0 text-held" />
        Why it was held: {review.refusal_reason}
      </p>

      <dl className="mt-3 space-y-2">
        <div>
          <dt className="tag text-xs text-ink-faint">
            Tableau
          </dt>
          <dd className="data mt-1 whitespace-pre-wrap break-all rounded border border-line px-2.5 py-2 text-xs text-source">
            {proposal.source_expression}
          </dd>
        </div>
        <div>
          <dt className="tag text-xs text-ink-faint">
            Drafted DAX
          </dt>
          <dd className="data mt-1 whitespace-pre-wrap break-all rounded border border-line px-2.5 py-2 text-xs text-target">
            {proposal.target_expression}
          </dd>
        </div>
      </dl>

      {proposal.explanation ? (
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-muted">
          {proposal.explanation}
        </p>
      ) : null}

      {(proposal.assumptions ?? []).length > 0 ? (
        <>
          {/* The part most likely to be wrong, and the part a reader can check. */}
          <h5 className="eyebrow mt-3">What it assumed</h5>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-ink-muted">
            {proposal.assumptions?.map((assumption) => (
              <li key={assumption}>{assumption}</li>
            ))}
          </ul>
        </>
      ) : null}

      <button
        type="button"
        className="btn btn-quiet mt-3 text-xs"
        aria-expanded={showPrompt}
        onClick={() => setShowPrompt((open) => !open)}
      >
        {showPrompt ? "Hide what was sent" : "Show what was sent to the model"}
      </button>
      {showPrompt ? (
        <pre className="data mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-all rounded border border-line p-3 text-[0.7rem] leading-relaxed text-ink-muted">
          {review.prompt_sent}
        </pre>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {decided ? (
          <span
            className={`data text-xs ${
              review.decision === "accepted" ? "text-good" : "text-ink-faint"
            }`}
          >
            {review.decision === "accepted"
              ? "Accepted — it will be used the next time this workbook is converted."
              : "Rejected — kept on record, and not used."}
          </span>
        ) : (
          <>
            <button
              type="button"
              className="btn"
              disabled={busy}
              onClick={() => onDecide(review, "accepted")}
            >
              Accept
            </button>
            <button
              type="button"
              className="btn btn-quiet"
              disabled={busy}
              onClick={() => onDecide(review, "rejected")}
            >
              Reject
            </button>
          </>
        )}
      </div>
    </motion.li>
  );
}
