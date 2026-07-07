import json
import logging

from rich.logging import RichHandler

from .config import Environment, settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "time": self.formatTime(record),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def _build_handler() -> logging.Handler:
    if settings.ENVIRONMENT == Environment.prod:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
    else:
        handler = RichHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
    return handler


logger = logging.getLogger("kgmemory")
logger.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
logger.addHandler(_build_handler())
