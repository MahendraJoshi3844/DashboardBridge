/**
 * The migration products an administrator grants, and whether each can be
 * granted meaningfully on this deployment.
 *
 * A product is a licence feature (`tableau`, `microstrategy`, `qlik`). The
 * server decides what a person can use: engine installed, licence includes it,
 * and - unless they are an administrator - they were given it. This file only
 * shapes that for the Users & access screen.
 */

import type { DirectionsProbe } from "@/lib/migrator/paths";
import type { Platform } from "@/types/contracts";

export interface Product {
  readonly id: "tableau" | "microstrategy" | "qlik";
  readonly label: string;
  /** The source platform whose direction(s) the product enables. */
  readonly source: Platform;
}

export const PRODUCTS: readonly Product[] = [
  { id: "tableau", label: "Tableau → Power BI", source: "tableau" },
  { id: "microstrategy", label: "MicroStrategy → Power BI", source: "microstrategy" },
  { id: "qlik", label: "Qlik → Power BI", source: "qlik" },
];

/**
 * Null when the product runs on this deployment; otherwise why it cannot (not
 * installed, not licensed). Read from an administrator's `/directions`, which is
 * never limited by grants. Unknown locks nothing, as elsewhere.
 */
export function productBlocked(probe: DirectionsProbe, product: Product): string | null {
  if (probe.phase !== "known") return null;
  const found = probe.directions.find((d) => d.source_platform === product.source && d.target_platform === "powerbi");
  if (found === undefined) return "No engine for this product on this deployment.";
  return found.state === "not_installed" || found.state === "not_licensed" ? found.reason || "Not available." : null;
}

/** The products a new person is given by default: every one this deployment can run. */
export function defaultProducts(probe: DirectionsProbe): string[] {
  return PRODUCTS.filter((p) => productBlocked(probe, p) === null).map((p) => p.id);
}

/** Toggle one product in a list, keeping the list sorted and free of duplicates. */
export function toggled(products: readonly string[], id: string, on: boolean): string[] {
  const set = new Set(products);
  if (on) set.add(id);
  else set.delete(id);
  return [...set].sort();
}
