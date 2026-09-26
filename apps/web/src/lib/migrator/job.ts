/**
 * A migration job: run it, or read back one that already ran, as log lines.
 *
 * Every line is something that happened. A step's line is written when its
 * request returns, timed across that request; the engine's own lines come from
 * the recording the converter made while it ran, at the offsets it recorded.
 * The progress figure is steps finished over steps there are, never a timer.
 * 03-ux-spec.md, "Progress is never faked".
 */

import {
  getAnalysis,
  getConversion,
  getRecordedRun,
  getValidation,
  startAnalysis,
  startConversion,
  startValidation,
  toApiError,
  type RecordedRun,
} from "@/lib/api/client";
import type { Analysis, ApiError, Conversion, Project, Validation } from "@/types/contracts";

export type LogLevel = "INFO" | "WARN" | "HELD" | "DONE" | "ERROR";

export interface LogLine {
  /** Wall-clock time the line was observed, or null for a line read back. */
  readonly at: Date | null;
  /** For the engine's own lines: milliseconds into the conversion. */
  readonly offsetMs: number | null;
  readonly level: LogLevel;
  readonly text: string;
}

export const STEPS = ["Uploaded", "Analysed", "Converted", "Engine log read", "Validated"] as const;
export type Step = (typeof STEPS)[number];

export interface JobSnapshot {
  readonly lines: readonly LogLine[];
  readonly done: ReadonlySet<Step>;
  readonly analysis: Analysis | null;
  readonly conversion: Conversion | null;
  readonly validation: Validation | null;
  readonly error: ApiError | null;
  readonly running: boolean;
}

export const emptySnapshot: JobSnapshot = {
  lines: [],
  done: new Set(),
  analysis: null,
  conversion: null,
  validation: null,
  error: null,
  running: false,
};

function line(level: LogLevel, text: string, live: boolean): LogLine {
  return { at: live ? new Date() : null, offsetMs: null, level, text };
}

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

function analysisLines(analysis: Analysis, live: boolean, project?: Project): LogLine[] {
  const inventory = analysis.inventory ?? {};
  if (project?.source_platform === "microstrategy") {
    return [
      line(
        "INFO",
        `MicroStrategy project read: ${plural(inventory.tables ?? 0, "table")}, ${plural(inventory.columns ?? 0, "column")}, ` +
          `${plural(inventory.calculations ?? 0, "metric or calculated column")} translated, ` +
          `${plural(inventory.visuals ?? 0, "visual")} on ${plural(inventory.dashboards ?? 0, "page")}`,
        live,
      ),
    ];
  }
  return [
    line(
      "INFO",
      `Workbook read: ${plural(inventory.tables ?? 0, "table")}, ${plural(inventory.columns ?? 0, "column")}, ` +
        `${plural(inventory.calculations ?? 0, "calculated field")}, ${plural(inventory.visuals ?? 0, "worksheet")}, ` +
        `${plural(inventory.dashboards ?? 0, "dashboard")}`,
      live,
    ),
  ];
}

function engineLines(run: RecordedRun): LogLine[] {
  return run.events.map((event) => {
    const held = event.outcome === "held";
    const what = `${event.stage} ${event.kind} ${event.name}`;
    const text = held
      ? `${what} — held: ${event.detail}`
      : event.result
        ? `${what} → ${event.result}`
        : `${what}${event.detail ? ` (${event.detail})` : ""}`;
    return { at: null, offsetMs: event.elapsed_ms, level: held ? "HELD" : "INFO", text };
  });
}

function conversionLines(conversion: Conversion, live: boolean): LogLine[] {
  const counts = conversion.compatibility;
  const lines: LogLine[] = [];
  if (counts) {
    lines.push(
      line(
        "INFO",
        `Conversion finished: ${counts.converted} of ${counts.total} objects converted, ` +
          `${counts.partial} partial, ${counts.ai_required ?? 0} held for a person, ` +
          `${counts.unsupported} unsupported, ${counts.failed} failed`,
        live,
      ),
    );
  }
  for (const flag of conversion.flags ?? []) {
    if (flag.status === "converted") continue;
    lines.push(line("WARN", `${flag.item}: ${flag.reason}`, live));
  }
  return lines;
}

function validationLines(validation: Validation, live: boolean): LogLine[] {
  const verdict = (validation.verdict ?? "unverified").replace("_", " ");
  const score =
    typeof validation.score === "number" ? ` — ${Math.round(validation.score * 100)}% of applicable checks passed` : "";
  const failed = (validation.rules ?? []).filter((rule) => rule.status === "FAIL");
  return [
    line(verdict === "failed" ? "ERROR" : "INFO", `Validation: ${verdict}${score}`, live),
    ...failed.map((rule) => line("WARN", `Check ${rule.rule_id} failed: ${rule.note}`, live)),
  ];
}

function isMissing(cause: unknown): boolean {
  const error = toApiError(cause);
  return error.category === "NOT_FOUND" || error.message.includes("not been");
}

/**
 * Read back a job that has already run. Lines carry no wall-clock time, since
 * the only honest timestamps are the ones observed when the step happened.
 */
export async function readJob(project: Project): Promise<JobSnapshot> {
  const done = new Set<Step>(["Uploaded"]);
  const lines: LogLine[] = [
    line("INFO", `Migration for ${project.source_platform === "microstrategy" ? "MicroStrategy project" : "workbook"}: ${project.name}`, false),
  ];
  let analysis: Analysis | null = null;
  let conversion: Conversion | null = null;
  let validation: Validation | null = null;

  try {
    analysis = await getAnalysis(project.project_id);
    done.add("Analysed");
    lines.push(...analysisLines(analysis, false, project));
  } catch (cause) {
    if (!isMissing(cause)) throw cause;
  }
  try {
    conversion = await getConversion(project.project_id);
    done.add("Converted");
    const run = await getRecordedRun(project.project_id);
    done.add("Engine log read");
    lines.push(...engineLines(run), ...conversionLines(conversion, false));
  } catch (cause) {
    if (!isMissing(cause)) throw cause;
  }
  try {
    validation = await getValidation(project.project_id);
    done.add("Validated");
    lines.push(...validationLines(validation, false));
  } catch (cause) {
    if (!isMissing(cause)) throw cause;
  }
  if (done.size === STEPS.length) {
    lines.push(line("DONE", "Migration complete. The Power BI project is ready in the workspace.", false));
  }
  return { lines, done, analysis, conversion, validation, error: null, running: false };
}

/**
 * Run whatever is left of the job, reporting after every step.
 *
 * Resumes rather than restarts: a step already done is read, not repeated, so
 * reopening a job that stopped half way carries on from where it stopped.
 */
export async function runJob(
  project: Project,
  report: (snapshot: JobSnapshot) => void,
  signal?: AbortSignal,
): Promise<void> {
  let snapshot: JobSnapshot = { ...(await readJob(project)), running: true };
  const push = (patch: Partial<JobSnapshot>, ...more: LogLine[]) => {
    snapshot = { ...snapshot, ...patch, lines: [...snapshot.lines, ...more] };
    report(snapshot);
  };
  const mark = (step: Step) => new Set([...snapshot.done, step]);
  push({}, line("INFO", "Starting migration", true));

  try {
    if (!snapshot.done.has("Analysed")) {
      push(
        {},
        line(
          "INFO",
          project.source_platform === "microstrategy"
            ? "Step 1: Reading the MicroStrategy export — attributes, facts, metrics, dossiers, reports"
            : "Step 1: Reading the workbook — tables, fields, calculations, worksheets",
          true,
        ),
      );
      const started = performance.now();
      await startAnalysis(project.project_id, { signal });
      const analysis = await getAnalysis(project.project_id, { signal });
      push(
        { analysis, done: mark("Analysed") },
        ...analysisLines(analysis, true, project),
        line("INFO", `Analysis took ${Math.round(performance.now() - started)} ms`, true),
      );
    }

    if (!snapshot.done.has("Converted")) {
      push({}, line("INFO", "Step 2: Converting — mapping the model, translating calculations to DAX, writing TMDL and PBIR", true));
      const started = performance.now();
      await startConversion(project.project_id, { ai_enabled: false }, { signal });
      const conversion = await getConversion(project.project_id, { signal });
      push(
        { conversion, done: mark("Converted") },
        line("INFO", `Conversion request returned in ${Math.round(performance.now() - started)} ms`, true),
      );
      const run = await getRecordedRun(project.project_id, { signal });
      push(
        { done: mark("Engine log read") },
        line("INFO", `Engine recording: ${plural(run.events.length, "object")} handled in ${run.durationMs} ms`, true),
        ...engineLines(run),
        ...conversionLines(conversion, true),
      );
    }

    if (!snapshot.done.has("Validated")) {
      push({}, line("INFO", "Step 3: Validating — structural, semantic and visual checks against the produced project", true));
      await startValidation(project.project_id, { signal });
      const validation = await getValidation(project.project_id, { signal });
      push({ validation, done: mark("Validated") }, ...validationLines(validation, true));
    }

    push(
      { running: false },
      line("DONE", "Migration complete. The Power BI project is ready in the workspace.", true),
    );
  } catch (cause) {
    const error = toApiError(cause);
    push({ error, running: false }, line("ERROR", error.message, true));
  }
}

export function formatLine(entry: LogLine): string {
  const time = entry.at
    ? entry.at.toLocaleTimeString()
    : entry.offsetMs !== null
      ? `+${entry.offsetMs} ms`
      : "recorded";
  return `${time} [${entry.level}] ${entry.text}`;
}
