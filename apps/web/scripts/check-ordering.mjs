/**
 * The flag-ordering rule, checked rather than asserted.
 *
 * 03-ux-spec.md, "Ordering by actionability", names a specific failure: forty
 * field-well notices buried six actionable calculations. That is a regression
 * with a shape, so it can be tested — and it is the one behaviour in the
 * dashboard that a person cannot verify by looking at a screenshot of a short
 * list.
 *
 * No test framework: `scripts/check-contrast.mjs` is the pattern this follows,
 * and the product ships air-gapped, where every dependency is a thing that has
 * to be vendored and audited. Node runs the TypeScript module directly — the
 * only import in it is `import type`, which type stripping removes, so nothing
 * has to resolve the `@/` alias at runtime.
 *
 *   node scripts/check-ordering.mjs       exits 1 on the first failure
 */

import { byActionability, needsAPerson, actionabilityRank } from "../src/lib/flags/ordering.ts";

let failures = 0;

/** @param {string} name @param {boolean} ok @param {string} [detail] */
function check(name, ok, detail = "") {
  if (!ok) failures += 1;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`);
}

/** A field well needing a click: found first, and much more numerous. */
const fieldWell = (n) => ({
  item: `Sheet ${n}: [ds].[none:Measure Names:nk]`,
  stage: "map",
  method: "manual",
  status: "unsupported",
  severity: "manual",
  reason: "no column equivalent; add this field well by hand.",
  ref: `Sheet ${n}`,
});

/** A calculation needing hand-written DAX: found last, and the real work. */
const calculation = (n) => ({
  item: `Orders.Calc ${n}`,
  stage: "translate",
  method: "manual",
  status: "ai_required",
  severity: "manual",
  reason: "The intended aggregation is not stated in the formula.",
  ref: `Orders.Calc ${n}`,
});

const tooltip = (n) => ({
  item: `Sheet ${n}: tooltip`,
  stage: "generate",
  method: "rule",
  status: "partial",
  severity: "info",
  reason: "Inline formatting has no PBIR equivalent.",
  ref: `Sheet ${n}`,
});

const engineFailure = {
  item: "Orders.Sales",
  stage: "extract",
  method: "deterministic",
  status: "failed",
  severity: "manual",
  reason: "The extract's schema could not be read.",
  ref: "Orders",
};

/* --- the spec's own scenario, in the order an engine finds it ----------- */
const wells = Array.from({ length: 40 }, (_, i) => fieldWell(i));
const calcs = Array.from({ length: 6 }, (_, i) => calculation(i));
const timelineOrder = [...wells, ...calcs];

{
  const ordered = byActionability(timelineOrder);
  const firstSix = ordered.slice(0, 6);
  check(
    "six actionable calculations are not buried under forty field wells",
    firstSix.every((flag) => flag.stage === "translate"),
    `first six stages: ${firstSix.map((f) => f.stage).join(", ")}`,
  );
}

{
  const ordered = byActionability([...calcs, tooltip(1), ...wells]);
  const positions = {
    translate: ordered.findIndex((f) => f.stage === "translate"),
    map: ordered.findIndex((f) => f.stage === "map"),
    generate: ordered.findIndex((f) => f.stage === "generate"),
  };
  check(
    "hand-written DAX outranks a field well, which outranks a tooltip",
    positions.translate < positions.map && positions.map < positions.generate,
    JSON.stringify(positions),
  );
}

{
  const ordered = byActionability([...wells, ...calcs, engineFailure]);
  check(
    "an engine failure is the first row a person sees",
    ordered[0].status === "failed",
    `first row: ${ordered[0].item} (${ordered[0].status})`,
  );
}

{
  const ordered = byActionability([tooltip(2), tooltip(1), ...calcs]);
  const informational = ordered.slice(-2);
  check(
    "informational items sink below everything needing a person",
    informational.every((flag) => flag.severity === "info"),
  );
}

{
  const input = [...wells, ...calcs, tooltip(1), engineFailure];
  const a = byActionability(input).map((f) => f.item);
  const b = byActionability([...input].reverse()).map((f) => f.item);
  check(
    "the order is total: the same set sorts identically whatever order it arrives in",
    JSON.stringify(a) === JSON.stringify(b),
  );
}

{
  const input = [...wells, ...calcs];
  const copy = JSON.stringify(input);
  byActionability(input);
  check("the input array is never mutated", JSON.stringify(input) === copy);
}

{
  check(
    "needsAPerson counts every item that has to be picked up",
    [...wells, ...calcs, engineFailure].every(needsAPerson) &&
      !needsAPerson(tooltip(1)),
  );
}

{
  check(
    "rank is a number the caller can group on",
    actionabilityRank(calculation(0)) < actionabilityRank(fieldWell(0)),
  );
}

console.log(
  `\n${failures === 0 ? "All ordering checks pass." : `${failures} FAILING.`}`,
);
process.exit(failures === 0 ? 0 : 1);
