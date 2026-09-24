import { describe, expect, it } from "vitest";

import { checkReferences, draftKey, statsOf, withDraft, withoutDraft } from "@/lib/migrator/workspace";
import type { WorkspaceModel } from "@/types/contracts";

const model: WorkspaceModel = {
  project_id: "00000000-0000-0000-0000-000000000000",
  name: "Test",
  version: 0,
  tables: [
    {
      name: "Sales",
      columns: [{ name: "Sales" }, { name: "Quantity" }],
      measures: [{ name: "Profit Ratio", expression: "1" }],
      partitions: [],
    },
    { name: "Order Lines", columns: [{ name: "Units" }], measures: [], partitions: [] },
  ],
  held: [{ item: "Sales.Rank", table: "Sales", name: "Rank", reason: "INDEX() has no equivalent" }],
};

describe("checkReferences", () => {
  it("accepts references that exist, quoted or not", () => {
    expect(checkReferences("SUM('Sales'[Sales]) / SUM(Sales[Quantity]) + [Profit Ratio]", model)).toEqual([]);
    expect(checkReferences("SUM('Order Lines'[Units])", model)).toEqual([]);
  });

  it("names a table that does not exist", () => {
    const [problem] = checkReferences("SUM(Ghost[Sales])", model);
    expect(problem?.reason).toContain("no table called Ghost");
  });

  it("names a column the table does not have", () => {
    const [problem] = checkReferences("SUM('Sales'[Margin])", model);
    expect(problem?.reason).toContain("Sales has no column or measure called Margin");
  });

  it("ignores brackets inside strings and comments", () => {
    expect(checkReferences('"see [Ghost]" // [Nope]\n+ 1', model)).toEqual([]);
  });
});

describe("drafts", () => {
  it("keeps one draft per object, the latest winning", () => {
    let drafts = withDraft(new Map(), { kind: "measure", table: "Sales", name: "X", expression: "1" });
    drafts = withDraft(drafts, { kind: "measure", table: "Sales", name: "X", expression: "2" });
    expect(drafts.size).toBe(1);
    expect(drafts.get(draftKey("measure", "Sales", "X"))?.expression).toBe("2");
    expect(withoutDraft(drafts, draftKey("measure", "Sales", "X")).size).toBe(0);
  });
});

describe("statsOf", () => {
  it("counts what the model holds", () => {
    expect(statsOf(model)).toEqual({ tables: 2, columns: 3, measures: 1, held: 1 });
  });
});
