"""Rich TUI interface, GitHub CI annotations, and Markdown renderer for git-narrator."""

import os
from typing import Any

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from git_narrator.schemas import GitNarratorReport, infer_blast_radius

console = Console()

REPO_URL = "https://github.com/GiDanis/git-narrator"


def _enum_str(value: Any) -> str:
    """Extract clean enum value string reliably across Python 3.12+ StrEnum/Enum."""
    return str(getattr(value, "value", value))


def get_impact_badge(impact_or_summary: Any) -> Text:
    """Return a styled badge for overall blast radius level."""
    if hasattr(impact_or_summary, "blast_radius"):
        imp = _enum_str(impact_or_summary.blast_radius).upper()
    else:
        raw = _enum_str(impact_or_summary).upper()
        imp = raw if raw in ("CRITICAL", "HIGH", "MEDIUM", "LOW") else infer_blast_radius(raw).value

    if imp == "CRITICAL":
        return Text(" CRITICAL ", style="bold white on red")
    if imp == "HIGH":
        return Text(" HIGH ", style="bold white on dark_orange")
    if imp == "MEDIUM":
        return Text(" MEDIUM ", style="bold black on yellow")
    return Text(" LOW ", style="bold white on green")


def get_severity_badge(severity: Any) -> Text:
    """Return a styled icon + label for risk severity."""
    sev = _enum_str(severity).upper()
    if sev == "CRITICAL":
        return Text("🔴 CRITICAL", style="bold red")
    if sev == "HIGH":
        return Text("🟠 HIGH", style="bold dark_orange")
    if sev == "MEDIUM":
        return Text("🟡 MEDIUM", style="bold yellow")
    if sev == "LOW":
        return Text("🟢 LOW", style="bold green")
    return Text("🔵 INFO", style="bold cyan")


def render_header(branch: str, stats_summary: str, provider_info: str) -> Panel:
    """Render the top branding and repository context bar."""
    grid = Table.grid(expand=True)
    grid.add_column(justify="left", ratio=1)
    grid.add_column(justify="right", ratio=1)

    left = Text.assemble(
        ("📖 GIT NARRATOR", "bold cyan"),
        (" • ", "dim white"),
        ("🌿 ", "green"),
        (branch, "bold white"),
        (" • ", "dim white"),
        (stats_summary, "yellow"),
    )
    right = Text.assemble(
        ("⚡ Engine: ", "dim white"),
        (provider_info, "bold magenta"),
    )
    grid.add_row(left, right)

    return Panel(
        grid,
        border_style="bright_blue",
        padding=(0, 1),
    )


def render_story_tab(report: GitNarratorReport) -> Group:
    """Render Tab 1: The Executive Story and Architecture Narrative."""
    elements: list[RenderableType] = []

    exec_summary = report.executive_summary
    headline_text = Text.assemble(
        (exec_summary.headline + "\n\n", "bold bright_white"),
        ("Intent: ", "bold cyan"),
        (exec_summary.intent + "\n", "italic white"),
        ("Impact: ", "bold cyan"),
        (exec_summary.overall_impact + "\n", "white"),
    )

    tags_text = Text("Tags: ", style="dim")
    for t in exec_summary.tags:
        tags_text.append(f"#{t} ", style="bold cyan")

    summary_content = Table.grid(expand=True)
    summary_content.add_column(ratio=5)
    summary_content.add_column(ratio=1, justify="right")
    summary_content.add_row(headline_text, get_impact_badge(exec_summary))

    elements.append(
        Panel(
            Group(summary_content, tags_text),
            title="[bold yellow]💡 The Executive Story[/bold yellow]",
            border_style="yellow",
            padding=(1, 2),
        )
    )

    arch = report.architecture_narrative
    arch_table = Table(box=None, expand=True, padding=(0, 2))
    arch_table.add_column("[bold red]◀ State Before[/bold red]", ratio=1)
    arch_table.add_column("[bold green]▶ State After[/bold green]", ratio=1)
    arch_table.add_row(
        Text(arch.before_state, style="white"),
        Text(arch.after_state, style="bright_white"),
    )

    elements.append(
        Panel(
            arch_table,
            title="[bold cyan]🏛️ Architectural Evolution[/bold cyan]",
            border_style="cyan",
            padding=(1, 1),
        )
    )

    if arch.components_affected:
        comp_table = Table(
            title="[bold magenta]Components Modified[/bold magenta]",
            expand=True,
            border_style="dim",
        )
        comp_table.add_column("Component", style="bold cyan", width=24)
        comp_table.add_column("Mutation", style="bold yellow", width=14)
        comp_table.add_column("Summary", style="white")

        for comp in arch.components_affected:
            comp_table.add_row(comp.component_name, comp.mutation_type, comp.summary)

        elements.append(comp_table)

    if arch.tech_debt:
        debt_text = Text.assemble(
            ("⚠️  Technical Debt Evaluation: ", "bold yellow"),
            (arch.tech_debt, "white"),
        )
        elements.append(Panel(debt_text, border_style="yellow", padding=(0, 1)))

    return Group(*elements)


def render_risk_tab(report: GitNarratorReport) -> Group:
    """Render Tab 2: Deep Risk & Negative Space Radar."""
    risks = report.risk_radar

    if not risks:
        return Group(
            Panel(
                Text(
                    "🟢 All Clear! No critical contract breaks, security leaks, or test gaps detected.",
                    style="bold green",
                ),
                title="[bold green]🛡️ Risk & Guard Radar[/bold green]",
                border_style="green",
                padding=(1, 2),
            )
        )

    risk_table = Table(
        title="[bold red]🛡️ Deep Risk & Security Radar[/bold red]",
        expand=True,
        border_style="red",
    )
    risk_table.add_column("Severity", width=14)
    risk_table.add_column("Category", width=22, style="cyan")
    risk_table.add_column("Finding & Impact", ratio=3)
    risk_table.add_column("Remediation", ratio=2, style="italic green")

    for r in risks:
        location = r.file_path or "repository-wide"
        finding = Text.assemble(
            (location, "bold underline white"),
            (f" ({r.line_hint})\n" if r.line_hint else "\n", "dim white"),
            (f"{r.title}\n", "bold yellow"),
            (r.explanation, "white"),
        )
        risk_table.add_row(
            get_severity_badge(r.severity),
            _enum_str(r.category),
            finding,
            r.remediation,
        )

    return Group(risk_table)


def render_diagram_tab(report: GitNarratorReport) -> Group:
    """Render Tab 3: Visual Flow Diagram & Review Checklist."""
    elements: list[RenderableType] = []

    flow = report.visual_flow
    if flow:
        if flow.ascii_diagram:
            elements.append(
                Panel(
                    Text(flow.ascii_diagram, style="bold cyan"),
                    title="[bold cyan]🗺️ Visual Flow (Terminal ASCII)[/bold cyan]",
                    border_style="cyan",
                    padding=(1, 2),
                )
            )

        if flow.mermaid_code:
            syntax = Syntax(flow.mermaid_code, "mermaid", theme="monokai", line_numbers=False)
            elements.append(
                Panel(
                    syntax,
                    title="[bold magenta]Mermaid Diagram (Press [m] to copy)[/bold magenta]",
                    border_style="magenta",
                    padding=(1, 2),
                )
            )
    else:
        elements.append(
            Panel(
                Text("No visual flow diagram generated for this changeset.", style="dim white"),
                title="[bold cyan]🗺️ Visual Flow[/bold cyan]",
                border_style="dim cyan",
                padding=(1, 2),
            )
        )

    checklist = report.review_checklist
    checks_grid = Table.grid(expand=True)
    checks_grid.add_column()

    if checklist.manual_checks:
        checks_grid.add_row(Text("Manual Verification Required:", style="bold yellow"))
        for item in checklist.manual_checks:
            checks_grid.add_row(Text(f"  [ ] {item}", style="white"))

    if checklist.breaking_changes:
        checks_grid.add_row(Text("\n⚠️ Explicit Breaking Changes:", style="bold red"))
        for item in checklist.breaking_changes:
            checks_grid.add_row(Text(f"  • {item}", style="bold red"))

    if not checklist.manual_checks and not checklist.breaking_changes:
        checks_grid.add_row(Text("No special manual checks or breaking changes flagged.", style="dim green"))

    elements.append(
        Panel(
            checks_grid,
            title="[bold yellow]📋 Review Checklist[/bold yellow]",
            border_style="yellow",
            padding=(1, 2),
        )
    )

    return Group(*elements)


def render_commit_tab(report: GitNarratorReport) -> Group:
    """Render Tab 4: Conventional Commit Message and PR Markdown."""
    elements: list[RenderableType] = [
        Panel(
            Text(report.conventional_commit, style="bold green"),
            title="[bold green]📦 Conventional Commit Message[/bold green]",
            subtitle="[dim]Press [c] to commit staged changes  •  [e] to edit[/dim]",
            border_style="green",
            padding=(1, 2),
        )
    ]

    pr_markdown = generate_pr_markdown(report)
    syntax = Syntax(pr_markdown, "markdown", theme="github-dark", line_numbers=False)

    elements.append(
        Panel(
            syntax,
            title="[bold blue]📝 Pull Request Description (Markdown)[/bold blue]",
            subtitle="[dim]Press [p] to copy to clipboard[/dim]",
            border_style="blue",
            padding=(1, 2),
        )
    )

    return Group(*elements)


def generate_pr_markdown(report: GitNarratorReport) -> str:
    """Generate a production-ready GitHub PR description."""
    exec_s = report.executive_summary
    arch = report.architecture_narrative
    risks = report.risk_radar
    flow = report.visual_flow
    chk = report.review_checklist
    blast = _enum_str(exec_s.blast_radius)

    lines = [
        f"## 📖 {exec_s.headline}",
        "",
        f"**Intent:** {exec_s.intent}",
        f"**Impact:** {exec_s.overall_impact}",
        f"**Blast Radius:** `{blast}` | **Tags:** " + " ".join(f"`#{t}`" for t in exec_s.tags),
        "",
        "### 🏛️ Architecture Evolution",
        "| State Before | State After |",
        "| :--- | :--- |",
        f"| {arch.before_state} | {arch.after_state} |",
        "",
    ]

    if arch.tech_debt:
        lines.extend([f"**Technical Debt:** {arch.tech_debt}", ""])

    if flow and flow.mermaid_code:
        lines.extend([
            "### 🗺️ Visual Flow",
            "```mermaid",
            flow.mermaid_code.strip(),
            "```",
            "",
        ])

    if risks:
        lines.extend([
            "### 🛡️ Risk & Security Assessment",
            "| Severity | Category | Finding | Remediation |",
            "| :--- | :--- | :--- | :--- |",
        ])
        for r in risks:
            loc = f"`{r.file_path}`: " if r.file_path else ""
            lines.append(
                f"| **{_enum_str(r.severity)}** | `{_enum_str(r.category)}` | {loc}{r.title} | {r.remediation} |"
            )
        lines.append("")

    if chk.breaking_changes:
        lines.append("### ⚠️ Breaking Changes")
        for b in chk.breaking_changes:
            lines.append(f"- {b}")
        lines.append("")

    if chk.manual_checks:
        lines.append("### 📋 Review Checklist")
        for c in chk.manual_checks:
            lines.append(f"- [ ] {c}")
        lines.append("")

    lines.append(f"*Generated by [git-narrator]({REPO_URL})*")
    return "\n".join(lines)


def emit_github_annotations(report: GitNarratorReport, out_console: Console | None = None) -> None:
    """Emit GitHub Actions workflow annotations (`::error` / `::warning`) for PR diff view."""
    printer = out_console or console
    for r in report.risk_radar:
        sev = _enum_str(r.severity).upper()
        if sev not in ("CRITICAL", "HIGH", "MEDIUM"):
            continue
        level = "error" if sev in ("CRITICAL", "HIGH") else "warning"
        file_attr = f"file={r.file_path}" if r.file_path else ""
        title_attr = f"title=[{sev}] {_enum_str(r.category)}: {r.title}"
        meta = ",".join(part for part in (file_attr, title_attr) if part)
        msg = f"{r.explanation} Remediation: {r.remediation}".replace("\n", " ")
        printer.print(f"::{level} {meta}::{msg}", markup=False, highlight=False)


def write_github_step_summary(report: GitNarratorReport) -> bool:
    """Append generated PR Markdown report to $GITHUB_STEP_SUMMARY when running in GitHub Actions."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return False
    try:
        markdown = generate_pr_markdown(report)
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write("\n" + markdown + "\n")
        return True
    except OSError:
        return False


def render_footer(current_tab: int, risk_count: int, toast: str | None = None) -> Group:
    """Render bottom tab switcher, shortcuts, and optional feedback toast."""
    def tab_title(num: int, label: str) -> Text:
        if current_tab == num:
            return Text(f" [{num}] {label} ", style="bold black on cyan")
        return Text(f" [{num}] {label} ", style="dim white")

    grid = Table.grid(expand=True)
    grid.add_column(justify="left", ratio=3)
    grid.add_column(justify="right", ratio=2)

    tabs = Text.assemble(
        tab_title(1, "The Story"),
        (" ", ""),
        tab_title(2, f"Risk Radar ({risk_count})"),
        (" ", ""),
        tab_title(3, "Visual Flow"),
        (" ", ""),
        tab_title(4, "Commit & PR"),
    )

    shortcuts = Text.assemble(
        ("[←/→]", "dim cyan"), (" Tab  ", "white"),
        ("[c]", "bold green"), (" Commit  ", "white"),
        ("[p]", "bold blue"), (" Copy PR  ", "white"),
        ("[m]", "bold magenta"), (" Mermaid  ", "white"),
        ("[e]", "bold yellow"), (" Edit  ", "white"),
        ("[q]", "bold red"), (" Quit", "white"),
    )

    grid.add_row(tabs, shortcuts)
    panel = Panel(grid, border_style="dim", padding=(0, 1))
    if toast:
        return Group(Text(f" {toast}", style="bold green"), panel)
    return Group(panel)
