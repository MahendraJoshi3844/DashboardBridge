/**
 * Keeping your place across a reload.
 *
 * The flow lived only in React state, so refreshing the page in the middle of
 * a migration dropped the user back at "choose a direction" with the analysis
 * they had waited for gone. Nothing was lost server-side — the project, the
 * artifact and the conversion all still existed — but the screen had no way
 * back to them.
 *
 * Two rules shape everything here.
 *
 * **Only resting states are worth restoring.** A reload destroys the component
 * that was holding the in-flight request, so a restored `CONVERTING` would put
 * a progress rail on screen for a conversion with no caller — an interface
 * claiming that work is happening when none is. That is the exact failure
 * `machine.ts` was written to make impossible, and persistence must not
 * reintroduce it through the back door. Every waiting state therefore rewinds
 * to the last resting state it can honestly resume from.
 *
 * **A stored flow is a guess about a previous build.** The shape of
 * `MachineState` is this module's input and it changes as the machine does, so
 * the payload carries `FLOW_VERSION`; anything older is discarded rather than
 * rendered. Bump it whenever a state's context changes.
 *
 * This module is pure — it takes and returns strings. The storage call itself
 * lives in the provider, which is where the browser is.
 */

import {
  initialState,
  transition,
  type MachineEvent,
  type MachineState,
  type MachineStateName,
} from "./machine";

/** Per-tab, under the app's own key. */
export const FLOW_STORAGE_KEY = "dashboardbridge.flow";

/**
 * The shape of what is written. Raise this whenever a state gains, loses or
 * renames a context field, so a flow written by the previous build is thrown
 * away instead of feeding a screen fields that no longer exist.
 */
export const FLOW_VERSION = 1;

const STATE_NAMES: ReadonlySet<string> = new Set<MachineStateName>([
  "IDLE",
  "SOURCE_SELECTED",
  "UPLOADING",
  "ANALYZING",
  "ANALYSIS_READY",
  "CONFIGURING",
  "CONVERTING",
  "CONVERTED",
  "VALIDATING",
  "COMPLETED",
  "ERROR",
]);

/**
 * Rewind a state that was waiting on a request nobody is making any more.
 *
 * `UPLOADING` and `ANALYZING` fall all the way back to the direction: the
 * analysis may well have completed on the server, but nothing on this side can
 * tell, and offering the workbook again is the only claim that is true either
 * way. `CONVERTING` and `VALIDATING` fall back one step each, because the
 * analysis and the conversion they are built on did complete.
 */
export function resumeAfterReload(state: MachineState): MachineState {
  switch (state.name) {
    case "UPLOADING":
    case "ANALYZING":
      return { name: "SOURCE_SELECTED", direction: state.direction };

    case "CONVERTING": {
      const {
        request: _request,
        conversionJob: _conversionJob,
        progress: _progress,
        ...rest
      } = state;
      return { ...rest, name: "CONFIGURING" };
    }

    case "VALIDATING":
      return { ...state, name: "CONVERTED" };

    case "ERROR":
      // Retry resumes from the origin, so the origin has to be resumable too.
      return { ...state, origin: resumeAfterReload(state.origin) as typeof state.origin };

    default:
      return state;
  }
}

/**
 * What to write down, or `null` when there is nothing worth remembering.
 *
 * The rewind happens here as well as on the way back in, so this never stores
 * a state it would refuse to restore.
 */
export function encodeFlow(state: MachineState): string | null {
  const resumable = resumeAfterReload(state);
  if (resumable.name === "IDLE") return null;
  return JSON.stringify({ v: FLOW_VERSION, state: resumable });
}

/**
 * Read a stored flow back. Anything unrecognised starts the run over, which is
 * the same place the user would have been without this module — a bad payload
 * must never be worse than no payload, so this does not throw.
 */
export function decodeFlow(raw: string | null): MachineState {
  if (!raw) return initialState;

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return initialState;
  }

  if (typeof parsed !== "object" || parsed === null) return initialState;
  const envelope = parsed as { v?: unknown; state?: unknown };
  if (envelope.v !== FLOW_VERSION) return initialState;

  const state = envelope.state;
  if (typeof state !== "object" || state === null) return initialState;
  if (!STATE_NAMES.has((state as { name?: unknown }).name as string)) {
    return initialState;
  }

  return resumeAfterReload(state as MachineState);
}

/* -------------------------------------------------------------------------
 * The reducer the provider runs.
 * ---------------------------------------------------------------------- */

/**
 * `RESUMED` is deliberately not a `MachineEvent`. Every event in `machine.ts`
 * is triggered by something the server said; this one is triggered by the
 * browser, and letting it into that union would make the machine's own rule
 * untrue.
 */
export type FlowAction =
  | MachineEvent
  | { readonly type: "RESUMED"; readonly state: MachineState };

export function flowReducer(
  state: MachineState,
  action: FlowAction,
): MachineState {
  if (action.type === "RESUMED") {
    // Storage is read in an effect, which runs a paint after the first render.
    // A user quick enough to choose a direction in that window has told us
    // more than storage has, so their choice wins.
    return state.name === "IDLE" ? action.state : state;
  }
  return transition(state, action);
}
