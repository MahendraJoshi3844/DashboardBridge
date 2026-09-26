/**
 * What each platform is called, in one place.
 *
 * Every screen used to carry its own two-entry map, and adding a third platform
 * meant finding them all. `Record<Platform, …>` makes the compiler do that now:
 * a new platform in the contract fails the build here until it has a name.
 */

import type { Platform } from "@/types/contracts";

export const PLATFORM_NAMES: Record<Platform, string> = {
  tableau: "Tableau",
  powerbi: "Power BI",
  microstrategy: "MicroStrategy",
  qlik: "Qlik",
};

export function directionLabel(source: Platform, target: Platform): string {
  return `${PLATFORM_NAMES[source]} → ${PLATFORM_NAMES[target]}`;
}

/** The target each source converts into - the path its migration card opens. */
export const TARGET_OF: Record<Platform, Platform> = {
  tableau: "powerbi",
  powerbi: "tableau",
  microstrategy: "powerbi",
  qlik: "powerbi",
};
