"""Logging JSON estruturado, com `request_id` por requisição (F0-13)."""

import json
import logging

from apps.core import request_context


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        ctx = request_context.get_current()
        record.request_id = str(ctx.request_id) if ctx.request_id else "-"
        record.user_id = getattr(ctx.actor, "pk", None) or "-"
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "user_id": getattr(record, "user_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)
