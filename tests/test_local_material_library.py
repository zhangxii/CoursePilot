import asyncio
from datetime import date
from pathlib import Path

from coursepilot.database import initialize_database
from coursepilot.ingestion import MarkdownValidator, MaterialIngestionService
from coursepilot.models import CourseContext, MaterialMetadata, MaterialStatus, MaterialType
from coursepilot.repositories import CourseRepository, MaterialRepository
from coursepilot.retrieval import LocalMaterialSearchGateway, search_current_course


def metadata(course_id: str) -> MaterialMetadata:
    return MaterialMetadata(
        course_id=course_id,
        course_name="Module Design",
        course_date=date(2026, 7, 17),
        teacher="Teacher",
        topic="Architecture",
        material_type=MaterialType.MARKDOWN,
        status=MaterialStatus.CURRENT,
    )


def test_uploaded_markdown_is_stored_as_a_file_and_retrieved_without_database_body(
    tmp_path: Path,
) -> None:
    database = tmp_path / "coursepilot.db"
    initialize_database(database)
    CourseRepository(database).add(
        course_id="current",
        name="Module Design",
        course_date=date(2026, 7, 17),
        teacher="Teacher",
        topic="Architecture",
        active=True,
    )
    source = tmp_path / "lesson.md"
    source.write_text("# Module Design\n\n## Page 2\nClear module boundaries", encoding="utf-8")
    repository = MaterialRepository(database)
    ingestion = MaterialIngestionService(
        repository=repository,
        validator=MarkdownValidator(max_upload_bytes=1024),
        material_root=tmp_path / "materials",
    )

    record = asyncio.run(ingestion.ingest(source, metadata("current")))
    result = asyncio.run(
        search_current_course(
            "module boundaries",
            CourseContext(active_course_id="current", active_course_name="Module Design"),
            gateway=LocalMaterialSearchGateway(repository, material_root=tmp_path / "materials"),
        )
    )

    stored = tmp_path / "materials" / record.storage_path
    assert stored.is_file()
    assert stored.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert result.items[0].source.file_name == "lesson.md"
    assert "Clear module boundaries" in result.items[0].source.excerpt

    stored.unlink()
    repaired = asyncio.run(ingestion.ingest(source, metadata("current")))
    assert repaired.id == record.id
    assert stored.is_file()


def test_uploaded_txt_is_normalized_to_a_markdown_file(tmp_path: Path) -> None:
    database = tmp_path / "coursepilot.db"
    initialize_database(database)
    CourseRepository(database).add(
        course_id="current",
        name="Module Design",
        course_date=date(2026, 7, 17),
        teacher="Teacher",
        topic="Architecture",
        active=True,
    )
    source = tmp_path / "notes.txt"
    source.write_text("Plain text course notes", encoding="utf-8")
    repository = MaterialRepository(database)
    ingestion = MaterialIngestionService(
        repository=repository,
        validator=MarkdownValidator(max_upload_bytes=1024),
        material_root=tmp_path / "materials",
    )
    text_metadata = metadata("current").model_copy(update={"material_type": MaterialType.TEXT})

    record = asyncio.run(ingestion.ingest(source, text_metadata))

    stored = tmp_path / "materials" / record.storage_path
    assert stored.suffix == ".md"
    assert stored.read_text(encoding="utf-8") == "Plain text course notes"
