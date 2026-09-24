"""Shared contracts. Single source of truth for both the API and the web app."""

from dashboardbridge_contracts import api, canonical, enums
from dashboardbridge_contracts.api import (
    AIProposal, Analysis, ApiError, Artifact, AuditEntry, CategoryScore, Compatibility, Complexity, Conversion,
    ConversionReport, ConversionRequest, CreateProjectRequest, HealthResponse,
    Inventory, Job, LicenseStatusResponse, LoginRequest,
    CreateUserRequest, UpdateUserRequest, UserAccount, UserList,
    NumericalValidation, Project, ProposalReview, ProposalSet, ProviderSettings,
    SkippedItem, Validation, ValidationRuleResult,
    WorkspaceColumn, WorkspaceCommit, WorkspaceEdit, WorkspaceFile, WorkspaceHeld,
    WorkspaceMeasure, WorkspaceModel, WorkspacePartition, WorkspaceTable, WorkspaceVersion,
    PublishRequest, ReportExplorer, ReportPage, ReportVisual,
)
from dashboardbridge_contracts.canonical import (
    CanonicalModel, Column, ConversionFlag, DataSource, Expression, FieldRef,
    Parameter, Relationship, Table, Translation, Visual, VisualBinding, Dashboard,
)
from dashboardbridge_contracts.enums import (
    Aggregation, ArtifactKind, BindingRole, ConversionMethod, ConversionStatus, DataType,
    DatePart, ErrorCategory, Grain, JobKind, JobStatus, Outcome, Platform,
    PrivacyMode,
    ProposalDecision, ProviderKind, Severity, Stage, Verdict,
)

__all__ = [n for n in dir() if not n.startswith("_")]
