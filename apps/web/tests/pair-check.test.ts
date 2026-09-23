import { describe, expect, it } from "vitest";

import { PAIR_CHECK_COPY, pairCheck } from "@/lib/comparison/pairs";
import type { Validation } from "@/types/contracts";

/**
 * What each comparison row may say about validation (P5.5).
 *
 * The row carries a line where a per-pair check result would go, because a
 * blank there reads as a PASS. That line was written when validation did not
 * exist and says validation "has not happened" — which, now that P5.1–P5.4 run,
 * is false, and false on the same screen that renders the validation panel.
 *
 * The truth has two shapes and they are not interchangeable: validation has not
 * run yet, or validation ran and scores the project by category rather than
 * naming this expression. Both mean "no check result for this pair"; only one
 * means "no checks at all".
 */
const validated: Validation = {
  validation_id: "33333333-3333-3333-3333-333333333333",
  status: "completed",
  verdict: "partially_verified",
};

describe("pairCheck", () => {
  it("says no check has run when validation has not run", () => {
    expect(pairCheck(null)).toBe("not_run");
  });

  it("says the checks do not name this pair once validation has run", () => {
    expect(pairCheck(validated)).toBe("not_per_pair");
  });

  it("never claims validation has not happened once it has", () => {
    // The specific regression: this line contradicting the validation panel
    // three inches above it.
    const copy = PAIR_CHECK_COPY[pairCheck(validated)].toLowerCase();
    expect(copy).not.toContain("have not happened");
    expect(copy).not.toContain("no check has been run");
  });

  it("does not imply a pass in either state", () => {
    for (const copy of Object.values(PAIR_CHECK_COPY)) {
      expect(copy.trim()).not.toBe("");
      expect(copy.toLowerCase()).not.toContain("passed");
    }
  });
});
