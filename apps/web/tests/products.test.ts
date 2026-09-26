import { describe, expect, it } from "vitest";

import { PRODUCTS, defaultProducts, productBlocked, toggled } from "@/lib/admin/products";
import type { DirectionsProbe } from "@/lib/migrator/paths";
import type { DirectionStatus } from "@/types/contracts";

function d(source: DirectionStatus["source_platform"], state: DirectionStatus["state"], reason = ""): DirectionStatus {
  return { source_platform: source, target_platform: "powerbi", state, engine: "x", engine_version: "", licence_feature: source, reason };
}

const deployment: DirectionsProbe = {
  phase: "known",
  directions: [
    d("tableau", "available"),
    d("microstrategy", "not_licensed", "MicroStrategy → Power BI is not included in this licence."),
    d("qlik", "available"),
  ],
};

const byId = (id: string) => PRODUCTS.find((p) => p.id === id)!;

describe("products an administrator can grant", () => {
  it("lists the three products", () => {
    expect(PRODUCTS.map((p) => p.id)).toEqual(["tableau", "microstrategy", "qlik"]);
  });

  it("marks a product the licence or installation does not cover", () => {
    expect(productBlocked(deployment, byId("tableau"))).toBeNull();
    expect(productBlocked(deployment, byId("microstrategy"))).toContain("not included in this licence");
    expect(productBlocked(deployment, byId("qlik"))).toBeNull();
  });

  it("gives a new person every product the deployment can run", () => {
    expect(defaultProducts(deployment)).toEqual(["tableau", "qlik"]);
  });

  it("locks nothing while unknown", () => {
    expect(productBlocked({ phase: "unknown" }, byId("qlik"))).toBeNull();
  });

  it("toggles without duplicates, sorted", () => {
    expect(toggled(["tableau"], "qlik", true)).toEqual(["qlik", "tableau"]);
    expect(toggled(["qlik", "tableau"], "qlik", true)).toEqual(["qlik", "tableau"]);
    expect(toggled(["qlik", "tableau"], "tableau", false)).toEqual(["qlik"]);
  });
});
