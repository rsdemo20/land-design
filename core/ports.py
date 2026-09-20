"""Ports used by the domain-facing application code."""

from pathlib import Path
from typing import Protocol

from .domain import Project


class ProjectRepository(Protocol):
    """Persistence boundary for complete plot-planning projects."""

    @property
    def path(self) -> Path:
        ...

    def load(self) -> Project:
        ...

    def save(self, project: Project) -> None:
        ...
