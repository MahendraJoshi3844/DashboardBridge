import { describe, expect, it } from "vitest";

import { comparisonSource } from "@/lib/comparison/pairs";
import type { Analysis, CanonicalModel, Conversion } from "@/types/contracts";

/**
 * Which of the two models the explorer is allowed to compare (P5.5).
 *
 * There are two `CanonicalModel`s in play and they are not interchangeable.
 * `Analysis.model` is the inventory read off the workbook *before* anything was
 * translated, so every `Column.translation` in it is null by construction.
 * `Conversion.model` is the same model after the pipeline ran, and it is the
 * only one that ever carries a target expression.
 *
 * Comparing the analysed model therefore does not merely lose the right-hand
 * column — it reports `not_returned` for objects that converted perfectly,
 * which is the service accusing itself of a defect it does not have. Picking
 * between them is a claim about the run, so it is decided here and tested,
 * not settled by whichever prop a component happened to be handed.
 */
function modelNamed(name: string): CanonicalModel {
  return { source_platform: "tableau", name };
}

function conversionWith(model: CanonicalModel | null): Conversion {
  return {
    conversion_id: "11111111-1111-1111-1111-111111111111",
    status: "completed",
    model,
  };
}

function analysisWith(model: CanonicalModel | null): Analysis {
  return {
    analysis_id: "22222222-2222-2222-2222-222222222222",
    status: "completed",
    model,
  };
}

describe("comparisonSource", () => {
  it("compares the converted model, the only one that can carry a target", () => {
    const source = comparisonSource(
      conversionWith(modelNamed("converted")),
      analysisWith(modelNamed("analysed")),
    );
    expect(source.kind).toBe("converted");
    expect(source.model?.name).toBe("converted");
  });

  it("falls back to the analysed model and records that it is the fallback", () => {
    // Not a silent substitution: the panel has to be able to say that no target
    // could be present, rather than implying the conversion produced none.
    const source = comparisonSource(
      conversionWith(null),
      analysisWith(modelNamed("analysed")),
    );
    expect(source.kind).toBe("analysed");
    expect(source.model?.name).toBe("analysed");
  });

  it("reports that neither model arrived rather than returning an empty one", () => {
    const source = comparisonSource(conversionWith(null), analysisWith(null));
    expect(source.kind).toBe("absent");
    expect(source.model).toBeNull();
  });
});
