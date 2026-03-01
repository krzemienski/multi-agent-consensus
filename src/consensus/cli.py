"""Click CLI for multi-agent consensus validation.

Provides the `consensus` command with subcommands for running
the full pipeline, validating a single phase, and generating reports.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import click
from rich.console import Console

from .config import ConsensusConfig

console = Console()


def setup_logging(verbose: bool) -> None:
    """Configure logging based on verbosity."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """Multi-Agent Consensus: 3-agent validation with hard gates.

    Three agents (Lead, Alpha, Bravo) independently validate work at
    phase gates. All three must vote PASS unanimously for the gate
    to open — no exceptions.
    """
    ctx.ensure_object(dict)
    setup_logging(verbose)
    ctx.obj["verbose"] = verbose


@cli.command()
@click.option("--target", "-t", type=click.Path(exists=True, path_type=Path),
              default=".", help="Project path to validate")
@click.option("--config", "-c", type=click.Path(exists=True, path_type=Path),
              default=None, help="YAML configuration file")
@click.option("--phases", "-p", type=str, default=None,
              help="Comma-separated phase names (overrides config)")
@click.option("--resume", is_flag=True, help="Resume from saved state")
@click.pass_context
def run(
    ctx: click.Context,
    target: Path,
    config: Path | None,
    phases: str | None,
    resume: bool,
) -> None:
    """Run the full consensus validation pipeline.

    Executes all configured phases with gate checks. Each gate requires
    unanimous PASS from all three agents (Lead, Alpha, Bravo).

    Example:
        consensus run --target ./my-project --phases "explore,audit,fix,verify"
    """
    from .orchestrator import PipelineOrchestrator

    cfg = ConsensusConfig.load(config)

    if phases:
        cfg.phases = [p.strip() for p in phases.split(",")]

    if resume:
        state_path = cfg.resolve_paths(target.resolve())["state"]
        if not state_path.exists():
            console.print("[red]No saved state found to resume from[/red]")
            sys.exit(1)
        orchestrator = PipelineOrchestrator.from_state_file(state_path, cfg)
    else:
        orchestrator = PipelineOrchestrator(target, cfg)

    console.print(f"[bold]Starting consensus pipeline for {target.resolve().name}[/bold]")
    console.print(f"Phases: {' → '.join(cfg.phases)}")
    console.print(f"Agents: Lead ({cfg.lead.model}), Alpha ({cfg.alpha.model}), "
                  f"Bravo ({cfg.bravo.model})")

    state = orchestrator.run()

    if state.is_complete():
        console.print("\n[bold green]All gates passed — pipeline complete![/bold green]")
    else:
        console.print("\n[bold red]Pipeline did not complete — check report above[/bold red]")
        sys.exit(1)


@cli.command()
@click.option("--target", "-t", type=click.Path(exists=True, path_type=Path),
              default=".", help="Project path to validate")
@click.option("--config", "-c", type=click.Path(exists=True, path_type=Path),
              default=None, help="YAML configuration file")
@click.option("--phase", "-p", type=str, required=True,
              help="Phase name to validate")
@click.pass_context
def validate(ctx: click.Context, target: Path, config: Path | None, phase: str) -> None:
    """Run a single gate check for one phase.

    Useful for testing or re-running a specific phase without
    executing the full pipeline.
    """
    from .evidence import EvidenceCollector
    from .gate import run_gate_check

    cfg = ConsensusConfig.load(config)

    if phase not in cfg.phases and phase not in cfg.phase_descriptions:
        console.print(f"[red]Unknown phase: {phase}[/red]")
        console.print(f"Available phases: {', '.join(cfg.phases)}")
        sys.exit(1)

    paths = cfg.resolve_paths(target.resolve())
    evidence = EvidenceCollector(paths["evidence"])

    console.print(f"[bold]Running gate check for phase '{phase}'...[/bold]")

    result = run_gate_check(
        phase_name=phase,
        gate_number=1,
        target_path=str(target.resolve()),
        config=cfg,
        evidence_collector=evidence,
    )

    # Display result
    console.print(f"\n{result.summary()}")

    evidence.write_manifest()

    if result.unanimous_pass:
        console.print("\n[bold green]Gate PASSED[/bold green]")
    else:
        console.print("\n[bold red]Gate FAILED[/bold red]")
        sys.exit(1)


@cli.command()
@click.option("--target", "-t", type=click.Path(exists=True, path_type=Path),
              default=".", help="Project path")
@click.option("--config", "-c", type=click.Path(exists=True, path_type=Path),
              default=None, help="YAML configuration file")
@click.option("--format", "-f", "output_format", type=click.Choice(["text", "json"]),
              default="text", help="Output format")
@click.pass_context
def report(
    ctx: click.Context,
    target: Path,
    config: Path | None,
    output_format: str,
) -> None:
    """Generate a report from the last pipeline run.

    Reads the saved state file and produces a formatted summary
    of all phases, gate results, and evidence artifacts.
    """
    from .orchestrator import PipelineOrchestrator

    cfg = ConsensusConfig.load(config)
    state_path = cfg.resolve_paths(target.resolve())["state"]

    if not state_path.exists():
        console.print("[red]No pipeline state found. Run the pipeline first.[/red]")
        sys.exit(1)

    orchestrator = PipelineOrchestrator.from_state_file(state_path, cfg)

    if output_format == "json":
        report_data = orchestrator.generate_report_json()
        console.print(json.dumps(report_data, indent=2, default=str))
    else:
        orchestrator.print_report()


@cli.command()
@click.pass_context
def roles(ctx: click.Context) -> None:
    """Display the role definitions for all three agents.

    Shows the specialized focus areas and what each agent is
    calibrated to catch in the consensus triad.
    """
    from .roles import format_role_summary

    console.print(format_role_summary())


@cli.command()
@click.option("--config", "-c", type=click.Path(exists=True, path_type=Path),
              default=None, help="YAML configuration file to display")
@click.pass_context
def show_config(ctx: click.Context, config: Path | None) -> None:
    """Display the current configuration.

    Shows agent models, pipeline phases, gate settings, and
    other configuration values (default or from file).
    """
    cfg = ConsensusConfig.load(config)

    console.print("[bold]Current Configuration[/bold]\n")
    console.print(json.dumps(cfg.to_dict(), indent=2))


if __name__ == "__main__":
    cli()
