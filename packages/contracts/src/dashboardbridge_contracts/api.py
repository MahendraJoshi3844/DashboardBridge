"""API request/response contracts. See docs/dashboardbridge/05-api-spec.md.

Nothing untyped crosses a service boundary (§45). These models are the single
source of truth and are generated into TypeScript for the web app.
"""

from __future__ import annotations

from typing import Literal
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .canonical import CanonicalModel, ConversionFlag
from .enums import (
    ArtifactKind,
    ErrorCategory,
    JobKind,
    JobStatus,
    Outcome,
    Platform,
    ProposalDecision,
    PrivacyMode,
    ProviderKind,
    Stage,
    Verdict,
    DirectionState,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------
# projects
# --------------------------------------------------------------------------


class CreateProjectRequest(ApiModel):
    source_platform: Platform
    target_platform: Platform
    name: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def platforms_must_differ(self) -> CreateProjectRequest:
        if self.source_platform == self.target_platform:
            raise ValueError("source_platform and target_platform must differ")
        return self


class Project(ApiModel):
    project_id: UUID
    name: str
    source_platform: Platform
    target_platform: Platform
    created_at: datetime


class Artifact(ApiModel):
    artifact_id: UUID
    kind: ArtifactKind = ArtifactKind.SOURCE
    filename: str = Field(description="Sanitised. Never used as a path.")
    size_bytes: int
    sha256: str
    detected_platform: Platform | None = None


# --------------------------------------------------------------------------
# jobs and events
# --------------------------------------------------------------------------


class Job(ApiModel):
    job_id: UUID
    kind: JobKind
    status: JobStatus
    stage: Stage | None = None


class ProgressEvent(ApiModel):
    """Emitted from a real EventSink. Never synthesised to smooth a bar."""

    stage: Stage
    completed: int
    total: int


class ItemEvent(ApiModel):
    kind: str
    name: str
    outcome: str
    method: str
    ref: str = ""


# --------------------------------------------------------------------------
# analysis
# --------------------------------------------------------------------------


class Inventory(ApiModel):
    datasources: int = 0
    tables: int = 0
    columns: int = 0
    calculations: int = 0
    visuals: int = 0
    parameters: int = 0
    relationships: int = 0
    dashboards: int = 0


class Complexity(ApiModel):
    score: float = Field(ge=0.0, le=1.0)
    band: str
    formula: str = Field(
        description="Returned so the UI can show the derivation. A score whose "
        "derivation a reader cannot follow is decoration."
    )


class Compatibility(ApiModel):
    converted: int = 0
    partial: int = 0
    ai_required: int = 0
    unsupported: int = 0
    failed: int = 0
    total: int = 0


class Analysis(ApiModel):
    analysis_id: UUID
    status: JobStatus
    model: CanonicalModel | None = None
    inventory: Inventory = Field(default_factory=Inventory)
    complexity: Complexity | None = None
    compatibility: Compatibility = Field(default_factory=Compatibility)
    flags: list[ConversionFlag] = Field(default_factory=list)


# --------------------------------------------------------------------------
# conversion
# --------------------------------------------------------------------------


class ConversionRequest(ApiModel):
    ai_enabled: bool = False
    provider: ProviderKind = ProviderKind.NONE
    privacy_mode: PrivacyMode = PrivacyMode.STANDARD

    @model_validator(mode="after")
    def ai_needs_a_provider(self) -> ConversionRequest:
        # Contradictory request. Guessing an intent here would be exactly the
        # wrong instinct for this product.
        if self.ai_enabled and self.provider is ProviderKind.NONE:
            raise ValueError("ai_enabled requires a provider other than 'none'")
        if self.privacy_mode is PrivacyMode.LOCAL_ONLY and self.provider is (
            ProviderKind.OPENAI_COMPATIBLE
        ):
            raise ValueError(
                "local_only forbids a remote provider; use 'ollama' or 'none'"
            )
        return self


class Conversion(ApiModel):
    conversion_id: UUID
    status: JobStatus
    compatibility: Compatibility = Field(default_factory=Compatibility)
    model: CanonicalModel | None = Field(
        default=None,
        description="The produced model, with translations filled in. The "
        "comparison view puts each source expression beside its target, so "
        "without this that column is empty for every row.",
    )
    artifact_id: UUID | None = None
    flags: list[ConversionFlag] = Field(default_factory=list)


class ProjectFile(ApiModel):
    """One file a finished job offers for download."""

    kind: Literal["extraction", "target", "validation_report"]
    label: str
    filename: str
    size_bytes: int = Field(ge=0)
    #: API path, relative to the API prefix, that serves it.
    href: str


class ProjectFiles(ApiModel):
    """What a job's Files tab offers. Only files that exist are listed."""

    files: list[ProjectFile] = Field(default_factory=list)
    extraction_available: bool = False
    #: Why there are no extracted files, when there are none - said plainly
    #: rather than left as an empty list a person has to interpret.
    note: str | None = None
    #: "PASSED" / "FAILED" from the extracted validation report, when there is one.
    validation: str | None = None


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------


class CategoryScore(ApiModel):
    score: float = Field(ge=0.0, le=1.0)
    checks: int
    passed: int


class NumericalValidation(ApiModel):
    """Always unmeasured in v1 (ADR-003).

    The field exists so the absence is explicit rather than inferred. Comparing
    results requires executing both dashboards against live data.
    """

    measured: bool = False
    reason: str = (
        "Requires executing both dashboards against live data; not available "
        "offline."
    )


class ValidationRuleResult(ApiModel):
    rule_id: str
    status: str
    note: str = ""


class Validation(ApiModel):
    validation_id: UUID
    status: JobStatus
    verdict: Verdict = Verdict.UNVERIFIED
    score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Computed only from measured categories.",
    )
    formula: str = ""
    categories: dict[str, CategoryScore] = Field(default_factory=dict)
    numerical: NumericalValidation = Field(default_factory=NumericalValidation)
    rules: list[ValidationRuleResult] = Field(default_factory=list)


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------


class AIProposal(ApiModel):
    """A drafted translation that survived the validation gauntlet (`P4.4`).

    A proposal is something to *show a person*, never something to apply. There
    is deliberately no `applied`, `accepted` or `auto_accept` field: ADR-007
    rejects an auto-apply path outright, because it contradicts the product's
    central claim, and a field named like permission is how such a path gets
    added by accident.

    `confidence` is what the model said about itself. It orders and pre-selects
    and does nothing else - models are not calibrated, and a self-reported 0.94
    is not a 94% chance of being correct.
    """

    proposal_id: UUID
    operation: str
    source_expression: str
    target_expression: str
    explanation: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    assumptions: list[str] = Field(default_factory=list)
    #: Always true. The model does not get to mark its own work as settled.
    requires_review: bool = True
    #: High confidence moves the radio button. A person still presses it.
    preselected: bool = False
    #: What produced it, for the audit trail and the accuracy metrics (§62).
    model: str = ""
    prompt_version: int = 0


class AuditEntry(ApiModel):
    """One object the conversion handled, and what became of it (P5.7, §41).

    Taken from the engine's own recording, not reconstructed. The flags say
    what did *not* come across; this is the only record of what did, and of the
    expression each translation actually produced - which is what "defend every
    transformation to a sceptical stakeholder" needs.

    **No timing.** The event stream carries `elapsed_ms` because it is about a
    run in progress. A record of a finished run must be byte-stable, or two
    conversions of one workbook produce reports that cannot be diffed, and a
    duration differs on every run.
    """

    seq: int = Field(description="Position in the recording. Ordering, not time.")
    stage: Stage
    kind: str = Field(
        description="table | column | calc | visual | parameter | relationship"
    )
    name: str
    outcome: Outcome
    detail: str = Field(default="", description="Why it was held, or what it became.")
    ref: str = Field(default="", description="Canonical id, e.g. 'Orders.Profit'.")
    source: str = Field(default="", description="The original expression, if any.")
    result: str = Field(default="", description="What was emitted. Empty if held.")


class ProposalReview(ApiModel):
    """One proposal, with everything a reviewer needs to judge it (ADR-007).

    07-ai-engine.md: the reviewer sees the source expression, the reason the
    deterministic path refused, the proposal, its explanation and assumptions,
    **and what was sent to the model**. The last one is why `prompt_sent` is
    here: a review of a proposal without the question it answered is a review of
    half of it, and it is also the only way a person can see for themselves that
    the workbook was not sent.
    """

    item: str = Field(description="`'<table>.<name>'` - the object it is about.")
    refusal_reason: str
    proposal: AIProposal
    prompt_sent: str = Field(
        description="Verbatim. Shown to the reviewer, never re-rendered."
    )
    decision: ProposalDecision = ProposalDecision.PENDING


class SkippedItem(ApiModel):
    """An object no proposal exists for, and which of the reasons applies.

    Never merged into "no suggestion available". A model that was never asked, a
    model that declined, and a draft that failed the gauntlet are three different
    facts, and only the third one says anything about the model's answer.
    """

    item: str
    outcome: str = Field(description="Router disposition or gauntlet rejection.")
    reason: str


class ProposalSet(ApiModel):
    """Everything a model was asked about for one project, and what came back."""

    project_id: UUID
    reviews: list[ProposalReview] = Field(default_factory=list)
    skipped: list[SkippedItem] = Field(default_factory=list)
    #: Stated even when nothing was produced, because an empty list with no
    #: explanation reads as "the model had nothing to say" whatever the truth.
    summary: str = ""


class ConversionReport(ApiModel):
    """The deliverable that outlives the session.

    Composed entirely of contracts that already crossed this boundary, so the
    report cannot say anything the API did not already say elsewhere. It is a
    rendering of the run, not a second opinion about it.

    `verdict` is repeated at the top level even though it also sits inside
    `validation`, because `validation` is null until the checks have run and a
    reader still needs an answer then. That answer is `unverified` - stated,
    never omitted, since an absent verdict reads as a passed one.
    """

    project: Project
    verdict: Verdict = Verdict.UNVERIFIED
    compatibility: Compatibility
    flags: list[ConversionFlag] = Field(default_factory=list)
    validation: Validation | None = None
    audit: list[AuditEntry] = Field(
        default_factory=list,
        description="The run as it was recorded, object by object. Empty when "
        "the conversion predates the recording being kept, which the report "
        "states rather than omitting the section.",
    )


# --------------------------------------------------------------------------
# errors and settings
# --------------------------------------------------------------------------


class ApiError(ApiModel):
    category: ErrorCategory
    message: str = Field(
        description="For a person. Never a stack trace, path, or HTTP code."
    )
    detail: str = Field(default="", description="For an engineer, behind a toggle.")
    request_id: str = ""
    project_id: UUID | None = None


class ProviderSettings(ApiModel):
    """Keys are write-only over the API.

    A GET never returns the value, nor a masked prefix, which leaks length and
    usually the first characters.
    """

    provider: ProviderKind = ProviderKind.NONE
    base_url: str = ""
    model: str = ""
    #: Whether a credential is present. The fact, never the value.
    configured: bool = False
    #: Whether it could actually be used right now.
    available: bool = False
    #: Empty when it is available. Otherwise the sentence saying which of the
    #: several different "no"s this is - not configured, configured but not
    #: running, or forbidden by the privacy mode. They need different actions.
    unavailable_because: str = ""


class HealthResponse(ApiModel):
    status: str
    version: str
    privacy_mode: PrivacyMode
    ai_available: bool


class UserAccount(ApiModel):
    """A person with an account on this deployment (`P7.1`).

    **There is no password field and there never will be.** The model has
    nowhere to put one, so a response cannot carry a password or its hash by
    accident - the same shape as `Artifact` having no column for bytes.
    """

    user_id: UUID
    email: str
    display_name: str = ""
    #: The only privilege that exists: may add and deactivate other people.
    #: Everyone converts, so there is no role vocabulary beyond this.
    is_admin: bool = False
    is_active: bool = True
    created_at: datetime | None = None
    last_login_at: datetime | None = None
    #: The migration products this person may use: `tableau`, `microstrategy`,
    #: `qlik`. An administrator has every licensed product whatever is listed.
    products: list[str] = Field(default_factory=list)


class LoginRequest(ApiModel):
    email: str
    password: str


class CreateUserRequest(ApiModel):
    email: str
    display_name: str = ""
    password: str
    #: Products to give the new person. `None` gives every product the licence
    #: includes - what adding someone meant before products were separate.
    products: list[str] | None = None


class UpdateUserRequest(ApiModel):
    """Only the two things an administrator may change about someone else.

    Not the password: an administrator who can set another person's password
    can sign in as them, and "who did this conversion" stops meaning anything.
    """

    is_active: bool | None = None
    is_admin: bool | None = None
    #: Replaces the person's product access when present.
    products: list[str] | None = None


class UserList(ApiModel):
    """The people on this deployment, and what the licence allows.

    The seat counts travel with the list because they are the answer to the
    question the list provokes - "can I add someone?" - and a client that has
    to make a second call to find out will show the button and then refuse.
    """

    users: list[UserAccount] = Field(default_factory=list)
    #: `None` when the licence does not state a seat count.
    seats_total: int | None = None
    seats_used: int = 0


class LicenseStatusResponse(ApiModel):
    """The licence this deployment runs under (`P7.1`).

    **Never carries the token.** The screen needs the customer, the expiry and
    the days left; it never needs the signed string, and a token on the wire is
    a token in somebody's proxy log.

    `licensed` is not the same question as "is anything wrong". A licence that
    is valid and expires in nine days is `licensed: true` with
    `expiring_soon: true` and a message - which is the whole point of warning
    before the day conversions stop rather than on it.
    """

    licensed: bool
    customer: str | None = None
    #: ISO date. A string rather than a date because it is displayed, and the
    #: only correct formatting is the reader's own locale's.
    expires: str | None = None
    days_remaining: int | None = None
    seats: int | None = None
    features: list[str] = Field(default_factory=list)
    expiring_soon: bool = False
    #: Present whenever something needs doing, including "valid, expiring soon".
    message: str | None = None


class DirectionStatus(ApiModel):
    """One migration direction and whether this deployment can run it."""

    source_platform: Platform
    target_platform: Platform
    state: DirectionState
    #: The engine that runs it, e.g. `t2pbi`, `mstr2pbi`, `qlik2pbi`.
    engine: str
    #: The installed engine's version; empty when it is not installed.
    engine_version: str = ""
    #: The licence feature that enables it, e.g. `qlik`.
    licence_feature: str
    #: Why it cannot run, for a person; empty when available.
    reason: str = ""


class DirectionList(ApiModel):
    directions: list[DirectionStatus] = Field(default_factory=list)


# --------------------------------------------------------------------------
# workspace: the produced Power BI project, read and edited after conversion
# --------------------------------------------------------------------------


class WorkspaceColumn(ApiModel):
    name: str
    data_type: str = ""


class WorkspaceMeasure(ApiModel):
    name: str
    expression: str


class WorkspacePartition(ApiModel):
    """A table's source, as written in its TMDL partition.

    `source_kind` is what the expression is written in: `m` for Power Query,
    `calculated` for a calculated table, whose source is DAX.
    """

    name: str
    mode: str = ""
    source_kind: str = "m"
    expression: str


class WorkspaceTable(ApiModel):
    name: str
    columns: list[WorkspaceColumn] = Field(default_factory=list)
    measures: list[WorkspaceMeasure] = Field(default_factory=list)
    partitions: list[WorkspacePartition] = Field(default_factory=list)


class WorkspaceFile(ApiModel):
    path: str
    size_bytes: int


class WorkspaceVersion(ApiModel):
    """One saved state of the produced project. v0 is what the converter wrote."""

    version: int
    artifact_id: UUID
    created_at: datetime
    note: str = ""


class WorkspaceHeld(ApiModel):
    """A calculation the converter refused, offered for a person to write.

    `source` is the original expression, verbatim. Nothing in the produced
    model stands for it: the converter emits no placeholder (AGENTS.md rule 1),
    so this list is the only place it appears in the workspace.
    """

    item: str
    table: str
    name: str
    source: str = ""
    reason: str


class WorkspaceModel(ApiModel):
    project_id: UUID
    name: str
    version: int
    versions: list[WorkspaceVersion] = Field(default_factory=list)
    tables: list[WorkspaceTable] = Field(default_factory=list)
    files: list[WorkspaceFile] = Field(default_factory=list)
    held: list[WorkspaceHeld] = Field(default_factory=list)


class WorkspaceEdit(ApiModel):
    """Set a measure's DAX, or a partition's Power Query, in one table.

    A measure that does not exist is added; that is how a held calculation is
    written by hand. A partition must already exist.
    """

    kind: Literal["measure", "partition"]
    table: str
    name: str
    expression: str = Field(min_length=1)


class WorkspaceCommit(ApiModel):
    """Edits saved together as one new version, on top of `base_version`.

    `base_version` makes a stale save fail loudly: two people editing the same
    version would otherwise have the second silently discard the first.
    """

    base_version: int
    note: str = ""
    edits: list[WorkspaceEdit] = Field(min_length=1)


class ReportVisual(ApiModel):
    """One Power BI visual in the produced report, and where it came from.

    `source_name` is the Tableau worksheet it was converted from and
    `source_mark` that worksheet's mark type. `status` is `converted` when no
    flag names the worksheet, `partial` when one does, and `notes` are those
    flags' reasons, verbatim.
    """

    id: str
    page_id: str
    visual_type: str
    source_name: str = ""
    source_mark: str = ""
    fields: list[str] = Field(default_factory=list)
    status: Literal["converted", "partial"] = "converted"
    notes: list[str] = Field(default_factory=list)


class ReportPage(ApiModel):
    id: str
    name: str
    width: int = 0
    height: int = 0
    visuals: list[ReportVisual] = Field(default_factory=list)
    #: Why a page carries no visual, when it carries none.
    notes: list[str] = Field(default_factory=list)


class ReportExplorer(ApiModel):
    version: int
    pages: list[ReportPage] = Field(default_factory=list)


class PublishRequest(ApiModel):
    """The visuals to carry in the exported project. Empty carries none."""

    visual_ids: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# workspace assistant: the Run menu's checks, fixes and AI advice
# --------------------------------------------------------------------------

AssistantStepName = Literal[
    "inventory",
    "check_references",
    "check_mquery",
    "model_health",
    "draft_dax",
    "format_mquery",
    "summarize",
    "chat",
]


class AssistantStepRequest(ApiModel):
    #: Which objects to work on - `Table.Name` for a measure or held
    #: calculation, a table name for a Power Query source. Empty means all.
    items: list[str] = Field(default_factory=list)
    #: The person's question, for `chat`.
    message: str = Field(default="", max_length=4000)


class AssistantMessage(ApiModel):
    role: Literal["system", "assistant"]
    text: str
    #: Set on an assistant message: which model wrote it.
    model: str = ""


class AssistantFinding(ApiModel):
    severity: Literal["info", "warning", "error"]
    item: str
    message: str
    check: str


class AssistantProposal(ApiModel):
    """A change offered to a person. Never applied by the step that made it.

    `origin` says what produced it: `rule` for a deterministic rewrite whose
    effect is stated in `reason`, `model` for a model's draft that has passed the
    proposal checks. Either way a person puts it into their draft changes, or
    does not.
    """

    kind: Literal["measure", "partition"]
    table: str
    name: str
    expression: str
    current: str = ""
    reason: str
    origin: Literal["rule", "model"]
    model: str = ""


class AssistantStepResult(ApiModel):
    step: AssistantStepName
    title: str
    messages: list[AssistantMessage] = Field(default_factory=list)
    findings: list[AssistantFinding] = Field(default_factory=list)
    proposals: list[AssistantProposal] = Field(default_factory=list)
    #: Checks that ran and how many found nothing, so a summary can state its
    #: denominator.
    checks_run: int = 0
    checks_clean: int = 0
