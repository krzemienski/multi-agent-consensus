"""Evidence artifact collection and management.

Handles the collection, storage, and retrieval of evidence artifacts
that support agent votes at gate checkpoints. Evidence is the foundation
of the consensus pattern — votes without evidence are worthless.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

from .models import Evidence, EvidenceType, Role

logger = logging.getLogger(__name__)


class EvidenceCollector:
    """Collects and manages evidence artifacts for a consensus pipeline run.

    Evidence is organized by phase and role:
        evidence_dir/
        ├── explore/
        │   ├── lead/
        │   ├── alpha/
        │   └── bravo/
        ├── audit/
        │   ├── lead/
        │   ├── alpha/
        │   └── bravo/
        └── ...
    """

    def __init__(self, evidence_dir: Path) -> None:
        """Initialize the evidence collector.

        Args:
            evidence_dir: Root directory for evidence storage.
        """
        self.evidence_dir = evidence_dir
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self._artifacts: list[Evidence] = []

    def _phase_role_dir(self, phase_name: str, role: Role) -> Path:
        """Get the directory for a specific phase and role."""
        d = self.evidence_dir / phase_name / role.value
        d.mkdir(parents=True, exist_ok=True)
        return d

    def record_inline(
        self,
        evidence_type: EvidenceType,
        role: Role,
        phase_name: str,
        title: str,
        content: str,
    ) -> Evidence:
        """Record inline evidence (command output, code snippets, etc.).

        Also writes the content to a file for persistence.

        Args:
            evidence_type: Type classification.
            role: Which agent produced this.
            phase_name: Current pipeline phase.
            title: Brief title.
            content: The evidence content.

        Returns:
            The recorded Evidence object.
        """
        # Write to file
        safe_title = title.replace(" ", "-").replace("/", "-")[:50]
        timestamp = datetime.now().strftime("%H%M%S")
        filename = f"{timestamp}-{safe_title}.txt"
        file_path = self._phase_role_dir(phase_name, role) / filename
        file_path.write_text(content, encoding="utf-8")

        evidence = Evidence(
            evidence_type=evidence_type,
            role=role,
            title=title,
            content=content,
            file_path=file_path,
            phase_name=phase_name,
        )

        self._artifacts.append(evidence)
        logger.debug("Recorded evidence: %s (%s/%s)", title, phase_name, role.value)
        return evidence

    def record_file(
        self,
        evidence_type: EvidenceType,
        role: Role,
        phase_name: str,
        title: str,
        source_path: Path,
    ) -> Evidence:
        """Record file-based evidence (screenshots, logs, etc.).

        Copies the source file into the evidence directory.

        Args:
            evidence_type: Type classification.
            role: Which agent produced this.
            phase_name: Current pipeline phase.
            title: Brief title.
            source_path: Path to the source file to copy.

        Returns:
            The recorded Evidence object.

        Raises:
            FileNotFoundError: If source file doesn't exist.
        """
        if not source_path.exists():
            raise FileNotFoundError(f"Evidence source not found: {source_path}")

        dest_dir = self._phase_role_dir(phase_name, role)
        timestamp = datetime.now().strftime("%H%M%S")
        dest_name = f"{timestamp}-{source_path.name}"
        dest_path = dest_dir / dest_name
        shutil.copy2(source_path, dest_path)

        evidence = Evidence(
            evidence_type=evidence_type,
            role=role,
            title=title,
            file_path=dest_path,
            phase_name=phase_name,
        )

        self._artifacts.append(evidence)
        logger.debug("Recorded file evidence: %s -> %s", source_path, dest_path)
        return evidence

    def get_phase_evidence(self, phase_name: str) -> list[Evidence]:
        """Get all evidence artifacts for a specific phase.

        Args:
            phase_name: The phase to filter by.

        Returns:
            List of evidence artifacts for the phase.
        """
        return [e for e in self._artifacts if e.phase_name == phase_name]

    def get_role_evidence(self, role: Role, phase_name: str | None = None) -> list[Evidence]:
        """Get all evidence artifacts from a specific role.

        Args:
            role: The role to filter by.
            phase_name: Optional phase filter.

        Returns:
            List of evidence artifacts from the role.
        """
        artifacts = [e for e in self._artifacts if e.role == role]
        if phase_name:
            artifacts = [e for e in artifacts if e.phase_name == phase_name]
        return artifacts

    def get_all_evidence(self) -> list[Evidence]:
        """Get all collected evidence artifacts."""
        return list(self._artifacts)

    def write_manifest(self) -> Path:
        """Write an evidence manifest JSON file.

        Returns:
            Path to the manifest file.
        """
        manifest_path = self.evidence_dir / "manifest.json"
        manifest_data = []

        for evidence in self._artifacts:
            entry = {
                "type": evidence.evidence_type.value,
                "role": evidence.role.value,
                "phase": evidence.phase_name,
                "title": evidence.title,
                "has_content": evidence.content is not None,
                "file_path": str(evidence.file_path) if evidence.file_path else None,
                "collected_at": evidence.collected_at.isoformat(),
            }
            manifest_data.append(entry)

        with open(manifest_path, "w") as f:
            json.dump(manifest_data, f, indent=2)

        logger.info("Evidence manifest written to %s (%d artifacts)", manifest_path, len(manifest_data))
        return manifest_path

    def summary(self) -> dict[str, int]:
        """Generate a summary of evidence counts by phase and role."""
        summary: dict[str, int] = {}
        for evidence in self._artifacts:
            key = f"{evidence.phase_name}/{evidence.role.value}"
            summary[key] = summary.get(key, 0) + 1
        summary["total"] = len(self._artifacts)
        return summary

    def cleanup(self) -> None:
        """Remove all evidence files and directories."""
        if self.evidence_dir.exists():
            shutil.rmtree(self.evidence_dir)
            logger.info("Cleaned up evidence directory: %s", self.evidence_dir)
        self._artifacts.clear()
