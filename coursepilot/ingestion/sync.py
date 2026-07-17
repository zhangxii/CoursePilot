"""Ingest user-prepared Markdown or text into managed Markdown files."""

from pathlib import Path

from coursepilot.ingestion.documents import MarkdownValidator, calculate_file_hash
from coursepilot.models import MaterialMetadata, MaterialRecord
from coursepilot.repositories import MaterialRepository


class MaterialIngestionService:
    def __init__(
        self,
        *,
        repository: MaterialRepository,
        validator: MarkdownValidator,
    ) -> None:
        self._repository = repository
        self._validator = validator

    async def ingest(self, path: Path, metadata: MaterialMetadata) -> MaterialRecord:
        material_type = self._validator.validate(path)
        if material_type is not metadata.material_type:
            raise ValueError("material metadata type does not match the uploaded file")
        return self._repository.add(
            metadata,
            file_name=path.name,
            file_hash=calculate_file_hash(path),
            body=path.read_text(encoding="utf-8"),
        )
