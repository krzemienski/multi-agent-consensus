"""Phase pipeline orchestrator with gate checkpoints.

Manages the full consensus pipeline lifecycle: phase progression,
gate checks, fix cycles, state persistence, and reporting.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .config import ConsensusConfig
from .evidence import EvidenceCollector
from .gate import run_gate_check
from .models import (
    GateResult,
    Phase,
    PhaseStatus,
    PipelineState,
)

logger = logging.getLogger(__name__)
console = Console()


class PipelineOrchestrator:
    """Orchestrates the full consensus validation pipeline.

    Manages phase progression, gate checks with fix cycles,
    evidence collection, state persistence, and reporting.
    """

    def __init__(
        self,
        target_path: Path,
        config: ConsensusConfig,
    ) -> None:
        """Initialize the orchestrator.

        Args:
            target_path: Path to the project being validated.
            config: Consensus pipeline configuration.
        """
        self.target_path = target_path.resolve()
        self.config = config
        self.paths = config.resolve_paths(self.target_path)
        self.evidence = EvidenceCollector(self.paths["evidence"])

        # Initialize pipeline state
        self.state = PipelineState(
            target_path=str(self.target_path),
            phases=[
                Phase(
                    name=name,
                    description=config.phase_descriptions.get(name, ""),
                    prompt_template=config.phase_prompts.get(name, ""),
                    max_fix_cycles=config.max_fix_cycles,
                )
                for name in config.phases
            ],
        )

        self._gate_counter = 0

    @classmethod
    def from_state_file(cls, state_path: Path, config: ConsensusConfig) -> PipelineOrchestrator:
        """Resume an orchestrator from a saved state file.

        Args:
            state_path: Path to the state JSON file.
            config: Configuration (may differ from original run).

        Returns:
            Orchestrator instance with restored state.
        """
        with open(state_path) as f:
            state_data = json.load(f)

        state = PipelineState.model_validate(state_data)
        target_path = Path(state.target_path)

        orchestrator = cls(target_path, config)
        orchestrator.state = state
        orchestrator._gate_counter = sum(
            len(p.gate_results) for p in state.phases
        )

        logger.info(
            "Resumed pipeline from %s (phase %d/%d)",
            state_path, state.current_phase_index + 1, len(state.phases),
        )

        return orchestrator

    def save_state(self) -> Path:
        """Save the current pipeline state to disk.

        Returns:
            Path to the saved state file.
        """
        state_path = self.paths["state"]
        state_path.parent.mkdir(parents=True, exist_ok=True)

        with open(state_path, "w") as f:
            json.dump(self.state.model_dump(mode="json"), f, indent=2, default=str)

        logger.debug("State saved to %s", state_path)
        return state_path

    def run_phase(self, phase: Phase) -> GateResult:
        """Run a single phase with its gate check.

        Args:
            phase: The phase to run.

        Returns:
            The gate result for this phase.
        """
        phase.status = PhaseStatus.IN_PROGRESS
        phase.started_at = datetime.now()

        console.print(f"\n[bold cyan]Phase: {phase.name}[/bold cyan]")
        console.print(f"  {phase.description}")
        console.print(f"  Max fix cycles: {phase.max_fix_cycles}")

        self._gate_counter += 1
        fix_cycle = 0

        while fix_cycle <= phase.max_fix_cycles:
            phase.status = PhaseStatus.GATE_CHECK
            console.print(f"\n  [yellow]Running gate check #{self._gate_counter} "
                         f"(fix cycle {fix_cycle})...[/yellow]")

            gate_result = run_gate_check(
                phase_name=phase.name,
                gate_number=self._gate_counter,
                target_path=str(self.target_path),
                config=self.config,
                evidence_collector=self.evidence,
                fix_cycle_count=fix_cycle,
            )

            phase.gate_results.append(gate_result)

            if gate_result.unanimous_pass:
                phase.status = PhaseStatus.PASSED
                phase.completed_at = datetime.now()
                console.print(f"  [bold green]Gate PASSED — all agents unanimous[/bold green]")
                self.save_state()
                return gate_result

            # Gate failed
            failing = gate_result.failing_agents()
            findings = gate_result.all_findings()
            console.print(
                f"  [bold red]Gate FAILED — {len(failing)} agent(s) voted FAIL[/bold red]"
            )
            for finding in findings[:5]:
                console.print(f"    - {finding}")

            if fix_cycle >= phase.max_fix_cycles:
                phase.status = PhaseStatus.FAILED
                phase.completed_at = datetime.now()
                console.print(
                    f"  [bold red]Max fix cycles ({phase.max_fix_cycles}) exhausted — "
                    f"HARD FAILURE[/bold red]"
                )
                self.save_state()
                return gate_result

            # Enter fix cycle
            phase.status = PhaseStatus.FIX_CYCLE
            fix_cycle += 1
            console.print(f"  [yellow]Entering fix cycle {fix_cycle}...[/yellow]")

            # Re-validate after fix cycle: ALL agents, not just the failing one
            console.print("  [dim]Re-validating with ALL THREE agents...[/dim]")
            self._gate_counter += 1
            self.save_state()

        # Should not reach here
        phase.status = PhaseStatus.FAILED
        phase.completed_at = datetime.now()
        return phase.gate_results[-1]

    def run(self) -> PipelineState:
        """Run the full pipeline: all phases with gate checks.

        Returns:
            Final pipeline state.
        """
        console.print(f"\n[bold]Consensus Pipeline: {self.target_path.name}[/bold]")
        console.print(f"Phases: {' → '.join(p.name for p in self.state.phases)}")
        console.print(f"Agents: Lead ({self.config.lead.model}), "
                      f"Alpha ({self.config.alpha.model}), "
                      f"Bravo ({self.config.bravo.model})")
        console.print()

        for i, phase in enumerate(self.state.phases):
            self.state.current_phase_index = i

            # Skip already-passed phases (for resume)
            if phase.status == PhaseStatus.PASSED:
                console.print(f"[dim]Skipping already-passed phase: {phase.name}[/dim]")
                continue

            gate_result = self.run_phase(phase)

            if not gate_result.unanimous_pass:
                console.print(
                    f"\n[bold red]Pipeline halted at phase '{phase.name}' — "
                    f"gate failed after max fix cycles[/bold red]"
                )
                break

        self.state.completed_at = datetime.now()
        self.save_state()
        self.evidence.write_manifest()

        # Print final report
        self.print_report()

        return self.state

    def print_report(self) -> None:
        """Print a formatted summary report of the pipeline run."""
        console.print("\n" + "=" * 60)
        console.print("[bold]Consensus Pipeline Report[/bold]")
        console.print("=" * 60)

        # Phase table
        table = Table(title="Phase Results")
        table.add_column("Phase", style="cyan")
        table.add_column("Status", justify="center")
        table.add_column("Gates", justify="right")
        table.add_column("Fix Cycles", justify="right")
        table.add_column("Duration", justify="right")

        for phase in self.state.phases:
            status_icon = {
                PhaseStatus.PASSED: "[green]PASSED[/green]",
                PhaseStatus.FAILED: "[red]FAILED[/red]",
                PhaseStatus.PENDING: "[dim]PENDING[/dim]",
                PhaseStatus.IN_PROGRESS: "[yellow]IN PROGRESS[/yellow]",
            }.get(phase.status, str(phase.status.value))

            elapsed = phase.elapsed_seconds()
            duration_str = f"{elapsed:.1f}s" if elapsed is not None else "-"

            fix_count = sum(g.fix_cycle_count for g in phase.gate_results)

            table.add_row(
                phase.name,
                status_icon,
                str(len(phase.gate_results)),
                str(fix_count),
                duration_str,
            )

        console.print(table)

        # Summary metrics
        summary = self.state.summary_table()
        console.print(f"\nTotal phases: {summary['total_phases']}")
        console.print(f"Gates passed: {summary['gates_passed']}")
        console.print(f"Total fix cycles: {summary['total_fix_cycles']}")
        console.print(f"Total findings: {summary['total_findings']}")
        console.print(f"Status: [bold]{summary['status']}[/bold]")

        # Evidence summary
        ev_summary = self.evidence.summary()
        console.print(f"\nEvidence artifacts: {ev_summary.get('total', 0)}")

    def generate_report_json(self) -> dict[str, object]:
        """Generate a machine-readable report.

        Returns:
            Dictionary with complete pipeline report data.
        """
        return {
            "target": str(self.target_path),
            "summary": self.state.summary_table(),
            "phases": [
                {
                    "name": p.name,
                    "status": p.status.value,
                    "gate_results": [
                        {
                            "gate_number": g.gate_number,
                            "unanimous_pass": g.unanimous_pass,
                            "votes": [
                                {
                                    "role": v.role.value,
                                    "outcome": v.outcome.value,
                                    "reasoning": v.reasoning,
                                }
                                for v in g.votes
                            ],
                            "fix_cycle": g.fix_cycle_count,
                        }
                        for g in p.gate_results
                    ],
                }
                for p in self.state.phases
            ],
            "evidence": self.evidence.summary(),
            "completed_at": self.state.completed_at.isoformat() if self.state.completed_at else None,
        }
