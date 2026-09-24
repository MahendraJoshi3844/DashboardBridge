/**
 * The Run menu's jobs, as sequences of assistant steps.
 *
 * A job is run one step per request, so "Task 2/4" on the screen means the
 * second request came back. Deterministic steps come first in every job; a
 * model is asked only by `draft_dax`, `summarize` and `chat`, and nothing any
 * step returns is applied until a person applies it.
 */

import type { AssistantStepName } from "@/lib/api/client";
import type { AssistantFinding, AssistantProposal } from "@/types/contracts";

/** Which objects a step works on: the current selection, or everything. */
export type Scope = "selection" | "all";

export interface JobStep {
  readonly step: AssistantStepName;
  readonly scope: Scope;
}

export interface RunJob {
  readonly id: string;
  readonly label: string;
  readonly steps: readonly JobStep[];
  /** True when a step would ask a model. The menu says so. */
  readonly usesAi: boolean;
}

const all = (step: AssistantStepName): JobStep => ({ step, scope: "all" });
const selected = (step: AssistantStepName): JobStep => ({ step, scope: "selection" });

export const RUN_JOBS: readonly RunJob[] = [
  {
    id: "optimize",
    label: "Optimize Model",
    steps: [all("inventory"), all("model_health"), all("check_references"), all("summarize")],
    usesAi: true,
  },
  { id: "validate_calculations", label: "Validate Calculations", steps: [all("check_references")], usesAi: false },
  {
    id: "fix_dax",
    label: "Validate & Fix DAX",
    steps: [selected("check_references"), selected("draft_dax")],
    usesAi: true,
  },
  {
    id: "fix_mquery",
    label: "Validate & Fix M-Query",
    steps: [selected("check_mquery"), selected("format_mquery")],
    usesAi: false,
  },
  {
    id: "health",
    label: "Full Health Check",
    steps: [all("inventory"), all("check_references"), all("check_mquery"), all("model_health"), all("summarize")],
    usesAi: true,
  },
  { id: "batch_dax", label: "Batch Fix DAX", steps: [all("check_references"), all("draft_dax")], usesAi: true },
  { id: "batch_mquery", label: "Batch Fix M-Query", steps: [all("check_mquery"), all("format_mquery")], usesAi: false },
  {
    id: "batch_all",
    label: "Batch Fix All",
    steps: [all("check_references"), all("check_mquery"), all("draft_dax"), all("format_mquery")],
    usesAi: true,
  },
];

export const STEP_TITLES: Record<AssistantStepName, string> = {
  inventory: "Model Inventory",
  check_references: "Validate Calculations",
  check_mquery: "Validate M-Query",
  model_health: "Model Health",
  draft_dax: "Draft DAX for held calculations",
  format_mquery: "Fix M-Query layout",
  summarize: "Generate Summary",
  chat: "Answer",
};

export type Speaker = "you" | "system" | "assistant";

export interface TranscriptEntry {
  readonly id: number;
  readonly speaker: Speaker;
  readonly at: Date;
  readonly text: string;
  readonly model?: string;
  readonly findings?: readonly AssistantFinding[];
  readonly proposals?: readonly AssistantProposal[];
  readonly tone?: "info" | "done" | "error";
}

/**
 * The objects a selection-scoped step works on.
 *
 * A measure or held calculation is named `Table.Name`; a Power Query source by
 * its table. With nothing selected the step works on everything, and the job's
 * opening line says so, rather than silently running on nothing.
 */
export function itemsFor(
  scope: Scope,
  step: AssistantStepName,
  selection: { readonly kind: string; readonly table?: string; readonly name?: string } | null,
): string[] {
  if (scope === "all" || selection === null || !selection.table) return [];
  if (step === "check_mquery" || step === "format_mquery") {
    return selection.kind === "partition" ? [selection.table] : [];
  }
  if (selection.kind === "measure" || selection.kind === "held") {
    return [`${selection.table}.${selection.name ?? ""}`];
  }
  return [];
}

export function severityRank(finding: AssistantFinding): number {
  return finding.severity === "error" ? 0 : finding.severity === "warning" ? 1 : 2;
}
