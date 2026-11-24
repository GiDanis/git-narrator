"""Pydantic v2 schemas for git-narrator architectural reports."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RiskCategory(StrEnum):
    """Categorization of negative-space and architectural risks."""

    CONTRACT_BREAK = "CONTRACT_BREAK"
    TEST_GAP = "TEST_GAP"
    SECURITY_LEAK = "SECURITY_LEAK"
    PERFORMANCE_REGRESSION = "PERFORMANCE_REGRESSION"
    CONCURRENCY_RACE = "CONCURRENCY_RACE"
    HALLUCINATED_DEPENDENCY = "HALLUCINATED_DEPENDENCY"


class RiskSeverity(StrEnum):
    """Severity level of identified risks."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


_CATEGORY_ALIASES: dict[str, RiskCategory] = {
    "CONTRACT_BREAK": RiskCategory.CONTRACT_BREAK,
    "BREAKING_CHANGE": RiskCategory.CONTRACT_BREAK,
    "API_BREAK": RiskCategory.CONTRACT_BREAK,
    "TEST_GAP": RiskCategory.TEST_GAP,
    "MISSING_TESTS": RiskCategory.TEST_GAP,
    "SECURITY_LEAK": RiskCategory.SECURITY_LEAK,
    "SECURITY": RiskCategory.SECURITY_LEAK,
    "SECRET_LEAK": RiskCategory.SECURITY_LEAK,
    "VULNERABILITY": RiskCategory.SECURITY_LEAK,
    "PERFORMANCE_REGRESSION": RiskCategory.PERFORMANCE_REGRESSION,
    "PERFORMANCE": RiskCategory.PERFORMANCE_REGRESSION,
    "PERF": RiskCategory.PERFORMANCE_REGRESSION,
    "CONCURRENCY_RACE": RiskCategory.CONCURRENCY_RACE,
    "RACE_CONDITION": RiskCategory.CONCURRENCY_RACE,
    "CONCURRENCY": RiskCategory.CONCURRENCY_RACE,
    "HALLUCINATED_DEPENDENCY": RiskCategory.HALLUCINATED_DEPENDENCY,
    "DEPENDENCY": RiskCategory.HALLUCINATED_DEPENDENCY,
    "SUPPLY_CHAIN": RiskCategory.HALLUCINATED_DEPENDENCY,
}

_SEVERITY_ALIASES: dict[str, RiskSeverity] = {
    "CRITICAL": RiskSeverity.CRITICAL,
    "CRIT": RiskSeverity.CRITICAL,
    "HIGH": RiskSeverity.HIGH,
    "MEDIUM": RiskSeverity.MEDIUM,
    "MED": RiskSeverity.MEDIUM,
    "MODERATE": RiskSeverity.MEDIUM,
    "LOW": RiskSeverity.LOW,
    "INFO": RiskSeverity.INFO,
    "INFORMATIONAL": RiskSeverity.INFO,
}


def infer_blast_radius(overall_impact: str, fallback: RiskSeverity = RiskSeverity.MEDIUM) -> RiskSeverity:
    """Infer structured blast radius severity from impact prose when omitted."""
    upper = overall_impact.upper()
    for level in (RiskSeverity.CRITICAL, RiskSeverity.HIGH, RiskSeverity.MEDIUM, RiskSeverity.LOW):
        if level.value in upper:
            return level
    return fallback


class RiskRadarItem(BaseModel):
    """Detailed risk assessment item focusing on implicit risks and negative space."""

    model_config = ConfigDict(extra="ignore")

    category: RiskCategory = Field(
        ...,
        description="The category of risk identified in the changes.",
    )
    severity: RiskSeverity = Field(
        ...,
        description="Severity level of the risk.",
    )
    title: str = Field(
        ...,
        description="Short, descriptive headline of the risk.",
    )
    file_path: str | None = Field(
        default=None,
        description="Path of the affected file if localized to a file.",
    )
    line_hint: str | None = Field(
        default=None,
        description="Line number or range hint where the issue originates.",
    )
    explanation: str = Field(
        ...,
        description="Thorough explanation of what could go wrong, negative space gaps, or missing safeguards.",
    )
    remediation: str = Field(
        ...,
        description="Concrete, actionable recommendations or code changes to eliminate the risk.",
    )

    @field_validator("category", mode="before")
    @classmethod
    def _normalize_category(cls, v: Any) -> Any:
        if isinstance(v, RiskCategory):
            return v
        if isinstance(v, str):
            key = v.strip().upper().replace(" ", "_").replace("-", "_")
            if key in _CATEGORY_ALIASES:
                return _CATEGORY_ALIASES[key]
        return v

    @field_validator("severity", mode="before")
    @classmethod
    def _normalize_severity(cls, v: Any) -> Any:
        if isinstance(v, RiskSeverity):
            return v
        if isinstance(v, str):
            key = v.strip().upper()
            if key in _SEVERITY_ALIASES:
                return _SEVERITY_ALIASES[key]
        return v


class ComponentMutation(BaseModel):
    """Architectural mutation observed within a component or module."""

    model_config = ConfigDict(extra="ignore")

    component_name: str = Field(
        ...,
        description="Name of the affected service, module, or logical component.",
    )
    mutation_type: str = Field(
        ...,
        description="Type of architectural mutation (e.g., ADDED, MODIFIED, REMOVED, REFACTORED, DEPRECATED).",
    )
    summary: str = Field(
        ...,
        description="Summary of the structural or behavioral modification.",
    )


class VisualFlow(BaseModel):
    """Visual diagram representations of the system change."""

    model_config = ConfigDict(extra="ignore")

    diagram_type: str = Field(
        default="flowchart",
        description="Mermaid diagram type (e.g., flowchart, sequenceDiagram).",
    )
    mermaid_code: str = Field(
        ...,
        description="Strict Mermaid syntax code with quoted node labels to ensure robust rendering.",
    )
    ascii_diagram: str = Field(
        default="",
        description="Clean ASCII diagram representation serving as a zero-dependency fallback.",
    )


class ExecutiveSummary(BaseModel):
    """High-level architectural summary of the changes."""

    model_config = ConfigDict(extra="ignore")

    headline: str = Field(
        ...,
        description="A crisp, one-line narrative describing the core architectural purpose.",
    )
    intent: str = Field(
        ...,
        description="The architectural intent and problem being solved.",
    )
    overall_impact: str = Field(
        ...,
        description="Assessment of overall impact on system stability, latency, throughput, and developer ergonomics.",
    )
    blast_radius: RiskSeverity = Field(
        default=RiskSeverity.MEDIUM,
        description="Discrete overall blast radius severity: CRITICAL, HIGH, MEDIUM, or LOW.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Architectural and domain tags (e.g. ['security', 'database', 'auth']).",
    )

    @model_validator(mode="before")
    @classmethod
    def _populate_blast_radius(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("blast_radius"):
            impact = str(data.get("overall_impact", ""))
            copied = dict(data)
            copied["blast_radius"] = infer_blast_radius(impact)
            return copied
        return data

    @field_validator("blast_radius", mode="before")
    @classmethod
    def _normalize_blast_radius(cls, v: Any) -> Any:
        if isinstance(v, RiskSeverity):
            return v
        if isinstance(v, str):
            key = v.strip().upper()
            if key in _SEVERITY_ALIASES:
                return _SEVERITY_ALIASES[key]
        return RiskSeverity.MEDIUM


class ArchitectureNarrative(BaseModel):
    """State transition narrative comparing the system before and after."""

    model_config = ConfigDict(extra="ignore")

    before_state: str = Field(
        ...,
        description="Description of how the system/component was structured and operated prior to the commit.",
    )
    after_state: str = Field(
        ...,
        description="Description of how the system/component operates now, including patterns and data flows.",
    )
    tech_debt: str = Field(
        ...,
        description="Technical debt evaluation: debt introduced, debt paid down, or deferred items.",
    )
    components_affected: list[ComponentMutation] = Field(
        default_factory=list,
        description="List of component mutations that occurred in this diff.",
    )


class ReviewChecklist(BaseModel):
    """Targeted checklist for human code reviewers."""

    model_config = ConfigDict(extra="ignore")

    manual_checks: list[str] = Field(
        default_factory=list,
        description="Specific edge cases, configs, or runtime scenarios requiring manual verification.",
    )
    breaking_changes: list[str] = Field(
        default_factory=list,
        description="Explicit list of breaking API, ABI, DB schema, or configuration changes.",
    )


class GitNarratorReport(BaseModel):
    """Root model representing the complete architectural report for a git diff."""

    model_config = ConfigDict(extra="ignore")

    executive_summary: ExecutiveSummary = Field(
        ...,
        description="High-level narrative and purpose.",
    )
    architecture_narrative: ArchitectureNarrative = Field(
        ...,
        description="Before/after comparison and component structural mutations.",
    )
    risk_radar: list[RiskRadarItem] = Field(
        default_factory=list,
        description="Identified risks focusing on negative space, race conditions, test gaps, and contracts.",
    )
    visual_flow: VisualFlow | None = Field(
        default=None,
        description="Visual flow diagram (Mermaid + ASCII fallback).",
    )
    review_checklist: ReviewChecklist = Field(
        default_factory=ReviewChecklist,
        description="Reviewer verification checklist and breaking changes.",
    )
    conventional_commit: str = Field(
        ...,
        description="Strictly formatted conventional commit message (type(scope): description).",
    )


def get_report_json_schema() -> dict[str, Any]:
    """Return JSON schema dict for GitNarratorReport."""
    return GitNarratorReport.model_json_schema()
