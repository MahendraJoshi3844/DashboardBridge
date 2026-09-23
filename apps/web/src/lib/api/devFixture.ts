/**
 * A sample `Analysis`, for developing the screens without a running gateway.
 *
 * ── THIS NEVER SHIPS ─────────────────────────────────────────────────────
 * The only caller loads this module through a dynamic `import()` inside an
 * `if (process.env.NODE_ENV !== "production")` branch. Next replaces that
 * expression at build time, so the branch — and this chunk with it — is
 * eliminated from a production bundle. `npm run build` output is the proof:
 * this file's contents do not appear in `.next/static`.
 * ─────────────────────────────────────────────────────────────────────────
 *
 * Two rules kept it honest while it existed:
 *
 * 1. **The screen says it is sample data, loudly**, so a screenshot of a
 *    fixture can never be mistaken for a measurement. §63 does not have an
 *    exception for development.
 * 2. **The shape is the contract**, imported from the generated types. A
 *    fixture written to match the component rather than the wire is the same
 *    mistake AGENTS.md records about `tests/fixtures/sample.twb`, where a
 *    completely broken visual layer passed 32 tests.
 *
 * The numbers below are the worked example in `05-api-spec.md`; the flag
 * reasons are the strings `engines/adapters/tableau.py` actually emits. The
 * proportions are the ones that matter for the ordering rule: a handful of
 * calculations that need a person, buried under dozens of field-well notices.
 */

import type { RunStage } from "./run";
import type {
  Analysis,
  ApiError,
  CanonicalModel,
  Column,
  Conversion,
  ConversionFlag,
  Validation,
} from "@/types/contracts";

/** The formula string the gateway returns, copied verbatim. */
const FORMULA =
  "score = Σ(count × weight) / (total objects × 5); " +
  "weights: calculation 5, visual 3, parameter 2, relationship 2, " +
  "dashboard 2, table 1, column 0.5. " +
  "1.0 would mean the workbook is nothing but calculated fields.";

const HELD_CALCULATIONS: readonly string[] = [
  "Orders.Profit Ratio",
  "Orders.Sales per Customer",
  "Orders.Running Total of Sales",
  "Orders.Rank of Sub-Category",
  "Orders.Days to Ship (Actual)",
  "People.Regional Attainment",
];

const UNSUPPORTED_SHELVES: readonly string[] = [
  "Sales by Sub-Category: [Orders].[none:Measure Names:nk]",
  "Profit Map: [Orders].[usr:Calculation_5309:qk]",
  "Forecast: [Orders].[tyr:Order Date:ok]",
];

const FIELD_WELL_ITEMS: readonly string[] = [
  "Sales by Segment",
  "Sales by Region",
  "Profit by Category",
  "Profit Ratio by Month",
  "Orders by Ship Mode",
  "Customer Scatter",
  "Returns by Region",
  "Sales Forecast",
  "Discount vs Profit",
  "Top Customers",
  "Category Treemap",
  "Sales KPI",
  "Monthly Trend",
  "Shipping Delay",
  "Regional Table",
  "Segment Donut",
  "Sub-Category Bars",
  "Order Detail",
  "Profit Waterfall",
  "State Choropleth",
];

/**
 * Flags in the order an engine would find them: the field wells first, because
 * worksheets are walked before calculations are classified. The dashboard must
 * re-order these, and if it ever stops doing so this fixture is what makes the
 * regression obvious on screen.
 */
const FLAGS: readonly ConversionFlag[] = [
  ...FIELD_WELL_ITEMS.map(
    (sheet): ConversionFlag => ({
      item: `${sheet}: tooltip`,
      stage: "generate",
      method: "rule",
      status: "partial",
      severity: "info",
      reason:
        "The tooltip is carried across as text; Tableau's inline formatting has no PBIR equivalent.",
      ref: sheet,
    }),
  ),
  ...UNSUPPORTED_SHELVES.map(
    (raw): ConversionFlag => ({
      item: raw,
      stage: "map",
      method: "manual",
      status: "unsupported",
      severity: "manual",
      reason:
        `${raw.split(": ")[1] ?? raw} is a Tableau construct with no column ` +
        "equivalent; add this field well by hand.",
      ref: raw.split(": ")[0] ?? raw,
    }),
  ),
  ...HELD_CALCULATIONS.map(
    (ref): ConversionFlag => ({
      item: ref,
      stage: "translate",
      method: "manual",
      status: "ai_required",
      severity: "manual",
      reason:
        "The intended aggregation is not stated in the formula, so the grain could not be determined.",
      ref,
    }),
  ),
  {
    item: "Orders.Sales (extract)",
    stage: "extract",
    method: "deterministic",
    status: "failed",
    severity: "manual",
    reason:
      "The packaged extract's schema could not be read, so its columns are not in the model.",
    ref: "Orders",
  },
];

/**
 * A model with real expression text, so the comparison explorer can be looked
 * at.
 *
 * The `id` of each column is the deterministic name path the adapter produces
 * (`"<table>.<display name>"`), which is the key a `ConversionFlag` joins on —
 * a fixture with prettier ids would test the component against a shape the wire
 * never sends, which is the mistake AGENTS.md records about `sample.twb`.
 *
 * One column carries a `translation` and the rest do not. That is deliberate:
 * the pipeline populates `translation` for nothing today, and the explorer has
 * to be legible in both cases — the crossed one and the far more common one
 * where the API returned no target expression at all.
 */
const CALCULATED: readonly Column[] = [
  {
    id: "Orders.Profit Ratio",
    name: "Profit Ratio",
    caption: "Profit Ratio",
    datatype: "decimal",
    role: "measure",
    grain: null,
    expression: {
      source_language: "tableau_calc",
      source_text: "SUM([Profit])/SUM([Sales])",
      references: [],
    },
    translation: null,
  },
  // The one column that crossed. It is deliberately *not* one of the held
  // calculations: a column carrying both a translation and a refusal would be
  // two contradictory claims about one object, and a fixture that contains one
  // teaches the screen to render an impossibility.
  {
    id: "Orders.Discount Band",
    name: "Discount Band",
    caption: "Discount Band",
    datatype: "string",
    role: "dimension",
    grain: "row",
    expression: {
      source_language: "tableau_calc",
      source_text: 'IF [Discount] > 0.2 THEN "High" ELSE "Low" END',
      references: [],
    },
    translation: {
      target_language: "dax",
      target_text: "IF('Orders'[Discount] > 0.2, \"High\", \"Low\")",
      method: "rule",
      rule_ids: ["TABLEAU_IF_TO_DAX_IF"],
      proposal_id: null,
    },
  },
  {
    id: "Orders.Sales per Customer",
    name: "Sales per Customer",
    caption: "Sales per Customer",
    datatype: "decimal",
    role: "measure",
    grain: null,
    expression: {
      source_language: "tableau_calc",
      source_text: "[Sales] / COUNTD([Customer ID])",
      references: [],
    },
    translation: null,
  },
  {
    id: "Orders.Running Total of Sales",
    name: "Running Total of Sales",
    caption: "Running Total of Sales",
    datatype: "decimal",
    role: "measure",
    grain: null,
    expression: {
      source_language: "tableau_calc",
      source_text: "RUNNING_SUM(SUM([Sales]))",
      references: [],
    },
    translation: null,
  },
  {
    id: "Orders.Rank of Sub-Category",
    name: "Rank of Sub-Category",
    caption: "Rank of Sub-Category",
    datatype: "integer",
    role: "measure",
    grain: null,
    expression: {
      source_language: "tableau_calc",
      source_text: "RANK(SUM([Sales]), 'desc')",
      references: [],
    },
    translation: null,
  },
  {
    id: "Orders.Days to Ship (Actual)",
    name: "Days to Ship (Actual)",
    caption: "Days to Ship (Actual)",
    datatype: "integer",
    role: "dimension",
    grain: "row",
    expression: {
      source_language: "tableau_calc",
      source_text: "DATEDIFF('day', [Order Date], [Ship Date])",
      references: [],
    },
    translation: null,
  },
  {
    id: "People.Regional Attainment",
    name: "Regional Attainment",
    caption: "Regional Attainment",
    datatype: "decimal",
    role: "measure",
    grain: null,
    expression: {
      source_language: "tableau_calc",
      source_text:
        "{ FIXED [Region] : SUM([Sales]) } / { FIXED [Region] : SUM([Quota]) }",
      references: [],
    },
    translation: null,
  },
];

export const DEV_MODEL: CanonicalModel = {
  source_platform: "tableau",
  source_version: "2021.4",
  name: "Superstore (sample fixture)",
  datasources: [
    {
      id: "federated.0",
      name: "Superstore",
      connection: "excel-direct",
      is_extract: false,
      source_id: "federated.0",
      tables: [
        {
          id: "Orders",
          name: "Orders",
          columns: CALCULATED.filter((column) =>
            column.id.startsWith("Orders."),
          ),
        },
        {
          id: "People",
          name: "People",
          columns: CALCULATED.filter((column) =>
            column.id.startsWith("People."),
          ),
        },
      ],
    },
  ],
  relationships: [],
  parameters: [],
  visuals: [],
  dashboards: [],
  flags: [],
};

export const DEV_ANALYSIS: Analysis = {
  analysis_id: "00000000-0000-4000-8000-000000000000",
  status: "completed",
  model: DEV_MODEL,
  inventory: {
    datasources: 3,
    tables: 5,
    columns: 54,
    calculations: 21,
    visuals: 21,
    parameters: 6,
    relationships: 2,
    dashboards: 6,
  },
  complexity: { score: 0.72, band: "high", formula: FORMULA },
  compatibility: {
    converted: 58,
    partial: 20,
    ai_required: 6,
    unsupported: 3,
    failed: 1,
    total: 88,
  },
  flags: [...FLAGS],
};

export const DEV_FILENAME = "Superstore (sample fixture).twbx";

/**
 * A finished run's timeline. The durations are the ones a local gateway
 * actually produces for a 1.1 MB workbook — single-digit milliseconds for the
 * database writes, tens of milliseconds for the parse. They exist so the
 * preview shows the same shape a real run does; they are still sample data, and
 * the screen says so.
 */
export const DEV_STAGES: readonly RunStage[] = [
  { id: "accepted", phase: "done", elapsedMs: 0, note: DEV_FILENAME },
  { id: "project", phase: "done", elapsedMs: 14.2, note: "3f2b1c9a-…" },
  { id: "upload", phase: "done", elapsedMs: 96.4, note: "sha256 9f2c1ab77e04…" },
  { id: "analysis", phase: "done", elapsedMs: 31.7, note: "b81e77d0-…" },
  { id: "results", phase: "done", elapsedMs: 8.9, note: "88 objects" },
];

/** The same run, caught mid-flight. */
export const DEV_STAGES_RUNNING: readonly RunStage[] = [
  { id: "accepted", phase: "done", elapsedMs: 0, note: DEV_FILENAME },
  { id: "project", phase: "done", elapsedMs: 14.2, note: "3f2b1c9a-…" },
  { id: "upload", phase: "active", elapsedMs: null, note: null },
  { id: "analysis", phase: "pending", elapsedMs: null, note: null },
  { id: "results", phase: "pending", elapsedMs: null, note: null },
];

/** A refusal in the contract shape, for looking at the error screen. */
export const DEV_ERROR: ApiError = {
  category: "PARSER_ERROR",
  message:
    "We could not read that workbook. It may be corrupted, or it may use a " +
    "feature this version does not understand yet.",
  detail:
    "XMLSyntaxError: Opening and ending tag mismatch: worksheet line 4412, column 18",
  request_id: "9c1d4f7e-2a55-4b90-9a41-0f7d2c6b8e31",
  project_id: "3f2b1c9a-77d0-4e2b-9c31-5a8e0b4f6d12",
};

/**
 * A finished conversion, in the contract shape.
 *
 * The counts are the analysis's expectations carried through unchanged, because
 * a deterministic run converts exactly what the parse said it would — and the
 * flags are the same list, because a refusal at parse time is still a refusal
 * afterwards. Nothing here is nudged upward to make the results screen read
 * better; the whole point of that screen is that it cannot be.
 */
export const DEV_CONVERSION: Conversion = {
  conversion_id: "b81e77d0-3c44-4f2a-9d15-6b0c2e4a8f31",
  status: "completed",
  compatibility: {
    converted: 58,
    partial: 20,
    ai_required: 6,
    unsupported: 3,
    failed: 1,
    total: 88,
  },
  artifact_id: "7d2f9a44-1c8e-4b60-b3a1-90e5c7d21f08",
  flags: [...FLAGS],
};

/** The conversion's own timeline: two observable milestones, both measured. */
export const DEV_CONVERSION_STAGES: readonly RunStage[] = [
  {
    id: "requested",
    phase: "done",
    elapsedMs: 612.4,
    note: "b81e77d0-3c44-4f2a-9d15-6b0c2e4a8f31",
  },
  {
    id: "engine",
    phase: "done",
    elapsedMs: 9.6,
    note: "88 objects · 30 flags · settled after 1 read",
  },
  {
    id: "checks",
    phase: "done",
    elapsedMs: 41.2,
    note: "59 of 65 checks passed",
  },
];

/**
 * What the checks found, in the contract shape.
 *
 * Deliberately not a clean sweep. The rule ids, the statuses and the wording of
 * the notes are the engine's own, taken from a real run rather than composed
 * here, because a fixture that passes everything is a fixture that never shows
 * the designer what a failure looks like - and the failing rows are the ones
 * this screen exists to present well.
 */
export const DEV_VALIDATION: Validation = {
  validation_id: "5a1c8e30-9b2f-4d76-8e04-1f3a7c9b2d55",
  status: "completed",
  verdict: "partially_verified",
  score: 0.8235,
  formula:
    "score = (0.4 × structural 15/17 + 0.4 × semantic 24/27 + 0.2 × visual 20/21) / 1.0 = 0.8235, " +
    "where each term is that category's passed/applicable checks. " +
    "Categories with no applicable check are excluded from both sides.",
  categories: {
    structural: { score: 0.8824, checks: 17, passed: 15 },
    semantic: { score: 0.8889, checks: 27, passed: 24 },
    visual: { score: 0.9524, checks: 21, passed: 20 },
  },
  numerical: {
    measured: false,
    reason:
      "Requires executing both dashboards against live data; not available offline.",
  },
  rules: [
    {
      rule_id: "WORKSHEET_COUNT_MATCH",
      status: "WARNING",
      note:
        "worksheets: source 21, target 20. 1 did not cross and every one is " +
        "reported as a conversion flag: Sales by Region (map).",
    },
    {
      rule_id: "CALCULATION_SEMANTIC_MATCH",
      status: "WARNING",
      note:
        "Profit Ratio: division is not equivalent - Tableau yields null when " +
        "the divisor is zero, DAX yields Infinity. DIVIDE() is the usual repair.",
    },
    {
      rule_id: "PARAMETER_MAPPING",
      status: "WARNING",
      note: "Date Granularity: no target table carries this parameter's values.",
    },
    {
      rule_id: "SEMANTIC_MODEL_TABLE_PARTITIONS",
      status: "PASS",
      note: "11 of 11 tables carry a partition.",
    },
    {
      rule_id: "EXPRESSION_REFERENCES_RESOLVE",
      status: "PASS",
      note: "43 references across 27 expressions, all resolving.",
    },
    {
      rule_id: "REFUSAL_INTEGRITY",
      status: "PASS",
      note: "9 objects did not cross; all 9 are reported as conversion flags.",
    },
    {
      rule_id: "OUTPUT_DETERMINISTIC",
      status: "PASS",
      note: "Converted twice; 34 of 34 files identical.",
    },
  ],
};

/** The same conversion, caught mid-flight. */
export const DEV_CONVERSION_STAGES_RUNNING: readonly RunStage[] = [
  { id: "requested", phase: "active", elapsedMs: null, note: null },
  { id: "engine", phase: "pending", elapsedMs: null, note: null },
  { id: "checks", phase: "pending", elapsedMs: null, note: null },
];
