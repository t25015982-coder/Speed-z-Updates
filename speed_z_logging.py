import os
import sys
import time
import json
import traceback
from pathlib import Path
from enum import Enum
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta


class LogLevel(Enum):
    DEBUG = 0
    INFO = 1
    WARN = 2
    ERROR = 3
    FATAL = 4


@dataclass
class LogEntry:
    timestamp: str
    level: str
    source: str
    message: str
    context: Optional[Dict[str, Any]] = None
    stack_trace: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps({
            "timestamp": self.timestamp,
            "level": self.level,
            "source": self.source,
            "message": self.message,
            "context": self.context,
            "stack_trace": self.stack_trace
        })


class DiagnosticLogger:
    """Rotating file logger with structured JSON output and in-memory buffer for crash telemetry. Max 5MB per file, 3 backups retained."""

    MAX_SIZE = 5 * 1024 * 1024  # 5MB
    MAX_BACKUPS = 3

    def __init__(self, log_dir: str, level: LogLevel = LogLevel.INFO):
        self.log_dir = Path(os.path.expandvars(log_dir))
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.level = level
        self._current_file = self.log_dir / "launcher.log"
        self._buffer: list[LogEntry] = []
        self._buffer_limit = 1000

    def _rotate_if_needed(self):
        """Rotate log files when size threshold exceeded."""
        if not self._current_file.exists():
            return
        if self._current_file.stat().st_size < self.MAX_SIZE:
            return

        for i in range(self.MAX_BACKUPS - 1, 0, -1):
            old = self.log_dir / f"launcher.log.{i}"
            older = self.log_dir / f"launcher.log.{i+1}"
            if old.exists():
                old.replace(older)

        self._current_file.replace(self.log_dir / "launcher.log.1")

    def _write(self, entry: LogEntry):
        """Atomic log write with rotation check."""
        self._rotate_if_needed()
        with open(self._current_file, "a", encoding="utf-8") as f:
            f.write(entry.to_json() + "
")

        self._buffer.append(entry)
        if len(self._buffer) > self._buffer_limit:
            self._buffer = self._buffer[-self._buffer_limit:]

    def log(self, level: LogLevel, source: str, message: str, context: Optional[Dict] = None):
        if level.value < self.level.value:
            return

        entry = LogEntry(
            timestamp=datetime.utcnow().isoformat() + "Z",
            level=level.name,
            source=source,
            message=message,
            context=context
        )
        self._write(entry)

    def debug(self, source: str, message: str, context: Optional[Dict] = None):
        self.log(LogLevel.DEBUG, source, message, context)

    def info(self, source: str, message: str, context: Optional[Dict] = None):
        self.log(LogLevel.INFO, source, message, context)

    def warn(self, source: str, message: str, context: Optional[Dict] = None):
        self.log(LogLevel.WARN, source, message, context)

    def error(self, source: str, message: str, context: Optional[Dict] = None):
        self.log(LogLevel.ERROR, source, message, context)

    def fatal(self, source: str, message: str, exc: Optional[Exception] = None):
        stack = traceback.format_exc() if exc else None
        entry = LogEntry(
            timestamp=datetime.utcnow().isoformat() + "Z",
            level="FATAL",
            source=source,
            message=message,
            stack_trace=stack
        )
        self._write(entry)
        self._flush_telemetry()

    def _flush_telemetry(self):
        """Write buffered logs to crash dump for remote analysis."""
        dump_path = self.log_dir / f"crash_dump_{int(time.time())}.json"
        with open(dump_path, "w", encoding="utf-8") as f:
            json.dump([asdict(e) for e in self._buffer], f, indent=2)

    def get_recent(self, count: int = 50) -> list[LogEntry]:
        """Retrieve recent log entries from memory buffer."""
        return self._buffer[-count:]


class TelemetryCollector:
    """Anonymous usage telemetry with opt-out. Collects performance metrics and update success rates for remote analysis."""

    def __init__(self, endpoint: str, logger: DiagnosticLogger, enabled: bool = True):
        self.endpoint = endpoint
        self.logger = logger
        self.enabled = enabled
        self._session_id = f"session_{int(time.time())}_{os.getpid()}"
        self._metrics: Dict[str, Any] = {}

    def record(self, metric_name: str, value: Any):
        self._metrics[metric_name] = {
            "value": value,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

    def flush(self):
        """Send accumulated metrics to telemetry endpoint."""
        if not self.enabled:
            return

        payload = {
            "session_id": self._session_id,
            "metrics": self._metrics,
            "system": {
                "platform": sys.platform,
                "python_version": sys.version
            }
        }

        try:
            import urllib.request
            req = urllib.request.Request(
                f"{self.endpoint}/telemetry",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            self.logger.debug("Telemetry", f"Flush failed: {e}")
