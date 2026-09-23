import { describe, expect, it } from "vitest";

import {
  actionabilityRank,
  byActionability,
  needsAPerson,
} from "@/lib/flags/ordering";
import type { ConversionFlag } from "@/types/contracts";

/**
 * `scripts/check-ordering.mjs` already reproduces the named regression from
 * 03-ux-spec.md — forty field wells burying six calculations — and it keeps
 * doing so, because it runs in `npm run check:ordering` where a checkout with
 * no dependencies installed can still run it.
 *
 * These are the properties that script does not assert: the shape of the
 * ranking function itself, which everything else is built on.
 */
const flag = (over: Partial<ConversionFlag>): ConversionFlag => ({
  item: "x",
  stage: "generate",
  method: "rule",
  status: "partial",
  severity: "info",
  reason: "",
  ref: "x",
  ...over,
});

describe("actionabilityRank", () => {
  it("ranks the two 'the source could not be read' stages together", () => {
    // Losing an object to a failed extract and losing it to a failed parse are
    // the same problem to the person holding it.
    const extract = flag({ stage: "extract", severity: "manual", status: "failed" });
    const parse = flag({ stage: "parse", severity: "manual", status: "failed" });
    expect(actionabilityRank(extract)).toBe(actionabilityRank(parse));
  });

  it("puts hand-written DAX above a re-bound field well", () => {
    const dax = flag({ stage: "translate", severity: "manual", status: "ai_required" });
    const well = flag({ stage: "map", severity: "manual", status: "unsupported" });
    expect(actionabilityRank(dax)).toBeLessThan(actionabilityRank(well));
  });

  it("treats a missing axis as its mildest value rather than throwing", () => {
    const bare: ConversionFlag = { item: "y", stage: "generate" };
    expect(() => actionabilityRank(bare)).not.toThrow();
    expect(needsAPerson(bare)).toBe(false);
  });
});

describe("byActionability", () => {
  it("never mutates the list it was given", () => {
    const input = [flag({ item: "b" }), flag({ item: "a" })];
    const copy = [...input];
    byActionability(input);
    expect(input).toEqual(copy);
  });

  it("breaks ties on the item name, so two runs agree", () => {
    const ordered = byActionability([
      flag({ item: "zebra" }),
      flag({ item: "apple" }),
    ]);
    expect(ordered.map((f) => f.item)).toEqual(["apple", "zebra"]);
  });
});
