import { describe, expect, it } from "vitest";

import { licenseNotice } from "../src/lib/license/notice";
import type { LicenseStatusResponse } from "../src/types/contracts";

function status(over: Partial<LicenseStatusResponse>): LicenseStatusResponse {
  return {
    licensed: true,
    customer: "Northwind BI",
    expires: "2027-01-31",
    days_remaining: 200,
    seats: 5,
    features: ["convert"],
    expiring_soon: false,
    message: null,
    ...over,
  } as LicenseStatusResponse;
}

describe("what the licence banner says", () => {
  it("says nothing at all while the answer is unknown", () => {
    // The gateway restarting must not accuse a paying customer of not paying.
    expect(licenseNotice({ phase: "unknown" })).toEqual({ kind: "silent" });
  });

  it("says nothing about a healthy licence", () => {
    // A permanent green badge is chrome, and chrome trains people to stop
    // reading banners - including the one that matters.
    expect(licenseNotice({ phase: "known", status: status({}) })).toEqual({
      kind: "silent",
    });
  });

  it("warns while the licence still works, not on the day it stops", () => {
    const notice = licenseNotice({
      phase: "known",
      status: status({ expiring_soon: true, days_remaining: 9 }),
    });
    expect(notice.kind).toBe("expiring");
    if (notice.kind !== "expiring") return;
    expect(notice.headline).toContain("in 9 days");
    expect(notice.detail).toContain("2027-01-31");
  });

  it("counts the last valid day as today rather than as expired", () => {
    // `License.days_remaining` returns 0 on the last usable day. Rendering that
    // as "expired" locks a customer out a day early on screen while the server
    // still converts - the two halves must agree.
    const notice = licenseNotice({
      phase: "known",
      status: status({ expiring_soon: true, days_remaining: 0 }),
    });
    expect(notice.kind).toBe("expiring");
    if (notice.kind !== "expiring") return;
    expect(notice.headline).toContain("today");
  });

  it("says tomorrow rather than in 1 days", () => {
    const notice = licenseNotice({
      phase: "known",
      status: status({ expiring_soon: true, days_remaining: 1 }),
    });
    if (notice.kind !== "expiring") throw new Error("expected a warning");
    expect(notice.headline).toContain("tomorrow");
    expect(notice.headline).not.toContain("1 days");
  });

  it("blocks with the server's own reason, which is never one reason", () => {
    // Never installed, expired on a date, or signed by a key this build does
    // not carry are three different conversations with three different people.
    const notice = licenseNotice({
      phase: "known",
      status: status({
        licensed: false,
        message: "The licence expired on 2026-08-31.",
      }),
    });
    if (notice.kind !== "blocked") throw new Error("expected a block");
    expect(notice.detail).toContain("expired on 2026-08-31");
  });

  it("never claims more is lost than the server actually blocks", () => {
    // `core/licensing` refuses conversions and deliberately leaves past
    // projects readable. A banner implying the product is locked would be
    // overstating the consequence to hurry a renewal - and untrue.
    const notice = licenseNotice({
      phase: "known",
      status: status({ licensed: false, message: null }),
    });
    if (notice.kind !== "blocked") throw new Error("expected a block");
    expect(notice.detail).toContain("stay open");
    expect(notice.headline).toContain("Northwind BI");
  });

  it("does not warn when the server has not said the licence is expiring", () => {
    // The threshold belongs to `engines/licensing` (WARN_WITHIN_DAYS) and is
    // deliberately not re-implemented here: two copies of a rule are two rules.
    expect(
      licenseNotice({
        phase: "known",
        status: status({ expiring_soon: false, days_remaining: 3 }),
      }),
    ).toEqual({ kind: "silent" });
  });

  it("stays silent rather than guessing when a day count is missing", () => {
    expect(
      licenseNotice({
        phase: "known",
        status: status({ expiring_soon: true, days_remaining: null }),
      }),
    ).toEqual({ kind: "silent" });
  });
});
