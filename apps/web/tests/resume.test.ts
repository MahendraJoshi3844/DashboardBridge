import { describe, expect, it } from "vitest";

import {
  FLOW_VERSION,
  decodeFlow,
  encodeFlow,
  flowReducer,
  resumeAfterReload,
} from "@/lib/state/persist";
import {
  initialState,
  transition,
  type MachineState,
} from "@/lib/state/machine";
import type {
  Analysis,
  Artifact,
  Conversion,
  Job,
  Project,
} from "@/types/contracts";

const project: Project = {
  project_id: "p",
  name: "Superstore.twb",
  source_platform: "tableau",
  target_platform: "powerbi",
  created_at: "2026-01-01T00:00:00Z",
};
const artifact: Artifact = {
  artifact_id: "a",
  kind: "source",
  filename: "Superstore.twb",
  size_bytes: 1,
  sha256: "d",
};
const job: Job = { job_id: "j", kind: "analysis", status: "completed" };
const analysis: Analysis = { analysis_id: "an", status: "completed" };
const conversion: Conversion = { conversion_id: "cv", status: "completed" };

function chosen(): MachineState {
  return transition(initialState, {
    type: "DIRECTION_CHOSEN",
    direction: { source: "tableau", target: "powerbi" },
  });
}

function uploading(): MachineState {
  return transition(chosen(), {
    type: "UPLOAD_STARTED",
    project,
    filename: "Superstore.twb",
  });
}

function analysing(): MachineState {
  return transition(uploading(), { type: "ANALYSIS_STARTED", artifact, job });
}

function analysed(): MachineState {
  return transition(analysing(), { type: "ANALYSIS_READY", analysis });
}

function converting(): MachineState {
  const configuring = transition(analysed(), {
    type: "CONFIGURATION_OPENED",
  });
  return transition(configuring, {
    type: "CONVERSION_STARTED",
    request: { ai_enabled: false, provider: "none" },
  });
}

function converted(): MachineState {
  return transition(converting(), {
    type: "CONVERSION_COMPLETED",
    conversion,
  });
}

/* ---------------------------------------------------------------------- *
 * Rewinding work that nobody is doing any more.
 *
 * A reload destroys the component that was holding the in-flight request.
 * Restoring `CONVERTING` would put a progress rail on screen for a conversion
 * that no longer has a caller — the interface claiming work is happening when
 * none is, which is the thing machine.ts exists to prevent. So every waiting
 * state rewinds to the last resting state it can honestly resume from.
 * ---------------------------------------------------------------------- */

describe("rewinding a state that was waiting on a request", () => {
  it("brings a run that was mid-conversion back to the configuration screen", () => {
    const resumed = resumeAfterReload(converting());

    expect(resumed.name).toBe("CONFIGURING");
    // The analysis is still true, so the user presses Convert, not Analyse.
    expect(resumed).toMatchObject({ analysis, artifact, project });
    expect(resumed).not.toHaveProperty("progress");
    expect(resumed).not.toHaveProperty("conversionJob");
  });

  it("brings a run that was mid-validation back to its results", () => {
    const validating = transition(converted(), { type: "VALIDATION_STARTED" });
    const resumed = resumeAfterReload(validating);

    expect(resumed.name).toBe("CONVERTED");
    expect(resumed).toMatchObject({ conversion });
  });

  it("keeps only the direction when the upload never finished", () => {
    const resumed = resumeAfterReload(uploading());

    expect(resumed).toEqual({
      name: "SOURCE_SELECTED",
      direction: { source: "tableau", target: "powerbi" },
    });
  });

  it("keeps only the direction when the analysis never returned", () => {
    // The analysis may well have finished on the server, but nothing here can
    // tell; offering the workbook again is the only honest option.
    expect(resumeAfterReload(analysing())).toEqual({
      name: "SOURCE_SELECTED",
      direction: { source: "tableau", target: "powerbi" },
    });
  });

  it("leaves a resting state alone", () => {
    const state = analysed();
    expect(resumeAfterReload(state)).toEqual(state);
  });

  it("rewinds the state an error came from, so retry resumes something real", () => {
    const failed = transition(converting(), {
      type: "FAILED",
      error: { category: "CONVERSION_ERROR", message: "boom" },
    });
    const resumed = resumeAfterReload(failed);

    expect(resumed.name).toBe("ERROR");
    expect(resumed).toMatchObject({ origin: { name: "CONFIGURING" } });
  });
});

/* ---------------------------------------------------------------------- */

describe("writing the flow down", () => {
  it("stores nothing for a run that has not started", () => {
    expect(encodeFlow(initialState)).toBeNull();
  });

  it("survives the round trip", () => {
    const state = analysed();
    expect(decodeFlow(encodeFlow(state))).toEqual(state);
  });

  it("never writes a state it would refuse to read back", () => {
    expect(decodeFlow(encodeFlow(converting()))?.name).toBe("CONFIGURING");
  });
});

describe("reading the flow back", () => {
  it("starts over rather than throwing on a payload that is not JSON", () => {
    expect(decodeFlow("{not json")).toEqual(initialState);
  });

  it("starts over when nothing was stored", () => {
    expect(decodeFlow(null)).toEqual(initialState);
  });

  it("discards a flow written by an older version of the machine", () => {
    const stale = JSON.stringify({
      v: FLOW_VERSION - 1,
      state: analysed(),
    });
    expect(decodeFlow(stale)).toEqual(initialState);
  });

  it("discards a state whose name the machine does not have", () => {
    const bogus = JSON.stringify({
      v: FLOW_VERSION,
      state: { name: "ALMOST_DONE" },
    });
    expect(decodeFlow(bogus)).toEqual(initialState);
  });

  it("rewinds a waiting state that was edited into storage by hand", () => {
    const tampered = JSON.stringify({ v: FLOW_VERSION, state: converting() });
    expect(decodeFlow(tampered)?.name).toBe("CONFIGURING");
  });
});

/* ---------------------------------------------------------------------- */

describe("the reducer the provider runs", () => {
  it("adopts a restored flow", () => {
    const restored = analysed();
    expect(flowReducer(initialState, { type: "RESUMED", state: restored })).toEqual(
      restored,
    );
  });

  it("refuses to overwrite a choice the user has already made", () => {
    // Storage is read in an effect, one paint after the first render. A user
    // who clicked in that window must not have the click undone.
    const clicked = chosen();
    expect(flowReducer(clicked, { type: "RESUMED", state: analysed() })).toEqual(
      clicked,
    );
  });

  it("passes ordinary events to the machine", () => {
    expect(
      flowReducer(initialState, {
        type: "DIRECTION_CHOSEN",
        direction: { source: "tableau", target: "powerbi" },
      }),
    ).toEqual(chosen());
  });
});
