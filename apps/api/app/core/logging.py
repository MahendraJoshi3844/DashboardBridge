"""Structured logging. Every line carries the ids needed to trace a job (§54)."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar

request_id: ContextVar[str] = ContextVar("request_id", default="")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname.lower(),
            "message": record.getMessage(),
            "logger": record.name,
            "request_id": request_id.get(),
        }
        for key in ("project_id", "job_id", "operation", "duration_ms", "status"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload)


def configure() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
