import { describe, expect, it } from "vitest";

import {
  initialState,
  isBusy,
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
const conversionJob: Job = { job_id: "cj", kind: "conversion", status: "completed" };
const analysis: Analysis = { analysis_id: "an", status: "completed" };
const conversion: Conversion = { conversion_id: "cv", status: "completed" };

/** Walk the machine to `ANALYSIS_READY` the only way it can be reached. */
function analysed(): MachineState {
  let state = transition(initialState, {
    type: "DIRECTION_CHOSEN",
    direction: { source: "tableau", target: "powerbi" },
  });
  state = transition(state, {
    type: "UPLOAD_STARTED",
    project,
    filename: "Superstore.twb",
  });
  state = transition(state, { type: "ANALYSIS_STARTED", artifact, job });
  return transition(state, { type: "ANALYSIS_READY", analysis });
}

function converting(): MachineState {
  const state = transition(analysed(), { type: "CONFIGURATION_OPENED" });
  return transition(state, {
    type: "CONVERSION_STARTED",
    request: { ai_enabled: false, provider: "none" },
  });
}

describe("the conversion path", () => {
  it("enters CONVERTING before the gateway has answered", () => {
    // The gateway converts inline: waiting for the job id would leave the user
    // on the configuration screen for the whole run.
    const state = converting();
    expect(state.name).toBe("CONVERTING");
    if (state.name !== "CONVERTING") return;
    expect(state.conversionJob).toBeNull();
  });

  it("fills the job id in without advancing the machine", () => {
    const state = transition(converting(), {
      type: "CONVERSION_ACCEPTED",
      job: conversionJob,
    });
    expect(state.name).toBe("CONVERTING");
    if (state.name !== "CONVERTING") return;
    expect(state.conversionJob?.job_id).toBe("cj");
  });

  it("settles in CONVERTED, not VALIDATING", () => {
    // Validation is Phase 5 and does not run. A machine that went straight to
    // VALIDATING would name an activity that is not happening.
    const state = transition(converting(), {
      type: "CONVERSION_COMPLETED",
      conversion,
    });
    expect(state.name).toBe("CONVERTED");
    expect(isBusy(state)).toBe(false);
  });

  it("keeps VALIDATING reachable for the phase that will use it", () => {
    let state = transition(converting(), {
      type: "CONVERSION_COMPLETED",
      conversion,
    });
    state = transition(state, { type: "VALIDATION_STARTED" });
    expect(state.name).toBe("VALIDATING");
    expect(isBusy(state)).toBe(true);
  });

  it("drops the progress it measured once the work it described is over", () => {
    let state = transition(converting(), {
      type: "CONVERSION_PROGRESSED",
      progress: { stage: "translate", completed: 18, total: 27 },
    });
    state = transition(state, { type: "CONVERSION_COMPLETED", conversion });
    expect(state).not.toHaveProperty("progress");
  });
});

describe("backing out and failing", () => {
  it("returns to the analysis when the configuration is cancelled", () => {
    const state = transition(analysed(), { type: "CONFIGURATION_OPENED" });
    expect(transition(state, { type: "CONFIGURATION_CANCELLED" }).name).toBe(
      "ANALYSIS_READY",
    );
  });

  it("retains CONVERTING as the origin so retry resumes rather than restarts", () => {
    const failed = transition(converting(), {
      type: "FAILED",
      error: {
        category: "CONVERSION_ERROR",
        message: "m",
        detail: "d",
        request_id: "",
        project_id: null,
      },
    });
    expect(failed.name).toBe("ERROR");
    if (failed.name !== "ERROR") return;
    expect(failed.origin.name).toBe("CONVERTING");
    expect(transition(failed, { type: "RETRIED" }).name).toBe("CONVERTING");
  });

  it("throws on an illegal transition outside production", () => {
    expect(() =>
      transition(analysed(), { type: "CONVERSION_COMPLETED", conversion }),
    ).toThrow(/Illegal transition/);
  });
});
