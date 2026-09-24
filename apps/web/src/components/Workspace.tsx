"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type ReactElement } from "react";

import {
  initialConversionStages,
  initialStages,
  runAnalysis,
  runConversion,
  runValidation,
  withStage,
  type ConversionEvent,
  type RunEvent,
  type RunStage,
  type ValidationEvent,
} from "@/lib/api/run";
import { useHealth, type HealthProbe } from "@/lib/hooks/useHealth";
import { useMigration, useMigrationDispatch } from "@/lib/state/context";
import type { Direction, MachineState } from "@/lib/state/machine";
import type {
  Analysis,
  ApiError,
  Artifact,
  Conversion,
  ConversionRequest,
  Job,
  Project,
  Validation,
} from "@/types/contracts";

import { AnalysisScreen } from "./AnalysisScreen";
import { ConversionScreen } from "./ConversionScreen";
import { ConvertScreen } from "./ConvertScreen";
import { ErrorPanel } from "./ErrorPanel";
import { ArrowRightIcon, CloseIcon, RetryIcon } from "./Icons";
import { MetadataDashboard } from "./MetadataDashboard";
import { ResultsScreen } from "./ResultsScreen";
import { StepRail } from "./StepRail";
import { UploadScreen } from "./UploadScreen";

/**
 * The workspace: upload (P1.2), analysis (P1.3-lite) and the metadata dashboard
 * (P1.4 / P2.6), driven by the one state machine.
 *
 * Which screen you see is `state.name` and nothing else. There is no
 * `isUploading`, no `hasAnalysed`, no `showResults` — four booleans describe
 * sixteen situations of which twelve are impossible, and the impossible ones
 * are where interfaces lie about what is happening (03-ux-spec.md, §58).
 *
 * Three pieces of local state sit beside the machine, and each is data the
 * machine deliberately does not carry:
 *
 * * `file` — a `File` handle is a browser object, not a contract type. The
 *   machine holds the *filename*, which is what a screen displays; the handle
 *   is what a retry re-sends, so it is held here.
 * * `stages` / `startedAt` — measurements of this client's own requests. They
 *   describe how the current state was reached, not which state it is.
 * * `refusal` — a file the pre-check rejected. It never entered the flow, so
 *   pushing it through the machine's `ERROR` would report a transition that did
 *   not happen.
 */
const SUPPORTED_DIRECTIONS: readonly Direction[] = [
  { source: "tableau", target: "powerbi" },
];

function isSupported(source: string | null, target: string | null): Direction | null {
  return (
    SUPPORTED_DIRECTIONS.find(
      (direction) => direction.source === source && direction.target === target,
    ) ?? null
  );
}

/** Where the user actually is, looking through `ERROR` to the state it retains. */
function resumable(state: MachineState) {
  return state.name === "ERROR" ? state.origin : state;
}

interface Resume {
  readonly project?: Project | null;
  readonly artifact?: Artifact | null;
  readonly job?: Job | null;
}

export function Workspace() {
  const state = useMigration();
  const dispatch = useMigrationDispatch();
  const searchParams = useSearchParams();

  const [file, setFile] = useState<File | null>(null);
  const [refusal, setRefusal] = useState<ApiError | null>(null);
  const [stages, setStages] = useState<readonly RunStage[]>(initialStages);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [totalMs, setTotalMs] = useState<number | null>(null);

  // The conversion's own measurements, kept apart from the analysis run's for
  // the same reason: they describe how a state was reached, not which it is.
  const [convertStages, setConvertStages] = useState<readonly RunStage[]>(
    initialConversionStages,
  );
  const [convertStartedAt, setConvertStartedAt] = useState<number | null>(null);
  const [convertTotalMs, setConvertTotalMs] = useState<number | null>(null);

  const abort = useRef<AbortController | null>(null);
  const runStart = useRef<number>(0);
  const convertStart = useRef<number>(0);
  const filename = useRef<string>("");

  // Read once for the whole workspace: the conversion screen must know whether
  // AI exists at all before it decides what to offer, and must not guess the
  // privacy mode it puts in a request body.
  const probe = useHealth();

  // A direction can arrive in the URL so this screen is linkable and
  // reloadable. It is applied once, only from IDLE, and only for a direction
  // the engine can actually do — an unsupported pair is ignored rather than
  // coerced into the one we support.
  const seeded = useRef(false);
  useEffect(() => {
    if (seeded.current || state.name !== "IDLE") return;
    const direction = isSupported(
      searchParams.get("source"),
      searchParams.get("target"),
    );
    if (direction === null) return;
    seeded.current = true;
    dispatch({ type: "DIRECTION_CHOSEN", direction });
  }, [dispatch, searchParams, state.name]);

  useEffect(() => () => abort.current?.abort(), []);

  const emit = useCallback(
    (event: RunEvent) => {
      switch (event.type) {
        case "STAGE_STARTED":
          setStages((current) =>
            withStage(current, event.id, { phase: "active" }),
          );
          return;
        case "STAGE_FINISHED":
          setStages((current) =>
            withStage(current, event.id, {
              phase: "done",
              elapsedMs: event.elapsedMs,
              note: event.note,
            }),
          );
          return;
        case "PROJECT_OPENED":
          dispatch({
            type: "UPLOAD_STARTED",
            project: event.project,
            filename: filename.current,
          });
          return;
        case "ANALYSIS_STARTED":
          dispatch({
            type: "ANALYSIS_STARTED",
            artifact: event.artifact,
            job: event.job,
          });
          return;
        case "ANALYSIS_READY":
          // A job that did not complete does not become a dashboard. Rendering
          // an incomplete analysis would show counts nobody finished measuring.
          if (event.analysis.status !== "completed") {
            dispatch({
              type: "FAILED",
              error: incomplete(event.analysis),
            });
            return;
          }
          setTotalMs(performance.now() - runStart.current);
          dispatch({ type: "ANALYSIS_READY", analysis: event.analysis });
          return;
        case "FAILED":
          dispatch({ type: "FAILED", error: event.error });
          return;
      }
    },
    [dispatch],
  );

  const begin = useCallback(
    (direction: Direction, chosen: File, resume: Resume, fresh: boolean) => {
      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;

      filename.current = chosen.name;
      runStart.current = performance.now();
      setStartedAt(runStart.current);
      setTotalMs(null);
      if (fresh) setStages(initialStages);

      void runAnalysis({
        file: chosen,
        source: direction.source,
        target: direction.target,
        project: resume.project ?? null,
        artifact: resume.artifact ?? null,
        job: resume.job ?? null,
        signal: controller.signal,
        emit,
      });
    },
    [emit],
  );

  const start = useCallback(() => {
    // Only from the state that offers the control. A second click while the
    // first run is between "project created" and the re-render would start a
    // second run whose `PROJECT_OPENED` the machine would rightly refuse.
    if (state.name !== "SOURCE_SELECTED" || file === null) return;
    setRefusal(null);
    begin(state.direction, file, {}, true);
  }, [begin, file, state]);

  /** The conversion's observed events, in the same shape as the analysis run's. */
  const convertEmit = useCallback(
    (event: ConversionEvent) => {
      switch (event.type) {
        case "STAGE_STARTED":
          setConvertStages((current) =>
            withStage(current, event.id, { phase: "active" }),
          );
          return;
        case "STAGE_FINISHED":
          setConvertStages((current) =>
            withStage(current, event.id, {
              phase: "done",
              elapsedMs: event.elapsedMs,
              note: event.note,
            }),
          );
          return;
        case "CONVERSION_ACCEPTED":
          dispatch({ type: "CONVERSION_ACCEPTED", job: event.job });
          return;
        case "CONVERSION_SETTLED":
          setConvertTotalMs(performance.now() - convertStart.current);
          dispatch({
            type: "CONVERSION_COMPLETED",
            conversion: event.conversion,
          });
          return;
        case "FAILED":
          dispatch({ type: "FAILED", error: event.error });
          return;
      }
    },
    [dispatch],
  );

  /**
   * Ask for the conversion.
   *
   * The machine is moved *before* the request is sent, not after it returns.
   * The gateway converts inline, so the call that answers with a job takes as
   * long as the whole conversion; waiting for it would leave the user on the
   * configuration screen, with the interface saying nothing was happening while
   * everything was. `CONVERSION_ACCEPTED` fills the job id in when it arrives.
   */
  const convert = useCallback(
    (request: ConversionRequest) => {
      if (state.name !== "CONFIGURING") return;
      const projectId = state.project.project_id;

      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;

      convertStart.current = performance.now();
      setConvertStartedAt(convertStart.current);
      setConvertTotalMs(null);
      setConvertStages(initialConversionStages);
      dispatch({ type: "CONVERSION_STARTED", request });

      void runConversion({
        projectId,
        request,
        signal: controller.signal,
        emit: convertEmit,
      });
    },
    [convertEmit, dispatch, state],
  );

  /** The validation's observed events, in the same shape as the other runs'. */
  const validateEmit = useCallback(
    (event: ValidationEvent) => {
      switch (event.type) {
        case "STAGE_STARTED":
          setConvertStages((current) =>
            withStage(current, event.id, { phase: "active" }),
          );
          return;
        case "STAGE_FINISHED":
          setConvertStages((current) =>
            withStage(current, event.id, {
              phase: "done",
              elapsedMs: event.elapsedMs,
              note: event.note,
            }),
          );
          return;
        case "VALIDATION_ACCEPTED":
          // Only now, so a refused request leaves the machine in CONVERTED with
          // its download intact rather than stranded in VALIDATING waiting for
          // an outcome that is never coming.
          dispatch({ type: "VALIDATION_STARTED" });
          return;
        case "VALIDATION_SETTLED":
          dispatch({
            type: "VALIDATION_COMPLETED",
            validation: event.validation,
          });
          return;
        case "FAILED":
          dispatch({ type: "FAILED", error: event.error });
          return;
      }
    },
    [dispatch],
  );

  /**
   * Validation follows a conversion without being asked for.
   *
   * A produced file is not evidence that it is correct, and putting the check
   * behind a button would make the unchecked reading of the results screen the
   * default one. Keyed on the machine reaching `CONVERTED`, which happens once
   * per run - and again after a retry, which is exactly when it should re-run.
   */
  const toValidate = state.name === "CONVERTED" ? state.project.project_id : null;
  useEffect(() => {
    if (toValidate === null) return;
    const controller = new AbortController();
    void runValidation({
      projectId: toValidate,
      signal: controller.signal,
      emit: validateEmit,
    });
    return () => controller.abort();
  }, [toValidate, validateEmit]);

  /**
   * Retry resumes; it does not restart. The origin state says how far the run
   * actually got, so a failure while reading the workbook re-reads it rather
   * than uploading the same bytes a second time.
   */
  const retry = useCallback(() => {
    if (state.name !== "ERROR") return;
    const origin = state.origin;

    // A conversion that failed is resumed from the project, not from the file:
    // the workbook is already uploaded and analysed, and re-sending it would
    // restart a run that got much further than that. The machine returns to
    // `CONVERTING`, which is exactly where a second attempt belongs.
    if (origin.name === "CONVERTING") {
      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;
      convertStart.current = performance.now();
      setConvertStartedAt(convertStart.current);
      setConvertTotalMs(null);
      setConvertStages(initialConversionStages);
      dispatch({ type: "RETRIED" });
      void runConversion({
        projectId: origin.project.project_id,
        request: origin.request,
        signal: controller.signal,
        emit: convertEmit,
      });
      return;
    }

    if (origin.name === "IDLE" || file === null) {
      dispatch({ type: "CANCELLED" });
      return;
    }
    dispatch({ type: "RETRIED" });
    if (origin.name === "SOURCE_SELECTED") {
      begin(origin.direction, file, {}, true);
      return;
    }
    if (origin.name === "UPLOADING") {
      begin(origin.direction, file, { project: origin.project }, false);
      return;
    }
    if (origin.name === "ANALYZING") {
      begin(
        origin.direction,
        file,
        { project: origin.project, artifact: origin.artifact, job: origin.job },
        false,
      );
    }
    // Any later origin has nothing this screen can resume; the machine is back
    // where it was and the user can act from there.
  }, [begin, convertEmit, dispatch, file, state]);

  const cancel = useCallback(() => {
    abort.current?.abort();
    dispatch({ type: "CANCELLED" });
    setFile(null);
    setRefusal(null);
    setStages(initialStages);
    setStartedAt(null);
    setTotalMs(null);
    setConvertStages(initialConversionStages);
    setConvertStartedAt(null);
    setConvertTotalMs(null);
  }, [dispatch]);

  const preview = usePreview(searchParams.get("preview"));
  if (preview !== null) return preview;

  return (
    <div className="space-y-8">
      <StepRail state={state}>{railNote(state)}</StepRail>
      <Screen
        state={state}
        file={file}
        refusal={refusal}
        stages={stages}
        startedAt={startedAt}
        totalMs={totalMs}
        probe={probe}
        convertStages={convertStages}
        convertStartedAt={convertStartedAt}
        convertTotalMs={convertTotalMs}
        onConfigure={() => dispatch({ type: "CONFIGURATION_OPENED" })}
        onConfigureCancelled={() =>
          dispatch({ type: "CONFIGURATION_CANCELLED" })
        }
        onConvert={convert}
        onAccepted={(chosen) => {
          setRefusal(null);
          setFile(chosen);
        }}
        onRefused={(error) => {
          setFile(null);
          setRefusal(error);
        }}
        onCleared={() => setFile(null)}
        onStart={start}
        onRetry={retry}
        onCancel={cancel}
      />
    </div>
  );
}

/* ---------------------------------------------------------------------- */

function Screen({
  state,
  file,
  refusal,
  stages,
  startedAt,
  totalMs,
  probe,
  convertStages,
  convertStartedAt,
  convertTotalMs,
  onAccepted,
  onRefused,
  onCleared,
  onStart,
  onConfigure,
  onConfigureCancelled,
  onConvert,
  onRetry,
  onCancel,
}: {
  readonly state: MachineState;
  readonly file: File | null;
  readonly refusal: ApiError | null;
  readonly stages: readonly RunStage[];
  readonly startedAt: number | null;
  readonly totalMs: number | null;
  readonly probe: HealthProbe;
  readonly convertStages: readonly RunStage[];
  readonly convertStartedAt: number | null;
  readonly convertTotalMs: number | null;
  readonly onAccepted: (file: File) => void;
  readonly onRefused: (error: ApiError) => void;
  readonly onCleared: () => void;
  readonly onStart: () => void;
  readonly onConfigure: () => void;
  readonly onConfigureCancelled: () => void;
  readonly onConvert: (request: ConversionRequest) => void;
  readonly onRetry: () => void;
  readonly onCancel: () => void;
}) {
  // From the health probe the screen already has. False while the probe is
  // unresolved, which is the honest default: an unanswered probe is not the
  // same as "a model is there".
  const aiAvailable = probe.phase === "ready" ? probe.health.ai_available : false;

  if (state.name === "ERROR") {
    return (
      <ErrorPanel error={state.error} heading={headingFor(state.origin)}>
        <button type="button" className="btn" onClick={onRetry}>
          <RetryIcon className="h-4 w-4" />
          Try that again
        </button>
        <button type="button" className="btn btn-quiet" onClick={onCancel}>
          <CloseIcon className="h-4 w-4" />
          Start over
        </button>
      </ErrorPanel>
    );
  }

  switch (state.name) {
    case "IDLE":
      return <NoDirection />;

    case "SOURCE_SELECTED":
      return (
        <UploadScreen
          source={state.direction.source}
          target={state.direction.target}
          file={file}
          refusal={refusal}
          onAccepted={onAccepted}
          onRefused={onRefused}
          onCleared={onCleared}
          onStart={onStart}
        />
      );

    case "UPLOADING":
    case "ANALYZING":
      return (
        <AnalysisScreen
          filename={state.filename}
          stages={stages}
          startedAt={startedAt}
        />
      );

    case "ANALYSIS_READY":
      return (
        <MetadataDashboard
          analysis={state.analysis}
          filename={state.filename}
          stages={stages}
          totalElapsedMs={totalMs}
          onConvert={onConfigure}
        />
      );

    case "CONFIGURING":
      return (
        <ConvertScreen
          analysis={state.analysis}
          filename={state.filename}
          probe={probe}
          onConvert={onConvert}
          onCancel={onConfigureCancelled}
        />
      );

    case "CONVERTING":
      return (
        <ConversionScreen
          filename={state.filename}
          stages={convertStages}
          startedAt={convertStartedAt}
          progress={state.progress}
        />
      );

    // The same screen in three positions of one sequence. `CONVERTED` and
    // `VALIDATING` both show an unverified result, because until the checks
    // have returned that is what it is; `validating` only says whether the
    // page is still waiting to be able to say more.
    case "CONVERTED":
    case "VALIDATING":
      return (
        <ResultsScreen
          conversion={state.conversion}
          analysis={state.analysis}
          filename={state.filename}
          projectId={state.project.project_id}
          stages={convertStages}
          totalElapsedMs={convertTotalMs}
          validation={null}
          validating={state.name === "VALIDATING"}
          aiAvailable={aiAvailable}
        />
      );

    case "COMPLETED":
      return (
        <ResultsScreen
          conversion={state.conversion}
          analysis={state.analysis}
          filename={state.filename}
          projectId={state.project.project_id}
          stages={convertStages}
          totalElapsedMs={convertTotalMs}
          validation={state.validation}
          validating={false}
          aiAvailable={aiAvailable}
        />
      );

    default:
      return <NotBuiltYet />;
  }
}

function NoDirection() {
  return (
    <section aria-labelledby="no-direction" className="panel p-6 sm:p-8">
      <h1
        id="no-direction"
        className="text-2xl font-semibold tracking-tight text-ink"
      >
        Choose a direction first
      </h1>
      <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-muted">
        A migration needs a starting tool and a destination before there is
        anything to open. Only Tableau → Power BI is available today; the reverse
        has no engine behind it yet (ADR-005).
      </p>
      <p className="mt-5">
        <Link className="btn" href="/classic">
          Choose a direction
          <ArrowRightIcon className="h-4 w-4" />
        </Link>
      </p>
    </section>
  );
}

function NotBuiltYet() {
  return (
    <section className="panel p-6 sm:p-8">
      <h1 className="text-2xl font-semibold tracking-tight text-ink">
        That step is still being built
      </h1>
      <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-muted">
        Validation comes next: the structural, semantic and visual checks that
        decide whether a conversion may be called verified. Nothing here is a
        placeholder for output that does not exist.
      </p>
    </section>
  );
}

function headingFor(origin: MachineState): string {
  switch (origin.name) {
    case "SOURCE_SELECTED":
      return "We could not open the migration";
    case "UPLOADING":
      return "We could not send the workbook";
    case "ANALYZING":
      return "We could not read the workbook";
    case "CONFIGURING":
    case "CONVERTING":
      return "We could not convert the workbook";
    default:
      return "That did not go through";
  }
}

function railNote(state: MachineState) {
  const current = resumable(state);
  if (state.name === "ERROR") {
    return "The run stopped where it was. Retrying picks it up from there rather than starting again.";
  }
  switch (current.name) {
    case "IDLE":
      return "Nothing has left this machine.";
    case "SOURCE_SELECTED":
      return "Choose a workbook. Nothing is sent until you ask for the analysis.";
    case "UPLOADING":
      return "Sending the workbook to the service on this machine.";
    case "ANALYZING":
      return "Reading the workbook. No conversion has started.";
    case "ANALYSIS_READY":
      return "Read and counted. Nothing has been converted.";
    case "CONFIGURING":
      return "Deciding how this is converted. Nothing has been produced yet.";
    case "CONVERTING":
      return "Converting. The checks run once there is something to check.";
    case "CONVERTED":
    case "VALIDATING":
      return "Converted and downloadable. Checking it against the workbook now.";
    case "COMPLETED":
      return "Converted, downloadable, and checked. The verdict is on this page.";
    default:
      return null;
  }
}

function incomplete(analysis: Analysis): ApiError {
  return {
    category: "METADATA_ERROR",
    message:
      "The analysis did not finish, so there are no counts to show. Nothing " +
      "has been converted and nothing was changed.",
    detail: `analysis ${analysis.analysis_id} returned status ${analysis.status}`,
    request_id: "",
    project_id: null,
  };
}

/* ---------------------------------------------------------------------- */

/**
 * Dev-only screen previews.
 *
 * `?preview=upload|analysing|ready|convert|converting|results|error` renders a
 * screen from a fixture so it
 * can be looked at and screenshotted without a gateway. It is guarded by
 * `process.env.NODE_ENV`, which Next replaces at build time, so the branch and
 * the dynamically imported fixture are both eliminated from a production
 * bundle.
 *
 * It never touches the state machine — a preview must not be able to move the
 * real flow — and every preview carries a banner saying the numbers are sample
 * data. §63 has no development exception.
 */
type PreviewData = {
  readonly analysis: Analysis;
  readonly filename: string;
  readonly stages: readonly RunStage[];
  readonly running: readonly RunStage[];
  readonly error: ApiError;
  readonly conversion: Conversion;
  readonly conversionStages: readonly RunStage[];
  readonly conversionRunning: readonly RunStage[];
  readonly validation: Validation;
};

function usePreview(name: string | null): ReactElement | null {
  const [data, setData] = useState<PreviewData | null>(null);
  const wanted = process.env.NODE_ENV !== "production" ? name : null;

  useEffect(() => {
    if (wanted === null) return;
    let live = true;
    // The `import()` sits *inside* the constant condition, not after an early
    // return from it. webpack evaluates `process.env.NODE_ENV` at parse time
    // and never creates the dependency for a block it can prove is dead — with
    // the check written as a guard clause instead, the fixture chunk is still
    // emitted and shipped, which is exactly what an earlier version of this
    // file did. `grep -rl "sample fixture" .next/static` is the check.
    if (process.env.NODE_ENV !== "production") {
      void import("@/lib/api/devFixture").then((fixture) => {
        if (!live) return;
        setData({
          analysis: fixture.DEV_ANALYSIS,
          filename: fixture.DEV_FILENAME,
          stages: fixture.DEV_STAGES,
          running: fixture.DEV_STAGES_RUNNING,
          error: fixture.DEV_ERROR,
          conversion: fixture.DEV_CONVERSION,
          conversionStages: fixture.DEV_CONVERSION_STAGES,
          conversionRunning: fixture.DEV_CONVERSION_STAGES_RUNNING,
          validation: fixture.DEV_VALIDATION,
        });
      });
    }
    return () => {
      live = false;
    };
  }, [wanted]);

  if (wanted === null || data === null) return null;

  const body =
    wanted === "ready" ? (
      <MetadataDashboard
        analysis={data.analysis}
        filename={data.filename}
        stages={data.stages}
        totalElapsedMs={151.2}
        onConvert={() => undefined}
      />
    ) : wanted === "convert" ? (
      <ConvertScreen
        analysis={data.analysis}
        filename={data.filename}
        probe={{
          phase: "ready",
          health: {
            status: "ok",
            version: "0.1.0",
            privacy_mode: "local_only",
            ai_available: false,
          },
        }}
        onConvert={() => undefined}
        onCancel={() => undefined}
      />
    ) : wanted === "converting" ? (
      <ConversionScreen
        filename={data.filename}
        stages={data.conversionRunning}
        startedAt={null}
        progress={null}
      />
    ) : wanted === "results" ? (
      <ResultsScreen
        conversion={data.conversion}
        analysis={data.analysis}
        filename={data.filename}
        projectId="3f2b1c9a-77d0-4e2b-9c31-5a8e0b4f6d12"
        stages={data.conversionStages}
        totalElapsedMs={622.0}
        validation={data.validation}
        validating={false}
      />
    ) : wanted === "analysing" || wanted === "analyzing" ? (
      <AnalysisScreen
        filename={data.filename}
        stages={data.running}
        startedAt={null}
      />
    ) : wanted === "error" ? (
      <ErrorPanel error={data.error} heading="We could not read the workbook">
        <span className="btn">
          <RetryIcon className="h-4 w-4" />
          Try that again
        </span>
        <span className="btn btn-quiet">
          <CloseIcon className="h-4 w-4" />
          Start over
        </span>
      </ErrorPanel>
    ) : (
      <UploadScreen
        source="tableau"
        target="powerbi"
        file={null}
        refusal={null}
        onAccepted={() => undefined}
        onRefused={() => undefined}
        onCleared={() => undefined}
        onStart={() => undefined}
      />
    );

  return (
    <div className="space-y-6">
      <p
        role="note"
        className="panel border-line-strong px-4 py-3 text-sm text-warning"
      >
        <strong className="font-semibold">Sample data — development preview.</strong>{" "}
        <span className="text-ink-muted">
          Nothing on this page was measured from a workbook. It exists so the
          screen can be reviewed without a gateway, and it is not in a production
          build.
        </span>
      </p>
      {body}
    </div>
  );
}
