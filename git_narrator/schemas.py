"""Pydantic v2 schemas for git-narrator architectural reports."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class RiskCategory(str, Enum):
    """Categorization of negative-space and architectural risks."""
    CONTRACT_BREAK = "CONTRACT_BREAK"
    TEST_GAP = "TEST_GAP"
    SECURITY_LEAK = "SECURITY_LEAK"
    PERFORMANCE_REGRESSION = "PERFORMANCE_REGRESSION"
    CONCURRENCY_RACE = "CONCURRENCY_RACE"
    HALLUCINATED_DEPENDENCY = "HALLUCINATED_DEPENDENCY"


class RiskSeverity(str, Enum):
    """Severity level of identified risks."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


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
    tags: list[str] = Field(
        default_factory=list,
        description="Architectural and domain tags (e.g. ['security', 'database', 'auth']).",
    )


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


def get_report_json_schema() -> dict:
    """Return JSON schema dict for GitNarratorReport."""
    return GitNarratorReport.model_json_schema()
