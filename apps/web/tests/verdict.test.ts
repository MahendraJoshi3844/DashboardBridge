import { describe, expect, it } from "vitest";

import {
  summarise,
  unverifiedBecause,
  verdictOf,
  VERDICT_COPY,
} from "@/lib/results/verdict";
import type { Conversion, Validation } from "@/types/contracts";

/**
 * The rule 08-validation-engine.md exists to protect:
 *
 * > The system never reports success it did not verify.
 *
 * Everything below is a way of failing that rule, written down so it fails a
 * test instead of a customer.
 */
const completed: Conversion = {
  conversion_id: "c",
  status: "completed",
  compatibility: {
    converted: 132,
    partial: 5,
    ai_required: 3,
    unsupported: 3,
    failed: 0,
    total: 143,
  },
  artifact_id: "a",
  flags: [],
};

describe("summarise", () => {
  it("keeps the denominator and the parts that make it up", () => {
    const summary = summarise(completed.compatibility);
    expect(summary.total).toBe(143);
    expect(summary.converted).toBe(132);
    // "8 need review" is partial + ai_required: both need a person, and the
    // spec's own worked example counts them together.
    expect(summary.needReview).toBe(8);
    expect(summary.unsupported).toBe(3);
    expect(summary.accountedFor).toBe(143);
    expect(summary.balances).toBe(true);
  });

  it("reports counts that do not reconcile rather than hiding them", () => {
    const summary = summarise({ converted: 10, total: 20 });
    expect(summary.accountedFor).toBe(10);
    expect(summary.balances).toBe(false);
  });

  it("treats an absent compatibility as zeroes, not as a full house", () => {
    const summary = summarise(undefined);
    expect(summary.total).toBe(0);
    expect(summary.converted).toBe(0);
    // 0 === 0, so an empty result is internally consistent — it just says
    // nothing, which is the correct thing for it to say.
    expect(summary.balances).toBe(true);
  });
});

describe("verdictOf", () => {
  it("never rises above 'unverified' on a conversion alone", () => {
    // This is the single most important assertion in the suite. A completed
    // conversion with files on disk is still unverified, because nothing
    // checked them.
    expect(verdictOf(completed, null)).toBe("unverified");
  });

  it("calls a conversion that did not finish 'failed'", () => {
    expect(verdictOf({ ...completed, status: "failed" }, null)).toBe("failed");
    expect(verdictOf({ ...completed, status: "cancelled" }, null)).toBe(
      "failed",
    );
  });

  it("defers to a real validation when there is one", () => {
    const validation: Validation = {
      validation_id: "v",
      status: "completed",
      verdict: "partially_verified",
    };
    expect(verdictOf(completed, validation)).toBe("partially_verified");
  });

  it("stays unverified when a validation exists but stated no verdict", () => {
    const validation: Validation = { validation_id: "v", status: "completed" };
    expect(verdictOf(completed, validation)).toBe("unverified");
  });
});

describe("the vocabulary", () => {
  it("is exactly the four words the product is allowed to use", () => {
    expect(Object.keys(VERDICT_COPY).sort()).toEqual([
      "failed",
      "partially_verified",
      "unverified",
      "verified",
    ]);
  });

  it("gives a reason only where the reason is ours to give", () => {
    // The sentence itself is copy and will be reworded; what must hold is that
    // there is one, and that it names the checks rather than blaming the file.
    const reason = unverifiedBecause("unverified") ?? "";
    expect(reason).toContain("checks");
    expect(reason.length).toBeGreaterThan(40);
    expect(unverifiedBecause("partially_verified")).toBeNull();
    expect(unverifiedBecause("verified")).toBeNull();
    expect(unverifiedBecause("failed")).toBeNull();
  });

  it("never describes an unvalidated result as a success", () => {
    const words = `${VERDICT_COPY.unverified.label} ${VERDICT_COPY.unverified.meaning}`;
    expect(words.toLowerCase()).not.toContain("success");
    expect(words.toLowerCase()).toContain("nothing has been checked");
  });
});
