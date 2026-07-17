import asyncio
from datetime import date
from pathlib import Path

from coursepilot.file_store import parse_front_matter
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


def test_uploaded_markdown_gets_front_matter_and_retrieval_returns_only_body(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    CourseRepository(data_root).add(
        course_id="current",
        name="Module Design",
        course_date=date(2026, 7, 17),
        teacher="Teacher",
        topic="Architecture",
        active=True,
    )
    source = tmp_path / "lesson.md"
    source.write_text("# Module Design\n\n## Page 2\nClear module boundaries", encoding="utf-8")
    repository = MaterialRepository(data_root)
    ingestion = MaterialIngestionService(
        repository=repository,
        validator=MarkdownValidator(max_upload_bytes=1024),
    )

    record = asyncio.run(ingestion.ingest(source, metadata("current")))
    result = asyncio.run(
        search_current_course(
            "module boundaries",
            CourseContext(
                active_course_id="current",
                active_course_name="Module Design",
                active_assignment_id="assignment-1",
            ),
            gateway=LocalMaterialSearchGateway(repository),
        )
    )

    stored = data_root / record.storage_path
    assert stored.is_file()
    front_matter, body = parse_front_matter(stored.read_text(encoding="utf-8"))
    assert front_matter["course_id"] == "current"
    assert front_matter["original_file_name"] == "lesson.md"
    assert body.strip() == source.read_text(encoding="utf-8")
    assert result.items[0].source.file_name == "lesson.md"
    assert "Clear module boundaries" in result.items[0].source.excerpt

    stored.unlink()
    repaired = asyncio.run(ingestion.ingest(source, metadata("current")))
    assert (data_root / repaired.storage_path).is_file()


def test_uploaded_txt_is_normalized_to_a_markdown_file(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    CourseRepository(data_root).add(
        course_id="current",
        name="Module Design",
        course_date=date(2026, 7, 17),
        teacher="Teacher",
        topic="Architecture",
        active=True,
    )
    source = tmp_path / "notes.txt"
    source.write_text("Plain text course notes", encoding="utf-8")
    repository = MaterialRepository(data_root)
    ingestion = MaterialIngestionService(
        repository=repository,
        validator=MarkdownValidator(max_upload_bytes=1024),
    )
    text_metadata = metadata("current").model_copy(update={"material_type": MaterialType.TEXT})

    record = asyncio.run(ingestion.ingest(source, text_metadata))

    stored = data_root / record.storage_path
    assert stored.suffix == ".md"
    metadata_header, body = parse_front_matter(stored.read_text(encoding="utf-8"))
    assert metadata_header["source_type"] == "text"
    assert body.strip() == "Plain text course notes"


def test_existing_front_matter_is_replaced_and_never_returned_as_body(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    CourseRepository(data_root).add(
        course_id="current",
        name="Module Design",
        course_date=date(2026, 7, 17),
        teacher="Teacher",
        topic="Architecture",
        active=True,
    )
    source = tmp_path / "headed.md"
    source.write_text("---\nuntrusted: value\n---\n\n# Trusted body", encoding="utf-8")
    repository = MaterialRepository(data_root)
    ingestion = MaterialIngestionService(
        repository=repository,
        validator=MarkdownValidator(max_upload_bytes=1024),
    )

    record = asyncio.run(ingestion.ingest(source, metadata("current")))

    stored_header, stored_body = parse_front_matter(
        (data_root / record.storage_path).read_text(encoding="utf-8")
    )
    assert "untrusted" not in stored_header
    assert stored_body.strip() == "# Trusted body"
    assert repository.read_body(record).strip() == "# Trusted body"
