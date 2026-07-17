"""Course creation, listing, and active-course switching."""

from datetime import date

from coursepilot.models import Course, CourseContext
from coursepilot.repositories import CourseRepository


class CourseNotFoundError(LookupError):
    """Raised when an operation targets an unknown course."""


class CourseService:
    def __init__(self, repository: CourseRepository) -> None:
        self._repository = repository

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

    def activate(
        self, course_id: str, context: CourseContext | None = None
    ) -> CourseContext | None:
        try:
            course = self._repository.activate(course_id)
        except KeyError as error:
            raise CourseNotFoundError(course_id) from error
        if context is None:
            return None
        return context.model_copy(
            update={"active_course_id": course.id, "active_course_name": course.name}
        )
