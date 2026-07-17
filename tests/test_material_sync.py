import asyncio
from datetime import date
from pathlib import Path

import fitz
import pytest

from coursepilot.database import initialize_database
from coursepilot.ingestion import (
    IndexingFailed,
    MaterialIngestionService,
    PreparedDocument,
    RemoteFileRef,
    RemoteUploadFailed,
    UploadValidator,
)
from coursepilot.models import IndexStatus, MaterialMetadata, MaterialStatus, MaterialType
from coursepilot.repositories import CourseRepository, MaterialRepository
from coursepilot.services import CourseService


class FakeVectorStoreGateway:
    def __init__(self, outcomes: list[RemoteFileRef | Exception]) -> None:
        self.outcomes = outcomes
        self.uploaded_file_names: list[str] = []
        self.deleted_file_ids: list[str] = []

    async def upload(self, document: PreparedDocument) -> RemoteFileRef:
        self.uploaded_file_names.append(document.file_name)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def delete(self, remote_file_id: str) -> None:
        self.deleted_file_ids.append(remote_file_id)


def create_pdf(path: Path, text: str) -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def metadata() -> MaterialMetadata:
    return MaterialMetadata(
        course_id="architecture-20260717",
        course_name="架构设计",
        course_date=date(2026, 7, 17),
        teacher="刘飞",
        topic="架构设计",
        material_type=MaterialType.PDF,
        status=MaterialStatus.CURRENT,
    )


def setup_repository(database: Path) -> MaterialRepository:
    initialize_database(database)
    CourseService(CourseRepository(database)).create(
        course_id="architecture-20260717",
        name="架构设计",
        course_date=date(2026, 7, 17),
        teacher="刘飞",
        topic="架构设计",
    )
    return MaterialRepository(database)


def test_successful_ingestion_indexes_once_and_deduplicates_by_course_hash(
    tmp_path: Path,
) -> None:
    source = tmp_path / "architecture.pdf"
    create_pdf(source, "Architecture content")
    repository = setup_repository(tmp_path / "coursepilot.db")
    gateway = FakeVectorStoreGateway(
        [RemoteFileRef(remote_file_id="file-1", status=IndexStatus.INDEXED)]
    )
    service = MaterialIngestionService(
        repository=repository,
        gateway=gateway,
        validator=UploadValidator(max_upload_bytes=1024 * 1024),
    )

    first = asyncio.run(service.ingest(source, metadata()))
    duplicate = asyncio.run(service.ingest(source, metadata()))

    assert first.id == duplicate.id
    assert first.index_status is IndexStatus.INDEXED
    assert first.remote_file_id == "file-1"
    assert gateway.uploaded_file_names == ["architecture.md"]
    assert len(repository.list_for_course("architecture-20260717")) == 1


def test_failed_upload_is_recorded_and_retry_reuses_the_material_record(tmp_path: Path) -> None:
    source = tmp_path / "architecture.pdf"
    create_pdf(source, "Architecture content")
    repository = setup_repository(tmp_path / "coursepilot.db")
    gateway = FakeVectorStoreGateway(
        [
            RuntimeError("network unavailable"),
            RemoteFileRef(remote_file_id="file-2", status=IndexStatus.INDEXED),
        ]
    )
    service = MaterialIngestionService(
        repository=repository,
        gateway=gateway,
        validator=UploadValidator(max_upload_bytes=1024 * 1024),
    )

    with pytest.raises(RemoteUploadFailed):
        asyncio.run(service.ingest(source, metadata()))

    failed = repository.list_for_course("architecture-20260717")[0]
    assert failed.index_status is IndexStatus.FAILED
    assert failed.error == "network unavailable"

    retried = asyncio.run(service.ingest(source, metadata()))

    assert retried.id == failed.id
    assert retried.index_status is IndexStatus.INDEXED
    assert retried.error is None
    assert len(repository.list_for_course("architecture-20260717")) == 1


def test_non_completed_remote_status_is_recorded_as_indexing_failure(tmp_path: Path) -> None:
    source = tmp_path / "architecture.pdf"
    create_pdf(source, "Architecture content")
    repository = setup_repository(tmp_path / "coursepilot.db")
    gateway = FakeVectorStoreGateway(
        [
            RemoteFileRef(remote_file_id="file-3", status=IndexStatus.FAILED),
            RemoteFileRef(remote_file_id="file-4", status=IndexStatus.INDEXED),
        ]
    )
    service = MaterialIngestionService(
        repository=repository,
        gateway=gateway,
        validator=UploadValidator(max_upload_bytes=1024 * 1024),
    )

    with pytest.raises(IndexingFailed):
        asyncio.run(service.ingest(source, metadata()))

    failed = repository.list_for_course("architecture-20260717")[0]
    assert failed.index_status is IndexStatus.FAILED
    assert failed.remote_file_id == "file-3"

    retried = asyncio.run(service.ingest(source, metadata()))

    assert gateway.deleted_file_ids == ["file-3"]
    assert retried.id == failed.id
    assert retried.remote_file_id == "file-4"
    assert retried.index_status is IndexStatus.INDEXED
