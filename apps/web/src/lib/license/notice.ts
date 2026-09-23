/**
 * What, if anything, to tell someone about this deployment's licence.
 *
 * The product runs on the customer's own machines and stops converting when the
 * licence lapses (`P7.1`). Before this, the only way a user learned that was by
 * uploading a workbook and receiving a 402 - which is the worst possible moment
 * to find out, because they have already done the work of getting the file
 * here.
 *
 * Kept as a pure function on purpose. It is the part where being wrong is a
 * false claim rather than a visual glitch, and `apps/web/tests` covers exactly
 * that kind of logic (see `vitest.config.ts`).
 *
 * ## Three decisions live here
 *
 * **A healthy licence says nothing.** A permanent green badge is chrome, and
 * chrome trains people to stop reading banners - so the one time it matters,
 * they will not read that one either.
 *
 * **Not knowing is not bad news.** If the service cannot be reached, the
 * licence state is unknown, and rendering "unlicensed" would accuse a paying
 * customer of not paying because their gateway restarted. The same rule
 * `useHealth` follows for AI: "we do not know yet" is not "there is none".
 *
 * **The notice must not claim more than the gate enforces.** `core/licensing`
 * blocks *conversions* and deliberately leaves past projects, reports and flags
 * readable - so the copy says that, rather than implying the product is locked.
 * Overstating the consequence to hurry a renewal is the kind of thing a
 * customer discovers is untrue and remembers.
 */

import type { LicenseStatusResponse } from "@/types/contracts";

/**
 * The probe, in the three states it genuinely has.
 *
 * `unknown` covers both "still asking" and "could not ask". They differ to the
 * engineer and not to the reader: in both cases the honest interface shows
 * nothing about licensing at all.
 */
export type LicenseProbe =
  | { readonly phase: "unknown" }
  | { readonly phase: "known"; readonly status: LicenseStatusResponse };

export type LicenseNotice =
  | { readonly kind: "silent" }
  | {
      /** Valid, and close enough to expiry to be worth acting on. */
      readonly kind: "expiring";
      readonly headline: string;
      readonly detail: string;
      readonly daysRemaining: number;
    }
  | {
      /** Conversions are refused right now. */
      readonly kind: "blocked";
      readonly headline: string;
      readonly detail: string;
    };

/** Whole days, phrased the way a person says them. */
function inDays(days: number): string {
  if (days <= 0) return "today";
  if (days === 1) return "tomorrow";
  return `in ${days} days`;
}

/**
 * The sentence about what still works. Stated in every lapsed notice, because
 * the first question anyone asks is whether they have lost their work.
 */
const STILL_READABLE =
  "Projects you have already converted stay open, with their reports and flags. " +
  "New conversions resume as soon as a licence is in place.";

export function licenseNotice(probe: LicenseProbe): LicenseNotice {
  if (probe.phase === "unknown") return { kind: "silent" };

  const { status } = probe;

  if (!status.licensed) {
    return {
      kind: "blocked",
      headline: status.customer
        ? `The licence for ${status.customer} is not active.`
        : "This deployment has no active licence.",
      // The server's own sentence when it has one: it knows which of the
      // several different "no"s this is - never installed, expired on a stated
      // date, signed by a key this build does not carry - and those are
      // different conversations with different people.
      detail: `${status.message ?? "Conversions are unavailable until a licence is installed."} ${STILL_READABLE}`,
    };
  }

  const days = status.days_remaining;
  if (!status.expiring_soon || days === null || days === undefined) {
    return { kind: "silent" };
  }

  return {
    kind: "expiring",
    daysRemaining: days,
    headline: `This licence expires ${inDays(days)}.`,
    detail:
      `Converting stops on ${status.expires ?? "the expiry date"}; ` +
      "everything already converted stays readable. Renew before then to " +
      "avoid a gap.",
  };
}
