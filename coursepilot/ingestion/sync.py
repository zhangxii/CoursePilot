"""Ingest user-prepared Markdown without parsing or conversion."""

from pathlib import Path

from coursepilot.ingestion.documents import MarkdownValidator, calculate_file_hash
from coursepilot.material_store import MaterialFileStore
from coursepilot.models import IndexStatus, MaterialMetadata, MaterialRecord
from coursepilot.repositories import MaterialRepository


class MaterialIngestionService:
    """Validate, deduplicate, and persist one Markdown material file."""

    def __init__(
        self,
        *,
        repository: MaterialRepository,
        validator: MarkdownValidator,
        material_root: Path,
    ) -> None:
        self._repository = repository
        self._validator = validator
        self._store = MaterialFileStore(material_root)

    async def ingest(self, path: Path, metadata: MaterialMetadata) -> MaterialRecord:
        material_type = self._validator.validate(path)
        if material_type is not metadata.material_type:
            raise ValueError("material metadata type does not match the uploaded file")
        file_hash = calculate_file_hash(path)
        existing = self._repository.find_by_course_hash(metadata.course_id, file_hash)
        if (
            existing is not None
            and existing.index_status is IndexStatus.INDEXED
            and self._store.exists(existing.storage_path)
        ):
            return existing
        material = existing or self._repository.reserve(
            metadata, file_name=path.name, file_hash=file_hash
        )
        self._repository.mark_pending(material.id)
        try:
            storage_key = self._store.write(material.id, path.read_text(encoding="utf-8"))
            return self._repository.mark_indexed(material.id, storage_key)
        except Exception as error:
            self._repository.mark_failed(material.id, str(error))
            raise
