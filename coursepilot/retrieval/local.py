"""Local full-context and keyword retrieval adapter."""

import re

from coursepilot.models import LocalMaterialDocument, MaterialSearchAttributes
from coursepilot.repositories import MaterialRepository
from coursepilot.retrieval.search import (
    CompoundFilter,
    MaterialSearchHit,
    SearchFilter,
)


class LocalMaterialSearchGateway:
    """Return full local documents when small, otherwise ranked Markdown sections."""

    def __init__(
        self,
        repository: MaterialRepository,
        *,
        full_context_chars: int = 60_000,
    ) -> None:
        if full_context_chars <= 0:
            raise ValueError("full_context_chars must be positive")
        self._repository = repository
        self._full_context_chars = full_context_chars

    async def search(
        self, query: str, filters: SearchFilter, max_results: int
    ) -> list[MaterialSearchHit]:
        documents = [
            document
            for document in self._repository.list_indexed_documents()
            if _matches(document.material.course_id, document.material.status.value, filters)
        ]
        contents = [
            (document, self._repository.read_body(document.material)) for document in documents
        ]
        total_chars = sum(len(markdown) for _, markdown in contents)
        if total_chars <= self._full_context_chars:
            return [_hit(document, markdown, 1.0) for document, markdown in contents]

        ranked = []
        for document, markdown in contents:
            for section in _sections(markdown):
                score = _score(query, section)
                if score > 0:
                    ranked.append((_hit(document, section, float(score)), score))
        ranked.sort(key=lambda item: item[1], reverse=True)
        return [item[0] for item in ranked[:max_results]]


def _hit(document: LocalMaterialDocument, text: str, score: float) -> MaterialSearchHit:
    material = document.material
    return MaterialSearchHit(
        file_id=material.id,
        filename=material.file_name,
        score=score,
        attributes=MaterialSearchAttributes(
            course_id=material.course_id,
            course_name=document.course_name,
            course_date=document.course_date,
            teacher=document.teacher,
            topic=document.topic,
            material_type=material.material_type,
            status=material.status,
        ),
        text=text,
    )


def _matches(course_id: str, status: str, filters: SearchFilter) -> bool:
    comparisons = filters.filters if isinstance(filters, CompoundFilter) else [filters]
    values = {"course_id": course_id, "status": status}
    for comparison in comparisons:
        actual = values.get(comparison.key)
        if comparison.type == "eq" and actual != comparison.value:
            return False
        if comparison.type == "ne" and actual == comparison.value:
            return False
    return True


def _sections(markdown: str) -> list[str]:
    starts = [match.start() for match in re.finditer(r"(?m)^## ", markdown)]
    if not starts:
        return [markdown]
    return [
        markdown[start : starts[index + 1] if index + 1 < len(starts) else None].strip()
        for index, start in enumerate(starts)
    ]


def _score(query: str, text: str) -> int:
    normalized_query = query.strip().casefold()
    normalized_text = text.casefold()
    terms = {normalized_query, *re.findall(r"[\w\u4e00-\u9fff]+", normalized_query)}
    return sum(normalized_text.count(term) for term in terms if term)
