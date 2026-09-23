import { describe, expect, it } from "vitest";

import {
  describeOutcome,
  OUTCOME_COPY,
  splitOutcomes,
} from "@/lib/proposals/outcomes";

/**
 * The distinction the whole AI layer keeps, defended at the last place it can
 * be thrown away (`P4.6`).
 *
 * The router has six ways of not reaching a model and the gauntlet has seven of
 * discarding what came back. All of that care is wasted if the screen renders
 * them as one grey "no suggestion available", so these tests hold the mapping
 * to two things: every outcome the service can send has copy, and the copy
 * never claims a model said something when none was asked.
 */
const NOT_ASKED = [
  "not_enabled",
  "no_provider",
  "provider_unavailable",
  "refused_by_privacy",
  "no_prompt",
  "no_answer",
];

const REJECTED = [
  "not_json",
  "schema",
  "wrong_operation",
  "unknown_reference",
  "disallowed_function",
  "security",
  "low_confidence",
];

describe("describeOutcome", () => {
  it("has copy for every outcome the router and the gauntlet can produce", () => {
    for (const outcome of [...NOT_ASKED, ...REJECTED]) {
      expect(OUTCOME_COPY[outcome], outcome).toBeDefined();
      expect(describeOutcome(outcome).label.trim()).not.toBe("");
      expect(describeOutcome(outcome).next.trim()).not.toBe("");
    }
  });

  it("separates what was never asked from what was asked and rejected", () => {
    for (const outcome of NOT_ASKED) {
      expect(describeOutcome(outcome).kind, outcome).toBe("not_asked");
    }
    for (const outcome of REJECTED) {
      expect(describeOutcome(outcome).kind, outcome).toBe("answer_rejected");
    }
  });

  it("never implies a model answered when none was asked", () => {
    // The specific lie to avoid: "the model had nothing to say" printed for an
    // item that was never sent anywhere.
    for (const outcome of NOT_ASKED.filter((name) => name !== "no_answer")) {
      const copy = `${describeOutcome(outcome).label} ${describeOutcome(outcome).next}`;
      expect(copy.toLowerCase(), outcome).not.toContain("the model said");
      expect(copy.toLowerCase(), outcome).not.toContain("suggested");
    }
  });

  it("falls back to the machine name rather than inventing one", () => {
    const unknown = describeOutcome("something_new_from_the_server");
    expect(unknown.label).toBe("something_new_from_the_server");
    expect(unknown.next).toBeTruthy();
  });
});

describe("splitOutcomes", () => {
  it("counts the two groups apart", () => {
    const counts = splitOutcomes([
      "not_enabled",
      "not_enabled",
      "unknown_reference",
    ]);
    expect(counts).toEqual({ notAsked: 2, rejected: 1 });
  });

  it("counts an unrecognised outcome as one nobody asked about", () => {
    // The safe side: claiming a model rejected something it never saw is the
    // worse of the two mistakes.
    expect(splitOutcomes(["brand_new"])).toEqual({ notAsked: 1, rejected: 0 });
  });
});
