from pathlib import Path

import pytest

from coursepilot.ingestion import EmptyMarkdown, MarkdownValidator, UnsupportedFileType
from coursepilot.models import MaterialType


def test_text_validator_accepts_non_empty_md_and_txt_and_rejects_other_files(
    tmp_path: Path,
) -> None:
    markdown = tmp_path / "course.MD"
    markdown.write_text("# Module design\n\n## Page 1\nClear boundaries", encoding="utf-8")
    text_file = tmp_path / "course.txt"
    text_file.write_text("plain text", encoding="utf-8")
    unsupported = tmp_path / "course.pdf"
    unsupported.write_bytes(b"pdf")
    empty = tmp_path / "empty.md"
    empty.write_text("  \n", encoding="utf-8")
    validator = MarkdownValidator(max_upload_bytes=1024)

    assert validator.validate(markdown) is MaterialType.MARKDOWN
    assert validator.validate(text_file) is MaterialType.TEXT
    with pytest.raises(UnsupportedFileType):
        validator.validate(unsupported)
    with pytest.raises(EmptyMarkdown):
        validator.validate(empty)
