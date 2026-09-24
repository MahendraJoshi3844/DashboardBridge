import { describe, expect, it } from "vitest";

import { RUN_JOBS, itemsFor } from "@/lib/migrator/assistant";

const MODEL_STEPS = new Set(["draft_dax", "summarize", "chat"]);

describe("RUN_JOBS", () => {
  it("offers every option the Run menu shows", () => {
    expect(RUN_JOBS.map((job) => job.label)).toEqual([
      "Optimize Model",
      "Validate Calculations",
      "Validate & Fix DAX",
      "Validate & Fix M-Query",
      "Full Health Check",
      "Batch Fix DAX",
      "Batch Fix M-Query",
      "Batch Fix All",
    ]);
  });

  it("runs deterministic checks before any model step (AGENTS.md rule 4)", () => {
    for (const job of RUN_JOBS) {
      const first = job.steps.findIndex((step) => MODEL_STEPS.has(step.step));
      if (first === -1) continue;
      expect(first, job.label).toBeGreaterThan(0);
    }
  });

  it("says which jobs ask a model, truthfully", () => {
    for (const job of RUN_JOBS) {
      expect(job.usesAi, job.label).toBe(job.steps.some((step) => MODEL_STEPS.has(step.step)));
    }
  });
});

describe("itemsFor", () => {
  const measure = { kind: "measure", table: "Sales", name: "Ratio" };
  const partition = { kind: "partition", table: "Sales", name: "Sales" };

  it("scopes DAX steps to the selected measure", () => {
    expect(itemsFor("selection", "check_references", measure)).toEqual(["Sales.Ratio"]);
  });

  it("scopes M-Query steps to the selected table", () => {
    expect(itemsFor("selection", "format_mquery", partition)).toEqual(["Sales"]);
  });

  it("works on everything when nothing fitting is selected, or for batch jobs", () => {
    expect(itemsFor("selection", "format_mquery", measure)).toEqual([]);
    expect(itemsFor("all", "check_references", measure)).toEqual([]);
    expect(itemsFor("selection", "check_references", null)).toEqual([]);
  });
});
