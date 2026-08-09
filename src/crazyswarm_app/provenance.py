from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RepositoryProvenance:
    commit: str | None
    dirty: bool
    available: bool

    def as_dict(self) -> dict[str, str | bool | None]:
        return {
            "repository_commit": self.commit,
            "repository_dirty": self.dirty,
            "repository_provenance_available": self.available,
        }


def repository_provenance(start: Path | None = None) -> RepositoryProvenance:
    """Return stable Git identity without making Git a runtime dependency."""

    working_directory = start or Path.cwd()
    try:
        root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=working_directory,
            check=True,
            capture_output=True,
            text=True,
            timeout=2.0,
        ).stdout.strip()
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=2.0,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=2.0,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return RepositoryProvenance(commit=None, dirty=False, available=False)
    return RepositoryProvenance(commit=commit or None, dirty=bool(status.strip()), available=True)
