"""Data models for the multi-agent consensus validation framework.

Defines the core data structures for the 3-agent consensus pattern:
roles, votes, gate results, phases, and evidence artifacts.
"""

from __future__ import annotations

import enum
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field


class Role(str, enum.Enum):
    """Agent roles in the consensus triad.

    Each role has a specialized perspective:
    - LEAD: Architecture and consistency specialist, breaks ties
    - ALPHA: Code and logic specialist, detail-oriented auditor
    - BRAVO: Systems thinker, edge cases, visual/functional verification
    """

    LEAD = "lead"
    ALPHA = "alpha"
    BRAVO = "bravo"


class VoteOutcome(str, enum.Enum):
    """Possible outcomes for an agent's gate vote."""

    PASS = "PASS"
    FAIL = "FAIL"


class PhaseStatus(str, enum.Enum):
    """Lifecycle status of a pipeline phase."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    GATE_CHECK = "gate_check"
    PASSED = "passed"
    FAILED = "failed"
    FIX_CYCLE = "fix_cycle"


class EvidenceType(str, enum.Enum):
    """Types of evidence artifacts that agents can produce."""

    BUILD_LOG = "build_log"
    SCREENSHOT = "screenshot"
    CURL_OUTPUT = "curl_output"
    CODE_ANALYSIS = "code_analysis"
    DIFF = "diff"
    PROCESS_CHECK = "process_check"
    TEST_OUTPUT = "test_output"
    CUSTOM = "custom"


class Vote(BaseModel):
    """A single agent's vote at a gate checkpoint.

    Each vote includes the outcome, evidence supporting the decision,
    and specific findings that led to the vote.
    """

    role: Role = Field(description="Which agent cast this vote")
    outcome: VoteOutcome = Field(description="PASS or FAIL")
    reasoning: str = Field(description="Brief explanation of the vote rationale")
    findings: list[str] = Field(
        default_factory=list,
        description="Specific issues or observations found during review",
    )
    evidence_paths: list[str] = Field(
        default_factory=list,
        description="Paths to evidence artifacts supporting this vote",
    )
    duration_seconds: float = Field(
        default=0.0,
        description="How long this agent spent on validation",
    )
    voted_at: datetime = Field(default_factory=datetime.now)

    def is_pass(self) -> bool:
        """Check if this vote is a PASS."""
        return self.outcome == VoteOutcome.PASS

    def is_fail(self) -> bool:
        """Check if this vote is a FAIL."""
        return self.outcome == VoteOutcome.FAIL


class Evidence(BaseModel):
    """A single evidence artifact collected during validation.

    Evidence supports an agent's vote with concrete, verifiable data.
    Can be a file (screenshot, log) or inline content (curl output, code snippet).
    """

    evidence_type: EvidenceType
    role: Role = Field(description="Which agent produced this evidence")
    title: str = Field(description="Brief title describing the evidence")
    content: str | None = Field(
        default=None,
        description="Inline content for small evidence (curl output, code snippets)",
    )
    file_path: Path | None = Field(
        default=None,
        description="Path to file-based evidence (screenshots, logs)",
    )
    phase_name: str = Field(default="", description="Phase this evidence belongs to")
    collected_at: datetime = Field(default_factory=datetime.now)

    class Config:
        arbitrary_types_allowed = True

    def has_content(self) -> bool:
        """Check if this evidence has either inline content or a file."""
        return bool(self.content) or (self.file_path is not None and self.file_path.exists())


class GateResult(BaseModel):
    """Result of a consensus gate check.

    A gate passes if and only if ALL three agents vote PASS (unanimous).
    Any single FAIL vote keeps the gate closed and triggers a fix cycle.
    """

    phase_name: str = Field(description="Name of the phase this gate guards")
    gate_number: int = Field(description="Sequential gate number in the pipeline")
    votes: list[Vote] = Field(description="All three agent votes")
    unanimous_pass: bool = Field(description="Whether all agents voted PASS")
    evidence: list[Evidence] = Field(
        default_factory=list,
        description="All evidence artifacts from this gate check",
    )
    fix_cycle_count: int = Field(
        default=0,
        description="How many fix cycles have occurred at this gate",
    )
    checked_at: datetime = Field(default_factory=datetime.now)

    @classmethod
    def from_votes(
        cls,
        phase_name: str,
        gate_number: int,
        votes: list[Vote],
        evidence: list[Evidence] | None = None,
        fix_cycle_count: int = 0,
    ) -> GateResult:
        """Create a GateResult from a list of votes, computing unanimity."""
        unanimous = all(v.is_pass() for v in votes)
        return cls(
            phase_name=phase_name,
            gate_number=gate_number,
            votes=votes,
            unanimous_pass=unanimous,
            evidence=evidence or [],
            fix_cycle_count=fix_cycle_count,
        )

    def failing_agents(self) -> list[Role]:
        """Return the roles of agents that voted FAIL."""
        return [v.role for v in self.votes if v.is_fail()]

    def all_findings(self) -> list[str]:
        """Aggregate all findings from failing agents."""
        findings: list[str] = []
        for vote in self.votes:
            if vote.is_fail():
                findings.extend(vote.findings)
        return findings

    def summary(self) -> str:
        """Generate a human-readable summary of the gate result."""
        status = "PASSED" if self.unanimous_pass else "FAILED"
        lines = [f"Gate #{self.gate_number} ({self.phase_name}): {status}"]
        for vote in self.votes:
            icon = "✅" if vote.is_pass() else "❌"
            lines.append(f"  {icon} {vote.role.value}: {vote.outcome.value} — {vote.reasoning}")
        if not self.unanimous_pass:
            lines.append(f"  Fix cycles so far: {self.fix_cycle_count}")
            findings = self.all_findings()
            if findings:
                lines.append("  Issues found:")
                for finding in findings:
                    lines.append(f"    - {finding}")
        return "\n".join(lines)


class Phase(BaseModel):
    """A single phase in the consensus pipeline.

    Each phase represents a distinct stage of work (e.g., Explore, Audit, Fix, Verify)
    with its own gate checkpoint at the end.
    """

    name: str = Field(description="Phase name, e.g. 'explore', 'audit', 'fix', 'verify'")
    description: str = Field(default="", description="What this phase does")
    prompt_template: str = Field(
        default="",
        description="Template for agent prompts during this phase's gate check",
    )
    status: PhaseStatus = Field(default=PhaseStatus.PENDING)
    gate_results: list[GateResult] = Field(
        default_factory=list,
        description="History of gate check results (multiple if fix cycles occurred)",
    )
    started_at: datetime | None = None
    completed_at: datetime | None = None
    max_fix_cycles: int = Field(default=3, description="Maximum fix cycles before hard failure")

    def latest_gate_result(self) -> GateResult | None:
        """Get the most recent gate result for this phase."""
        return self.gate_results[-1] if self.gate_results else None

    def is_gate_passed(self) -> bool:
        """Check if the latest gate result is a unanimous pass."""
        result = self.latest_gate_result()
        return result is not None and result.unanimous_pass

    def fix_cycles_remaining(self) -> int:
        """Calculate how many fix cycles remain before hard failure."""
        result = self.latest_gate_result()
        current = result.fix_cycle_count if result else 0
        return max(0, self.max_fix_cycles - current)

    def elapsed_seconds(self) -> float | None:
        """Calculate elapsed time for this phase."""
        if self.started_at is None:
            return None
        end = self.completed_at or datetime.now()
        return (end - self.started_at).total_seconds()


class PipelineState(BaseModel):
    """Top-level state for the entire consensus pipeline run.

    Tracks all phases, their gate results, and aggregate statistics
    for reporting and resumability.
    """

    target_path: str = Field(description="Path to the project being validated")
    phases: list[Phase] = Field(default_factory=list)
    current_phase_index: int = Field(default=0)
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: datetime | None = None

    @property
    def current_phase(self) -> Phase | None:
        """Get the currently active phase."""
        if 0 <= self.current_phase_index < len(self.phases):
            return self.phases[self.current_phase_index]
        return None

    @property
    def total_gates_passed(self) -> int:
        """Count how many gates have passed across all phases."""
        return sum(1 for p in self.phases if p.is_gate_passed())

    @property
    def total_fix_cycles(self) -> int:
        """Count total fix cycles across all phases."""
        total = 0
        for phase in self.phases:
            for gate in phase.gate_results:
                total += gate.fix_cycle_count
        return total

    @property
    def total_findings(self) -> int:
        """Count total unique findings across all gate results."""
        all_findings: set[str] = set()
        for phase in self.phases:
            for gate in phase.gate_results:
                all_findings.update(gate.all_findings())
        return len(all_findings)

    def is_complete(self) -> bool:
        """Check if all phases have passed their gates."""
        return all(p.is_gate_passed() for p in self.phases)

    def summary_table(self) -> dict[str, int | float | str]:
        """Generate summary metrics for reporting."""
        return {
            "target": self.target_path,
            "total_phases": len(self.phases),
            "gates_passed": self.total_gates_passed,
            "total_fix_cycles": self.total_fix_cycles,
            "total_findings": self.total_findings,
            "status": "complete" if self.is_complete() else "in_progress",
        }
