import json
import logging


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        item = {
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "time": self.formatTime(record),
        }
        if record.exc_info:
            item["exception"] = self.formatException(record.exc_info)
        return json.dumps(item)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
    # URLs can contain credentials and user queries; do not log them at INFO.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
