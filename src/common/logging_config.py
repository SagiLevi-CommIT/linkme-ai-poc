"""Structured JSON logging with correlation ID injection."""

from __future__ import annotations

import json
import logging
import logging.config
import os
from datetime import datetime, timezone

from common.correlation import get_correlation_id


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }
        for attr in ("tenant_id", "message_id", "stage", "duration_ms", "cache_result", "model_used"):
            if hasattr(record, attr):
                log_data[attr] = getattr(record, attr)
        if record.exc_info and record.exc_info[1]:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data, default=str)


def setup_logging(level: str = "INFO") -> None:
    is_lambda = "AWS_LAMBDA_FUNCTION_NAME" in os.environ
    handlers_config: dict = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "stream": "ext://sys.stdout",
        },
    }
    handler_names = ["console"]

    if not is_lambda:
        os.makedirs(".logs", exist_ok=True)
        handlers_config["file"] = {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "formatter": "json",
            "filename": ".logs/app.log",
            "when": "midnight",
            "backupCount": 7,
        }
        handler_names.append("file")

    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {"()": JSONFormatter},
        },
        "handlers": handlers_config,
        "root": {
            "level": level,
            "handlers": handler_names,
        },
    }
    logging.config.dictConfig(config)
