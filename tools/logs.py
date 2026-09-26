import re
from collections import Counter
from datetime import datetime

from pydantic import BaseModel, Field

from core.enums import LogLevel
from core.models import LogEntry
from tools.backend import SimulatedOpsBackend
from tools.common import WindowQuery

LEVEL_ORDER = {level: i for i, level in enumerate(LogLevel)}
_VOLATILE = re.compile(r"\b[0-9a-f]{6,}\b|\d+")


class LogsQuery(WindowQuery):
    min_level: LogLevel = LogLevel.INFO
    limit: int = Field(default=200, ge=1, le=2000)


class ErrorPattern(BaseModel):
    pattern: str
    example: str
    level: LogLevel
    count: int


class LogsResult(BaseModel):
    service: str
    start: datetime
    end: datetime
    total_lines: int
    error_count: int
    top_errors: list[ErrorPattern]
    entries: list[LogEntry]


def normalize(message: str) -> str:
    # Collapse ids and numbers so repeated errors group together.
    return _VOLATILE.sub("<n>", message)


def summarize_errors(entries: list[LogEntry], top: int = 5) -> list[ErrorPattern]:
    errors = [e for e in entries if LEVEL_ORDER[e.level] >= LEVEL_ORDER[LogLevel.ERROR]]
    counts = Counter(normalize(e.message) for e in errors)
    examples: dict[str, LogEntry] = {}
    for entry in errors:
        examples.setdefault(normalize(entry.message), entry)
    return [
        ErrorPattern(
            pattern=pattern,
            example=examples[pattern].message,
            level=examples[pattern].level,
            count=count,
        )
        for pattern, count in counts.most_common(top)
    ]


async def get_recent_logs(backend: SimulatedOpsBackend, query: LogsQuery) -> LogsResult:
    start, end = query.window(backend)
    entries = backend.logs(query.service, start, end)
    threshold = LEVEL_ORDER[query.min_level]
    filtered = [e for e in entries if LEVEL_ORDER[e.level] >= threshold]
    return LogsResult(
        service=query.service,
        start=start,
        end=end,
        total_lines=len(entries),
        error_count=sum(LEVEL_ORDER[e.level] >= LEVEL_ORDER[LogLevel.ERROR] for e in entries),
        top_errors=summarize_errors(entries),
        entries=filtered[-query.limit :],
    )
