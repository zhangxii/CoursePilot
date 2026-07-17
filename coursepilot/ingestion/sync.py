"""Local course-material ingestion and durable Markdown storage."""

from pathlib import Path

from coursepilot.ingestion.documents import (
    MarkdownRenderer,
    MaterialParser,
    PdfParser,
    PptxParser,
    UploadValidator,
    calculate_file_hash,
)
from coursepilot.models import IndexStatus, MaterialMetadata, MaterialRecord
from coursepilot.repositories import MaterialRepository


class MaterialIngestionService:
    """Validate, parse, render, deduplicate, and store one local material."""

    def __init__(
        self,
        *,
        repository: MaterialRepository,
        validator: UploadValidator,
        parsers: tuple[MaterialParser, ...] | None = None,
        renderer: MarkdownRenderer | None = None,
    ) -> None:
        self._repository = repository
        self._validator = validator
        self._parsers = parsers or (PdfParser(), PptxParser())
        self._renderer = renderer or MarkdownRenderer()

    async def ingest(self, path: Path, metadata: MaterialMetadata) -> MaterialRecord:
        material_type = self._validator.validate(path)
        if material_type is not metadata.material_type:
            raise ValueError("material metadata type does not match the uploaded file")
        file_hash = calculate_file_hash(path)
        existing = self._repository.find_by_course_hash(metadata.course_id, file_hash)
        if existing is not None and existing.index_status is IndexStatus.INDEXED:
            return existing
        material = existing or self._repository.reserve(
            metadata, file_name=path.name, file_hash=file_hash
        )
        self._repository.mark_pending(material.id)
        try:
            pages = self._parser_for(path.name).parse(path)
            markdown = self._renderer.render(metadata.course_name, pages, material_type)
            return self._repository.mark_indexed(material.id, markdown)
        except Exception as error:
            self._repository.mark_failed(material.id, str(error))
            raise

    def _parser_for(self, file_name: str) -> MaterialParser:
        for parser in self._parsers:
            if parser.supports(file_name):
                return parser
        raise ValueError(f"no parser registered for {file_name}")
