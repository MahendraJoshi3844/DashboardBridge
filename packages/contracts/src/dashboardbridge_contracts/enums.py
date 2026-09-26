"""Shared vocabulary. Every value here appears in an API payload and in the UI.

Three axes are deliberately separate (ADR-004): a single enum cannot express
"the AI was asked, the user declined, so a person must do it", and the audit
trail is required to answer exactly that.
"""

from __future__ import annotations

from enum import Enum


class Platform(str, Enum):
    TABLEAU = "tableau"
    POWERBI = "powerbi"
    # Sources only: each has a reader (the `mstr2pbi` / `qlik2pbi` engine) and no writer.
    MICROSTRATEGY = "microstrategy"
    QLIK = "qlik"


class Stage(str, Enum):
    """Pipeline stages. Progress events name one of these and nothing else."""

    EXTRACT = "extract"
    PARSE = "parse"
    MAP = "map"
    TRANSLATE = "translate"
    GENERATE = "generate"
    VALIDATE = "validate"
    REPORT = "report"


class Outcome(str, Enum):
    """Which side of the seam an object ended on.

    There is no third value by design: an object that was neither converted nor
    reported would be the silent drop this product exists to prevent. The engine
    enforces the same two in `t2pbi.events`.
    """

    CROSSED = "crossed"
    HELD = "held"


class ProposalDecision(str, Enum):
    """What a person did about a proposal (§62).

    `PENDING` exists so "nobody has looked at this yet" is a state the audit
    trail can report, rather than being indistinguishable from "rejected".
    """

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ConversionMethod(str, Enum):
    """*How* an object was converted."""

    DETERMINISTIC = "deterministic"
    RULE = "rule"
    AI_ASSISTED = "ai_assisted"
    MANUAL = "manual"


class ConversionStatus(str, Enum):
    """*What became of* an object."""

    CONVERTED = "converted"
    PARTIAL = "partial"
    AI_REQUIRED = "ai_required"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class Severity(str, Enum):
    """How loudly the report says so."""

    INFO = "info"
    WARNING = "warning"
    MANUAL = "manual"


class Grain(str, Enum):
    """Where an expression evaluates.

    The single most consequential property in the model: source tools decide
    aggregation at query time, targets must commit at definition time. `None`
    (absent) means the grain could not be determined, and the object is refused
    rather than guessed.
    """

    ROW = "row"
    AGGREGATE = "aggregate"


class DataType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    UNKNOWN = "unknown"


class BindingRole(str, Enum):
    """Platform-neutral replacement for Tableau's shelves (ADR-002)."""

    CATEGORY = "category"
    VALUE = "value"
    SERIES = "series"
    DETAIL = "detail"
    TOOLTIP = "tooltip"
    FILTER = "filter"


class Aggregation(str, Enum):
    SUM = "sum"
    AVERAGE = "average"
    MIN = "min"
    MAX = "max"
    COUNT = "count"
    COUNT_DISTINCT = "count_distinct"
    MEDIAN = "median"
    ATTRIBUTE = "attribute"


class DatePart(str, Enum):
    YEAR = "year"
    QUARTER = "quarter"
    MONTH = "month"
    WEEK = "week"
    DAY = "day"
    HOUR = "hour"
    MINUTE = "minute"
    SECOND = "second"


class ArtifactKind(str, Enum):
    """An artifact is either what was uploaded or what was produced.

    GET /projects/{id}/artifact must return the target, so the distinction has
    to exist in the contract and not only in the database.
    """

    SOURCE = "source"
    TARGET = "target"


class JobKind(str, Enum):
    """Analysis, conversion and validation are three jobs against one project,
    so a job row is not findable without saying which it is."""

    ANALYSIS = "analysis"
    CONVERSION = "conversion"
    VALIDATION = "validation"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PrivacyMode(str, Enum):
    STANDARD = "standard"
    LOCAL_ONLY = "local_only"
    ENTERPRISE_PRIVATE = "enterprise_private"


class ProviderKind(str, Enum):
    NONE = "none"
    OLLAMA = "ollama"
    OPENAI_COMPATIBLE = "openai_compatible"


class Verdict(str, Enum):
    """What the product is allowed to claim (§63). Never 'success'."""

    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    UNVERIFIED = "unverified"
    FAILED = "failed"


class ErrorCategory(str, Enum):
    UPLOAD_ERROR = "UPLOAD_ERROR"
    PARSER_ERROR = "PARSER_ERROR"
    UNSUPPORTED_ARTIFACT = "UNSUPPORTED_ARTIFACT"
    METADATA_ERROR = "METADATA_ERROR"
    RULE_ERROR = "RULE_ERROR"
    AI_ERROR = "AI_ERROR"
    CONVERSION_ERROR = "CONVERSION_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    # A missing or unreadable resource is not a system fault, and telling the
    # user it was ours misdirects them.
    #: Not signed in, or signed in and not allowed. One category, because the
    #: two are the same conversation from the client's side: it needs to send
    #: the user somewhere. The status code separates 401 from 403.
    AUTH_ERROR = "AUTH_ERROR"
    NOT_FOUND = "NOT_FOUND"
    SYSTEM_ERROR = "SYSTEM_ERROR"
