"use client";

import { useEffect, useState } from "react";

import { license } from "@/lib/api/client";
import type { LicenseProbe } from "@/lib/license/notice";

/**
 * The deployment's licence state, as the one thing the banner may read.
 *
 * **A failed request is `unknown`, not "unlicensed".** That collapse is the
 * whole reason this hook exists rather than the component calling the client
 * itself: an error path that produced a "no licence" state would tell a paying
 * customer they had not paid every time their gateway restarted, and it would
 * look entirely reasonable in review. The same rule `useHealth` follows for AI
 * - "we do not know yet" is not "there is none".
 *
 * Asked once, on mount. The expiry does not move while someone is looking at
 * the page, and a poll would be a request every few seconds for a date.
 */
export function useLicense(): LicenseProbe {
  const [probe, setProbe] = useState<LicenseProbe>({ phase: "unknown" });

  useEffect(() => {
    const controller = new AbortController();
    license({ signal: controller.signal })
      .then((status) => setProbe({ phase: "known", status }))
      .catch(() => {
        // Deliberately swallowed. The service being unreachable is already
        // reported by `StatusStrip`, in the place a person looks for it;
        // saying it twice in two different vocabularies is noise, and saying
        // anything about the *licence* here would be a claim we cannot make.
      });
    return () => controller.abort();
  }, []);

  return probe;
}
