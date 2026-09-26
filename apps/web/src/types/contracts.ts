/**
 * GENERATED FILE — DO NOT EDIT.
 *
 * Source: packages/contracts/schema.json (Pydantic → JSON Schema).
 * Regenerate: npm run gen:types
 *
 * 85 contract definitions.
 */

/* eslint-disable */

export type ProposalId = string;
export type Operation = string;
export type SourceExpression = string;
export type TargetExpression = string;
export type Explanation = string;
export type Confidence = number;
export type Assumptions = string[];
export type RequiresReview = boolean;
export type Preselected = boolean;
export type Model = string;
export type PromptVersion = number;
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "Aggregation".
 */
export type Aggregation = "sum" | "average" | "min" | "max" | "count" | "count_distinct" | "median" | "attribute";
export type AnalysisId = string;
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "JobStatus".
 */
export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "Platform".
 */
export type Platform = "tableau" | "powerbi" | "microstrategy" | "qlik";
export type SourceVersion = string;
export type Name = string;
export type Id = string;
export type Name1 = string;
export type Connection = string;
export type IsExtract = boolean;
/**
 * The platform's own datasource id. Visual bindings are scoped by it, so a field name present in two sources binds correctly.
 */
export type SourceId = string;
export type Id1 = string;
export type Name2 = string;
/**
 * Deterministic: '<table>.<name>'. Never random.
 */
export type Id2 = string;
export type Name3 = string;
/**
 * Display name. Often differs from name; collapsing them loses data and produces references to names that do not exist.
 */
export type Caption = string | null;
export type DataType = "string" | "integer" | "decimal" | "boolean" | "date" | "datetime" | "unknown";
export type Role = string;
/**
 * Where an expression evaluates.
 *
 * The single most consequential property in the model: source tools decide
 * aggregation at query time, targets must commit at definition time. `None`
 * (absent) means the grain could not be determined, and the object is refused
 * rather than guessed.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "Grain".
 */
export type Grain = "row" | "aggregate";
/**
 * e.g. tableau_calc, dax
 */
export type SourceLanguage = string;
/**
 * Verbatim source. Untrusted: never interpolated into a prompt as instruction, only as delimited USER DATA.
 */
export type SourceText = string;
export type Table1 = string | null;
export type Column1 = string;
export type Resolved = boolean;
export type References = FieldRef[];
export type TargetLanguage = string;
export type TargetText = string;
/**
 * *How* an object was converted.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "ConversionMethod".
 */
export type ConversionMethod = "deterministic" | "rule" | "ai_assisted" | "manual";
/**
 * Every rule-pack mapping that produced this translation, sorted. Plural because one expression can fire several; empty when no mapping fired, which is a fact about the translation and not a gap - a control-flow rewrite is the translator's own work.
 */
export type RuleIds = string[];
/**
 * Set when a human accepted an AI proposal. Never set by the model itself.
 */
export type ProposalId1 = string | null;
export type Columns = Column[];
export type Tables = Table[];
export type Datasources = DataSource[];
export type FromTable = string;
export type FromColumn = string;
export type ToTable = string;
export type ToColumn = string;
export type Kind = string;
export type Relationships = Relationship[];
export type Id3 = string;
export type Name4 = string;
export type Caption1 = string;
export type DataType1 = "string" | "integer" | "decimal" | "boolean" | "date" | "datetime" | "unknown";
export type DefaultValue = string;
export type Kind1 = string;
export type MinValue = string | null;
export type MaxValue = string | null;
export type Step = string | null;
export type Members = string[];
export type Parameters = Parameter[];
export type Id4 = string;
export type Name5 = string;
export type VisualType = string;
/**
 * Platform-neutral replacement for Tableau's shelves (ADR-002).
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "BindingRole".
 */
export type BindingRole = "category" | "value" | "series" | "detail" | "tooltip" | "filter";
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "DatePart".
 */
export type DatePart = "year" | "quarter" | "month" | "week" | "day" | "hour" | "minute" | "second";
/**
 * False for constructs naming no real column. Binding one to a guess is how every visual ends up pointing at a column that does not exist.
 */
export type Resolvable = boolean;
/**
 * The original token, for the report.
 */
export type Raw = string;
export type Bindings = VisualBinding[];
export type Filters = VisualBinding[];
export type Visuals = Visual[];
export type Id5 = string;
export type Name6 = string;
export type VisualIds = string[];
export type Dashboards = Dashboard[];
export type Item = string;
/**
 * Pipeline stages. Progress events name one of these and nothing else.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "Stage".
 */
export type Stage = "extract" | "parse" | "map" | "translate" | "generate" | "validate" | "report";
/**
 * *How* an object was converted.
 */
export type ConversionMethod1 = "deterministic" | "rule" | "ai_assisted" | "manual";
/**
 * *What became of* an object.
 */
export type ConversionStatus = "converted" | "partial" | "ai_required" | "unsupported" | "failed";
/**
 * How loudly the report says so.
 */
export type Severity = "info" | "warning" | "manual";
export type Reason = string;
export type Ref = string;
export type Flags = ConversionFlag[];
export type Datasources1 = number;
export type Tables1 = number;
export type Columns1 = number;
export type Calculations = number;
export type Visuals1 = number;
export type Parameters1 = number;
export type Relationships1 = number;
export type Dashboards1 = number;
export type Score = number;
export type Band = string;
/**
 * Returned so the UI can show the derivation. A score whose derivation a reader cannot follow is decoration.
 */
export type Formula = string;
export type Converted = number;
export type Partial = number;
export type AiRequired = number;
export type Unsupported = number;
export type Failed = number;
export type Total = number;
export type Flags1 = ConversionFlag[];
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "ErrorCategory".
 */
export type ErrorCategory =
  | "UPLOAD_ERROR"
  | "PARSER_ERROR"
  | "UNSUPPORTED_ARTIFACT"
  | "METADATA_ERROR"
  | "RULE_ERROR"
  | "AI_ERROR"
  | "CONVERSION_ERROR"
  | "VALIDATION_ERROR"
  | "AUTH_ERROR"
  | "NOT_FOUND"
  | "SYSTEM_ERROR";
/**
 * For a person. Never a stack trace, path, or HTTP code.
 */
export type Message = string;
/**
 * For an engineer, behind a toggle.
 */
export type Detail = string;
export type RequestId = string;
export type ProjectId = string | null;
export type ArtifactId = string;
/**
 * An artifact is either what was uploaded or what was produced.
 *
 * GET /projects/{id}/artifact must return the target, so the distinction has
 * to exist in the contract and not only in the database.
 */
export type ArtifactKind = "source" | "target";
/**
 * Sanitised. Never used as a path.
 */
export type Filename = string;
export type SizeBytes = number;
export type Sha256 = string;
/**
 * An artifact is either what was uploaded or what was produced.
 *
 * GET /projects/{id}/artifact must return the target, so the distinction has
 * to exist in the contract and not only in the database.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "ArtifactKind".
 */
export type ArtifactKind1 = "source" | "target";
export type Severity1 = "info" | "warning" | "error";
export type Item1 = string;
export type Message1 = string;
export type Check = string;
export type Role1 = "system" | "assistant";
export type Text = string;
export type Model1 = string;
export type Kind2 = "measure" | "partition";
export type Table2 = string;
export type Name7 = string;
export type Expression1 = string;
export type Current = string;
export type Reason1 = string;
export type Origin = "rule" | "model";
export type Model2 = string;
export type Items = string[];
export type Message2 = string;
export type Step1 =
  | "inventory"
  | "check_references"
  | "check_mquery"
  | "model_health"
  | "draft_dax"
  | "format_mquery"
  | "summarize"
  | "chat";
export type Title = string;
export type Messages = AssistantMessage[];
export type Findings = AssistantFinding[];
export type Proposals = AssistantProposal[];
export type ChecksRun = number;
export type ChecksClean = number;
/**
 * Position in the recording. Ordering, not time.
 */
export type Seq = number;
/**
 * table | column | calc | visual | parameter | relationship
 */
export type Kind3 = string;
export type Name8 = string;
/**
 * Which side of the seam an object ended on.
 *
 * There is no third value by design: an object that was neither converted nor
 * reported would be the silent drop this product exists to prevent. The engine
 * enforces the same two in `t2pbi.events`.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "Outcome".
 */
export type Outcome = "crossed" | "held";
/**
 * Why it was held, or what it became.
 */
export type Detail1 = string;
/**
 * Canonical id, e.g. 'Orders.Profit'.
 */
export type Ref1 = string;
/**
 * The original expression, if any.
 */
export type Source = string;
/**
 * What was emitted. Empty if held.
 */
export type Result = string;
export type Score1 = number;
export type Checks = number;
export type Passed = number;
export type ConversionId = string;
export type ArtifactId1 = string | null;
export type Flags2 = ConversionFlag[];
export type ProjectId1 = string;
export type Name9 = string;
export type CreatedAt = string;
/**
 * What the product is allowed to claim (§63). Never 'success'.
 */
export type Verdict = "verified" | "partially_verified" | "unverified" | "failed";
export type Flags3 = ConversionFlag[];
export type ValidationId = string;
/**
 * What the product is allowed to claim (§63). Never 'success'.
 */
export type Verdict1 = "verified" | "partially_verified" | "unverified" | "failed";
/**
 * Computed only from measured categories.
 */
export type Score2 = number | null;
export type Formula1 = string;
export type Measured = boolean;
export type Reason2 = string;
export type RuleId = string;
export type Status = string;
export type Note = string;
export type Rules = ValidationRuleResult[];
/**
 * The run as it was recorded, object by object. Empty when the conversion predates the recording being kept, which the report states rather than omitting the section.
 */
export type Audit = AuditEntry[];
export type AiEnabled = boolean;
export type ProviderKind = "none" | "ollama" | "openai_compatible";
export type PrivacyMode = "standard" | "local_only" | "enterprise_private";
/**
 * *What became of* an object.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "ConversionStatus".
 */
export type ConversionStatus1 = "converted" | "partial" | "ai_required" | "unsupported" | "failed";
export type Name10 = string;
export type Email = string;
export type DisplayName = string;
export type Password = string;
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "DataType".
 */
export type DataType2 = "string" | "integer" | "decimal" | "boolean" | "date" | "datetime" | "unknown";
/**
 * Whether this deployment can run a migration direction, and if not, why.
 *
 * Engines are separate products: a deployment installs the ones a customer
 * bought, and the licence says which may run. The two answers are different
 * remedies (install a package / buy the engine), so they are different states.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "DirectionState".
 */
export type DirectionState = "available" | "not_installed" | "not_licensed";
export type Engine = string;
export type EngineVersion = string;
export type LicenceFeature = string;
export type Reason3 = string;
export type Directions = DirectionStatus[];
export type Status1 = string;
export type Version = string;
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "PrivacyMode".
 */
export type PrivacyMode1 = "standard" | "local_only" | "enterprise_private";
export type AiAvailable = boolean;
export type Kind4 = string;
export type Name11 = string;
export type Outcome1 = string;
export type Method = string;
export type Ref2 = string;
export type JobId = string;
/**
 * Analysis, conversion and validation are three jobs against one project,
 * so a job row is not findable without saying which it is.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "JobKind".
 */
export type JobKind = "analysis" | "conversion" | "validation";
export type Licensed = boolean;
export type Customer = string | null;
export type Expires = string | null;
export type DaysRemaining = number | null;
export type Seats = number | null;
export type Features = string[];
export type ExpiringSoon = boolean;
export type Message3 = string | null;
export type Email1 = string;
export type Password1 = string;
export type Completed = number;
export type Total1 = number;
/**
 * What a person did about a proposal (§62).
 *
 * `PENDING` exists so "nobody has looked at this yet" is a state the audit
 * trail can report, rather than being indistinguishable from "rejected".
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "ProposalDecision".
 */
export type ProposalDecision = "pending" | "accepted" | "rejected";
/**
 * `'<table>.<name>'` - the object it is about.
 */
export type Item2 = string;
export type RefusalReason = string;
/**
 * Verbatim. Shown to the reviewer, never re-rendered.
 */
export type PromptSent = string;
/**
 * What a person did about a proposal (§62).
 *
 * `PENDING` exists so "nobody has looked at this yet" is a state the audit
 * trail can report, rather than being indistinguishable from "rejected".
 */
export type ProposalDecision1 = "pending" | "accepted" | "rejected";
export type ProjectId2 = string;
export type Reviews = ProposalReview[];
export type Item3 = string;
/**
 * Router disposition or gauntlet rejection.
 */
export type Outcome2 = string;
export type Reason4 = string;
export type Skipped = SkippedItem[];
export type Summary = string;
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "ProviderKind".
 */
export type ProviderKind1 = "none" | "ollama" | "openai_compatible";
export type ProviderKind2 = "none" | "ollama" | "openai_compatible";
export type BaseUrl = string;
export type Model3 = string;
export type Configured = boolean;
export type Available = boolean;
export type UnavailableBecause = string;
export type VisualIds1 = string[];
export type Version1 = number;
export type Id6 = string;
export type Name12 = string;
export type Width = number;
export type Height = number;
export type Id7 = string;
export type PageId = string;
export type VisualType1 = string;
export type SourceName = string;
export type SourceMark = string;
export type Fields = string[];
export type Status2 = "converted" | "partial";
export type Notes = string[];
export type Visuals2 = ReportVisual[];
export type Notes1 = string[];
export type Pages = ReportPage[];
/**
 * How loudly the report says so.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "Severity".
 */
export type Severity2 = "info" | "warning" | "manual";
export type IsActive = boolean | null;
export type IsAdmin = boolean | null;
export type UserId = string;
export type Email2 = string;
export type DisplayName1 = string;
export type IsAdmin1 = boolean;
export type IsActive1 = boolean;
export type CreatedAt1 = string | null;
export type LastLoginAt = string | null;
export type Users = UserAccount[];
export type SeatsTotal = number | null;
export type SeatsUsed = number;
/**
 * What the product is allowed to claim (§63). Never 'success'.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "Verdict".
 */
export type Verdict2 = "verified" | "partially_verified" | "unverified" | "failed";
export type Name13 = string;
export type DataType3 = string;
export type BaseVersion = number;
export type Note1 = string;
/**
 * @minItems 1
 */
export type Edits = [WorkspaceEdit, ...WorkspaceEdit[]];
export type Kind5 = "measure" | "partition";
export type Table3 = string;
export type Name14 = string;
export type Expression2 = string;
export type Path = string;
export type SizeBytes1 = number;
export type Item4 = string;
export type Table4 = string;
export type Name15 = string;
export type Source1 = string;
export type Reason5 = string;
export type Name16 = string;
export type Expression3 = string;
export type ProjectId3 = string;
export type Name17 = string;
export type Version2 = number;
export type Version3 = number;
export type ArtifactId2 = string;
export type CreatedAt2 = string;
export type Note2 = string;
export type Versions = WorkspaceVersion[];
export type Name18 = string;
export type Columns2 = WorkspaceColumn[];
export type Measures = WorkspaceMeasure[];
export type Name19 = string;
export type Mode = string;
export type SourceKind = string;
export type Expression4 = string;
export type Partitions = WorkspacePartition[];
export type Tables2 = WorkspaceTable[];
export type Files = WorkspaceFile[];
export type Held = WorkspaceHeld[];

export interface DashboardBridgeContracts {
  [k: string]: unknown;
}
/**
 * A drafted translation that survived the validation gauntlet (`P4.4`).
 *
 * A proposal is something to *show a person*, never something to apply. There
 * is deliberately no `applied`, `accepted` or `auto_accept` field: ADR-007
 * rejects an auto-apply path outright, because it contradicts the product's
 * central claim, and a field named like permission is how such a path gets
 * added by accident.
 *
 * `confidence` is what the model said about itself. It orders and pre-selects
 * and does nothing else - models are not calibrated, and a self-reported 0.94
 * is not a 94% chance of being correct.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "AIProposal".
 */
export interface AIProposal {
  proposal_id: ProposalId;
  operation: Operation;
  source_expression: SourceExpression;
  target_expression: TargetExpression;
  explanation?: Explanation;
  confidence: Confidence;
  assumptions?: Assumptions;
  requires_review?: RequiresReview;
  preselected?: Preselected;
  model?: Model;
  prompt_version?: PromptVersion;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "Analysis".
 */
export interface Analysis {
  analysis_id: AnalysisId;
  status: JobStatus;
  model?: CanonicalModel | null;
  inventory?: Inventory;
  complexity?: Complexity | null;
  compatibility?: Compatibility;
  flags?: Flags1;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "CanonicalModel".
 */
export interface CanonicalModel {
  source_platform: Platform;
  source_version?: SourceVersion;
  name?: Name;
  datasources?: Datasources;
  relationships?: Relationships;
  parameters?: Parameters;
  visuals?: Visuals;
  dashboards?: Dashboards;
  flags?: Flags;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "DataSource".
 */
export interface DataSource {
  id: Id;
  name: Name1;
  connection?: Connection;
  is_extract?: IsExtract;
  source_id?: SourceId;
  tables?: Tables;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "Table".
 */
export interface Table {
  id: Id1;
  name: Name2;
  columns?: Columns;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "Column".
 */
export interface Column {
  id: Id2;
  name: Name3;
  caption?: Caption;
  datatype?: DataType;
  role?: Role;
  /**
   * None means the grain could not be determined; the object is refused rather than guessed.
   */
  grain?: Grain | null;
  expression?: Expression | null;
  translation?: Translation | null;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "Expression".
 */
export interface Expression {
  source_language: SourceLanguage;
  source_text: SourceText;
  references?: References;
}
/**
 * A reference to a column, resolved or not.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "FieldRef".
 */
export interface FieldRef {
  table?: Table1;
  column: Column1;
  resolved?: Resolved;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "Translation".
 */
export interface Translation {
  target_language: TargetLanguage;
  target_text: TargetText;
  method: ConversionMethod;
  rule_ids?: RuleIds;
  proposal_id?: ProposalId1;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "Relationship".
 */
export interface Relationship {
  from_table: FromTable;
  from_column: FromColumn;
  to_table: ToTable;
  to_column: ToColumn;
  kind?: Kind;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "Parameter".
 */
export interface Parameter {
  id: Id3;
  name: Name4;
  caption: Caption1;
  datatype?: DataType1;
  default_value?: DefaultValue;
  kind?: Kind1;
  min_value?: MinValue;
  max_value?: MaxValue;
  step?: Step;
  members?: Members;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "Visual".
 */
export interface Visual {
  id: Id4;
  name: Name5;
  visual_type?: VisualType;
  bindings?: Bindings;
  filters?: Filters;
}
/**
 * One field placed in one well. Replaces Tableau-shaped shelf encodings.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "VisualBinding".
 */
export interface VisualBinding {
  role: BindingRole;
  field?: FieldRef | null;
  aggregation?: Aggregation | null;
  date_part?: DatePart | null;
  resolvable?: Resolvable;
  raw?: Raw;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "Dashboard".
 */
export interface Dashboard {
  id: Id5;
  name: Name6;
  visual_ids?: VisualIds;
}
/**
 * Anything that did not convert cleanly. Nothing is ever dropped silently.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "ConversionFlag".
 */
export interface ConversionFlag {
  item: Item;
  stage: Stage;
  method?: ConversionMethod1;
  status?: ConversionStatus;
  severity?: Severity;
  reason?: Reason;
  ref?: Ref;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "Inventory".
 */
export interface Inventory {
  datasources?: Datasources1;
  tables?: Tables1;
  columns?: Columns1;
  calculations?: Calculations;
  visuals?: Visuals1;
  parameters?: Parameters1;
  relationships?: Relationships1;
  dashboards?: Dashboards1;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "Complexity".
 */
export interface Complexity {
  score: Score;
  band: Band;
  formula: Formula;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "Compatibility".
 */
export interface Compatibility {
  converted?: Converted;
  partial?: Partial;
  ai_required?: AiRequired;
  unsupported?: Unsupported;
  failed?: Failed;
  total?: Total;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "ApiError".
 */
export interface ApiError {
  category: ErrorCategory;
  message: Message;
  detail?: Detail;
  request_id?: RequestId;
  project_id?: ProjectId;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "Artifact".
 */
export interface Artifact {
  artifact_id: ArtifactId;
  kind?: ArtifactKind;
  filename: Filename;
  size_bytes: SizeBytes;
  sha256: Sha256;
  detected_platform?: Platform | null;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "AssistantFinding".
 */
export interface AssistantFinding {
  severity: Severity1;
  item: Item1;
  message: Message1;
  check: Check;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "AssistantMessage".
 */
export interface AssistantMessage {
  role: Role1;
  text: Text;
  model?: Model1;
}
/**
 * A change offered to a person. Never applied by the step that made it.
 *
 * `origin` says what produced it: `rule` for a deterministic rewrite whose
 * effect is stated in `reason`, `model` for a model's draft that has passed the
 * proposal checks. Either way a person puts it into their draft changes, or
 * does not.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "AssistantProposal".
 */
export interface AssistantProposal {
  kind: Kind2;
  table: Table2;
  name: Name7;
  expression: Expression1;
  current?: Current;
  reason: Reason1;
  origin: Origin;
  model?: Model2;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "AssistantStepRequest".
 */
export interface AssistantStepRequest {
  items?: Items;
  message?: Message2;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "AssistantStepResult".
 */
export interface AssistantStepResult {
  step: Step1;
  title: Title;
  messages?: Messages;
  findings?: Findings;
  proposals?: Proposals;
  checks_run?: ChecksRun;
  checks_clean?: ChecksClean;
}
/**
 * One object the conversion handled, and what became of it (P5.7, §41).
 *
 * Taken from the engine's own recording, not reconstructed. The flags say
 * what did *not* come across; this is the only record of what did, and of the
 * expression each translation actually produced - which is what "defend every
 * transformation to a sceptical stakeholder" needs.
 *
 * **No timing.** The event stream carries `elapsed_ms` because it is about a
 * run in progress. A record of a finished run must be byte-stable, or two
 * conversions of one workbook produce reports that cannot be diffed, and a
 * duration differs on every run.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "AuditEntry".
 */
export interface AuditEntry {
  seq: Seq;
  stage: Stage;
  kind: Kind3;
  name: Name8;
  outcome: Outcome;
  detail?: Detail1;
  ref?: Ref1;
  source?: Source;
  result?: Result;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "CategoryScore".
 */
export interface CategoryScore {
  score: Score1;
  checks: Checks;
  passed: Passed;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "Conversion".
 */
export interface Conversion {
  conversion_id: ConversionId;
  status: JobStatus;
  compatibility?: Compatibility;
  /**
   * The produced model, with translations filled in. The comparison view puts each source expression beside its target, so without this that column is empty for every row.
   */
  model?: CanonicalModel | null;
  artifact_id?: ArtifactId1;
  flags?: Flags2;
}
/**
 * The deliverable that outlives the session.
 *
 * Composed entirely of contracts that already crossed this boundary, so the
 * report cannot say anything the API did not already say elsewhere. It is a
 * rendering of the run, not a second opinion about it.
 *
 * `verdict` is repeated at the top level even though it also sits inside
 * `validation`, because `validation` is null until the checks have run and a
 * reader still needs an answer then. That answer is `unverified` - stated,
 * never omitted, since an absent verdict reads as a passed one.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "ConversionReport".
 */
export interface ConversionReport {
  project: Project;
  verdict?: Verdict;
  compatibility: Compatibility;
  flags?: Flags3;
  validation?: Validation | null;
  audit?: Audit;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "Project".
 */
export interface Project {
  project_id: ProjectId1;
  name: Name9;
  source_platform: Platform;
  target_platform: Platform;
  created_at: CreatedAt;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "Validation".
 */
export interface Validation {
  validation_id: ValidationId;
  status: JobStatus;
  verdict?: Verdict1;
  score?: Score2;
  formula?: Formula1;
  categories?: Categories;
  numerical?: NumericalValidation;
  rules?: Rules;
}
export interface Categories {
  [k: string]: CategoryScore;
}
/**
 * Always unmeasured in v1 (ADR-003).
 *
 * The field exists so the absence is explicit rather than inferred. Comparing
 * results requires executing both dashboards against live data.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "NumericalValidation".
 */
export interface NumericalValidation {
  measured?: Measured;
  reason?: Reason2;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "ValidationRuleResult".
 */
export interface ValidationRuleResult {
  rule_id: RuleId;
  status: Status;
  note?: Note;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "ConversionRequest".
 */
export interface ConversionRequest {
  ai_enabled?: AiEnabled;
  provider?: ProviderKind;
  privacy_mode?: PrivacyMode;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "CreateProjectRequest".
 */
export interface CreateProjectRequest {
  source_platform: Platform;
  target_platform: Platform;
  name: Name10;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "CreateUserRequest".
 */
export interface CreateUserRequest {
  email: Email;
  display_name?: DisplayName;
  password: Password;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "DirectionList".
 */
export interface DirectionList {
  directions?: Directions;
}
/**
 * One migration direction and whether this deployment can run it.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "DirectionStatus".
 */
export interface DirectionStatus {
  source_platform: Platform;
  target_platform: Platform;
  state: DirectionState;
  engine: Engine;
  engine_version?: EngineVersion;
  licence_feature: LicenceFeature;
  reason?: Reason3;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "HealthResponse".
 */
export interface HealthResponse {
  status: Status1;
  version: Version;
  privacy_mode: PrivacyMode1;
  ai_available: AiAvailable;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "ItemEvent".
 */
export interface ItemEvent {
  kind: Kind4;
  name: Name11;
  outcome: Outcome1;
  method: Method;
  ref?: Ref2;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "Job".
 */
export interface Job {
  job_id: JobId;
  kind: JobKind;
  status: JobStatus;
  stage?: Stage | null;
}
/**
 * The licence this deployment runs under (`P7.1`).
 *
 * **Never carries the token.** The screen needs the customer, the expiry and
 * the days left; it never needs the signed string, and a token on the wire is
 * a token in somebody's proxy log.
 *
 * `licensed` is not the same question as "is anything wrong". A licence that
 * is valid and expires in nine days is `licensed: true` with
 * `expiring_soon: true` and a message - which is the whole point of warning
 * before the day conversions stop rather than on it.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "LicenseStatusResponse".
 */
export interface LicenseStatusResponse {
  licensed: Licensed;
  customer?: Customer;
  expires?: Expires;
  days_remaining?: DaysRemaining;
  seats?: Seats;
  features?: Features;
  expiring_soon?: ExpiringSoon;
  message?: Message3;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "LoginRequest".
 */
export interface LoginRequest {
  email: Email1;
  password: Password1;
}
/**
 * Emitted from a real EventSink. Never synthesised to smooth a bar.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "ProgressEvent".
 */
export interface ProgressEvent {
  stage: Stage;
  completed: Completed;
  total: Total1;
}
/**
 * One proposal, with everything a reviewer needs to judge it (ADR-007).
 *
 * 07-ai-engine.md: the reviewer sees the source expression, the reason the
 * deterministic path refused, the proposal, its explanation and assumptions,
 * **and what was sent to the model**. The last one is why `prompt_sent` is
 * here: a review of a proposal without the question it answered is a review of
 * half of it, and it is also the only way a person can see for themselves that
 * the workbook was not sent.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "ProposalReview".
 */
export interface ProposalReview {
  item: Item2;
  refusal_reason: RefusalReason;
  proposal: AIProposal;
  prompt_sent: PromptSent;
  decision?: ProposalDecision1;
}
/**
 * Everything a model was asked about for one project, and what came back.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "ProposalSet".
 */
export interface ProposalSet {
  project_id: ProjectId2;
  reviews?: Reviews;
  skipped?: Skipped;
  summary?: Summary;
}
/**
 * An object no proposal exists for, and which of the reasons applies.
 *
 * Never merged into "no suggestion available". A model that was never asked, a
 * model that declined, and a draft that failed the gauntlet are three different
 * facts, and only the third one says anything about the model's answer.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "SkippedItem".
 */
export interface SkippedItem {
  item: Item3;
  outcome: Outcome2;
  reason: Reason4;
}
/**
 * Keys are write-only over the API.
 *
 * A GET never returns the value, nor a masked prefix, which leaks length and
 * usually the first characters.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "ProviderSettings".
 */
export interface ProviderSettings {
  provider?: ProviderKind2;
  base_url?: BaseUrl;
  model?: Model3;
  configured?: Configured;
  available?: Available;
  unavailable_because?: UnavailableBecause;
}
/**
 * The visuals to carry in the exported project. Empty carries none.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "PublishRequest".
 */
export interface PublishRequest {
  visual_ids?: VisualIds1;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "ReportExplorer".
 */
export interface ReportExplorer {
  version: Version1;
  pages?: Pages;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "ReportPage".
 */
export interface ReportPage {
  id: Id6;
  name: Name12;
  width?: Width;
  height?: Height;
  visuals?: Visuals2;
  notes?: Notes1;
}
/**
 * One Power BI visual in the produced report, and where it came from.
 *
 * `source_name` is the Tableau worksheet it was converted from and
 * `source_mark` that worksheet's mark type. `status` is `converted` when no
 * flag names the worksheet, `partial` when one does, and `notes` are those
 * flags' reasons, verbatim.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "ReportVisual".
 */
export interface ReportVisual {
  id: Id7;
  page_id: PageId;
  visual_type: VisualType1;
  source_name?: SourceName;
  source_mark?: SourceMark;
  fields?: Fields;
  status?: Status2;
  notes?: Notes;
}
/**
 * Only the two things an administrator may change about someone else.
 *
 * Not the password: an administrator who can set another person's password
 * can sign in as them, and "who did this conversion" stops meaning anything.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "UpdateUserRequest".
 */
export interface UpdateUserRequest {
  is_active?: IsActive;
  is_admin?: IsAdmin;
}
/**
 * A person with an account on this deployment (`P7.1`).
 *
 * **There is no password field and there never will be.** The model has
 * nowhere to put one, so a response cannot carry a password or its hash by
 * accident - the same shape as `Artifact` having no column for bytes.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "UserAccount".
 */
export interface UserAccount {
  user_id: UserId;
  email: Email2;
  display_name?: DisplayName1;
  is_admin?: IsAdmin1;
  is_active?: IsActive1;
  created_at?: CreatedAt1;
  last_login_at?: LastLoginAt;
}
/**
 * The people on this deployment, and what the licence allows.
 *
 * The seat counts travel with the list because they are the answer to the
 * question the list provokes - "can I add someone?" - and a client that has
 * to make a second call to find out will show the button and then refuse.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "UserList".
 */
export interface UserList {
  users?: Users;
  seats_total?: SeatsTotal;
  seats_used?: SeatsUsed;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "WorkspaceColumn".
 */
export interface WorkspaceColumn {
  name: Name13;
  data_type?: DataType3;
}
/**
 * Edits saved together as one new version, on top of `base_version`.
 *
 * `base_version` makes a stale save fail loudly: two people editing the same
 * version would otherwise have the second silently discard the first.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "WorkspaceCommit".
 */
export interface WorkspaceCommit {
  base_version: BaseVersion;
  note?: Note1;
  edits: Edits;
}
/**
 * Set a measure's DAX, or a partition's Power Query, in one table.
 *
 * A measure that does not exist is added; that is how a held calculation is
 * written by hand. A partition must already exist.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "WorkspaceEdit".
 */
export interface WorkspaceEdit {
  kind: Kind5;
  table: Table3;
  name: Name14;
  expression: Expression2;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "WorkspaceFile".
 */
export interface WorkspaceFile {
  path: Path;
  size_bytes: SizeBytes1;
}
/**
 * A calculation the converter refused, offered for a person to write.
 *
 * `source` is the original expression, verbatim. Nothing in the produced
 * model stands for it: the converter emits no placeholder (AGENTS.md rule 1),
 * so this list is the only place it appears in the workspace.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "WorkspaceHeld".
 */
export interface WorkspaceHeld {
  item: Item4;
  table: Table4;
  name: Name15;
  source?: Source1;
  reason: Reason5;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "WorkspaceMeasure".
 */
export interface WorkspaceMeasure {
  name: Name16;
  expression: Expression3;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "WorkspaceModel".
 */
export interface WorkspaceModel {
  project_id: ProjectId3;
  name: Name17;
  version: Version2;
  versions?: Versions;
  tables?: Tables2;
  files?: Files;
  held?: Held;
}
/**
 * One saved state of the produced project. v0 is what the converter wrote.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "WorkspaceVersion".
 */
export interface WorkspaceVersion {
  version: Version3;
  artifact_id: ArtifactId2;
  created_at: CreatedAt2;
  note?: Note2;
}
/**
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "WorkspaceTable".
 */
export interface WorkspaceTable {
  name: Name18;
  columns?: Columns2;
  measures?: Measures;
  partitions?: Partitions;
}
/**
 * A table's source, as written in its TMDL partition.
 *
 * `source_kind` is what the expression is written in: `m` for Power Query,
 * `calculated` for a calculated table, whose source is DAX.
 *
 * This interface was referenced by `DashboardBridgeContracts`'s JSON-Schema
 * via the `definition` "WorkspacePartition".
 */
export interface WorkspacePartition {
  name: Name19;
  mode?: Mode;
  source_kind?: SourceKind;
  expression: Expression4;
}
