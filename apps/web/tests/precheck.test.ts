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
