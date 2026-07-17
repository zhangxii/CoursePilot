"""Request tracing and redacted structured diagnostics."""

import json
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter
from uuid import uuid4

from pydantic import BaseModel, ConfigDict


class TraceContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str
    session_id: str
    active_course_id: str | None = None
    intent: str | None = None

    @classmethod
    def create(cls, session_id: str, active_course_id: str | None = None) -> "TraceContext":
        return cls(
            request_id=str(uuid4()),
            session_id=session_id,
            active_course_id=active_course_id,
        )


class SpanRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str
    name: str
    elapsed_ms: float
    attributes: dict[str, str]
    error: str | None = None


class TraceCollector:
    def __init__(self) -> None:
        self.records: list[SpanRecord] = []

    @contextmanager
    def span(self, context: TraceContext, name: str, **attributes: str) -> Iterator[None]:
        started = perf_counter()
        error_name = None
        try:
            yield
        except Exception as error:
            error_name = type(error).__name__
            raise
        finally:
            self.records.append(
                SpanRecord(
                    request_id=context.request_id,
                    name=name,
                    elapsed_ms=(perf_counter() - started) * 1000,
                    attributes=attributes,
                    error=error_name,
                )
            )


_SECRET = re.compile(r"(?i)(sk-[a-z0-9_-]+|bearer\s+[a-z0-9._-]+)")


def redact(value: str) -> str:
    return _SECRET.sub("[REDACTED]", value)


def log_error(logger: logging.Logger, context: TraceContext, error: Exception) -> None:
    payload = {
        "request_id": context.request_id,
        "session_id": context.session_id,
        "error_type": type(error).__name__,
        "message": redact(str(error)),
    }
    logger.error(json.dumps(payload, ensure_ascii=False))
