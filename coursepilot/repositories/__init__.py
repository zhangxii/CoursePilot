"""File-backed repositories for persisted CoursePilot entities."""

from coursepilot.repositories.courses import CourseRepository
from coursepilot.repositories.materials import MaterialRepository
from coursepilot.repositories.workspace import WorkspaceRepository

__all__ = ["CourseRepository", "MaterialRepository", "WorkspaceRepository"]
