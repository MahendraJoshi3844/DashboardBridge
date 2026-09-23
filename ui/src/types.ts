/** Mirrors t2pbi.events - the payload the Python bridge hands us. */

export type Outcome = "crossed" | "held";

export type Kind =
  "table" | "column" | "calc" | "visual" | "parameter" | "relationship";

export interface ConversionEvent {
  seq: number;
  elapsed_ms: number;
  stage: string;
  kind: Kind;
  name: string;
  outcome: Outcome;
  detail: string;
  ref: string;
  /** The original Tableau expression; empty for anything that is not a calc. */
  source: string;
  /** The emitted DAX; empty when the item was held. */
  result: string;
}

export interface Timeline {
  durationMs: number;
  events: ConversionEvent[];
}

export interface RunResult {
  timeline: Timeline;
  stats: Record<string, number>;
  pbipPath: string;
  reportPath: string;
}

/** Plural nouns for the ledger, in the order a reader cares about them. */
export const KIND_ORDER: Kind[] = [
  "table",
  "column",
  "calc",
  "visual",
  "parameter",
  "relationship",
];

export const KIND_LABEL: Record<Kind, string> = {
  table: "tables",
  column: "columns",
  calc: "calculations",
  visual: "visuals",
  parameter: "parameters",
  relationship: "relationships",
};
