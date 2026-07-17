"""Course creation, listing, and active-course switching."""

from datetime import date
from typing import Protocol

from coursepilot.models import Course, CourseContext
from coursepilot.repositories import CourseRepository


class CourseNotFoundError(LookupError):
    """Raised when an operation targets an unknown course."""


class CourseStatusGateway(Protocol):
    async def activate_course(self, course_id: str) -> None: ...


class CourseService:
    def __init__(
        self,
        repository: CourseRepository,
        status_gateway: CourseStatusGateway | None = None,
    ) -> None:
        self._repository = repository
        self._status_gateway = status_gateway

    def create(
        self,
        *,
        course_id: str,
        name: str,
        course_date: date,
        teacher: str,
        topic: str,
    ) -> Course:
        return self._repository.add(
            course_id=course_id,
            name=name,
            course_date=course_date,
            teacher=teacher,
            topic=topic,
            active=self._repository.get_active() is None,
        )

    def list_courses(self) -> list[Course]:
        return self._repository.list()

    def get_active(self) -> Course:
        course = self._repository.get_active()
        if course is None:
            raise CourseNotFoundError("no active course")
        return course

    async def activate(self, course_id: str, context: CourseContext) -> CourseContext:
        if self._status_gateway is None:
            raise RuntimeError("course activation requires a status synchronization gateway")
        try:
            self._repository.get(course_id)
        except KeyError as error:
            raise CourseNotFoundError(course_id) from error
        await self._status_gateway.activate_course(course_id)
        try:
            course = self._repository.activate(course_id)
        except KeyError as error:
            raise CourseNotFoundError(course_id) from error
        return context.model_copy(
            update={"active_course_id": course.id, "active_course_name": course.name}
        )
