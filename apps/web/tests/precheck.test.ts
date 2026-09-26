import { describe, expect, it } from "vitest";

import { formatBytes, precheck, precheckDrop } from "@/lib/upload/precheck";

/**
 * The client-side pre-check. It is a courtesy and not a security boundary, and
 * the thing worth testing about it is the *copy contract*: every refusal has to
 * arrive in the contract error shape, with a message for a person and a detail
 * for an engineer, so there is only one error path in the UI.
 */
function fileOf(name: string, size: number): File {
  // Real bytes, so `File.size` is the browser's own answer rather than a
  // property we redefined to suit the assertion.
  return new File([new Uint8Array(size)], name);
}

describe("precheck", () => {
  it("accepts a Tableau workbook", () => {
    const result = precheck(fileOf("Superstore.twbx", 1_100_000));
    expect(result.ok).toBe(true);
  });

  it("names what it can do instead of shrugging at a Power BI file", () => {
    const result = precheck(fileOf("Sales.pbix", 1000));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.message).toContain("Power BI");
    expect(result.error.message).toContain(".twb");
    expect(result.error.category).toBe("UPLOAD_ERROR");
  });

  it("refuses an unknown extension with both messages present", () => {
    const result = precheck(fileOf("notes.pdf", 1000));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.message.length).toBeGreaterThan(0);
    expect(result.error.detail).toContain(".pdf");
    // No HTTP code, no stack trace, no apology (03-ux-spec.md, Copy).
    expect(result.error.message).not.toMatch(/\b[45]\d\d\b/);
    expect(result.error.message.toLowerCase()).not.toContain("sorry");
  });

  it("refuses an empty file rather than uploading nothing", () => {
    const result = precheck(fileOf("Superstore.twb", 0));
    expect(result.ok).toBe(false);
  });

  it("refuses a multi-file drop rather than guessing which one was meant", () => {
    const result = precheckDrop([
      fileOf("a.twb", 10),
      fileOf("b.twb", 10),
    ]);
    expect(result.ok).toBe(false);
  });

  it("accepts a single-file drop", () => {
    expect(precheckDrop([fileOf("a.twb", 10)]).ok).toBe(true);
  });
});

describe("formatBytes", () => {
  it("reads as a person reads a size", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1024)).toBe("1.0 KB");
    expect(formatBytes(1_150_000)).toBe("1.1 MB");
  });
});

describe("precheck for a Power BI source", () => {
  it("accepts a zipped project folder", () => {
    expect(precheck(fileOf("Retail.zip", 5000), "powerbi").ok).toBe(true);
  });

  it("gives the remedy for a .pbix rather than a shrug", () => {
    const result = precheck(fileOf("Sales.pbix", 1000), "powerbi");
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.message).toContain("PBIP");
    expect(result.error.message).toContain("zip");
  });

  it("explains that a .pbip on its own is only the manifest", () => {
    const result = precheck(fileOf("Retail.pbip", 200), "powerbi");
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.message).toContain("manifest");
  });

  it("names the mismatch when a Tableau file is opened in this direction", () => {
    const result = precheck(fileOf("Superstore.twbx", 1000), "powerbi");
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.message).toContain("Tableau → Power BI");
  });

  it("names the mismatch when a Power BI project is opened for Tableau", () => {
    const result = precheck(fileOf("Retail.zip", 1000), "tableau");
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.message).toContain("Power BI → Tableau");
  });
});

describe("precheck for MicroStrategy", () => {
  it("accepts a .mstr package and a zipped metadata export", () => {
    expect(precheck(fileOf("Executive Sales.mstr", 5000), "microstrategy").ok).toBe(true);
    expect(precheck(fileOf("retail_bundle.zip", 5000), "microstrategy").ok).toBe(true);
  });

  it("sends a Tableau workbook back to the Tableau migration", () => {
    const result = precheck(fileOf("Superstore.twbx", 1000), "microstrategy");
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.message).toContain("Tableau → Power BI");
  });

  it("sends a .mstr package opened elsewhere to MicroStrategy → Power BI", () => {
    for (const source of ["tableau", "powerbi"] as const) {
      const result = precheck(fileOf("Executive Sales.mstr", 1000), source);
      expect(result.ok).toBe(false);
      if (result.ok) return;
      expect(result.error.message).toContain("MicroStrategy → Power BI");
    }
  });

  it("names what it reads when the file is something else", () => {
    const result = precheck(fileOf("notes.txt", 10), "microstrategy");
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.message).toContain("MicroStrategy package");
  });
});

describe("precheck for Qlik", () => {
  it("accepts a zipped unbuild folder and a load script", () => {
    expect(precheck(fileOf("Sales.zip", 5000), "qlik").ok).toBe(true);
    expect(precheck(fileOf("script.qvs", 500), "qlik").ok).toBe(true);
  });

  it("explains how to export a .qvf or .qvw instead of refusing blankly", () => {
    for (const name of ["Sales.qvf", "Sales.qvw"]) {
      const result = precheck(fileOf(name, 1000), "qlik");
      expect(result.ok).toBe(false);
      if (result.ok) return;
      expect(result.error.message).toMatch(/unbuild|-prj/);
    }
  });

  it("sends a .qvs opened elsewhere to Qlik → Power BI", () => {
    const result = precheck(fileOf("script.qvs", 100), "tableau");
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.message).toContain("Qlik → Power BI");
  });
});
