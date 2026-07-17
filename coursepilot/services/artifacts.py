"""Assignment artifacts and user-owned formal versions."""

import re
import xml.etree.ElementTree as ET
from difflib import unified_diff
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from coursepilot.models import (
    AnswerRecord,
    AnswerVersionComparison,
    AssignmentUploadPurpose,
    AttachmentRecord,
    ImportedAssignment,
)
from coursepilot.repositories import WorkspaceRepository
from coursepilot.services.workspace import WorkspaceService


class AssignmentArtifactService:
    """Import user files without mixing them into the course material library."""

    def __init__(
        self,
        data_root: str | Path,
        workspace: WorkspaceService,
        *,
        max_upload_bytes: int = 20 * 1024 * 1024,
    ) -> None:
        self._repository = WorkspaceRepository(data_root)
        self._workspace = workspace
        if max_upload_bytes < 1:
            raise ValueError("max_upload_bytes must be positive")
        self._max_upload_bytes = max_upload_bytes

    def import_assignment(
        self,
        file_name: str,
        content: bytes,
        purpose: AssignmentUploadPurpose,
        member_id: str,
        version_note: str,
    ) -> ImportedAssignment:
        if len(content) > self._max_upload_bytes:
            raise ValueError(f"assignment file exceeds {self._max_upload_bytes} bytes")
        normalized = self._decode_text(file_name, content)
        safe_name = self._safe_name(file_name)
        return self._repository.import_assignment_artifact(
            file_name=file_name,
            safe_name=safe_name,
            original=content,
            normalized=normalized,
            purpose=purpose,
            member_id=member_id,
            version_note=version_note,
        )

    def get_answer_version(self, answer_id: str) -> AnswerRecord:
        return self._workspace.get_answer(answer_id)

    def list_answer_versions(self) -> list[AnswerRecord]:
        return self._workspace.list_answers()

    def list_attachments(self) -> list[AttachmentRecord]:
        return self._repository.list_attachments(self._workspace.get_assignment().id)

    def compare_answer_versions(
        self, source_answer_id: str, result_answer_id: str
    ) -> AnswerVersionComparison:
        source = self._workspace.get_answer(source_answer_id)
        result = self._workspace.get_answer(result_answer_id)
        if source.assignment_id != result.assignment_id:
            raise ValueError("answer versions belong to different assignments")
        diff = "\n".join(
            unified_diff(
                source.content.splitlines(),
                result.content.splitlines(),
                fromfile=f"v{source.version}",
                tofile=f"v{result.version}",
                lineterm="",
            )
        )
        candidate = (
            None
            if result.adopted_candidate_id is None
            else self._repository.get_candidate(result.adopted_candidate_id)
        )
        return AnswerVersionComparison(
            source_answer_id=source.id,
            result_answer_id=result.id,
            source_version=source.version,
            result_version=result.version,
            source_content=source.content,
            result_content=result.content,
            unified_diff=diff or "No textual changes",
            change_summary="" if candidate is None else candidate.change_summary,
            resolved_issues=[] if candidate is None else candidate.resolved_issues,
            unresolved_issues=[] if candidate is None else candidate.unresolved_issues,
        )

    @staticmethod
    def _decode_text(file_name: str, content: bytes) -> str:
        suffix = Path(file_name).suffix.lower()
        if suffix == ".docx":
            return AssignmentArtifactService._decode_docx(content)
        if suffix not in {".md", ".txt"}:
            raise ValueError("assignment file must be .md, .txt, or .docx")
        try:
            result = content.decode("utf-8").strip()
        except UnicodeDecodeError as error:
            raise ValueError("assignment text file must be UTF-8") from error
        if not result:
            raise ValueError("assignment file must not be empty")
        return result

    @staticmethod
    def _decode_docx(content: bytes) -> str:
        try:
            with ZipFile(BytesIO(content)) as archive:
                info = archive.getinfo("word/document.xml")
                if info.file_size > 10 * 1024 * 1024:
                    raise ValueError("DOCX document text exceeds 10 MB")
                document = archive.read(info)
        except (BadZipFile, KeyError) as error:
            raise ValueError("assignment DOCX is invalid") from error
        try:
            root = ET.fromstring(document)
        except ET.ParseError as error:
            raise ValueError("assignment DOCX document XML is invalid") from error
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paragraphs = []
        for paragraph in root.iter(f"{namespace}p"):
            text = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t")).strip()
            if text:
                paragraphs.append(text)
        result = "\n\n".join(paragraphs).strip()
        if not result:
            raise ValueError("assignment file must not be empty")
        return result

    @staticmethod
    def _safe_name(file_name: str) -> str:
        name = Path(file_name).name
        if name != file_name or len(name) > 128:
            raise ValueError("assignment file name is invalid")
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).rstrip(". ")
        if safe in {"", ".", ".."}:
            raise ValueError("assignment file name is invalid")
        reserved = {"CON", "PRN", "AUX", "NUL"} | {
            f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
        }
        if Path(safe).stem.upper() in reserved:
            raise ValueError("assignment file name is reserved")
        return safe
