"""JSON logging with scoped context and bounded, value-free exception diagnostics."""

import json
import logging
import re
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from time import perf_counter

logger = logging.getLogger("bi_wiki")
_context: ContextVar[dict | None] = ContextVar("log_context", default=None)
_FIELDS = (
    "request_id",
    "run_id",
    "workflow",
    "stage",
    "status",
    "method",
    "route",
    "status_code",
    "elapsed_ms",
    "error_type",
)


@contextmanager
def log_context(**fields):
    """Bind trusted identifiers for this task; nested scopes restore their parent."""
    unknown = fields.keys() - set(_FIELDS)
    if unknown:
        raise ValueError("Unsupported log context field")
    token = _context.set({**(_context.get() or {}), **fields})
    try:
        yield
    finally:
        _context.reset(token)


@contextmanager
def timed_step(stage: str):
    started = perf_counter()
    status = "failed"
    with log_context(stage=stage):
        try:
            yield
            status = "succeeded"
        finally:
            logger.info(
                "step_completed",
                extra={"status": status, "elapsed_ms": round((perf_counter() - started) * 1000, 2)},
            )


def _safe(value):
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    text = str(value)
    text = re.sub(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s]+", "[REDACTED_URL]", text)
    text = re.sub(r"(?i)(bearer\s+)\S+", r"\1[REDACTED]", text)
    text = re.sub(
        r"(?i)((?:password|token|api[_-]?key|secret)\s*[=:]\s*)\S+", r"\1[REDACTED]", text
    )
    return text[:512]


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        internal = record.name == "bi_wiki" or record.name.startswith("bi_wiki.")
        # Third-party messages can contain URLs, SQL and arbitrary bodies: keep metadata only.
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": _safe(record.getMessage()) if internal else "third_party_log",
            "source": {
                "file": Path(record.pathname).name,
                "line": record.lineno,
                "function": record.funcName,
            },
        }
        for name in _FIELDS:
            value = getattr(record, name, (_context.get() or {}).get(name))
            if value is not None:
                entry[name] = _safe(value)
        if record.exc_info and record.exc_info[0]:
            entry["error_type"] = record.exc_info[0].__name__
            frames = []
            tb = record.exc_info[2]
            while tb is not None:
                frames.append(
                    {
                        "file": Path(tb.tb_frame.f_code.co_filename).name,
                        "line": tb.tb_lineno,
                        "function": tb.tb_frame.f_code.co_name,
                    }
                )
                tb = tb.tb_next
            entry["stack"] = frames[-32:]
        return json.dumps(entry, ensure_ascii=False)


def setup_logging(level: str, *, log_file: Path | None = None, backup_count: int = 7) -> None:
    """Configure once per process; repeated calls replace and close owned handlers."""
    root = logging.getLogger()
    for handler in root.handlers[:]:
        if getattr(handler, "_bi_wiki_owned", False):
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            TimedRotatingFileHandler(
                log_file, when="midnight", utc=True, backupCount=backup_count, encoding="utf-8"
            )
        )
    for handler in handlers:
        handler._bi_wiki_owned = True
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
    for name in (
        "bi_wiki",
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "sqlalchemy",
        "sqlalchemy.engine",
        "sqlalchemy.pool",
        "asyncpg",
        "httpx",
        "httpcore",
    ):
        target = logging.getLogger(name)
        for handler in target.handlers[:]:
            target.removeHandler(handler)
            handler.close()
        target.propagate = True
        target.setLevel(
            logging.NOTSET if name.startswith(("bi_wiki", "uvicorn")) else logging.WARNING
        )
    logging.getLogger("uvicorn.access").disabled = True
