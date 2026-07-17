from datetime import date
from pathlib import Path

import pytest

from coursepilot.models import CourseContext, MaterialMetadata, MaterialStatus, MaterialType
from coursepilot.repositories import CourseRepository, MaterialRepository
from coursepilot.services import CourseNotFoundError, CourseService


def test_course_service_creates_lists_and_switches_the_single_active_course(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    service = CourseService(CourseRepository(data_root))

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
    materials = MaterialRepository(data_root)
    first_material = materials.add(
        MaterialMetadata(
            course_id=first.id,
            course_name=first.name,
            course_date=first.course_date,
            teacher=first.teacher,
            topic=first.topic,
            material_type=MaterialType.MARKDOWN,
            status=MaterialStatus.CURRENT,
        ),
        file_name="requirements.md",
        file_hash="requirements-hash",
        body="# Requirements",
    )
    second_material = materials.add(
        MaterialMetadata(
            course_id=second.id,
            course_name=second.name,
            course_date=second.course_date,
            teacher=second.teacher,
            topic=second.topic,
            material_type=MaterialType.MARKDOWN,
            status=MaterialStatus.CURRENT,
        ),
        file_name="architecture.md",
        file_hash="architecture-hash",
        body="# Architecture",
    )

    assert first_material.status is MaterialStatus.CURRENT
    assert second_material.status is MaterialStatus.ARCHIVED

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
    assert materials.get(first_material.id).status is MaterialStatus.ARCHIVED
    assert materials.get(second_material.id).status is MaterialStatus.CURRENT


def test_activating_unknown_course_preserves_the_current_course(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    service = CourseService(CourseRepository(data_root))
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
