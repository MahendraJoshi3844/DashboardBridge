/**
 * What each way of not producing a proposal means, in a person's words.
 *
 * The service returns a machine name — `not_enabled`, `provider_unavailable`,
 * `unknown_reference` — and the screen has to turn it into something a reader
 * can act on. Doing that with a map, tested, rather than a chain of ternaries
 * in a component, because the whole point of keeping these distinct through the
 * router and the gauntlet is lost the moment the UI renders them all as
 * *no suggestion available*.
 *
 * They fall into two groups and the difference matters more than the wording:
 * some are facts about **this machine** — nothing was asked — and some are facts
 * about **the answer** — something was asked and what came back was not usable.
 * Only the second group says anything about the model.
 */

/** Whether anything was sent at all. */
export type OutcomeKind = "not_asked" | "answer_rejected";

export interface OutcomeCopy {
  readonly kind: OutcomeKind;
  readonly label: string;
  /** What a person would do about it, when there is anything to do. */
  readonly next: string;
}

const NOT_ASKED = (label: string, next: string): OutcomeCopy => ({
  kind: "not_asked",
  label,
  next,
});

const REJECTED = (label: string, next: string): OutcomeCopy => ({
  kind: "answer_rejected",
  label,
  next,
});

export const OUTCOME_COPY: Record<string, OutcomeCopy> = {
  // --- nothing was asked ---------------------------------------------------
  not_enabled: NOT_ASKED(
    "AI is switched off",
    "Nothing was sent to a model. This item is yours to write.",
  ),
  no_provider: NOT_ASKED(
    "No model is configured",
    "Configure a provider on the server if you want drafts; the item converts either way.",
  ),
  provider_unavailable: NOT_ASKED(
    "The model is not answering",
    "The configured provider did not respond. Nothing was sent anywhere else.",
  ),
  refused_by_privacy: NOT_ASKED(
    "The privacy mode forbids this provider",
    "A remote provider cannot be used in local-only mode. Two settings disagree.",
  ),
  no_prompt: NOT_ASKED(
    "This build has no prompt for that",
    "A defect here rather than something you can act on. Nothing was sent.",
  ),
  no_answer: NOT_ASKED(
    "The model had no suggestion",
    "It was asked and declined, which is a better answer than a guess.",
  ),

  // --- something came back and did not survive checking --------------------
  not_json: REJECTED(
    "The answer was not in the agreed form",
    "Discarded. Reading an expression out of prose would mean guessing where it began.",
  ),
  schema: REJECTED(
    "The answer was missing something",
    "Discarded rather than filled in, because filling it in is how an assumption becomes a fact.",
  ),
  wrong_operation: REJECTED(
    "The model answered a different question",
    "Discarded.",
  ),
  unknown_reference: REJECTED(
    "It referred to something that does not exist",
    "Discarded. It would have parsed and then failed when you opened the report.",
  ),
  disallowed_function: REJECTED(
    "It used a function we cannot vouch for",
    "Discarded. Unknown-good is not the same as known-good.",
  ),
  security: REJECTED(
    "The answer carried something an expression never does",
    "Discarded — a link, a path, or part of the prompt echoed back.",
  ),
  low_confidence: REJECTED(
    "The model was not confident enough",
    "Discarded rather than shown, so it cannot be skimmed past.",
  ),
};

/** Falls back to the machine name rather than inventing a friendlier one. */
export function describeOutcome(outcome: string): OutcomeCopy {
  return (
    OUTCOME_COPY[outcome] ?? {
      kind: "not_asked",
      label: outcome,
      next: "No proposal was produced for this item.",
    }
  );
}

/**
 * How many were never asked about, and how many were asked and rejected.
 *
 * A heading that says "8 items have no proposal" hides the only distinction
 * that matters: whether the model was involved.
 */
export function splitOutcomes(
  outcomes: readonly string[],
): { readonly notAsked: number; readonly rejected: number } {
  let notAsked = 0;
  let rejected = 0;
  for (const outcome of outcomes) {
    if (describeOutcome(outcome).kind === "answer_rejected") rejected += 1;
    else notAsked += 1;
  }
  return { notAsked, rejected };
}
