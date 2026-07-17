import asyncio
from datetime import date
from types import SimpleNamespace
from typing import Any, cast

from openai import AsyncOpenAI

from coursepilot.ingestion import PreparedDocument
from coursepilot.integrations import OpenAIVectorStoreGateway
from coursepilot.models import IndexStatus, MaterialMetadata, MaterialStatus, MaterialType
from coursepilot.retrieval import ComparisonFilter


class FakeFilesResource:
    def __init__(self) -> None:
        self.upload_arguments: dict[str, Any] | None = None
        self.delete_arguments: tuple[str, str] | None = None
        self.update_arguments: list[dict[str, Any]] = []

    async def upload_and_poll(self, **arguments: Any) -> object:
        self.upload_arguments = arguments
        return SimpleNamespace(id="file-1", status="completed")

    async def delete(self, file_id: str, *, vector_store_id: str) -> None:
        self.delete_arguments = (file_id, vector_store_id)

    def list(self, vector_store_id: str) -> object:
        attributes = prepared_document().search_attributes().model_dump(mode="json")

        async def items() -> Any:
            yield SimpleNamespace(id="file-1", attributes=attributes)

        return items()

    async def update(self, file_id: str, **arguments: Any) -> None:
        self.update_arguments.append({"file_id": file_id, **arguments})


class FakeVectorStoresResource:
    def __init__(self) -> None:
        self.files = FakeFilesResource()
        self.search_arguments: dict[str, Any] | None = None

    async def search(self, vector_store_id: str, **arguments: Any) -> object:
        self.search_arguments = {"vector_store_id": vector_store_id, **arguments}
        item = SimpleNamespace(
            file_id="file-1",
            filename="architecture.md",
            score=0.93,
            attributes={
                "course_id": "architecture-20260717",
                "course_name": "Architecture",
                "course_date": "2026-07-17",
                "teacher": "Teacher",
                "topic": "Architecture",
                "material_type": "pdf",
                "status": "current",
            },
            content=[SimpleNamespace(text="## PDF 第 1 页\n\nContent")],
        )
        return SimpleNamespace(data=[item])


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.vector_stores = FakeVectorStoresResource()


def prepared_document() -> PreparedDocument:
    return PreparedDocument(
        file_name="architecture.md",
        markdown="# Architecture\n",
        file_hash="hash",
        metadata=MaterialMetadata(
            course_id="architecture-20260717",
            course_name="架构设计",
            course_date=date(2026, 7, 17),
            teacher="刘飞",
            topic="架构设计",
            material_type=MaterialType.PDF,
            status=MaterialStatus.CURRENT,
        ),
    )


def test_openai_gateway_maps_upload_search_and_delete_sdk_contracts() -> None:
    client = FakeOpenAIClient()
    gateway = OpenAIVectorStoreGateway(cast(AsyncOpenAI, client), "vs_test")

    uploaded = asyncio.run(gateway.upload(prepared_document()))
    hits = asyncio.run(
        gateway.search(
            "architecture",
            ComparisonFilter(type="eq", key="course_id", value="architecture-20260717"),
            5,
        )
    )
    asyncio.run(gateway.delete("file-1"))
    asyncio.run(gateway.activate_course("another-course"))

    assert uploaded.remote_file_id == "file-1"
    assert uploaded.status is IndexStatus.INDEXED
    assert client.vector_stores.files.upload_arguments is not None
    assert client.vector_stores.files.upload_arguments["vector_store_id"] == "vs_test"
    assert client.vector_stores.files.upload_arguments["attributes"]["course_id"] == (
        "architecture-20260717"
    )
    assert client.vector_stores.search_arguments == {
        "vector_store_id": "vs_test",
        "query": "architecture",
        "filters": {
            "type": "eq",
            "key": "course_id",
            "value": "architecture-20260717",
        },
        "max_num_results": 5,
    }
    assert hits[0].text == "## PDF 第 1 页\n\nContent"
    assert client.vector_stores.files.delete_arguments == ("file-1", "vs_test")
    assert client.vector_stores.files.update_arguments[0]["attributes"]["status"] == "archived"
