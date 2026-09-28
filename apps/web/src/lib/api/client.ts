/**
 * The only place the web app talks to the gateway.
 *
 * AGENTS.md rule 8: conversion logic never lives in a React component. Nor does
 * transport. Components call a named function here and receive a contract type;
 * they never see a URL, a status code, or a raw response.
 *
 * AGENTS.md rule 5: nothing crosses this boundary untyped. Every shape below is
 * imported from `src/types/contracts.ts`, which is generated from Pydantic.
 */

import type {
  AssistantStepRequest,
  AssistantStepResult,
  Analysis,
  ApiError,
  Artifact,
  Conversion,
  ConversionRequest,
  CreateProjectRequest,
  ErrorCategory,
  HealthResponse,
  Job,
  LicenseStatusResponse,
  DirectionList,
  CreateUserRequest,
  UpdateUserRequest,
  UserList,
  LoginRequest,
  Project,
  ProjectFile,
  ProjectFiles,
  ProposalReview,
  ProposalSet,
  ProviderSettings,
  UserAccount,
  Validation,
  ReportExplorer,
  WorkspaceCommit,
  WorkspaceModel,
} from "@/types/contracts";

/**
 * In Local/air-gapped mode this is a loopback address and nothing else is ever
 * contacted (ADR-006, §51).
 */
export const API_BASE_URL: string =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const API_PREFIX = "/api/v1";

/**
 * A failed call, carrying the contract error whole.
 *
 * `payload.message` is written for a person and is the only part a screen may
 * show by default. `payload.detail` is written for an engineer and belongs
 * behind *View technical details* — present, but disclosed rather than
 * displayed (05-api-spec.md, §46).
 */
export class ApiRequestError extends Error {
  readonly payload: ApiError;
  /**
   * The HTTP status, or `0` when the request never got an answer.
   *
   * Carried because the *category* cannot always stand in for it. `P7.1` made
   * "not signed in" (401) and "signed in and not allowed" (403) one category
   * deliberately - a client needs to send the user somewhere in both cases -
   * and the session gate has to tell them apart to decide whether to show the
   * sign-in form or an error. Without this the two are indistinguishable and a
   * forbidden action would sign someone out.
   */
  readonly status: number;

  constructor(payload: ApiError, status = 0) {
    super(payload.message);
    this.name = "ApiRequestError";
    this.payload = payload;
    this.status = status;
  }

  get category(): ErrorCategory {
    return this.payload.category;
  }

  /** Empty when the server sent nothing an engineer could act on. */
  get detail(): string {
    return this.payload.detail ?? "";
  }
}

/** Narrow an unknown JSON body to the contract error without asserting. */
function asApiError(body: unknown): ApiError | null {
  if (typeof body !== "object" || body === null) return null;
  const record = body as Record<string, unknown>;
  if (typeof record.category !== "string") return null;
  if (typeof record.message !== "string") return null;
  return {
    category: record.category as ErrorCategory,
    message: record.message,
    detail: typeof record.detail === "string" ? record.detail : "",
    request_id: typeof record.request_id === "string" ? record.request_id : "",
    project_id: typeof record.project_id === "string" ? record.project_id : null,
  };
}

/**
 * Build the error the UI shows when the server could not answer in its own
 * words — an unreachable gateway, a proxy's HTML page, a truncated body.
 *
 * The message stays in the interface's voice and carries no status code; the
 * code goes to `detail`, where an engineer will look for it (03-ux-spec.md,
 * "Copy").
 */
function fallbackError(message: string, detail: string): ApiError {
  return {
    category: "SYSTEM_ERROR",
    message,
    detail,
    request_id: "",
    project_id: null,
  };
}

interface RequestOptions {
  readonly signal?: AbortSignal;
  /** Defaults to GET. Every verb goes through the one error path below. */
  readonly method?: "GET" | "POST" | "PUT" | "PATCH";
  /** A JSON body, or a FormData body for multipart. Never both. */
  readonly body?: unknown;
}

/**
 * Build the request init for a body the caller supplied.
 *
 * FormData sets its own `Content-Type` including the multipart boundary, so
 * naming a content type here would produce a body the server cannot split.
 */
function encodeBody(body: unknown): {
  headers: Record<string, string>;
  payload: BodyInit | undefined;
} {
  if (body === undefined) return { headers: {}, payload: undefined };
  if (typeof FormData !== "undefined" && body instanceof FormData) {
    return { headers: {}, payload: body };
  }
  return {
    headers: { "Content-Type": "application/json" },
    payload: JSON.stringify(body),
  };
}

/**
 * Send the session cookie with every request (`P7.1`).
 *
 * The cookie is `httpOnly`, so the page cannot read it and cannot attach it by
 * hand - the browser has to, and it only does when the request asks. Without
 * this every call is anonymous and every gated route answers 401, which is
 * exactly what a browser does *silently*: the request succeeds, the response is
 * a refusal, and nothing in the network tab says "no credentials were offered".
 *
 * In development the web app is on :3000 and the API on :8000. Those are
 * different origins, which is why `credentials` is needed at all - but they are
 * the same *site* (`SameSite` compares registrable domains, and both are
 * `localhost`), so a `Lax` cookie is still sent. In production they belong
 * behind one origin.
 */
const WITH_SESSION: RequestCredentials = "include";

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? "GET";
  const url = `${API_BASE_URL}${API_PREFIX}${path}`;
  const { headers, payload } = encodeBody(options.body);
  let response: Response;

  try {
    response = await fetch(url, {
      method,
      headers: { Accept: "application/json", ...headers },
      credentials: WITH_SESSION,
      cache: "no-store",
      ...(payload === undefined ? {} : { body: payload }),
      ...(options.signal ? { signal: options.signal } : {}),
    });
  } catch (cause) {
    throw new ApiRequestError(
      fallbackError(
        "We cannot reach the DashboardBridge service. Check that it is running, then try again.",
        `${method} ${url} — ${cause instanceof Error ? cause.message : String(cause)}`,
      ),
    );
  }

  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (!response.ok) {
    const contractError = asApiError(body);
    throw new ApiRequestError(
      contractError ??
        fallbackError(
          "The service could not complete that request.",
          `${method} ${url} responded ${response.status} ${response.statusText}`,
        ),
      response.status,
    );
  }

  if (body === null) {
    throw new ApiRequestError(
      fallbackError(
        "The service replied with something we could not read.",
        `${method} ${url} returned a body that is not JSON`,
      ),
    );
  }

  return body as T;
}

/**
 * Capability probe. The UI reads this to know what it may offer — notably
 * whether AI exists at all. When `ai_available` is false, AI is absent from the
 * interface, not shown and disabled: offering a control that cannot work is a
 * promise the product cannot keep.
 */
export function health(options: RequestOptions = {}): Promise<HealthResponse> {
  return request<HealthResponse>("/health", options);
}

/**
 * The licence this deployment runs under (`P7.1`).
 *
 * Read-only, and it never carries the token: the screen needs the customer, the
 * expiry and the days left, and a signed string on the wire is a signed string
 * in somebody's proxy log. There is no route to install one either - that is
 * putting a file on the machine and restarting, which is an operator's job.
 */
export function license(
  options: RequestOptions = {},
): Promise<LicenseStatusResponse> {
  return request<LicenseStatusResponse>("/license", options);
}

/** Which migration directions this deployment has an installed, licensed engine for. */
export function directions(options: RequestOptions = {}): Promise<DirectionList> {
  return request<DirectionList>("/directions", options);
}

/**
 * Sign in (`P7.1`). The session arrives as an `httpOnly` cookie the browser
 * keeps; nothing here holds a token, which is the point.
 */
export function login(
  body: LoginRequest,
  options: RequestOptions = {},
): Promise<UserAccount> {
  return request<UserAccount>("/auth/login", { ...options, method: "POST", body });
}

export function logout(options: RequestOptions = {}): Promise<unknown> {
  return request<unknown>("/auth/logout", { ...options, method: "POST" });
}

/**
 * Who is signed in. A 401 is the ordinary answer for "nobody", so callers
 * handle `ApiRequestError` rather than expecting a null user - the server
 * deliberately does not return `200` with an empty body, because that shape is
 * what makes a client forget to check.
 */
export function me(options: RequestOptions = {}): Promise<UserAccount> {
  return request<UserAccount>("/auth/me", options);
}

/** Everyone on this deployment, with seats. Administrators only. */
export function listUsers(options: RequestOptions = {}): Promise<UserList> {
  return request<UserList>("/users", options);
}

/** Add a person, with the products they may use. Administrators only. */
export function addUser(body: CreateUserRequest, options: RequestOptions = {}): Promise<UserAccount> {
  return request<UserAccount>("/users", { ...options, method: "POST", body });
}

/** Change someone's active/admin state or product access. Administrators only. */
export function updateUser(userId: string, body: UpdateUserRequest, options: RequestOptions = {}): Promise<UserAccount> {
  return request<UserAccount>(`/users/${userId}`, { ...options, method: "PATCH", body });
}

/**
 * Open a migration. The project is the thing everything else hangs from: an
 * artifact with nowhere to belong is not stored (05-api-spec.md, Artifacts).
 */
export function createProject(
  body: CreateProjectRequest,
  options: RequestOptions = {},
): Promise<Project> {
  return request<Project>("/projects", { ...options, method: "POST", body });
}

/**
 * Send the workbook. The multipart field is named `file`, which is what the
 * gateway's handler binds; renaming it here would produce a 422 the user could
 * do nothing about.
 *
 * The server re-validates extension, MIME, declared and streamed size, archive
 * limits and platform detection before a byte reaches storage. The checks in
 * `@/lib/upload/precheck` are a courtesy that saves a doomed upload — they are
 * not a security boundary and removing the server's copy would not be safe.
 */
export function uploadArtifact(
  projectId: string,
  file: File,
  options: RequestOptions = {},
): Promise<Artifact> {
  const form = new FormData();
  form.append("file", file, file.name);
  return request<Artifact>(`/projects/${projectId}/artifacts`, {
    ...options,
    method: "POST",
    body: form,
  });
}

/** 202 → a Job. Long work never blocks the request (05-api-spec.md). */
export function startAnalysis(
  projectId: string,
  options: RequestOptions = {},
): Promise<Job> {
  return request<Job>(`/projects/${projectId}/analysis`, {
    ...options,
    method: "POST",
  });
}

/** The finished analysis: inventory, complexity, compatibility, flags. */
export function getAnalysis(
  projectId: string,
  options: RequestOptions = {},
): Promise<Analysis> {
  return request<Analysis>(`/projects/${projectId}/analysis`, options);
}

/**
 * Ask for the conversion. `202` → a `Job`; the outcome is read back separately.
 *
 * The body is the whole of the AI decision (03-ux-spec.md: `CONFIGURING` is
 * client-only and "the configuration it collects becomes the body of
 * `POST /conversion`"). It is passed through exactly as the screen collected
 * it — in particular `ai_enabled: true` with `provider: "none"` is *not*
 * repaired here. The server refuses that contradiction, and guessing an intent
 * would be exactly the wrong instinct (05-api-spec.md, Conversion).
 */
export function startConversion(
  projectId: string,
  body: ConversionRequest,
  options: RequestOptions = {},
): Promise<Job> {
  return request<Job>(`/projects/${projectId}/conversion`, {
    ...options,
    method: "POST",
    body,
  });
}

/**
 * The conversion as it stands: status, counts, flags, and the id of what was
 * produced. Polled until the status is terminal.
 *
 * A `404 NOT_FOUND` here means *not yet*, not *never*: the contract returns
 * `202` before there is a result to read. The poller in `./run` treats that
 * category as "keep waiting" and every other error as a failure.
 */
export function getConversion(
  projectId: string,
  options: RequestOptions = {},
): Promise<Conversion> {
  return request<Conversion>(`/projects/${projectId}/conversion`, options);
}

/**
 * Ask for the conversion to be validated. `202` -> a `Job`, read back below.
 *
 * `409 VALIDATION_ERROR` means there is nothing to validate yet: a conversion
 * has to have produced something before anything can be checked against it.
 */
export function startValidation(
  projectId: string,
  options: RequestOptions = {},
): Promise<Job> {
  return request<Job>(`/projects/${projectId}/validation`, {
    ...options,
    method: "POST",
  });
}

/**
 * The validation as it stands: verdict, score, the formula that produced the
 * score, and every rule with its note.
 *
 * A `404 NOT_FOUND` here means validation has not run, which is a different
 * thing from a conversion that failed validation. The results screen says
 * "Unverified" for the first and "Failed" for the second, and conflating them
 * would be the exact overstatement the verdict vocabulary exists to prevent.
 */
export function getValidation(
  projectId: string,
  options: RequestOptions = {},
): Promise<Validation> {
  return request<Validation>(`/projects/${projectId}/validation`, options);
}

/** What came back from the artifact endpoint, with the name to save it under. */
export interface DownloadedArtifact {
  readonly blob: Blob;
  readonly filename: string;
}

/**
 * Read `filename` out of a `content-disposition` header.
 *
 * Returns null far more often than you would expect: a browser can only read a
 * response header the server has listed in `Access-Control-Expose-Headers`, and
 * the gateway currently exposes `x-request-id` and `x-next-cursor` only. So the
 * caller must supply a name it can defend, and this is an improvement on it
 * when the header is actually reachable.
 */
function filenameFrom(header: string | null): string | null {
  if (header === null) return null;
  const encoded = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (encoded?.[1]) {
    try {
      return decodeURIComponent(encoded[1]);
    } catch {
      /* A malformed header is not a reason to fail the download. */
    }
  }
  const quoted = header.match(/filename="([^"]+)"/i) ?? header.match(/filename=([^;]+)/i);
  return quoted?.[1]?.trim() ?? null;
}

/**
 * Download the produced project.
 *
 * This is the one response that is not JSON, so it does not go through
 * `request()`. It goes through the same *error* path, though: a `409` while the
 * conversion is unfinished arrives as the contract error and reaches the screen
 * with a message for a person and a detail for an engineer. A partial artifact
 * is never served as if it were finished (05-api-spec.md, Artifact download).
 */
/**
 * What the service will say about its model configuration (`P4.7`).
 *
 * Never carries a key: the endpoint has no field for one, and there is no
 * route that accepts one either. What comes back is which provider, whether a
 * credential is present, whether it is usable, and - when it is not - which of
 * the several different "no"s this is.
 */
export function getAiSettings(
  options: RequestOptions = {},
): Promise<ProviderSettings> {
  return request<ProviderSettings>("/settings/ai", options);
}

/**
 * Ask a model about everything the converter refused (`P4.6`).
 *
 * A POST because it is not free: it reaches a model, and it writes the
 * proposals so a decision has something durable to attach to. It applies
 * nothing.
 */
export function createProposals(
  projectId: string,
  options: RequestOptions = {},
): Promise<ProposalSet> {
  return request<ProposalSet>(`/projects/${projectId}/proposals`, {
    ...options,
    method: "POST",
  });
}

/** What was drafted before, with decisions as they stand. Never re-asks. */
export function getProposals(
  projectId: string,
  options: RequestOptions = {},
): Promise<ProposalSet> {
  return request<ProposalSet>(`/projects/${projectId}/proposals`, options);
}

/**
 * Record a person's decision - the only way a proposal is ever accepted.
 *
 * `pending` is deliberately not offerable: it is where a proposal starts, not
 * something anyone decides, and being able to send it would let the UI quietly
 * un-review something.
 */
export function decideProposal(
  projectId: string,
  proposalId: string,
  decision: "accepted" | "rejected",
  options: RequestOptions = {},
): Promise<ProposalReview> {
  return request<ProposalReview>(
    `/projects/${projectId}/proposals/${proposalId}/${decision}`,
    { ...options, method: "POST" },
  );
}

export function downloadArtifact(
  projectId: string,
  fallbackFilename: string,
  options: RequestOptions = {},
): Promise<DownloadedArtifact> {
  return downloadFrom(
    `/projects/${projectId}/artifact`,
    fallbackFilename,
    "The produced project could not be downloaded.",
    options,
  );
}

/** What a job's Files tab offers: only files that exist, and why not when not. */
export function getProjectFiles(projectId: string, options: RequestOptions = {}): Promise<ProjectFiles> {
  return request<ProjectFiles>(`/projects/${projectId}/files`, options);
}

/** One of the files `getProjectFiles` listed, by the path it gave. */
export function downloadProjectFile(file: ProjectFile, options: RequestOptions = {}): Promise<DownloadedArtifact> {
  return downloadFrom(file.href, file.filename, `${file.label} could not be downloaded.`, options);
}

async function downloadFrom(
  path: string,
  fallbackFilename: string,
  failure: string,
  options: RequestOptions = {},
): Promise<DownloadedArtifact> {
  const url = `${API_BASE_URL}${API_PREFIX}${path}`;
  let response: Response;

  try {
    response = await fetch(url, {
      method: "GET",
      headers: { Accept: "application/octet-stream, application/json" },
      credentials: WITH_SESSION,
      cache: "no-store",
      ...(options.signal ? { signal: options.signal } : {}),
    });
  } catch (cause) {
    throw new ApiRequestError(
      fallbackError(
        "We cannot reach the DashboardBridge service. Check that it is running, then try again.",
        `GET ${url} — ${cause instanceof Error ? cause.message : String(cause)}`,
      ),
    );
  }

  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    throw new ApiRequestError(
      asApiError(body) ??
        fallbackError(
          failure,
          `GET ${url} responded ${response.status} ${response.statusText}`,
        ),
    );
  }

  return {
    blob: await response.blob(),
    filename:
      filenameFrom(response.headers.get("content-disposition")) ??
      fallbackFilename,
  };
}

/**
 * Narrow any thrown value to the contract error, so a screen always has a
 * `message` for a person and a `detail` for an engineer — never a bare string
 * and never an HTTP code (05-api-spec.md, Errors).
 */
export function toApiError(cause: unknown): ApiError {
  if (cause instanceof ApiRequestError) return cause.payload;
  return fallbackError(
    "Something went wrong on this machine before the service was reached.",
    cause instanceof Error ? `${cause.name}: ${cause.message}` : String(cause),
  );
}


/* -------------------------------------------------------------------------
 * The migrator screens: jobs, their recorded run, and the workspace.
 * ---------------------------------------------------------------------- */

export function listProjects(options: RequestOptions = {}): Promise<Project[]> {
  return request<Project[]>("/projects", options);
}

export function getProject(projectId: string, options: RequestOptions = {}): Promise<Project> {
  return request<Project>(`/projects/${projectId}`, options);
}

export function getWorkspace(
  projectId: string,
  options: RequestOptions = {},
): Promise<WorkspaceModel> {
  return request<WorkspaceModel>(`/projects/${projectId}/workspace`, options);
}

export function saveWorkspaceVersion(
  projectId: string,
  body: WorkspaceCommit,
  options: RequestOptions = {},
): Promise<WorkspaceModel> {
  return request<WorkspaceModel>(`/projects/${projectId}/workspace/versions`, {
    ...options,
    method: "POST",
    body,
  });
}

/** A text resource, through the same error path as every JSON one. */
async function requestText(path: string, options: RequestOptions = {}): Promise<string> {
  const url = `${API_BASE_URL}${API_PREFIX}${path}`;
  let response: Response;
  try {
    response = await fetch(url, {
      credentials: WITH_SESSION,
      cache: "no-store",
      ...(options.signal ? { signal: options.signal } : {}),
    });
  } catch (cause) {
    throw new ApiRequestError(
      fallbackError(
        "We cannot reach the DashboardBridge service. Check that it is running, then try again.",
        `GET ${url} — ${cause instanceof Error ? cause.message : String(cause)}`,
      ),
    );
  }
  const text = await response.text();
  if (!response.ok) {
    let body: unknown = null;
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
    throw new ApiRequestError(
      asApiError(body) ??
        fallbackError(
          "The service could not complete that request.",
          `GET ${url} responded ${response.status} ${response.statusText}`,
        ),
      response.status,
    );
  }
  return text;
}

export function getWorkspaceFile(
  projectId: string,
  path: string,
  options: RequestOptions = {},
): Promise<string> {
  return requestText(
    `/projects/${projectId}/workspace/file?path=${encodeURIComponent(path)}`,
    options,
  );
}

/** One item the engine handled, as the recorded run reports it. */
export interface RecordedEvent {
  readonly name: string;
  readonly outcome: string;
  readonly stage: string;
  readonly kind: string;
  readonly detail: string;
  readonly ref: string;
  readonly source: string;
  readonly result: string;
  readonly elapsed_ms: number;
}

export interface RecordedRun {
  readonly events: readonly RecordedEvent[];
  readonly durationMs: number;
}

/**
 * The finished conversion's recording, read in one request.
 *
 * The gateway serves it as server-sent events because the desktop replay
 * consumes it that way. It is a *finished* run, so there is nothing to wait
 * for: reading the whole stream and parsing it is the same data without a
 * connection held open.
 */
export async function getRecordedRun(
  projectId: string,
  options: RequestOptions = {},
): Promise<RecordedRun> {
  const text = await requestText(`/projects/${projectId}/events`, options);
  const events: RecordedEvent[] = [];
  let durationMs = 0;
  for (const frame of text.split(/\r?\n\r?\n/)) {
    const name = /^event: (.*)$/m.exec(frame)?.[1];
    const data = /^data: (.*)$/m.exec(frame)?.[1];
    if (!name || !data) continue;
    const parsed = JSON.parse(data) as Record<string, unknown>;
    if (name === "conversion.item") events.push(parsed as unknown as RecordedEvent);
    if (name === "conversion.completed") durationMs = Number(parsed.duration_ms ?? 0);
  }
  return { events, durationMs };
}

export function reportUrl(projectId: string): string {
  return `${API_BASE_URL}${API_PREFIX}/projects/${projectId}/report?format=html`;
}

export function getReportExplorer(
  projectId: string,
  options: RequestOptions = {},
): Promise<ReportExplorer> {
  return request<ReportExplorer>(`/projects/${projectId}/workspace/report`, options);
}

/** The newest version as a .pbip archive carrying only the chosen visuals. */
export async function publishSelection(
  projectId: string,
  visualIds: readonly string[],
  fallbackFilename: string,
): Promise<DownloadedArtifact> {
  const url = `${API_BASE_URL}${API_PREFIX}/projects/${projectId}/workspace/publish`;
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/zip, application/json" },
      credentials: WITH_SESSION,
      cache: "no-store",
      body: JSON.stringify({ visual_ids: visualIds }),
    });
  } catch (cause) {
    throw new ApiRequestError(
      fallbackError(
        "We cannot reach the DashboardBridge service. Check that it is running, then try again.",
        `POST ${url} — ${cause instanceof Error ? cause.message : String(cause)}`,
      ),
    );
  }
  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    throw new ApiRequestError(
      asApiError(body) ??
        fallbackError(
          "The project could not be exported.",
          `POST ${url} responded ${response.status} ${response.statusText}`,
        ),
      response.status,
    );
  }
  return {
    blob: await response.blob(),
    filename: filenameFrom(response.headers.get("content-disposition")) ?? fallbackFilename,
  };
}

export type AssistantStepName = AssistantStepResult["step"];

export function runAssistantStep(
  projectId: string,
  step: AssistantStepName,
  body: AssistantStepRequest = {},
  options: RequestOptions = {},
): Promise<AssistantStepResult> {
  return request<AssistantStepResult>(`/projects/${projectId}/workspace/assistant/${step}`, {
    ...options,
    method: "POST",
    body,
  });
}
