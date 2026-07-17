import asyncio
from datetime import date
from pathlib import Path

import fitz

from coursepilot.database import initialize_database
from coursepilot.ingestion import MaterialIngestionService, UploadValidator
from coursepilot.models import CourseContext, MaterialMetadata, MaterialStatus, MaterialType
from coursepilot.repositories import CourseRepository, MaterialRepository
from coursepilot.retrieval import (
    ArchiveSearchReason,
    LocalMaterialSearchGateway,
    search_course_archive,
    search_current_course,
)


def create_pdf(path: Path, pages: list[str]) -> None:
    document = fitz.open()
    for text in pages:
        page = document.new_page()
        page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def metadata(course_id: str, status: MaterialStatus) -> MaterialMetadata:
    return MaterialMetadata(
        course_id=course_id,
        course_name=course_id,
        course_date=date(2026, 7, 17),
        teacher="Teacher",
        topic="Architecture",
        material_type=MaterialType.PDF,
        status=status,
    )


def setup_courses(database: Path) -> None:
    courses = CourseRepository(database)
    courses.add(
        course_id="current",
        name="Current",
        course_date=date(2026, 7, 17),
        teacher="Teacher",
        topic="Current standard",
        active=True,
    )
    courses.add(
        course_id="history",
        name="History",
        course_date=date(2026, 7, 1),
        teacher="Teacher",
        topic="Old standard",
        active=False,
    )


def test_local_ingestion_and_search_need_no_remote_service(tmp_path: Path) -> None:
    database = tmp_path / "coursepilot.db"
    initialize_database(database)
    setup_courses(database)
    source = tmp_path / "lesson.pdf"
    create_pdf(source, ["Current architecture standard", "Explain module boundaries"])
    repository = MaterialRepository(database)
    ingestion = MaterialIngestionService(
        repository=repository,
        validator=UploadValidator(max_upload_bytes=1024 * 1024),
    )

    first = asyncio.run(ingestion.ingest(source, metadata("current", MaterialStatus.CURRENT)))
    duplicate = asyncio.run(ingestion.ingest(source, metadata("current", MaterialStatus.CURRENT)))
    result = asyncio.run(
        search_current_course(
            "module boundaries",
            CourseContext(active_course_id="current", active_course_name="Current"),
            gateway=LocalMaterialSearchGateway(repository),
        )
    )

    assert first.id == duplicate.id
    assert first.content_markdown.startswith("# current")
    assert result.items[0].source.file_name == "lesson.pdf"
    assert "module boundaries" in result.items[0].source.excerpt


def test_large_local_library_ranks_relevant_sections_and_keeps_course_scope(
    tmp_path: Path,
) -> None:
    database = tmp_path / "coursepilot.db"
    initialize_database(database)
    setup_courses(database)
    repository = MaterialRepository(database)
    ingestion = MaterialIngestionService(
        repository=repository,
        validator=UploadValidator(max_upload_bytes=1024 * 1024),
    )
    current_pdf = tmp_path / "current.pdf"
    history_pdf = tmp_path / "history.pdf"
    create_pdf(current_pdf, ["cohesion " * 80, "deployment tradeoff evidence"])
    create_pdf(history_pdf, ["historical deployment rule"])
    asyncio.run(ingestion.ingest(current_pdf, metadata("current", MaterialStatus.CURRENT)))
    asyncio.run(ingestion.ingest(history_pdf, metadata("history", MaterialStatus.ARCHIVED)))
    gateway = LocalMaterialSearchGateway(repository, full_context_chars=100)
    context = CourseContext(active_course_id="current", active_course_name="Current")

    current = asyncio.run(search_current_course("deployment", context, gateway=gateway))
    archive = asyncio.run(
        search_course_archive(
            "deployment",
            ArchiveSearchReason.USER_REQUESTED,
            context,
            gateway=gateway,
        )
    )

    assert {item.source.course_id for item in current.items} == {"current"}
    assert "deployment tradeoff" in current.items[0].source.excerpt
    assert {item.source.course_id for item in archive.items} == {"history"}
