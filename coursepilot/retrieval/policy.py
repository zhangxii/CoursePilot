"""Stateful permission gate enforcing current-course retrieval before archive access."""

from coursepilot.retrieval.search import ArchiveSearchReason


class CurrentFirstPolicy:
    def __init__(self) -> None:
        self._current_searched = False

    def record_current_search(self) -> None:
        self._current_searched = True

    def authorize_archive(self, reason: ArchiveSearchReason) -> None:
        if not self._current_searched:
            raise ValueError("archive search requires a prior current-course search")
