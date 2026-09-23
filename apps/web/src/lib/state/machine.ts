/**
 * The migration state machine (03-ux-spec.md, "State machine", §58).
 *
 *   IDLE → SOURCE_SELECTED → UPLOADING → ANALYZING → ANALYSIS_READY
 *        → CONFIGURING → CONVERTING → CONVERTED → VALIDATING → COMPLETED
 *
 *   ANY_STATE → ERROR → { RETRY | CANCEL }
 *
 * ## Why `CONVERTED` is in that line and not in the spec's
 *
 * 03-ux-spec.md draws `CONVERTING → VALIDATING`, which assumes validation
 * begins the moment conversion ends. It does not: validation is Phase 5 and no
 * endpoint for it exists, so a machine that went straight to `VALIDATING` would
 * sit in a state named for an activity that is not happening, and the rail and
 * the results screen would both say so on its behalf. That is precisely the
 * claim AGENTS.md rule 2 forbids.
 *
 * `CONVERTED` is the honest resting state: files were produced, nothing has
 * been checked. It is what the results screen renders, and it is why that
 * screen says **Unverified** rather than borrowing a verdict from a validation
 * that never ran. `VALIDATION_STARTED` is the event Phase 5 dispatches when
 * `POST /validation` returns, which keeps `VALIDATING` reachable rather than
 * stranded — an unreachable state is the category error the spec names.
 *
 * One machine, one current state. There are no `isLoading` / `hasError` /
 * `isDone` booleans anywhere in this app, because four booleans describe
 * sixteen situations of which twelve are impossible, and the impossible ones
 * are where interfaces lie about what is happening.
 *
 * Three rules from the spec are enforced here rather than trusted:
 *
 * 1. Transitions are triggered by server events, never by a timer. Every event
 *    below carries a payload that came from the API; none is time-based.
 * 2. `ERROR` retains the state it came from, so retry resumes rather than
 *    restarts.
 * 3. Illegal transitions throw in development and are logged in production.
 *
 * This module is pure: no React, no fetch. It is the part of the flow that can
 * be tested without a browser.
 */

import type {
  Analysis,
  ApiError,
  Artifact,
  Conversion,
  ConversionRequest,
  Job,
  Platform,
  ProgressEvent as JobProgressEvent,
  Project,
  Validation,
} from "@/types/contracts";

/* -------------------------------------------------------------------------
 * Context — what is known, accumulating as the run proceeds.
 * Each state carries exactly what has actually been established, so a screen
 * cannot render a number that does not exist yet.
 * ---------------------------------------------------------------------- */

export interface Direction {
  readonly source: Platform;
  readonly target: Platform;
}

interface DirectionContext {
  readonly direction: Direction;
}

interface UploadContext extends DirectionContext {
  readonly project: Project;
  /** The user's own filename, for display only — storage renames it (§15). */
  readonly filename: string;
}

interface ArtifactContext extends UploadContext {
  readonly artifact: Artifact;
  readonly job: Job;
}

interface AnalysisContext extends ArtifactContext {
  readonly analysis: Analysis;
}

interface ConversionContext extends AnalysisContext {
  readonly request: ConversionRequest;
  /**
   * The conversion job, once the gateway has accepted it — null in the window
   * between asking and being answered.
   *
   * That window is not a formality: the gateway converts inline, so the request
   * that returns the job takes as long as the whole conversion. A machine that
   * waited for the job before entering `CONVERTING` would leave the user on the
   * configuration screen for the entire run, with the interface claiming
   * nothing was happening while everything was.
   *
   * It is a separate field from the inherited `job` — the analysis job — on
   * purpose. Shadowing that one would erase the id the analysis is traced by,
   * and a run needs both ids to be followed end to end.
   */
  readonly conversionJob: Job | null;
  /** The last real progress event. Absent until the job reports one. */
  readonly progress: JobProgressEvent | null;
}

interface ConvertedContext extends AnalysisContext {
  readonly request: ConversionRequest;
  readonly conversion: Conversion;
}

/* -------------------------------------------------------------------------
 * States
 * ---------------------------------------------------------------------- */

export type MachineStateName =
  | "IDLE"
  | "SOURCE_SELECTED"
  | "UPLOADING"
  | "ANALYZING"
  | "ANALYSIS_READY"
  | "CONFIGURING"
  | "CONVERTING"
  | "CONVERTED"
  | "VALIDATING"
  | "COMPLETED"
  | "ERROR";

/** Every state except ERROR. ERROR holds one of these as its origin. */
export type ResumableState =
  | { readonly name: "IDLE" }
  | ({ readonly name: "SOURCE_SELECTED" } & DirectionContext)
  | ({ readonly name: "UPLOADING" } & UploadContext)
  | ({ readonly name: "ANALYZING" } & ArtifactContext)
  | ({ readonly name: "ANALYSIS_READY" } & AnalysisContext)
  | ({ readonly name: "CONFIGURING" } & AnalysisContext)
  | ({ readonly name: "CONVERTING" } & ConversionContext)
  | ({ readonly name: "CONVERTED" } & ConvertedContext)
  | ({ readonly name: "VALIDATING" } & ConvertedContext)
  | ({
      readonly name: "COMPLETED";
      readonly validation: Validation;
    } & ConvertedContext);

export interface ErrorState {
  readonly name: "ERROR";
  readonly error: ApiError;
  /** Retry resumes from here. It never restarts the run. */
  readonly origin: ResumableState;
}

export type MachineState = ResumableState | ErrorState;

export const initialState: MachineState = { name: "IDLE" };

/* -------------------------------------------------------------------------
 * Events — all server-originated.
 * ---------------------------------------------------------------------- */

export type MachineEvent =
  | { readonly type: "DIRECTION_CHOSEN"; readonly direction: Direction }
  | { readonly type: "DIRECTION_CLEARED" }
  | {
      readonly type: "UPLOAD_STARTED";
      readonly project: Project;
      readonly filename: string;
    }
  | {
      readonly type: "ANALYSIS_STARTED";
      readonly artifact: Artifact;
      readonly job: Job;
    }
  | { readonly type: "ANALYSIS_READY"; readonly analysis: Analysis }
  | { readonly type: "CONFIGURATION_OPENED" }
  /** The user backed out of the AI decision without converting. */
  | { readonly type: "CONFIGURATION_CANCELLED" }
  /** The user asked for the conversion. The request is what they chose. */
  | {
      readonly type: "CONVERSION_STARTED";
      readonly request: ConversionRequest;
    }
  /** The gateway answered `202` with a job id. */
  | { readonly type: "CONVERSION_ACCEPTED"; readonly job: Job }
  | {
      readonly type: "CONVERSION_PROGRESSED";
      readonly progress: JobProgressEvent;
    }
  | { readonly type: "CONVERSION_COMPLETED"; readonly conversion: Conversion }
  /**
   * `POST /validation` was accepted. Dispatched by Phase 5; declared now so
   * `VALIDATING` is reachable rather than stranded behind an unbuilt step.
   */
  | { readonly type: "VALIDATION_STARTED" }
  | { readonly type: "VALIDATION_COMPLETED"; readonly validation: Validation }
  | { readonly type: "FAILED"; readonly error: ApiError }
  | { readonly type: "RETRIED" }
  | { readonly type: "CANCELLED" };

export type MachineEventType = MachineEvent["type"];

/* -------------------------------------------------------------------------
 * Transition
 * ---------------------------------------------------------------------- */

export class IllegalTransitionError extends Error {
  readonly from: MachineStateName;
  readonly event: MachineEventType;

  constructor(from: MachineStateName, event: MachineEventType) {
    super(`Illegal transition: ${event} is not accepted in ${from}.`);
    this.name = "IllegalTransitionError";
    this.from = from;
    this.event = event;
  }
}

/**
 * Development throws so the mistake is found by whoever made it. Production
 * logs and holds the current state, because dropping a user mid-migration to
 * report a programming error serves nobody.
 */
function refuse(state: MachineState, event: MachineEvent): MachineState {
  const error = new IllegalTransitionError(state.name, event.type);
  if (process.env.NODE_ENV !== "production") {
    throw error;
  }
  console.error(error.message);
  return state;
}

export function transition(
  state: MachineState,
  event: MachineEvent,
): MachineState {
  // Failure and recovery are legal from anywhere, so they are handled before
  // the per-state table rather than repeated in every branch of it.
  if (event.type === "FAILED") {
    if (state.name === "ERROR") return state;
    return { name: "ERROR", error: event.error, origin: state };
  }

  if (state.name === "ERROR") {
    switch (event.type) {
      case "RETRIED":
        return state.origin;
      case "CANCELLED":
        return initialState;
      default:
        return refuse(state, event);
    }
  }

  switch (state.name) {
    case "IDLE":
      if (event.type === "DIRECTION_CHOSEN") {
        return { name: "SOURCE_SELECTED", direction: event.direction };
      }
      return refuse(state, event);

    case "SOURCE_SELECTED":
      if (event.type === "DIRECTION_CLEARED") return initialState;
      if (event.type === "UPLOAD_STARTED") {
        return {
          name: "UPLOADING",
          direction: state.direction,
          project: event.project,
          filename: event.filename,
        };
      }
      return refuse(state, event);

    case "UPLOADING":
      if (event.type === "ANALYSIS_STARTED") {
        return {
          name: "ANALYZING",
          direction: state.direction,
          project: state.project,
          filename: state.filename,
          artifact: event.artifact,
          job: event.job,
        };
      }
      return refuse(state, event);

    case "ANALYZING":
      if (event.type === "ANALYSIS_READY") {
        return { ...state, name: "ANALYSIS_READY", analysis: event.analysis };
      }
      return refuse(state, event);

    case "ANALYSIS_READY":
      if (event.type === "CONFIGURATION_OPENED") {
        return { ...state, name: "CONFIGURING" };
      }
      return refuse(state, event);

    case "CONFIGURING":
      if (event.type === "CONFIGURATION_CANCELLED") {
        return { ...state, name: "ANALYSIS_READY" };
      }
      if (event.type === "CONVERSION_STARTED") {
        return {
          ...state,
          name: "CONVERTING",
          request: event.request,
          conversionJob: null,
          progress: null,
        };
      }
      return refuse(state, event);

    case "CONVERTING":
      // The job id and the progress events both *refine* this state; neither
      // advances the machine. Only the outcome does.
      if (event.type === "CONVERSION_ACCEPTED") {
        return { ...state, conversionJob: event.job };
      }
      if (event.type === "CONVERSION_PROGRESSED") {
        return { ...state, progress: event.progress };
      }
      if (event.type === "CONVERSION_COMPLETED") {
        // `progress` is dropped: it described work that has finished, and a
        // stale count on the results screen would be a number nobody
        // measured. The conversion job id goes with it — the outcome carries
        // its own `conversion_id`, which is what the results screen shows.
        const { progress: _progress, conversionJob: _job, ...rest } = state;
        return { ...rest, name: "CONVERTED", conversion: event.conversion };
      }
      return refuse(state, event);

    case "CONVERTED":
      if (event.type === "VALIDATION_STARTED") {
        return { ...state, name: "VALIDATING" };
      }
      return refuse(state, event);

    case "VALIDATING":
      if (event.type === "VALIDATION_COMPLETED") {
        return { ...state, name: "COMPLETED", validation: event.validation };
      }
      return refuse(state, event);

    case "COMPLETED":
      return refuse(state, event);

    default:
      return refuse(state, event);
  }
}

/** True while the machine is waiting on work the server is doing. */
export function isBusy(state: MachineState): boolean {
  return (
    state.name === "UPLOADING" ||
    state.name === "ANALYZING" ||
    state.name === "CONVERTING" ||
    state.name === "VALIDATING"
  );
}
