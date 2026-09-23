import { describe, expect, it } from "vitest";

import { compare } from "@/lib/comparison/pairs";
import type { CanonicalModel, ConversionFlag } from "@/types/contracts";

/**
 * The comparison explorer's pairing rule (P5.5).
 *
 * The failure this guards against is the tempting one: quietly dropping the
 * rows with no target, so the explorer looks full and successful. What did not
 * convert is as much a result as what did (08-validation-engine.md).
 */
function modelWith(
  columns: NonNullable<
    NonNullable<CanonicalModel["datasources"]>[number]["tables"]
  >[number]["columns"],
): CanonicalModel {
  return {
    source_platform: "tableau",
    datasources: [
      { id: "ds", name: "ds", tables: [{ id: "Orders", name: "Orders", columns }] },
    ],
  };
}

const refusal: ConversionFlag = {
  item: "Orders.Rank",
  stage: "translate",
  method: "manual",
  status: "ai_required",
  severity: "manual",
  reason: "The intended aggregation is not stated in the formula.",
  ref: "Orders.Rank",
};

const plain = {
  id: "Orders.Quantity",
  name: "Quantity",
  datatype: "integer" as const,
};

const refused = {
  id: "Orders.Rank",
  name: "Rank",
  expression: {
    source_language: "tableau_calc",
    source_text: "RANK(SUM([Sales]))",
  },
};

const crossed = {
  id: "Orders.Band",
  name: "Band",
  expression: { source_language: "tableau_calc", source_text: 'IF [x] THEN "a" END' },
  translation: {
    target_language: "dax",
    target_text: 'IF(x, "a")',
    method: "rule" as const,
    rule_ids: ["R1"],
  },
};

describe("compare", () => {
  it("has a row for every expression and none for a plain column", () => {
    const { rows } = compare(modelWith([plain, refused, crossed]), [refusal]);
    expect(rows.map((row) => row.id)).toEqual(["Orders.Rank", "Orders.Band"]);
  });

  it("attaches the refusal to the object it refused", () => {
    const { rows } = compare(modelWith([refused]), [refusal]);
    expect(rows[0]?.refusal?.reason).toBe(refusal.reason);
    expect(rows[0]?.targetAbsence).toBe("refused");
    expect(rows[0]?.status).toBe("ai_required");
  });

  it("carries the target expression and its provenance when there is one", () => {
    const { rows } = compare(modelWith([crossed]), []);
    expect(rows[0]?.target?.target_text).toBe('IF(x, "a")');
    expect(rows[0]?.target?.rule_ids).toEqual(["R1"]);
    expect(rows[0]?.targetAbsence).toBeNull();
    expect(rows[0]?.status).toBe("converted");
  });

  it("distinguishes 'refused' from 'nothing was returned'", () => {
    // These are opposite claims and must never render as one message: one says
    // we declined, the other says we cannot show you what we did.
    const { rows } = compare(modelWith([refused]), []);
    expect(rows[0]?.targetAbsence).toBe("not_returned");
    expect(rows[0]?.refusal).toBeNull();
  });

  it("counts crossed, refused and unaccounted separately", () => {
    const c = compare(modelWith([refused, crossed]), [refusal]);
    expect(c.crossed).toBe(1);
    expect(c.refused).toBe(1);
    expect(c.unaccounted).toBe(0);
  });

  it("puts what needs a person above what does not", () => {
    const { rows } = compare(modelWith([crossed, refused]), [refusal]);
    expect(rows[0]?.id).toBe("Orders.Rank");
  });

  it("is deterministic whatever order the columns arrive in", () => {
    const a = compare(modelWith([crossed, refused]), [refusal]);
    const b = compare(modelWith([refused, crossed]), [refusal]);
    expect(a.rows.map((r) => r.id)).toEqual(b.rows.map((r) => r.id));
  });

  it("says nothing rather than inventing rows when there is no model", () => {
    expect(compare(null, [refusal]).rows).toEqual([]);
    expect(compare(undefined, [refusal]).rows).toEqual([]);
  });
});
