"""OpenAI Vector Store adapter isolated from application services."""

from typing import cast

from openai import AsyncOpenAI
from openai.types import vector_store_search_params

from coursepilot.ingestion import PreparedDocument, RemoteFileRef
from coursepilot.models import IndexStatus, MaterialSearchAttributes
from coursepilot.retrieval import RemoteSearchHit
from coursepilot.retrieval.search import SearchFilter


class OpenAIVectorStoreGateway:
    def __init__(self, client: AsyncOpenAI, vector_store_id: str) -> None:
        self._client = client
        self._vector_store_id = vector_store_id

    async def upload(self, document: PreparedDocument) -> RemoteFileRef:
        response = await self._client.vector_stores.files.upload_and_poll(
            vector_store_id=self._vector_store_id,
            file=(document.file_name, document.markdown.encode("utf-8"), "text/markdown"),
            attributes=document.search_attributes().model_dump(mode="json"),
        )
        status = IndexStatus.INDEXED if response.status == "completed" else IndexStatus.FAILED
        return RemoteFileRef(remote_file_id=response.id, status=status)

    async def delete(self, remote_file_id: str) -> None:
        await self._client.vector_stores.files.delete(
            remote_file_id, vector_store_id=self._vector_store_id
        )

    async def search(
        self, query: str, filters: SearchFilter, max_results: int
    ) -> list[RemoteSearchHit]:
        sdk_filters = cast(
            vector_store_search_params.Filters,
            filters.model_dump(mode="python"),
        )
        response = await self._client.vector_stores.search(
            self._vector_store_id,
            query=query,
            filters=sdk_filters,
            max_num_results=max_results,
        )
        return [
            RemoteSearchHit(
                file_id=item.file_id,
                filename=item.filename,
                score=item.score,
                attributes=MaterialSearchAttributes.model_validate(item.attributes or {}),
                text="\n\n".join(content.text for content in item.content),
            )
            for item in response.data
        ]
