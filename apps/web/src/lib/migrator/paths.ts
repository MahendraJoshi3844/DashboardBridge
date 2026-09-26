/**
 * Whether a migration card or sidebar link opens, decided from `GET /directions`.
 *
 * Engines are separate products: a deployment has the ones its customer bought,
 * and the licence says which may run. The server is the authority - it refuses
 * an unavailable direction however the request arrives - so this only decides
 * what to *show*, and it follows the licence banner's rule: **a failed or
 * pending request is "unknown", and unknown locks nothing.** Telling a customer
 * an engine is missing because the gateway blinked would be a claim we cannot
 * make; if it really is missing, the server's refusal says so, in its words.
 */

import type { DirectionStatus, Platform } from "@/types/contracts";

export type DirectionsProbe =
  | { readonly phase: "unknown" }
  | { readonly phase: "known"; readonly directions: readonly DirectionStatus[] };

/** Null when the direction may be opened; otherwise the reason to show. */
export function directionLock(probe: DirectionsProbe, source: Platform, target: Platform): string | null {
  if (probe.phase !== "known") return null;
  const found = probe.directions.find((d) => d.source_platform === source && d.target_platform === target);
  if (found === undefined) return "This deployment has no engine for this direction.";
  return found.state === "available" ? null : found.reason || "Not available on this deployment.";
}
