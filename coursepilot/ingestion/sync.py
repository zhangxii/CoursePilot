"""Material ingestion orchestration and vector-store boundary."""

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from coursepilot.ingestion.documents import (
    MarkdownRenderer,
    MaterialParser,
    PdfParser,
    PptxParser,
    UploadValidator,
    calculate_file_hash,
)
from coursepilot.models import (
    IndexStatus,
    MaterialMetadata,
    MaterialRecord,
    MaterialSearchAttributes,
)
from coursepilot.repositories import MaterialRepository


class RemoteUploadFailed(RuntimeError):
    """Raised when a prepared document cannot be uploaded."""


class IndexingFailed(RuntimeError):
    """Raised when the remote vector store does not index an uploaded document."""


class PreparedDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    file_name: str
    markdown: str
    file_hash: str
    metadata: MaterialMetadata

    def search_attributes(self) -> MaterialSearchAttributes:
        return MaterialSearchAttributes.from_metadata(self.metadata)


class RemoteFileRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    remote_file_id: str
    status: IndexStatus


class VectorStoreGateway(Protocol):
    async def upload(self, document: PreparedDocument) -> RemoteFileRef: ...

    async def delete(self, remote_file_id: str) -> None: ...


class MaterialIngestionService:
    def __init__(
        self,
        *,
        repository: MaterialRepository,
        gateway: VectorStoreGateway,
        validator: UploadValidator,
        parsers: tuple[MaterialParser, ...] | None = None,
        renderer: MarkdownRenderer | None = None,
    ) -> None:
        self._repository = repository
        self._gateway = gateway
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

        parser = self._parser_for(path.name)
        pages = parser.parse(path)
        markdown = self._renderer.render(metadata.course_name, pages, material_type)
        material = existing or self._repository.reserve(
            metadata, file_name=path.name, file_hash=file_hash
        )
        prepared = PreparedDocument(
            file_name=f"{path.stem}.md",
            markdown=markdown,
            file_hash=file_hash,
            metadata=metadata.model_copy(update={"status": material.status}),
        )
        if material.remote_file_id is not None:
            try:
                await self._gateway.delete(material.remote_file_id)
            except Exception as error:
                self._repository.mark_failed(
                    material.id, str(error), remote_file_id=material.remote_file_id
                )
                raise RemoteUploadFailed(str(error)) from error
        self._repository.mark_pending(material.id)

        try:
            remote = await self._gateway.upload(prepared)
        except Exception as error:
            self._repository.mark_failed(material.id, str(error))
            raise RemoteUploadFailed(str(error)) from error

        self._repository.mark_uploaded(material.id, remote.remote_file_id)
        if remote.status is not IndexStatus.INDEXED:
            message = f"remote indexing ended with status {remote.status.value}"
            self._repository.mark_failed(material.id, message, remote_file_id=remote.remote_file_id)
            raise IndexingFailed(message)
        return self._repository.mark_indexed(material.id)

    def _parser_for(self, file_name: str) -> MaterialParser:
        for parser in self._parsers:
            if parser.supports(file_name):
                return parser
        raise ValueError(f"no parser registered for {file_name}")
