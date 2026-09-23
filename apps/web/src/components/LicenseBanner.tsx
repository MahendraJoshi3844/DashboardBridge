"use client";

import { useLicense } from "@/lib/hooks/useLicense";
import { licenseNotice } from "@/lib/license/notice";

import { AlertIcon } from "./Icons";

/**
 * Says that this deployment's licence is lapsing, or has.
 *
 * Before this, the only way a user learned the licence had expired was to
 * upload a workbook and receive a 402 - after doing the work of getting the
 * file here. The banner moves that discovery to the top of the page and to
 * *before* expiry.
 *
 * Everything it decides lives in `lib/license/notice.ts`, which is pure and
 * tested; this file only renders. That split is why the interesting rules -
 * a healthy licence says nothing, an unreachable service says nothing, and the
 * copy never claims more is lost than the server actually blocks - are covered
 * by `apps/web/tests/license.test.ts` rather than by a person remembering to
 * look at the screen.
 *
 * Not dismissible. A notice about work that is about to stop being possible is
 * not something to tidy away, and a dismissal would have to be remembered
 * somewhere, which means a licence warning that a `localStorage` entry can
 * silence.
 */
export function LicenseBanner() {
  const notice = licenseNotice(useLicense());
  if (notice.kind === "silent") return null;

  const blocked = notice.kind === "blocked";

  return (
    <section
      // `alert` for a state that stops work now, `status` for one that will.
      // The difference is whether a screen reader interrupts, and interrupting
      // someone over a date three weeks out is the wrong trade.
      role={blocked ? "alert" : "status"}
      aria-live={blocked ? "assertive" : "polite"}
      aria-label="Licence"
      className="panel flex items-start gap-3 px-4 py-3 sm:px-5"
    >
      <AlertIcon
        className={
          blocked
            ? "mt-0.5 h-4 w-4 shrink-0 text-critical"
            : "mt-0.5 h-4 w-4 shrink-0 text-warning"
        }
      />
      <div className="flex flex-col gap-1">
        <p
          className={
            blocked
              ? "text-sm font-medium text-critical"
              : "text-sm font-medium text-ink"
          }
        >
          {notice.headline}
        </p>
        <p className="text-sm text-ink-muted">{notice.detail}</p>
      </div>
    </section>
  );
}
