import { describe, expect, it } from "vitest";

import { copyFor } from "@/lib/direction/copy";

/**
 * SPEC-powerbi-to-tableau-web.md FR2 and AC12: no screen names the wrong
 * platform. Every direction-dependent word lives in one table, so this test can
 * read the whole of it rather than every component.
 */
const toPowerBi = copyFor({ source: "tableau", target: "powerbi" });
const toTableau = copyFor({ source: "powerbi", target: "tableau" });

function everyString(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(everyString);
  if (value && typeof value === "object") return Object.values(value).flatMap(everyString);
  return [];
}

describe("copyFor", () => {
  it("names each side of Tableau → Power BI", () => {
    expect(toPowerBi.sourceName).toBe("Tableau");
    expect(toPowerBi.targetName).toBe("Power BI");
    expect(toPowerBi.download).toContain("Power BI project");
  });

  it("names each side of Power BI → Tableau", () => {
    expect(toTableau.sourceName).toBe("Power BI");
    expect(toTableau.targetName).toBe("Tableau");
    expect(toTableau.download).toContain("Tableau workbook");
    expect(toTableau.dropPrompt).toContain("Power BI project");
  });

  it("never mentions a Power BI output format when the output is Tableau", () => {
    for (const text of everyString(toTableau)) {
      expect(text).not.toMatch(/PBIR|TMDL|\.pbip\.zip|Power BI Desktop/);
    }
  });

  it("never mentions a Tableau output format when the output is Power BI", () => {
    // `accept` and the input label describe what goes *in*, which is Tableau.
    const { accept: _accept, inputLabel: _label, ...output } = toPowerBi;
    for (const text of everyString(output)) {
      expect(text).not.toMatch(/\.twb\b|Tableau Desktop/);
    }
  });

  it("says what has not been checked, in the target's own tool", () => {
    expect(toTableau.desktopCaveat).toContain("Tableau Desktop");
    expect(toPowerBi.desktopCaveat).toContain("Power BI Desktop");
  });

  it("names the target platform when something has no equivalent", () => {
    expect(toTableau.noEquivalent).toContain("Tableau has no equivalent");
    expect(toPowerBi.noEquivalent).toContain("Power BI has no equivalent");
  });

  it("falls back to the direction that has always existed", () => {
    expect(copyFor(null)).toEqual(toPowerBi);
  });
});
