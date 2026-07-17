from datetime import date
from pathlib import Path

import pytest

from coursepilot.database import initialize_database
from coursepilot.models import CourseContext
from coursepilot.repositories import CourseRepository
from coursepilot.services import CourseNotFoundError, CourseService


def test_course_service_creates_lists_and_switches_the_single_active_course(
    tmp_path: Path,
) -> None:
    database = tmp_path / "coursepilot.db"
    initialize_database(database)
    service = CourseService(CourseRepository(database))

    first = service.create(
        course_id="requirements-20260701",
        name="系统需求",
        course_date=date(2026, 7, 1),
        teacher="刘飞",
        topic="系统需求与 DFX",
    )
    second = service.create(
        course_id="architecture-20260717",
        name="架构设计",
        course_date=date(2026, 7, 17),
        teacher="刘飞",
        topic="架构设计",
    )

    assert first.is_active is True
    assert second.is_active is False
    assert [course.id for course in service.list_courses()] == [
        "architecture-20260717",
        "requirements-20260701",
    ]

    context = CourseContext(
        active_course_id=first.id,
        active_course_name=first.name,
    )
    updated_context = service.activate(second.id, context)

    assert service.get_active().id == second.id
    assert updated_context.active_course_id == second.id
    assert updated_context.active_course_name == second.name
    assert sum(course.is_active for course in service.list_courses()) == 1


def test_activating_unknown_course_preserves_the_current_course(tmp_path: Path) -> None:
    database = tmp_path / "coursepilot.db"
    initialize_database(database)
    service = CourseService(CourseRepository(database))
    active = service.create(
        course_id="requirements-20260701",
        name="系统需求",
        course_date=date(2026, 7, 1),
        teacher="刘飞",
        topic="系统需求与 DFX",
    )

    context = CourseContext(
        active_course_id=active.id,
        active_course_name=active.name,
    )
    with pytest.raises(CourseNotFoundError):
        service.activate("missing-course", context)

    assert service.get_active().id == active.id
