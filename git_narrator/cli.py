"""git-narrator CLI entrypoint with sub-35ms lazy-import architecture."""

import os
import sys

import click


@click.group(invoke_without_command=True)
@click.pass_context
@click.option("--local", "-l", is_flag=True, help="Force local Ollama model (100% offline & private).")
@click.option("--provider", "-p", help="Override AI provider (ollama, gemini, openai, anthropic, groq).")
@click.option("--model", "-m", help="Override AI model name.")
@click.option("--format", "-f", "output_format", type=click.Choice(["interactive", "markdown", "json"]), default="interactive", help="Output format.")
@click.option("--fail-on-risk", type=click.Choice(["CRITICAL", "HIGH", "MEDIUM", "LOW"]), help="CI/CD gate: exit 1 if risk at or above this severity.")
@click.option("--copy", "-c", is_flag=True, help="Copy PR markdown or commit message to clipboard automatically.")
@click.version_option(version="0.1.0", prog_name="git-narrator")
def cli(
    ctx: click.Context,
    local: bool,
    provider: str | None,
    model: str | None,
    output_format: str,
    fail_on_risk: str | None,
    copy: bool,
) -> None:
    """Understand any git diff in 5 seconds.
    
    The AI-powered narrative walkthrough and risk radar for human and agentic code.
    """
    if ctx.invoked_subcommand is None:
        # Default behavior: run analysis on auto-detected scope
        run_narrator_flow(
            target_ref=None,
            forced_local=local,
            override_provider=provider,
            override_model=model,
            output_format=output_format,
            fail_on_risk=fail_on_risk,
            auto_copy=copy,
        )


@cli.command("diff")
@click.argument("ref", required=False)
@click.option("--local", "-l", is_flag=True, help="Force local Ollama model.")
@click.option("--provider", "-p", help="Override AI provider.")
@click.option("--model", "-m", help="Override AI model name.")
@click.option("--format", "-f", "output_format", type=click.Choice(["interactive", "markdown", "json"]), default="interactive")
@click.option("--fail-on-risk", type=click.Choice(["CRITICAL", "HIGH", "MEDIUM", "LOW"]))
@click.option("--copy", "-c", is_flag=True, help="Copy to clipboard automatically.")
def diff_cmd(
    ref: str | None,
    local: bool,
    provider: str | None,
    model: str | None,
    output_format: str,
    fail_on_risk: str | None,
    copy: bool,
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
    )


@cli.command("commit")
@click.option("--local", "-l", is_flag=True, help="Force local Ollama model.")
@click.option("--provider", "-p", help="Override AI provider.")
@click.option("--model", "-m", help="Override AI model name.")
@click.option("--yes", "-y", is_flag=True, help="Automatically commit without interactive confirmation.")
def commit_cmd(local: bool, provider: str | None, model: str | None, yes: bool) -> None:
    """Generate a Conventional Commit message and commit staged changes immediately."""
    from rich.console import Console
    from rich.prompt import Confirm

    from git_narrator.clipboard import copy_to_clipboard
    from git_narrator.git_engine import detect_change_scope, is_git_repo, run_git

    console = Console()
    if not is_git_repo():
        console.print("[bold red]Error:[/bold red] Not inside a git repository.")
        sys.exit(1)

    scope = detect_change_scope()
    if scope.scope_type == "empty":
        console.print("[yellow]Working directory clean. No changes to commit.[/yellow]")
        return

    report = run_analysis_pipeline(
        target_ref=None,
        forced_local=local,
        override_provider=provider,
        override_model=model,
    )

    commit_msg = report.conventional_commit.strip()
    console.print(f"\n[bold cyan]Generated Commit Message:[/bold cyan]\n[green]{commit_msg}[/green]\n")

    if yes or Confirm.ask("[bold]Apply this commit?[/bold]", default=True):
        try:
            run_git(["commit", "-m", commit_msg])
            console.print("[bold green]✓ Successfully committed changes![/bold green]")
        except Exception as e:
            console.print(f"[bold red]Commit failed:[/bold red] {e}")
            copy_to_clipboard(commit_msg)
            console.print("[dim]Message copied to clipboard instead.[/dim]")
    else:
        copy_to_clipboard(commit_msg)
        console.print("[yellow]Commit aborted. Message copied to clipboard.[/yellow]")


@cli.command("pr")
@click.argument("ref", required=False)
@click.option("--local", "-l", is_flag=True, help="Force local Ollama model.")
@click.option("--provider", "-p", help="Override AI provider.")
@click.option("--model", "-m", help="Override AI model name.")
def pr_cmd(ref: str | None, local: bool, provider: str | None, model: str | None) -> None:
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
    )

    markdown = generate_pr_markdown(report)
    console.print(markdown)
    if copy_to_clipboard(markdown):
        console.print("\n[bold green]✓ PR Markdown copied to clipboard via OSC 52![/bold green]")


@cli.command("config")
def config_cmd() -> None:
    """Display and configure active AI providers and preferences."""
    from rich.console import Console
    from rich.table import Table

    from git_narrator.config import (
        is_ollama_reachable,
        load_config,
        resolve_provider_and_model,
    )

    console = Console()
    config = load_config()
    prov, mod, key, base = resolve_provider_and_model()

    table = Table(title="[bold cyan]git-narrator Configuration[/bold cyan]", expand=False)
    table.add_column("Setting", style="bold white")
    table.add_column("Current Value", style="yellow")
    table.add_column("Status / Source", style="cyan")

    ollama_ok = is_ollama_reachable()
    table.add_row("Active Provider", prov.upper(), "[green]Online[/green]" if (prov != "ollama" or ollama_ok) else "[red]Offline[/red]")
    table.add_row("Active Model", mod, "Auto-selected" if not config.get("model") else "Configured")
    table.add_row("Ollama Status", "http://localhost:11434", "[green]Running[/green]" if ollama_ok else "[dim]Not detected[/dim]")
    table.add_row("Gemini API Key", "***" if os.environ.get("GEMINI_API_KEY") else "Not set", "Env Var" if os.environ.get("GEMINI_API_KEY") else "-")
    table.add_row("OpenAI API Key", "***" if os.environ.get("OPENAI_API_KEY") else "Not set", "Env Var" if os.environ.get("OPENAI_API_KEY") else "-")

    console.print(table)


def run_analysis_pipeline(
    target_ref: str | None,
    forced_local: bool = False,
    override_provider: str | None = None,
    override_model: str | None = None,
):
    """Executes the complete git diff inspection, compaction, and AI generation pipeline."""
    import asyncio

    from rich.console import Console

    from git_narrator.config import resolve_provider_and_model
    from git_narrator.git_engine import (
        detect_change_scope,
        get_current_branch,
        get_diff,
        get_numstat,
        get_stat,
        is_git_repo,
    )
    from git_narrator.knapsack import optimize_diff_tokens
    from git_narrator.lockfile import strip_lockfiles_and_inject_summary
    from git_narrator.parser import parse_and_validate_report
    from git_narrator.prompts import SYSTEM_PROMPT, build_narrator_prompt
    from git_narrator.providers.anthropic import AnthropicProvider
    from git_narrator.providers.gemini import GeminiProvider
    from git_narrator.providers.ollama import OllamaProvider
    from git_narrator.providers.openai import OpenAIProvider
    from git_narrator.sanitizer import sanitize_diff
    from git_narrator.schemas import get_report_json_schema

    console = Console()
    if not is_git_repo():
        console.print("[bold red]Error:[/bold red] Not inside a git repository.")
        sys.exit(1)

    # 1. Resolve Git Scope
    if target_ref:
        target = target_ref
    else:
        scope = detect_change_scope(".")
        if scope.scope_type == "empty":
            console.print("[yellow]Working tree clean, no modified files or commits to analyze.[/yellow]")
            sys.exit(0)
        target = scope.target or scope.scope_type

    # 2. Extract Git Stats & Diff
    raw_diff = get_diff(".", target=target)
    diff_stat = get_stat(".", target=target)
    numstats = get_numstat(".", target=target)
    branch = get_current_branch(".") or "HEAD"

    # 3. Sanitize and Compact Lockfiles
    sanitized = sanitize_diff(raw_diff)
    cleaned_diff, dep_summary, _ = strip_lockfiles_and_inject_summary(sanitized.cleaned_diff)

    # 4. Knapsack Token Optimization
    knapsack = optimize_diff_tokens(cleaned_diff, token_budget=14000)
    final_diff = knapsack.optimized_diff

    # 5. Resolve AI Provider
    prov_name, model_name, api_key, base_url = resolve_provider_and_model(
        forced_local=forced_local,
        override_provider=override_provider,
        override_model=override_model,
    )

    schema = get_report_json_schema()
    prompt = build_narrator_prompt(
        diff=final_diff,
        stat=diff_stat,
        lockfile_mutations=dep_summary,
        branch_info=branch,
    )

    # Instantiate Provider Driver
    if prov_name == "ollama":
        provider = OllamaProvider(model=model_name, base_url=base_url or "http://localhost:11434")
    elif prov_name == "gemini":
        if not api_key:
            console.print("[bold red]Error:[/bold red] GEMINI_API_KEY environment variable required for Gemini provider.")
            sys.exit(1)
        provider = GeminiProvider(api_key=api_key, model=model_name)
    elif prov_name == "anthropic":
        if not api_key:
            console.print("[bold red]Error:[/bold red] ANTHROPIC_API_KEY environment variable required for Anthropic provider.")
            sys.exit(1)
        provider = AnthropicProvider(api_key=api_key, model=model_name)
    else:
        # Default OpenAI / compatible (Groq, DeepSeek, etc.)
        if not api_key and "localhost" not in (base_url or ""):
            console.print("[bold red]Error:[/bold red] OPENAI_API_KEY environment variable required for OpenAI provider.")
            sys.exit(1)
        provider = OpenAIProvider(api_key=api_key or "sk-dummy", model=model_name, base_url=base_url or "https://api.openai.com/v1")

    # Execute stream with animated spinner
    chunks = []
    async def collect_stream():
        with console.status(f"[cyan]Narrating git diff via [bold magenta]{prov_name}/{model_name}[/bold magenta]...[/cyan]", spinner="dots"):
            async for chunk in provider.stream_structured(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=prompt,
                json_schema=schema,
            ):
                chunks.append(chunk)

    try:
        asyncio.run(collect_stream())
    except Exception as e:
        console.print(f"[bold red]AI Engine Connection Error ({prov_name}):[/bold red] {e}")
        console.print("[yellow]Tip: Run with --local to use Ollama, or set GEMINI_API_KEY / OPENAI_API_KEY.[/yellow]")
        sys.exit(1)

    full_response = "".join(chunks)
    report = parse_and_validate_report(full_response)
    return report


def run_narrator_flow(
    target_ref: str | None,
    forced_local: bool,
    override_provider: str | None,
    override_model: str | None,
    output_format: str,
    fail_on_risk: str | None,
    auto_copy: bool,
) -> None:
    """Orchestrates analysis and handles interactive dashboard or formatted outputs."""
    from rich.console import Console

    from git_narrator.clipboard import copy_to_clipboard
    from git_narrator.config import resolve_provider_and_model
    from git_narrator.git_engine import (
        detect_change_scope,
        get_current_branch,
        get_stat,
    )
    from git_narrator.keyboard import get_single_key
    from git_narrator.ui import (
        generate_pr_markdown,
        render_commit_tab,
        render_diagram_tab,
        render_footer,
        render_header,
        render_risk_tab,
        render_story_tab,
    )

    console = Console()
    report = run_analysis_pipeline(
        target_ref=target_ref,
        forced_local=forced_local,
        override_provider=override_provider,
        override_model=override_model,
    )

    # CI/CD Gate check
    if fail_on_risk:
        severity_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}
        threshold = severity_rank.get(fail_on_risk.upper(), 3)
        for r in report.risk_radar:
            if severity_rank.get(str(r.severity).upper(), 0) >= threshold:
                console.print(f"[bold red]CI Gate Failed:[/bold red] Detected {r.severity} risk: {r.title} in {r.file_path}")
                sys.exit(1)

    # Non-interactive formats
    if output_format == "json":
        console.print_json(report.model_dump_json(indent=2))
        return
    elif output_format == "markdown":
        md = generate_pr_markdown(report)
        console.print(md)
        if auto_copy:
            copy_to_clipboard(md)
        return

    # Interactive TUI mode
    prov_name, model_name, _, _ = resolve_provider_and_model(
        forced_local=forced_local,
        override_provider=override_provider,
        override_model=override_model,
    )
    branch = get_current_branch(".") or "HEAD"
    target = target_ref or (detect_change_scope(".").target or detect_change_scope(".").scope_type)
    stat = get_stat(".", target=target)
    short_stat = stat.strip().splitlines()[-1] if stat.strip() else "changes detected"

    current_tab = 1
    risk_count = len(report.risk_radar)

    while True:
        console.clear()
        console.print(render_header(branch, short_stat, f"{prov_name}/{model_name}"))
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
        console.print(render_footer(current_tab, risk_count))

        key = get_single_key()
        if key == "q":
            break
        elif key in ("1", "2", "3", "4"):
            current_tab = int(key)
        elif key == "c":
            # Direct commit
            from git_narrator.git_engine import run_git
            try:
                run_git(["commit", "-m", report.conventional_commit.strip()])
                console.print("\n[bold green]✓ Successfully committed staged changes![/bold green]")
                break
            except Exception as e:
                console.print(f"\n[bold red]Commit failed:[/bold red] {e}")
                copy_to_clipboard(report.conventional_commit.strip())
                console.print("[dim]Message copied to clipboard instead.[/dim]")
                break
        elif key == "p":
            md = generate_pr_markdown(report)
            copy_to_clipboard(md)
            console.print("\n[bold green]✓ PR Markdown copied to clipboard via OSC 52![/bold green]")
            break
        elif key == "e":
            editor = os.environ.get("EDITOR", "nano")
            import tempfile
            with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False) as tf:
                tf.write(report.conventional_commit)
                tf_path = tf.name
            os.system(f"{editor} {tf_path}")
            with open(tf_path, "r") as tf:
                report.conventional_commit = tf.read().strip()
            os.unlink(tf_path)


def main() -> None:
    """Package entrypoint."""
    cli()


if __name__ == "__main__":
    main()
