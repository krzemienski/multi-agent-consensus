"""Gate implementation: independent validation with unanimity requirement.

The gate is the critical mechanism of the consensus pattern.
Three agents validate independently, and ALL THREE must vote PASS
for the gate to open. Any single FAIL keeps the gate closed.

Key properties:
- Independent verification: no shared state between agents during review
- Hard gates: 2/3 does not pass. Unanimity or nothing.
- Re-validation after fixes: ALL agents re-validate, not just the failing one
"""

from __future__ import annotations

import json
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from .config import ConsensusConfig
from .evidence import EvidenceCollector
from .models import (
    Evidence,
    EvidenceType,
    GateResult,
    Role,
    Vote,
    VoteOutcome,
)
from .roles import ROLE_DEFINITIONS, RoleDefinition

logger = logging.getLogger(__name__)


def run_agent_validation(
    role_def: RoleDefinition,
    phase_name: str,
    target_path: str,
    config: ConsensusConfig,
) -> Vote:
    """Run a single agent's independent validation.

    The agent receives its role-specific system prompt and the phase
    context, then produces a structured vote with evidence.

    Args:
        role_def: Role definition with system prompt and focus areas.
        phase_name: Current pipeline phase.
        target_path: Path to the project being validated.
        config: Consensus pipeline configuration.

    Returns:
        The agent's Vote.
    """
    agent_config = config.get_agent_config(role_def.role.value)
    system_prompt = role_def.format_system_prompt(phase_name, target_path)
    user_prompt = config.get_phase_prompt(phase_name, role_def.title, target_path)

    cmd = [
        "claude", "--print",
        "--model", agent_config.model,
        "--system-prompt", system_prompt,
        user_prompt,
    ]

    start_time = datetime.now()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=agent_config.timeout_seconds,
        )
    except FileNotFoundError:
        return Vote(
            role=role_def.role,
            outcome=VoteOutcome.FAIL,
            reasoning="Claude CLI not found — cannot validate",
            findings=["Claude CLI not installed"],
            duration_seconds=0.0,
        )
    except subprocess.TimeoutExpired:
        elapsed = (datetime.now() - start_time).total_seconds()
        return Vote(
            role=role_def.role,
            outcome=VoteOutcome.FAIL,
            reasoning=f"Validation timed out after {agent_config.timeout_seconds}s",
            findings=["Agent timed out — may indicate overly complex validation scope"],
            duration_seconds=elapsed,
        )

    elapsed = (datetime.now() - start_time).total_seconds()

    if result.returncode != 0:
        return Vote(
            role=role_def.role,
            outcome=VoteOutcome.FAIL,
            reasoning=f"Agent process failed: {result.stderr.strip()[:200]}",
            findings=[f"Process error: {result.stderr.strip()[:200]}"],
            duration_seconds=elapsed,
        )

    return parse_vote_response(role_def.role, result.stdout.strip(), elapsed)


def parse_vote_response(role: Role, raw_response: str, duration: float) -> Vote:
    """Parse an agent's JSON response into a Vote.

    Handles common formatting issues and gracefully degrades on parse failure.

    Args:
        role: The role that produced this response.
        raw_response: Raw text from Claude.
        duration: Time spent on validation in seconds.

    Returns:
        Parsed Vote object.
    """
    text = raw_response.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse %s vote JSON: %s", role.value, e)
        # If we can't parse, default to FAIL for safety
        return Vote(
            role=role,
            outcome=VoteOutcome.FAIL,
            reasoning=f"Vote response parsing failed: {e}",
            findings=["Agent response was not valid JSON — treating as FAIL for safety"],
            duration_seconds=duration,
        )

    # Parse outcome
    outcome_str = str(data.get("outcome", "FAIL")).upper()
    outcome = VoteOutcome.PASS if outcome_str == "PASS" else VoteOutcome.FAIL

    return Vote(
        role=role,
        outcome=outcome,
        reasoning=str(data.get("reasoning", "")),
        findings=list(data.get("findings", [])),
        evidence_paths=list(data.get("evidence", [])),
        duration_seconds=duration,
    )


def run_gate_check(
    phase_name: str,
    gate_number: int,
    target_path: str,
    config: ConsensusConfig,
    evidence_collector: EvidenceCollector | None = None,
    fix_cycle_count: int = 0,
) -> GateResult:
    """Run a full gate check: all three agents validate independently.

    If parallel_agents is enabled in config, agents run concurrently.
    Otherwise, they run sequentially (useful for debugging).

    Args:
        phase_name: Current pipeline phase.
        gate_number: Sequential gate number.
        target_path: Path to the project being validated.
        config: Consensus pipeline configuration.
        evidence_collector: Optional collector for evidence artifacts.
        fix_cycle_count: Current fix cycle count for this gate.

    Returns:
        GateResult with all three votes and unanimity status.
    """
    logger.info(
        "Running gate check #%d for phase '%s' (fix cycle %d)",
        gate_number, phase_name, fix_cycle_count,
    )

    roles = [ROLE_DEFINITIONS[Role.LEAD], ROLE_DEFINITIONS[Role.ALPHA], ROLE_DEFINITIONS[Role.BRAVO]]
    votes: list[Vote] = []
    evidence_artifacts: list[Evidence] = []

    if config.parallel_agents:
        # Run all three agents in parallel — true independence
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_role = {
                executor.submit(
                    run_agent_validation, role_def, phase_name, target_path, config,
                ): role_def
                for role_def in roles
            }

            for future in as_completed(future_to_role):
                role_def = future_to_role[future]
                try:
                    vote = future.result()
                    votes.append(vote)
                    logger.info(
                        "  %s voted %s (%.1fs): %s",
                        role_def.role.value, vote.outcome.value,
                        vote.duration_seconds, vote.reasoning[:100],
                    )
                except Exception as e:
                    logger.error("Agent %s failed: %s", role_def.role.value, e)
                    votes.append(Vote(
                        role=role_def.role,
                        outcome=VoteOutcome.FAIL,
                        reasoning=f"Agent execution failed: {e}",
                        findings=[str(e)],
                    ))
    else:
        # Sequential execution (easier to debug)
        for role_def in roles:
            try:
                vote = run_agent_validation(role_def, phase_name, target_path, config)
                votes.append(vote)
                logger.info(
                    "  %s voted %s (%.1fs): %s",
                    role_def.role.value, vote.outcome.value,
                    vote.duration_seconds, vote.reasoning[:100],
                )
            except Exception as e:
                logger.error("Agent %s failed: %s", role_def.role.value, e)
                votes.append(Vote(
                    role=role_def.role,
                    outcome=VoteOutcome.FAIL,
                    reasoning=f"Agent execution failed: {e}",
                    findings=[str(e)],
                ))

    # Record evidence from votes
    if evidence_collector:
        for vote in votes:
            if vote.findings or vote.evidence_paths:
                content_parts = [f"Outcome: {vote.outcome.value}", f"Reasoning: {vote.reasoning}"]
                if vote.findings:
                    content_parts.append("\nFindings:")
                    for f in vote.findings:
                        content_parts.append(f"  - {f}")
                if vote.evidence_paths:
                    content_parts.append("\nEvidence paths:")
                    for p in vote.evidence_paths:
                        content_parts.append(f"  - {p}")

                artifact = evidence_collector.record_inline(
                    evidence_type=EvidenceType.CODE_ANALYSIS,
                    role=vote.role,
                    phase_name=phase_name,
                    title=f"gate-{gate_number}-vote-{vote.role.value}",
                    content="\n".join(content_parts),
                )
                evidence_artifacts.append(artifact)

    result = GateResult.from_votes(
        phase_name=phase_name,
        gate_number=gate_number,
        votes=votes,
        evidence=evidence_artifacts,
        fix_cycle_count=fix_cycle_count,
    )

    status = "PASSED ✅" if result.unanimous_pass else "FAILED ❌"
    logger.info("Gate #%d %s (votes: %s)", gate_number, status,
                ", ".join(f"{v.role.value}={v.outcome.value}" for v in votes))

    return result


def run_gate_with_fix_cycles(
    phase_name: str,
    gate_number: int,
    target_path: str,
    config: ConsensusConfig,
    evidence_collector: EvidenceCollector | None = None,
    max_fix_cycles: int = 3,
    fix_callback: object | None = None,
) -> GateResult:
    """Run a gate check with automatic fix-and-retry cycles.

    If the gate fails, the fix_callback is invoked with the findings,
    and then ALL THREE agents re-validate (not just the failing one).

    Args:
        phase_name: Current pipeline phase.
        gate_number: Sequential gate number.
        target_path: Path to the project.
        config: Consensus configuration.
        evidence_collector: Optional evidence collector.
        max_fix_cycles: Maximum fix cycles before hard failure.
        fix_callback: Optional callable(findings: list[str]) -> bool that
            implements fixes. Returns True if fixes were applied.

    Returns:
        Final GateResult after all fix cycles.
    """
    for cycle in range(max_fix_cycles + 1):
        result = run_gate_check(
            phase_name=phase_name,
            gate_number=gate_number,
            target_path=target_path,
            config=config,
            evidence_collector=evidence_collector,
            fix_cycle_count=cycle,
        )

        if result.unanimous_pass:
            return result

        if cycle >= max_fix_cycles:
            logger.error(
                "Gate #%d exhausted all %d fix cycles — HARD FAILURE",
                gate_number, max_fix_cycles,
            )
            return result

        # Attempt fixes
        findings = result.all_findings()
        if fix_callback and callable(fix_callback):
            logger.info("Applying fixes for cycle %d (%d findings)...", cycle + 1, len(findings))
            fixes_applied = fix_callback(findings)
            if not fixes_applied:
                logger.warning("Fix callback returned False — no fixes applied")
                return result
        else:
            logger.warning("No fix callback provided — cannot retry")
            return result

        logger.info("Re-validating with ALL THREE agents after fix cycle %d...", cycle + 1)

    return result  # Should not reach here, but satisfies type checker
