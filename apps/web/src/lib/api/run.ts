/**
 * The upload → analyse sequence, as a series of real, observed milestones.
 *
 * AGENTS.md rule 8 keeps flow control out of React components: this module
 * calls the client, records when each call actually started and finished, and
 * reports each transition to its caller. The component renders what it is told
 * and dispatches to the machine; it does not know the order of the calls.
 *
 * **Nothing here is synthesised.** Every stage below flips because a request
 * returned, and every duration is `performance.now()` measured across that
 * request. There is no timer that advances a stage, no interpolation, and no
 * percentage — 03-ux-spec.md, "Progress is never faked". Analysis of a real
 * workbook takes about 25 ms, so most of these resolve almost instantly; that
 * is a fact to display, not a problem to disguise with a delay.
 *
 * The `project` / `artifact` / `job` options are what makes retry a **resume**
 * rather than a restart (03-ux-spec.md: "`ERROR` retains the state it came
 * from"). A run that failed at the analysis step does not re-upload the
 * workbook; it carries on from the artifact it already has.
 */

import type {
  Analysis,
  ApiError,
  Artifact,
  Conversion,
  ConversionRequest,
  Job,
  Platform,
  Project,
  Validation,
} from "@/types/contracts";

import {
  createProject,
  getAnalysis,
  getConversion,
  getValidation,
  startAnalysis,
  startConversion,
  startValidation,
  toApiError,
  uploadArtifact,
} from "./client";

/** The milestones a person can actually see happen, in the order they happen. */
export const RUN_STAGE_IDS = [
  "accepted",
  "project",
  "upload",
  "analysis",
  "results",
] as const;

/**
 * The conversion's own milestones.
 *
 * There are two of them because two things are actually observable: the request
 * was accepted, and the job reached a terminal state and reported what it did.
 * A longer list would read better and would be fiction — 03-ux-spec.md,
 * "Progress is never faked".
 *
 * There is deliberately no `translate` / `generate` / `emit` row here. The
 * engine does record those, and `GET /projects/{id}/events` now replays that
 * recording — but it replays a *finished* run, because the gateway converts
 * inline and there is nothing to subscribe to while the request is open.
 * Driving these rows from a replay would mean animating a progression after it
 * had already happened, which is the same fiction with extra steps. The
 * recording is shown where it is true: on the results screen, as what
 * happened.
 */
export const CONVERSION_STAGE_IDS = ["requested", "engine", "checks"] as const;

export type RunStageId =
  | (typeof RUN_STAGE_IDS)[number]
  | (typeof CONVERSION_STAGE_IDS)[number];

/** Named for what the user did or is waiting on, never for the endpoint. */
export const RUN_STAGE_LABELS: Record<RunStageId, string> = {
  accepted: "Workbook checked",
  project: "Migration opened",
  upload: "Workbook sent and fingerprinted",
  analysis: "Workbook read",
  results: "Inventory returned",
  requested: "Conversion accepted",
  engine: "Engine finished and reported",
  checks: "Output checked against the workbook",
};

export type RunStagePhase = "pending" | "active" | "done";

export interface RunStage {
  readonly id: RunStageId;
  readonly phase: RunStagePhase;
  /** Milliseconds this stage actually took. Null until it has finished. */
  readonly elapsedMs: number | null;
  /** A real detail measured at this stage — a name, a digest, a count. */
  readonly note: string | null;
}

function pending(ids: readonly RunStageId[]): readonly RunStage[] {
  return ids.map((id) => ({
    id,
    phase: "pending" as RunStagePhase,
    elapsedMs: null,
    note: null,
  }));
}

export const initialStages: readonly RunStage[] = pending(RUN_STAGE_IDS);

export const initialConversionStages: readonly RunStage[] =
  pending(CONVERSION_STAGE_IDS);

export function withStage(
  stages: readonly RunStage[],
  id: RunStageId,
  patch: Partial<Omit<RunStage, "id">>,
): RunStage[] {
  return stages.map((stage) => (stage.id === id ? { ...stage, ...patch } : stage));
}

/** A milestone starting or finishing. Shared by both sequences below. */
export type StageEvent =
  | { readonly type: "STAGE_STARTED"; readonly id: RunStageId }
  | {
      readonly type: "STAGE_FINISHED";
      readonly id: RunStageId;
      readonly elapsedMs: number;
      readonly note: string | null;
    };

/** What the caller is told, as it happens. Each one is an observed event. */
export type RunEvent =
  | StageEvent
  | { readonly type: "PROJECT_OPENED"; readonly project: Project }
  | {
      readonly type: "ANALYSIS_STARTED";
      readonly artifact: Artifact;
      readonly job: Job;
    }
  | { readonly type: "ANALYSIS_READY"; readonly analysis: Analysis }
  | { readonly type: "FAILED"; readonly error: ApiError };

export interface RunOptions {
  readonly file: File;
  readonly source: Platform;
  readonly target: Platform;
  /** Already created — skip that step and keep the artifact where it belongs. */
  readonly project?: Project | null;
  /** Already uploaded — skip the upload. */
  readonly artifact?: Artifact | null;
  /** Already started — skip the request that starts it. */
  readonly job?: Job | null;
  readonly signal?: AbortSignal;
  readonly emit: (event: RunEvent) => void;
}

function digestPrefix(sha256: string): string {
  return sha256.slice(0, 12);
}

function countObjects(analysis: Analysis): string | null {
  const inventory = analysis.inventory;
  if (inventory === undefined) return null;
  const counted =
    (inventory.columns ?? 0) +
    (inventory.visuals ?? 0) +
    (inventory.parameters ?? 0) +
    (inventory.relationships ?? 0) +
    (inventory.tables ?? 0);
  return `${counted} objects`;
}

/**
 * Run the sequence. Resolves when the analysis has been read, or after a
 * `FAILED` event has been emitted — the caller never has to catch as well as
 * listen.
 */
export async function runAnalysis(options: RunOptions): Promise<void> {
  const { file, source, target, signal, emit } = options;
  const request = signal ? { signal } : {};

  async function stage<T>(
    id: RunStageId,
    work: () => Promise<T>,
    note: (value: T) => string | null,
  ): Promise<T> {
    emit({ type: "STAGE_STARTED", id });
    const startedAt = performance.now();
    const value = await work();
    emit({
      type: "STAGE_FINISHED",
      id,
      elapsedMs: performance.now() - startedAt,
      note: note(value),
    });
    return value;
  }

  try {
    // The pre-check already ran in the dropzone; this stage records what it
    // established so the timeline opens with a real, user-visible fact.
    emit({ type: "STAGE_STARTED", id: "accepted" });
    emit({
      type: "STAGE_FINISHED",
      id: "accepted",
      elapsedMs: 0,
      note: file.name,
    });

    // `const` after the branch: TypeScript's narrowing of a `let` does not
    // survive into the closures below, and a non-null assertion would be a
    // claim the compiler cannot check.
    let opened = options.project ?? null;
    if (opened === null) {
      opened = await stage(
        "project",
        () =>
          createProject(
            {
              source_platform: source,
              target_platform: target,
              name: file.name,
            },
            request,
          ),
        (value) => value.project_id,
      );
      emit({ type: "PROJECT_OPENED", project: opened });
    }
    const project: Project = opened;

    let artifact = options.artifact ?? null;
    let job = options.job ?? null;

    if (artifact === null || job === null) {
      if (artifact === null) {
        artifact = await stage(
          "upload",
          () => uploadArtifact(project.project_id, file, request),
          (value) => `sha256 ${digestPrefix(value.sha256)}…`,
        );
      }
      job = await stage(
        "analysis",
        () => startAnalysis(project.project_id, request),
        (value) => value.job_id,
      );
      // Announced only when this run is what started it. Re-announcing a job
      // the machine already knows about would be an illegal transition, which
      // the machine is right to refuse.
      emit({ type: "ANALYSIS_STARTED", artifact, job });
    }

    const analysis = await stage(
      "results",
      () => getAnalysis(project.project_id, request),
      countObjects,
    );
    emit({ type: "ANALYSIS_READY", analysis });
  } catch (cause) {
    if (signal?.aborted) return;
    emit({ type: "FAILED", error: toApiError(cause) });
  }
}

/* -------------------------------------------------------------------------
 * Conversion
 * ---------------------------------------------------------------------- */

/** What the conversion sequence reports, as it happens. */
export type ConversionEvent =
  | StageEvent
  | { readonly type: "CONVERSION_ACCEPTED"; readonly job: Job }
  | { readonly type: "CONVERSION_SETTLED"; readonly conversion: Conversion }
  | { readonly type: "FAILED"; readonly error: ApiError };

export interface ConversionRunOptions {
  readonly projectId: string;
  /** Exactly what the AI-decision screen collected. Not repaired on the way. */
  readonly request: ConversionRequest;
  readonly signal?: AbortSignal;
  readonly emit: (event: ConversionEvent) => void;
}

/**
 * How often the outcome is asked for while the job is unfinished, and how long
 * that is allowed to go on.
 *
 * The gateway currently converts inline, so the first read is almost always the
 * last one. The loop exists because the contract says `202` and a job — the
 * client must not depend on work happening to be synchronous, or it breaks the
 * day the gateway queues it. The deadline exists because a poller with no
 * deadline is a page that spins forever with nothing to show for it.
 */
const POLL_INTERVAL_MS = 400;
const POLL_DEADLINE_MS = 10 * 60 * 1000;

const TERMINAL: readonly Conversion["status"][] = [
  "completed",
  "failed",
  "cancelled",
];

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const id = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(id);
        resolve();
      },
      { once: true },
    );
  });
}

/** Why a terminal-but-not-completed job is a failure, in the user's words. */
function unfinished(conversion: Conversion): ApiError {
  return {
    category: "CONVERSION_ERROR",
    message:
      conversion.status === "cancelled"
        ? "The conversion was stopped before it finished. Nothing was produced, and the workbook you uploaded is unchanged."
        : "The conversion did not finish. Nothing was produced, and the workbook you uploaded is unchanged.",
    detail: `conversion ${conversion.conversion_id} ended with status ${conversion.status}`,
    request_id: "",
    project_id: null,
  };
}

function timedOut(elapsedMs: number): ApiError {
  return {
    category: "CONVERSION_ERROR",
    message:
      "The conversion is still running after a long time, so we have stopped " +
      "watching it. Nothing was changed, and you can ask for it again.",
    detail: `no terminal conversion status after ${Math.round(elapsedMs)} ms`,
    request_id: "",
    project_id: null,
  };
}

/**
 * Count what the outcome actually says, for the stage note. Every number here
 * is a field of the contract; none is derived from another.
 */
function outcomeNote(conversion: Conversion, reads: number): string {
  const flags = conversion.flags?.length ?? 0;
  const total = conversion.compatibility?.total ?? 0;
  const plural = reads === 1 ? "read" : "reads";
  return `${total} objects · ${flags} flags · settled after ${reads} ${plural}`;
}

/**
 * Run the conversion: ask for it, then watch it until it settles.
 *
 * **No progress is synthesised.** The two stages below flip because a request
 * returned. There is still no percentage anywhere in this function: the
 * gateway converts inline, so `GET /events` has nothing to report until the
 * conversion it describes is already over. A bar fed from that replay would be
 * counting work that had finished, which is the exact thing 03-ux-spec.md
 * forbids. The recording is read afterwards instead, by `runValidation`'s
 * caller, and shown as history rather than progress.
 *
 * Resolves once the outcome has been read, or after `FAILED` has been emitted.
 */
export async function runConversion(
  options: ConversionRunOptions,
): Promise<void> {
  const { projectId, request, signal, emit } = options;
  const call = signal ? { signal } : {};

  try {
    emit({ type: "STAGE_STARTED", id: "requested" });
    const acceptedAt = performance.now();
    const job = await startConversion(projectId, request, call);
    emit({
      type: "STAGE_FINISHED",
      id: "requested",
      elapsedMs: performance.now() - acceptedAt,
      note: job.job_id,
    });
    emit({ type: "CONVERSION_ACCEPTED", job });

    emit({ type: "STAGE_STARTED", id: "engine" });
    const watchedFrom = performance.now();
    let reads = 0;

    for (;;) {
      if (signal?.aborted) return;

      let conversion: Conversion | null = null;
      try {
        reads += 1;
        conversion = await getConversion(projectId, call);
      } catch (cause) {
        // `404 NOT_FOUND` means *not yet*: the contract returns 202 before
        // there is an outcome to read. Any other category is a real failure
        // and is not swallowed by the loop.
        if (toApiError(cause).category !== "NOT_FOUND") throw cause;
      }

      if (conversion !== null && TERMINAL.includes(conversion.status)) {
        if (conversion.status !== "completed") {
          emit({ type: "FAILED", error: unfinished(conversion) });
          return;
        }
        emit({
          type: "STAGE_FINISHED",
          id: "engine",
          elapsedMs: performance.now() - watchedFrom,
          note: outcomeNote(conversion, reads),
        });
        emit({ type: "CONVERSION_SETTLED", conversion });
        return;
      }

      const waited = performance.now() - watchedFrom;
      if (waited > POLL_DEADLINE_MS) {
        emit({ type: "FAILED", error: timedOut(waited) });
        return;
      }
      await sleep(POLL_INTERVAL_MS, signal);
    }
  } catch (cause) {
    if (signal?.aborted) return;
    emit({ type: "FAILED", error: toApiError(cause) });
  }
}

/* -------------------------------------------------------------------------
 * Validation
 * ---------------------------------------------------------------------- */

/** What the validation sequence reports, as it happens. */
export type ValidationEvent =
  | StageEvent
  | { readonly type: "VALIDATION_ACCEPTED"; readonly job: Job }
  | { readonly type: "VALIDATION_SETTLED"; readonly validation: Validation }
  | { readonly type: "FAILED"; readonly error: ApiError };

export interface ValidationRunOptions {
  readonly projectId: string;
  readonly signal?: AbortSignal;
  readonly emit: (event: ValidationEvent) => void;
}

/**
 * What the validation found, for the stage note.
 *
 * Deliberately not the score. A score with no denominator beside it is the
 * bare percentage 03-ux-spec.md forbids, and this note has room for one number
 * only — so it carries the count of checks that actually ran, which is the
 * number that makes the score meaningful rather than the score itself.
 */
function checkNote(validation: Validation): string {
  const categories = Object.values(validation.categories ?? {});
  const checks = categories.reduce((sum, category) => sum + (category.checks ?? 0), 0);
  const passed = categories.reduce((sum, category) => sum + (category.passed ?? 0), 0);
  return `${passed} of ${checks} checks passed`;
}

/**
 * Validate the conversion: ask for it, then read what it found.
 *
 * Runs only after a conversion has settled. Asking earlier gets a
 * `409 VALIDATION_ERROR`, which is correct — there is nothing to check
 * against until something has been produced.
 *
 * A failure here is **not** a failed conversion. The produced project is
 * untouched and still downloadable; what is lost is the ability to say
 * anything about it, so the caller keeps the results screen and shows the
 * verdict as `unverified`.
 */
export async function runValidation(
  options: ValidationRunOptions,
): Promise<void> {
  const { projectId, signal, emit } = options;
  const call = signal ? { signal } : {};

  try {
    emit({ type: "STAGE_STARTED", id: "checks" });
    const startedAt = performance.now();
    const job = await startValidation(projectId, call);
    emit({ type: "VALIDATION_ACCEPTED", job });

    const validation = await getValidation(projectId, call);
    emit({
      type: "STAGE_FINISHED",
      id: "checks",
      elapsedMs: performance.now() - startedAt,
      note: checkNote(validation),
    });
    emit({ type: "VALIDATION_SETTLED", validation });
  } catch (cause) {
    if (signal?.aborted) return;
    emit({ type: "FAILED", error: toApiError(cause) });
  }
}
