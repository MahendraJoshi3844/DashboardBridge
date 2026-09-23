"use client";

import { useEffect, useState } from "react";

import { health, toApiError } from "@/lib/api/client";
import type { ApiError, HealthResponse } from "@/types/contracts";

/**
 * The capability probe, as one typed state.
 *
 * The conversion screen needs two facts from it and must not guess either:
 *
 * * `ai_available` — when false, AI is **absent** from the interface, not shown
 *   and disabled. An offer that cannot be honoured is worse than no offer
 *   (01-product-spec.md, "AI as informed consent").
 * * `privacy_mode` — the conversion request carries one, and the honest value
 *   is the server's own. Defaulting it here would put a claim about where the
 *   workbook is processed into a request body on no evidence.
 *
 * While the probe is unresolved neither fact is known, so the screen renders
 * neither. `checking` and `unreachable` are separate from `ready` for exactly
 * that reason: "we do not know yet" is not "there is no AI".
 */
export type HealthProbe =
  | { readonly phase: "checking" }
  | { readonly phase: "ready"; readonly health: HealthResponse }
  | { readonly phase: "unreachable"; readonly error: ApiError };

export function useHealth(): HealthProbe {
  const [probe, setProbe] = useState<HealthProbe>({ phase: "checking" });

  useEffect(() => {
    const controller = new AbortController();
    health({ signal: controller.signal })
      .then((response) => setProbe({ phase: "ready", health: response }))
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setProbe({ phase: "unreachable", error: toApiError(cause) });
      });
    return () => controller.abort();
  }, []);

  return probe;
}
