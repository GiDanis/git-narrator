"""git-narrator CLI entrypoint with lazy-import architecture and live streaming."""

import os
import sys
import time
from typing import TYPE_CHECKING, Any

import click

from git_narrator import __version__

if TYPE_CHECKING:
    from git_narrator.schemas import GitNarratorReport

_SEVERITY_RANK = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}


class AnalysisResult:
    """Full output plus git/provider metadata from an analysis run."""

    __slots__ = ("branch", "provider_label", "report", "short_stat", "staged_only")

    def __init__(
        self,
        report: "GitNarratorReport",
        branch: str,
        short_stat: str,
        provider_label: str,
        staged_only: bool = False,
    ) -> None:
        self.report = report
        self.branch = branch
        self.short_stat = short_stat
        self.provider_label = provider_label
        self.staged_only = staged_only


def _shared_provider_options(func: Any) -> Any:
    """Apply common AI & diff options cleanly without duplication."""
    decorators = [
        click.option("--local", "-l", is_flag=True, help="Force local Ollama model (100% offline & private)."),
        click.option(
            "--provider",
            "-p",
            help="Override AI provider (ollama, gemini, openai, anthropic, groq, deepseek, openrouter).",
        ),
        click.option("--model", "-m", help="Override AI model name."),
        click.option("--context", "-x", "extra_context", default="", help="Additional architectural intent or context for AI."),
        click.option("--lang", default=None, help="Target language for prose narratives (e.g. 'Italian', 'English')."),
        click.option("--max-tokens", type=int, default=None, help="Override knapsack token budget for diff compaction."),
    ]
    for dec in reversed(decorators):
        func = dec(func)
    return func


def _shared_output_options(func: Any) -> Any:
    """Apply common output, scope, and CI gate options."""
    decorators = [
        click.option("--staged", is_flag=True, help="Analyze only staged changes."),
        click.option("--unstaged", is_flag=True, help="Analyze only unstaged/untracked working tree changes."),
        click.option(
            "--format",
            "-f",
            "output_format",
            type=click.Choice(["interactive", "markdown", "json"]),
            default="interactive",
            help="Output format.",
        ),
        click.option(
            "--fail-on-risk",
            type=click.Choice(["CRITICAL", "HIGH", "MEDIUM", "LOW"]),
            help="CI/CD gate: exit 1 if risk at or above this severity.",
        ),
        click.option("--copy", "-c", is_flag=True, help="Copy PR markdown to clipboard automatically."),
        click.option("--ci", is_flag=True, help="CI mode: non-interactive Markdown, GitHub annotations & $GITHUB_STEP_SUMMARY."),
    ]
    for dec in reversed(decorators):
        func = dec(func)
    return func


@click.group(invoke_without_command=True)
@click.pass_context
@_shared_provider_options
@_shared_output_options
@click.version_option(version=__version__, prog_name="git-narrator")
def cli(
    ctx: click.Context,
    local: bool,
    provider: str | None,
    model: str | None,
    extra_context: str,
    lang: str | None,
    max_tokens: int | None,
    staged: bool,
    unstaged: bool,
    output_format: str,
    fail_on_risk: str | None,
    copy: bool,
    ci: bool,
) -> None:
    """Understand any git diff in 5 seconds.

    The AI-powered narrative walkthrough and risk radar for human and agentic code.
    """
    if ctx.invoked_subcommand is None:
        run_narrator_flow(
            target_ref=None,
            forced_local=local,
            override_provider=provider,
            override_model=model,
            output_format=output_format,
            fail_on_risk=fail_on_risk,
            auto_copy=copy,
            extra_context=extra_context,
            language=lang,
            max_tokens=max_tokens,
            staged=staged,
            unstaged=unstaged,
            ci_mode=ci,
        )


@cli.command("diff")
@click.argument("ref", required=False)
@_shared_provider_options
@_shared_output_options
def diff_cmd(
    ref: str | None,
    local: bool,
    provider: str | None,
    model: str | None,
    extra_context: str,
    lang: str | None,
    max_tokens: int | None,
    staged: bool,
    unstaged: bool,
    output_format: str,
    fail_on_risk: str | None,
    copy: bool,
    ci: bool,
) -> None:
    """Analyze a specific git commit, range, or branch diff (e.g. HEAD~1, main..feature)."""
    run_narrator_flow(
        target_ref=ref,
        forced_local=local,
        override_provider=provider,
        override_model=model,
        output_format=output_format,
        fail_on_risk=fail_on_risk,
        auto_copy=copy,
        extra_context=extra_context,
        language=lang,
        max_tokens=max_tokens,
        staged=staged,
        unstaged=unstaged,
        ci_mode=ci,
    )


@cli.command("commit")
@_shared_provider_options
@click.option("--yes", "-y", is_flag=True, help="Automatically commit without interactive confirmation.")
def commit_cmd(
    local: bool,
    provider: str | None,
    model: str | None,
    extra_context: str,
    lang: str | None,
    max_tokens: int | None,
    yes: bool,
) -> None:
    """Generate a Conventional Commit message and commit staged changes immediately."""
    from rich.console import Console
    from rich.prompt import Confirm

    from git_narrator.clipboard import copy_to_clipboard
    from git_narrator.git_engine import GitError, detect_change_scope, is_git_repo, run_git

    console = Console()
    if not is_git_repo():
        console.print("[bold red]Error:[/bold red] Not inside a git repository.")
        sys.exit(1)

    scope = detect_change_scope(".")
    if scope.scope_type != "staged":
        if scope.scope_type == "unstaged":
            console.print("[yellow]No staged changes found. Run `git add` on files to commit first.[/yellow]")
        else:
            console.print("[yellow]Working directory clean. No staged changes to commit.[/yellow]")
        return

    report = run_analysis_pipeline(
        target_ref=None,
        forced_local=local,
        override_provider=provider,
        override_model=model,
        extra_context=extra_context,
        language=lang,
        max_tokens=max_tokens,
        staged=True,
    )

    commit_msg = report.conventional_commit.strip()
    console.print(f"\n[bold cyan]Generated Commit Message:[/bold cyan]\n[green]{commit_msg}[/green]\n")

    if yes or Confirm.ask("[bold]Apply this commit?[/bold]", default=True):
        try:
            run_git(["commit", "-m", commit_msg], check=True)
            console.print("[bold green]✓ Successfully committed changes![/bold green]")
        except GitError as exc:
            console.print(f"[bold red]Commit failed:[/bold red] {exc}")
            copy_to_clipboard(commit_msg)
            console.print("[dim]Message copied to clipboard instead.[/dim]")
            sys.exit(1)
    else:
        copy_to_clipboard(commit_msg)
        console.print("[yellow]Commit aborted. Message copied to clipboard.[/yellow]")


@cli.command("pr")
@click.argument("ref", required=False)
@_shared_provider_options
@click.option("--staged", is_flag=True, help="Generate PR summary from staged changes.")
def pr_cmd(
    ref: str | None,
    local: bool,
    provider: str | None,
    model: str | None,
    extra_context: str,
    lang: str | None,
    max_tokens: int | None,
    staged: bool,
) -> None:
    """Generate a complete GitHub Pull Request description in Markdown and copy to clipboard."""
    from rich.console import Console

    from git_narrator.clipboard import copy_to_clipboard
    from git_narrator.ui import generate_pr_markdown

    console = Console()
    report = run_analysis_pipeline(
        target_ref=ref,
        forced_local=local,
        override_provider=provider,
        override_model=model,
        extra_context=extra_context,
        language=lang,
        max_tokens=max_tokens,
        staged=staged,
    )

    markdown = generate_pr_markdown(report)
    console.print(markdown, markup=False)
    if copy_to_clipboard(markdown):
        console.print("\n[bold green]✓ PR Markdown copied to clipboard![/bold green]")


@cli.group("config", invoke_without_command=True)
@click.pass_context
def config_cmd(ctx: click.Context) -> None:
    """Display and configure active AI providers and preferences."""
    if ctx.invoked_subcommand is not None:
        return

    from rich.console import Console
    from rich.table import Table

    from git_narrator.config import (
        GLOBAL_CONFIG_PATH,
        PROVIDER_SPECS,
        _ollama_url,
        is_ollama_reachable,
        load_config,
        resolve_provider_and_model,
    )

    console = Console()
    config = load_config()
    prov, mod, _key, _base = resolve_provider_and_model(auto_discover_ollama=False)

    table = Table(title="[bold cyan]git-narrator Configuration[/bold cyan]", expand=False)
    table.add_column("Setting", style="bold white")
    table.add_column("Current Value", style="yellow")
    table.add_column("Status / Source", style="cyan")

    ollama_url = _ollama_url(config)
    ollama_ok = is_ollama_reachable(base_url=ollama_url)
    table.add_row(
        "Active Provider",
        prov.upper(),
        "[green]Online[/green]" if (prov != "ollama" or ollama_ok) else "[red]Offline[/red]",
    )
    table.add_row("Active Model", mod, "Configured" if config.get("model") else "Auto-selected")
    table.add_row(
        "Ollama Daemon",
        ollama_url,
        "[green]Running[/green]" if ollama_ok else "[dim]Not detected[/dim]",
    )

    for p_name, spec in PROVIDER_SPECS.items():
        if not spec.env_key:
            continue
        has_env = bool(os.environ.get(spec.env_key))
        has_cfg = bool(config.get(f"{p_name}_api_key"))
        status = "Env Var" if has_env else ("Config File" if has_cfg else "-")
        table.add_row(spec.env_key, "***" if (has_env or has_cfg) else "Not set", status)

    table.add_row("Global Config", str(GLOBAL_CONFIG_PATH), "Exists" if GLOBAL_CONFIG_PATH.exists() else "Not created")
    console.print(table)


@config_cmd.command("set")
@click.argument("key")
@click.argument("value")
def config_set_cmd(key: str, value: str) -> None:
    """Persist a global configuration key/value (e.g. `git narrator config set provider gemini`)."""
    from rich.console import Console

    from git_narrator.config import GLOBAL_CONFIG_PATH, save_global_config

    save_global_config({key: value})
    Console().print(f"[green]✓ Saved[/green] [bold]{key}[/bold] = {value!r} in {GLOBAL_CONFIG_PATH}")


@cli.command("install-hook")
@click.option("--force", is_flag=True, help="Overwrite existing non-git-narrator prepare-commit-msg hook.")
def install_hook_cmd(force: bool) -> None:
    """Install a `prepare-commit-msg` git hook to pre-fill Conventional Commit messages."""
    from rich.console import Console

    from git_narrator.git_engine import GitError, install_prepare_commit_msg_hook

    console = Console()
    try:
        hook_path = install_prepare_commit_msg_hook(".", force=force)
        console.print(f"[bold green]✓ Installed git-narrator hook at:[/bold green] {hook_path}")
    except GitError as exc:
        console.print(f"[bold red]Hook installation failed:[/bold red] {exc}")
        sys.exit(1)


@cli.command("_prepare-hook", hidden=True)
@click.argument("commit_msg_file")
def prepare_hook_internal(commit_msg_file: str) -> None:
    """Internal entrypoint invoked by `.git/hooks/prepare-commit-msg`."""
    from pathlib import Path

    try:
        report = run_analysis_pipeline(target_ref=None, staged=True)
        commit_msg = report.conventional_commit.strip()
        msg_path = Path(commit_msg_file)
        existing = msg_path.read_text(encoding="utf-8", errors="replace") if msg_path.exists() else ""
        # Keep Git's comment lines intact beneath generated commit message
        if existing and not existing.lstrip().startswith("#"):
            return
        msg_path.write_text(f"{commit_msg}\n\n{existing}", encoding="utf-8")
    except SystemExit:
        return
    except Exception:  # noqa: BLE001 — hooks must fail open so git commit is never blocked
        return


def _detect_stream_stage(partial_json: str) -> str:
    """Infer current JSON section being streamed for live UX status."""
    if '"conventional_commit"' in partial_json:
        return "Synthesizing Conventional Commit & PR..."
    if '"visual_flow"' in partial_json:
        return "Drawing visual architecture flow..."
    if '"risk_radar"' in partial_json:
        return "Scanning negative-space Risk Radar..."
    if '"architecture_narrative"' in partial_json:
        return "Mapping Before/After architecture..."
    if '"executive_summary"' in partial_json:
        return "Writing executive story..."
    return "Reading changeset & planning narrative..."


def _format_pruned_summary(pruned_files: list[Any], secret_findings: list[Any]) -> str:
    lines: list[str] = []
    for p in pruned_files[:25]:
        reason = getattr(p.reason, "value", str(p.reason))
        lines.append(f"- `{p.path}` [{reason}]")
    if len(pruned_files) > 25:
        lines.append(f"- ... and {len(pruned_files) - 25} more pruned files")
    for s in secret_findings[:10]:
        lines.append(f"- `{s.file_path}` [SECRET_REDACTED: {s.secret_type}]")
    return "\n".join(lines)


def _merge_deterministic_risks(report: "GitNarratorReport", deterministic_risks: list[Any]) -> None:
    """Prepend deterministic safety risks without duplicating identical findings."""
    existing_keys = {(str(r.category), r.file_path, r.title) for r in report.risk_radar}
    to_prepend = [
        risk
        for risk in deterministic_risks
        if (str(risk.category), risk.file_path, risk.title) not in existing_keys
    ]
    if to_prepend:
        report.risk_radar = [*to_prepend, *report.risk_radar]


def run_analysis_with_context(
    target_ref: str | None,
    forced_local: bool = False,
    override_provider: str | None = None,
    override_model: str | None = None,
    extra_context: str = "",
    language: str | None = None,
    max_tokens: int | None = None,
    staged: bool = False,
    unstaged: bool = False,
) -> AnalysisResult:
    """Execute complete git diff extraction, sanitization, compaction, and AI generation."""
    import asyncio

    from rich.console import Console
    from rich.live import Live
    from rich.spinner import Spinner

    from git_narrator.config import PROVIDER_SPECS, resolve_provider_and_model
    from git_narrator.git_engine import (
        detect_change_scope,
        get_commit_context,
        get_current_branch,
        get_diff,
        get_repo_root,
        get_stat,
        get_untracked_diffs,
        is_git_repo,
    )
    from git_narrator.knapsack import optimize_diff_tokens
    from git_narrator.lockfile import strip_lockfiles_and_inject_summary
    from git_narrator.parser import parse_and_validate_report
    from git_narrator.prompts import SYSTEM_PROMPT, build_narrator_prompt
    from git_narrator.providers import create_provider
    from git_narrator.sanitizer import sanitize_diff, scan_deterministic_risks
    from git_narrator.schemas import get_report_json_schema
    from git_narrator.transport import HTTPStatusError, TransportError

    console = Console()
    if not is_git_repo():
        console.print("[bold red]Error:[/bold red] Not inside a git repository.")
        sys.exit(1)

    repo_root = get_repo_root(".")

    # 1. Resolve Git Scope
    staged_flag = staged
    target: str | None = target_ref
    commit_ctx_str = ""
    untracked_files: list[str] = []

    if staged:
        target = None
        staged_flag = True
    elif unstaged:
        scope = detect_change_scope(".")
        target = None
        staged_flag = False
        untracked_files = scope.untracked_files
    elif target_ref:
        target = target_ref
        if ".." not in target_ref:
            try:
                cinfo = get_commit_context(repo_root, target_ref)
                commit_ctx_str = f"Commit {cinfo.short_sha} by {cinfo.author_name}: {cinfo.message}"
            except Exception:  # noqa: BLE001
                commit_ctx_str = ""
    else:
        scope = detect_change_scope(repo_root)
        if scope.scope_type == "empty":
            console.print("[yellow]Working tree clean, no modified files or commits to analyze.[/yellow]")
            sys.exit(0)
        if scope.scope_type == "staged":
            staged_flag = True
            target = None
        elif scope.scope_type == "unstaged":
            staged_flag = False
            target = None
            untracked_files = scope.untracked_files
        else:
            target = scope.ref or "HEAD"
            if scope.commit_info:
                commit_ctx_str = (
                    f"Commit {scope.commit_info.short_sha} by "
                    f"{scope.commit_info.author_name}: {scope.commit_info.message}"
                )

    # 2. Extract Git Diff & Summary
    raw_diff = get_diff(repo_root, target=target, staged=staged_flag)
    if untracked_files:
        raw_diff += get_untracked_diffs(repo_root, untracked_files)

    diff_stat = get_stat(repo_root, target=target, staged=staged_flag)
    branch = get_current_branch(repo_root) or "HEAD"

    # 3. Sanitize (including .narratorignore, .gitattributes & Secret Redaction) + Compact Lockfiles
    sanitized = sanitize_diff(raw_diff, repo_root=repo_root)
    cleaned_diff, dep_summary, _ = strip_lockfiles_and_inject_summary(sanitized.cleaned_diff)
    deterministic_risks = scan_deterministic_risks(sanitized.cleaned_diff, sanitized.secret_findings)

    # 4. Resolve AI Provider & Model-Aware Knapsack Budget
    prov_name, model_name, api_key, base_url = resolve_provider_and_model(
        forced_local=forced_local,
        override_provider=override_provider,
        override_model=override_model,
    )
    spec = PROVIDER_SPECS.get(prov_name)
    budget = max_tokens or (spec.recommended_diff_tokens if spec else 14000)

    knapsack = optimize_diff_tokens(cleaned_diff, token_budget=budget)
    final_diff = knapsack.optimized_diff

    if spec and spec.env_key and not api_key and "localhost" not in (base_url or ""):
        console.print(
            f"[bold red]Error:[/bold red] {spec.env_key} environment variable required for {prov_name} provider."
        )
        sys.exit(1)

    try:
        ai_provider = create_provider(
            provider_name=prov_name,
            model=model_name,
            api_key=api_key,
            base_url=base_url,
        )
    except ValueError as exc:
        console.print(f"[bold red]Provider Configuration Error:[/bold red] {exc}")
        sys.exit(1)

    schema = get_report_json_schema()
    prompt = build_narrator_prompt(
        diff=final_diff,
        stat=diff_stat,
        lockfile_mutations=dep_summary,
        branch_info=branch,
        extra_context=extra_context,
        commit_context=commit_ctx_str,
        pruned_summary=_format_pruned_summary(sanitized.pruned_files, sanitized.secret_findings),
        language=language,
        include_schema=not ai_provider.supports_native_schema,
    )

    chunks: list[str] = []

    async def collect_stream() -> None:
        start_ts = time.perf_counter()
        use_live = sys.stderr.isatty() or sys.stdout.isatty()
        label = f"[bold magenta]{prov_name}/{model_name}[/bold magenta]"

        async with ai_provider as active_provider:
            if not use_live:
                async for chunk in active_provider.stream_structured(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=prompt,
                    json_schema=schema,
                ):
                    chunks.append(chunk)
                return

            spinner = Spinner("dots", text=f"[cyan]Narrating via {label}...[/cyan]")
            with Live(spinner, console=console, transient=True, refresh_per_second=12):
                chars = 0
                async for chunk in active_provider.stream_structured(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=prompt,
                    json_schema=schema,
                ):
                    chunks.append(chunk)
                    chars += len(chunk)
                    elapsed = time.perf_counter() - start_ts
                    stage = _detect_stream_stage("".join(chunks))
                    spinner.update(
                        text=(
                            f"[cyan]{stage}[/cyan] ({label} • "
                            f"[dim]{chars} chars • {elapsed:.1f}s[/dim])"
                        )
                    )

    try:
        asyncio.run(collect_stream())
    except HTTPStatusError as exc:
        console.print(f"[bold red]AI Provider Error ({prov_name} HTTP {exc.status_code}):[/bold red] {exc.message}")
        if prov_name == "ollama" and exc.status_code == 404:
            console.print(f"[yellow]Tip: Pull the model first with: `ollama pull {model_name}`[/yellow]")
        else:
            console.print("[yellow]Tip: Run with --local to use Ollama, or check your API key/model config.[/yellow]")
        sys.exit(1)
    except (TransportError, OSError, RuntimeError) as exc:
        console.print(f"[bold red]AI Engine Connection Error ({prov_name}):[/bold red] {exc}")
        console.print("[yellow]Tip: Run with --local to use Ollama, or set GEMINI_API_KEY / OPENAI_API_KEY.[/yellow]")
        sys.exit(1)

    report = parse_and_validate_report("".join(chunks))
    _merge_deterministic_risks(report, deterministic_risks)

    stat_lines = diff_stat.strip().splitlines()
    short_stat = stat_lines[-1] if stat_lines else f"{len(sanitized.kept_files)} files changed"
    return AnalysisResult(
        report=report,
        branch=branch,
        short_stat=short_stat,
        provider_label=f"{prov_name}/{model_name}",
        staged_only=staged_flag,
    )


def run_analysis_pipeline(
    target_ref: str | None,
    forced_local: bool = False,
    override_provider: str | None = None,
    override_model: str | None = None,
    extra_context: str = "",
    language: str | None = None,
    max_tokens: int | None = None,
    staged: bool = False,
    unstaged: bool = False,
) -> "GitNarratorReport":
    """Backward-compatible wrapper returning only the validated GitNarratorReport."""
    return run_analysis_with_context(
        target_ref=target_ref,
        forced_local=forced_local,
        override_provider=override_provider,
        override_model=override_model,
        extra_context=extra_context,
        language=language,
        max_tokens=max_tokens,
        staged=staged,
        unstaged=unstaged,
    ).report


def run_narrator_flow(
    target_ref: str | None,
    forced_local: bool,
    override_provider: str | None,
    override_model: str | None,
    output_format: str,
    fail_on_risk: str | None,
    auto_copy: bool,
    extra_context: str = "",
    language: str | None = None,
    max_tokens: int | None = None,
    staged: bool = False,
    unstaged: bool = False,
    ci_mode: bool = False,
) -> None:
    """Orchestrate analysis, CI gates, and interactive or non-interactive rendering."""
    from rich.console import Console

    from git_narrator.clipboard import copy_to_clipboard
    from git_narrator.git_engine import GitError, run_git
    from git_narrator.keyboard import get_single_key
    from git_narrator.ui import (
        emit_github_annotations,
        generate_pr_markdown,
        render_commit_tab,
        render_diagram_tab,
        render_footer,
        render_header,
        render_risk_tab,
        render_story_tab,
        write_github_step_summary,
    )

    console = Console()
    result = run_analysis_with_context(
        target_ref=target_ref,
        forced_local=forced_local,
        override_provider=override_provider,
        override_model=override_model,
        extra_context=extra_context,
        language=language,
        max_tokens=max_tokens,
        staged=staged,
        unstaged=unstaged,
    )
    report = result.report

    if ci_mode:
        if output_format == "interactive":
            output_format = "markdown"
        emit_github_annotations(report, out_console=console)
        write_github_step_summary(report)

    # Non-interactive fallback when piped or inside headless terminal
    if output_format == "interactive" and (not sys.stdout.isatty() or not sys.stdin.isatty()):
        output_format = "markdown"

    # CI/CD Gate check
    gate_failed = False
    gate_failure_msg = ""
    if fail_on_risk:
        threshold = _SEVERITY_RANK.get(fail_on_risk.upper(), 3)
        for r in report.risk_radar:
            sev_name = r.severity.value if hasattr(r.severity, "value") else str(r.severity)
            if _SEVERITY_RANK.get(sev_name.upper(), 0) >= threshold:
                gate_failed = True
                loc = r.file_path or "repository"
                gate_failure_msg = f"Detected {sev_name} risk: {r.title} in {loc}"
                break

    if output_format == "json":
        console.print_json(report.model_dump_json(indent=2))
        if gate_failed:
            console.print(f"[bold red]CI Gate Failed:[/bold red] {gate_failure_msg}")
            sys.exit(1)
        return

    if output_format == "markdown":
        md = generate_pr_markdown(report)
        console.print(md, markup=False)
        if auto_copy:
            copy_to_clipboard(md)
        if gate_failed:
            console.print(f"[bold red]CI Gate Failed:[/bold red] {gate_failure_msg}")
            sys.exit(1)
        return

    if gate_failed:
        console.print(f"[bold red]CI Gate Failed:[/bold red] {gate_failure_msg}")
        sys.exit(1)

    # Interactive TUI mode inside clean alternate screen buffer
    current_tab = 1
    risk_count = len(report.risk_radar)
    toast: str | None = None
    post_exit_message: str | None = None

    with console.screen():
        while True:
            console.clear()
            console.print(render_header(result.branch, result.short_stat, result.provider_label))
            console.print()

            if current_tab == 1:
                console.print(render_story_tab(report))
            elif current_tab == 2:
                console.print(render_risk_tab(report))
            elif current_tab == 3:
                console.print(render_diagram_tab(report))
            elif current_tab == 4:
                console.print(render_commit_tab(report))

            console.print()
            console.print(render_footer(current_tab, risk_count, toast=toast))
            toast = None

            key = get_single_key()
            if key == "q":
                break
            if key in ("1", "2", "3", "4"):
                current_tab = int(key)
            elif key in ("right", "l", "tab"):
                current_tab = (current_tab % 4) + 1
            elif key in ("left", "h"):
                current_tab = ((current_tab - 2) % 4) + 1
            elif key == "c":
                try:
                    run_git(["commit", "-m", report.conventional_commit.strip()], check=True)
                    post_exit_message = f"[bold green]✓ Committed:[/bold green] {report.conventional_commit.strip()}"
                    break
                except GitError as exc:
                    copy_to_clipboard(report.conventional_commit.strip())
                    toast = f"Commit failed ({exc}); message copied to clipboard instead."
            elif key == "p":
                md = generate_pr_markdown(report)
                if copy_to_clipboard(md):
                    toast = "✓ PR Markdown copied to clipboard!"
                else:
                    toast = "Clipboard unavailable on this system."
            elif key == "m":
                if report.visual_flow and report.visual_flow.mermaid_code:
                    if copy_to_clipboard(report.visual_flow.mermaid_code.strip()):
                        toast = "✓ Mermaid diagram copied to clipboard!"
                    else:
                        toast = "Clipboard unavailable on this system."
                else:
                    toast = "No Mermaid diagram present for this changeset."
            elif key == "e":
                edited = click.edit(report.conventional_commit)
                if edited is not None and edited.strip():
                    report.conventional_commit = edited.strip()
                    toast = "✓ Commit message updated."

    if post_exit_message:
        console.print(post_exit_message)


def main() -> None:
    """Package entrypoint."""
    cli()


if __name__ == "__main__":
    main()
