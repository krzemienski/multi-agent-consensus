"""Configuration management for the consensus validation framework.

Supports YAML configuration files for defining pipeline phases,
agent models, thresholds, and validation criteria.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class AgentConfig:
    """Configuration for a single agent role."""

    model: str = "sonnet"
    timeout_seconds: int = 300
    temperature: float = 0.0


@dataclass
class ConsensusConfig:
    """Top-level configuration for the consensus pipeline."""

    # Agent models
    lead: AgentConfig = field(default_factory=lambda: AgentConfig(model="opus"))
    alpha: AgentConfig = field(default_factory=lambda: AgentConfig(model="sonnet"))
    bravo: AgentConfig = field(default_factory=lambda: AgentConfig(model="sonnet"))

    # Pipeline settings
    phases: list[str] = field(default_factory=lambda: [
        "explore", "audit", "fix", "verify",
    ])
    max_fix_cycles: int = 3
    evidence_dir: str = ".consensus/evidence"
    state_file: str = ".consensus/state.json"

    # Gate settings
    require_unanimous: bool = True
    require_evidence: bool = True

    # Execution
    parallel_agents: bool = True
    verbose: bool = False

    # Phase descriptions
    phase_descriptions: dict[str, str] = field(default_factory=lambda: {
        "explore": "Map the codebase, understand architecture, identify areas of concern",
        "audit": "Deep review of implementation against requirements and best practices",
        "fix": "Implement fixes for all issues identified during audit",
        "verify": "Final verification that all fixes are correct and no regressions exist",
    })

    # Phase prompt templates
    phase_prompts: dict[str, str] = field(default_factory=lambda: {
        "explore": (
            "You are {role}. Independently explore the codebase at {target}.\n"
            "Map the architecture, identify patterns, and note areas of concern.\n"
            "Report PASS if the codebase is well-understood, FAIL if critical areas are unclear."
        ),
        "audit": (
            "You are {role}. Independently audit the code at {target}.\n"
            "Check for: correctness, edge cases, error handling, security, performance.\n"
            "Report PASS if code meets quality standards, FAIL with specific issues if not."
        ),
        "fix": (
            "You are {role}. Independently verify that fixes at {target} address all findings.\n"
            "Check each fix against the original issue. Verify no regressions introduced.\n"
            "Report PASS if all fixes are correct, FAIL with specific remaining issues."
        ),
        "verify": (
            "You are {role}. Final independent verification of {target}.\n"
            "Run build, check endpoints, verify UI behavior, trace critical paths.\n"
            "Report PASS only if everything works end-to-end, FAIL with evidence of problems."
        ),
    })

    @classmethod
    def load(cls, config_path: Path | None = None) -> ConsensusConfig:
        """Load configuration from a YAML file with defaults.

        Args:
            config_path: Path to YAML config file. If None, uses defaults.

        Returns:
            Populated ConsensusConfig instance.
        """
        config = cls()

        if config_path and config_path.exists():
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
            config._merge_from_dict(data)

        return config

    def _merge_from_dict(self, data: dict[str, object]) -> None:
        """Merge settings from a parsed YAML dictionary."""
        # Agent configs
        agents = data.get("agents", {})
        if isinstance(agents, dict):
            for role_name in ("lead", "alpha", "bravo"):
                agent_data = agents.get(role_name, {})
                if isinstance(agent_data, dict):
                    agent_config = getattr(self, role_name)
                    if "model" in agent_data:
                        agent_config.model = str(agent_data["model"])
                    if "timeout_seconds" in agent_data:
                        agent_config.timeout_seconds = int(agent_data["timeout_seconds"])
                    if "temperature" in agent_data:
                        agent_config.temperature = float(agent_data["temperature"])

        # Pipeline settings
        pipeline = data.get("pipeline", {})
        if isinstance(pipeline, dict):
            if "phases" in pipeline:
                phases = pipeline["phases"]
                if isinstance(phases, list):
                    self.phases = [str(p) for p in phases]
            if "max_fix_cycles" in pipeline:
                self.max_fix_cycles = int(pipeline["max_fix_cycles"])
            if "evidence_dir" in pipeline:
                self.evidence_dir = str(pipeline["evidence_dir"])
            if "parallel_agents" in pipeline:
                self.parallel_agents = bool(pipeline["parallel_agents"])

        # Gate settings
        gate = data.get("gate", {})
        if isinstance(gate, dict):
            if "require_unanimous" in gate:
                self.require_unanimous = bool(gate["require_unanimous"])
            if "require_evidence" in gate:
                self.require_evidence = bool(gate["require_evidence"])

        # Phase descriptions
        descriptions = data.get("phase_descriptions", {})
        if isinstance(descriptions, dict):
            for phase_name, desc in descriptions.items():
                self.phase_descriptions[str(phase_name)] = str(desc)

        # Phase prompts
        prompts = data.get("phase_prompts", {})
        if isinstance(prompts, dict):
            for phase_name, prompt in prompts.items():
                self.phase_prompts[str(phase_name)] = str(prompt)

    def get_agent_config(self, role: str) -> AgentConfig:
        """Get the configuration for a specific agent role."""
        role_lower = role.lower()
        if role_lower == "lead":
            return self.lead
        elif role_lower == "alpha":
            return self.alpha
        elif role_lower == "bravo":
            return self.bravo
        else:
            raise ValueError(f"Unknown role: {role}. Must be one of: lead, alpha, bravo")

    def get_phase_prompt(self, phase_name: str, role: str, target: str) -> str:
        """Get the formatted prompt for a specific phase and role."""
        template = self.phase_prompts.get(
            phase_name,
            "You are {role}. Validate {target} for phase '{phase}'. Report PASS or FAIL.",
        )
        return template.format(role=role, target=target, phase=phase_name)

    def resolve_paths(self, base_path: Path) -> dict[str, Path]:
        """Resolve relative paths against a base directory."""
        return {
            "evidence": base_path / self.evidence_dir,
            "state": base_path / self.state_file,
        }

    def to_dict(self) -> dict[str, object]:
        """Serialize config to a dictionary for display."""
        return {
            "agents": {
                "lead": {"model": self.lead.model, "timeout": self.lead.timeout_seconds},
                "alpha": {"model": self.alpha.model, "timeout": self.alpha.timeout_seconds},
                "bravo": {"model": self.bravo.model, "timeout": self.bravo.timeout_seconds},
            },
            "pipeline": {
                "phases": self.phases,
                "max_fix_cycles": self.max_fix_cycles,
                "parallel_agents": self.parallel_agents,
            },
            "gate": {
                "require_unanimous": self.require_unanimous,
                "require_evidence": self.require_evidence,
            },
        }
