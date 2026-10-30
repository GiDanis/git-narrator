"""Rich TUI interface and interactive visual renderer for git-narrator."""

from typing import Any, Dict, List, Optional
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.syntax import Syntax


console = Console()


def get_impact_badge(impact: str) -> Text:
    """Returns a styled badge for overall impact level."""
    imp = str(impact).upper()
    if imp == "CRITICAL":
        return Text(" CRITICAL ", style="bold white on red")
    elif imp == "HIGH":
        return Text(" HIGH ", style="bold white on dark_orange")
    elif imp == "MEDIUM":
        return Text(" MEDIUM ", style="bold black on yellow")
    else:
        return Text(" LOW ", style="bold white on green")


def get_severity_badge(severity: str) -> Text:
    """Returns a styled icon + text for risk severity."""
    sev = str(severity).upper()
    if sev == "CRITICAL":
        return Text("🔴 CRITICAL", style="bold red")
    elif sev == "HIGH":
        return Text("🟠 HIGH", style="bold dark_orange")
    elif sev == "MEDIUM":
        return Text("🟡 MEDIUM", style="bold yellow")
    elif sev == "LOW":
        return Text("🟢 LOW", style="bold green")
    else:
        return Text("🔵 INFO", style="bold cyan")


def render_header(branch: str, stats_summary: str, provider_info: str) -> Panel:
    """Renders the top branding and repository context bar."""
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


def render_story_tab(report: Any) -> Group:
    """Renders Tab 1: The Executive Story and Architecture Narrative."""
    elements = []

    # 1. Executive Summary Panel
    exec_summary = report.executive_summary
    headline_text = Text.assemble(
        (exec_summary.headline + "\n\n", "bold bright_white"),
        ("Intent: ", "bold cyan"),
        (exec_summary.intent + "\n", "italic white"),
    )

    tags_text = Text("Tags: ", style="dim")
    for t in exec_summary.tags:
        tags_text.append(f"#{t} ", style="bold cyan")

    summary_content = Table.grid(expand=True)
    summary_content.add_column(ratio=5)
    summary_content.add_column(ratio=1, justify="right")
    summary_content.add_row(headline_text, get_impact_badge(exec_summary.overall_impact))

    elements.append(
        Panel(
            Group(summary_content, tags_text),
            title="[bold yellow]💡 The Executive Story[/bold yellow]",
            border_style="yellow",
            padding=(1, 2),
        )
    )

    # 2. Architecture Evolution Panel (Before vs After)
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

    # 3. Component Mutations
    if arch.components_affected:
        comp_table = Table(title="[bold magenta]Components Modified[/bold magenta]", expand=True, border_style="dim")
        comp_table.add_column("Component", style="bold cyan", width=24)
        comp_table.add_column("Mutation", style="bold yellow", width=14)
        comp_table.add_column("Summary", style="white")

        for comp in arch.components_affected:
            comp_table.add_row(comp.component_name, comp.mutation_type, comp.summary)

        elements.append(comp_table)

    # 4. Tech Debt Incurred
    if arch.architectural_debt_incurred:
        debt_text = Text.assemble(
            ("⚠️  Note on Technical Debt: ", "bold yellow"),
            (arch.architectural_debt_incurred, "white"),
        )
        elements.append(Panel(debt_text, border_style="yellow", padding=(0, 1)))

    return Group(*elements)


def render_risk_tab(report: Any) -> Group:
    """Renders Tab 2: Deep Risk & Negative Space Radar."""
    risks = report.risk_radar

    if not risks:
        return Group(
            Panel(
                Text("🟢 All Clear! No critical contract breaks, security leaks, or missing test gaps detected.", style="bold green"),
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
    risk_table.add_column("Category", width=20, style="cyan")
    risk_table.add_column("Finding & Impact", ratio=3)
    risk_table.add_column("Remediation", ratio=2, style="italic green")

    for r in risks:
        finding = Text.assemble(
            (f"{r.file_path}", "bold underline white"),
            (f" ({r.line_hint})\n" if r.line_hint else "\n", "dim white"),
            (f"{r.title}\n", "bold yellow"),
            (f"{r.explanation}", "white"),
        )
        risk_table.add_row(
            get_severity_badge(r.severity),
            r.category,
            finding,
            r.remediation,
        )

    return Group(risk_table)


def render_diagram_tab(report: Any) -> Group:
    """Renders Tab 3: Visual Flow Diagram & Review Checklist."""
    elements = []

    # Visual Diagram Box
    flow = report.visual_flow
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
                title="[bold magenta]Mermaid Diagram (Ready for PR/Docs)[/bold magenta]",
                border_style="magenta",
                padding=(1, 2),
            )
        )

    # Review Checklist Box
    checklist = report.review_checklist
    checks_grid = Table.grid(expand=True)
    checks_grid.add_column()

    if checklist.manual_checks:
        checks_grid.add_row(Text("Manual Verification Required in Staging:", style="bold yellow"))
        for item in checklist.manual_checks:
            checks_grid.add_row(Text(f"  [ ] {item}", style="white"))

    if checklist.breaking_changes:
        checks_grid.add_row(Text("\n⚠️ Explicit Breaking Changes:", style="bold red"))
        for item in checklist.breaking_changes:
            checks_grid.add_row(Text(f"  • {item}", style="bold red"))

    elements.append(
        Panel(
            checks_grid,
            title="[bold yellow]📋 Review Checklist[/bold yellow]",
            border_style="yellow",
            padding=(1, 2),
        )
    )

    return Group(*elements)


def render_commit_tab(report: Any) -> Group:
    """Renders Tab 4: Conventional Commit Message and PR Markdown."""
    elements = []

    # Conventional Commit Panel
    elements.append(
        Panel(
            Text(report.conventional_commit, style="bold green"),
            title="[bold green]📦 Conventional Commit Message[/bold green]",
            subtitle="[dim]Press [c] to commit directly[/dim]",
            border_style="green",
            padding=(1, 2),
        )
    )

    # PR Markdown Generator
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


def generate_pr_markdown(report: Any) -> str:
    """Generates an aesthetic, production-ready GitHub PR description."""
    exec_s = report.executive_summary
    arch = report.architecture_narrative
    risks = report.risk_radar
    flow = report.visual_flow
    chk = report.review_checklist

    lines = [
        f"## 📖 {exec_s.headline}",
        "",
        f"**Intent:** {exec_s.intent}",
        f"**Blast Radius:** `{exec_s.overall_impact}` | **Tags:** " + " ".join([f"`#{t}`" for t in exec_s.tags]),
        "",
        "### 🏛️ Architecture Evolution",
        "| State Before | State After |",
        "| :--- | :--- |",
        f"| {arch.before_state} | {arch.after_state} |",
        "",
    ]

    if flow.mermaid_code:
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
            "| Severity | Finding | Remediation |",
            "| :--- | :--- | :--- |",
        ])
        for r in risks:
            lines.append(f"| **{r.severity}** | `{r.file_path}`: {r.title} | {r.remediation} |")
        lines.append("")

    if chk.manual_checks:
        lines.append("### 📋 Review Checklist")
        for c in chk.manual_checks:
            lines.append(f"- [ ] {c}")
        lines.append("")

    lines.append("*Generated by [git-narrator](https://github.com/giuseppe/git-narrator)*")
    return "\n".join(lines)


def render_footer(current_tab: int, risk_count: int) -> Panel:
    """Renders the bottom tab switcher and shortcut key guide."""
    def tab_title(num: int, label: str) -> Text:
        if current_tab == num:
            return Text(f" [{num}] {label} ", style="bold black on cyan")
        return Text(f" [{num}] {label} ", style="dim white")

    grid = Table.grid(expand=True)
    grid.add_column(justify="left", ratio=3)
    grid.add_column(justify="right", ratio=2)

    risk_label = f"Risk Radar ({risk_count})" if risk_count > 0 else "Risk Radar (0)"
    tabs = Text.assemble(
        tab_title(1, "The Story"),
        (" ", ""),
        tab_title(2, risk_label),
        (" ", ""),
        tab_title(3, "Visual Flow"),
        (" ", ""),
        tab_title(4, "Commit & PR"),
    )

    shortcuts = Text.assemble(
        ("[c]", "bold green"), (" Commit  ", "white"),
        ("[p]", "bold blue"), (" Copy PR  ", "white"),
        ("[e]", "bold yellow"), (" Edit in $EDITOR  ", "white"),
        ("[q]", "bold red"), (" Quit", "white"),
    )

    grid.add_row(tabs, shortcuts)
    return Panel(grid, border_style="dim", padding=(0, 1))
