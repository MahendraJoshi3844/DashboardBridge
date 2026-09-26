import { describe, expect, it } from "vitest";

import { directionLock, type DirectionsProbe } from "@/lib/migrator/paths";
import type { DirectionStatus } from "@/types/contracts";

function direction(source: DirectionStatus["source_platform"], state: DirectionStatus["state"], reason = ""): DirectionStatus {
  return { source_platform: source, target_platform: "powerbi", state, engine: "x", engine_version: "", licence_feature: source, reason };
}

const tableauOnly: DirectionsProbe = {
  phase: "known",
  directions: [
    direction("tableau", "available"),
    direction("microstrategy", "not_installed", "The MicroStrategy → Power BI engine (mstr2pbi) is not installed on this deployment."),
    direction("qlik", "not_licensed", "Qlik → Power BI is not included in this licence."),
  ],
};

describe("directionLock", () => {
  it("opens what the deployment can run and locks the rest with the server's reason", () => {
    expect(directionLock(tableauOnly, "tableau", "powerbi")).toBeNull();
    expect(directionLock(tableauOnly, "microstrategy", "powerbi")).toContain("not installed");
    expect(directionLock(tableauOnly, "qlik", "powerbi")).toContain("not included in this licence");
  });

  it("locks nothing while the answer is unknown - a failed request is not a missing engine", () => {
    expect(directionLock({ phase: "unknown" }, "qlik", "powerbi")).toBeNull();
    expect(directionLock({ phase: "unknown" }, "microstrategy", "powerbi")).toBeNull();
  });

  it("locks a direction the server does not list at all", () => {
    expect(directionLock(tableauOnly, "powerbi", "tableau")).toContain("no engine");
  });
});
