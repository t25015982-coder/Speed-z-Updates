import sys
import time
from enum import Enum, auto
from typing import Optional, Callable, Any
from dataclasses import dataclass


class ErrorCategory(Enum):
    NETWORK = auto()
    AUTH = auto()
    FILESYSTEM = auto()
    VALIDATION = auto()
    RUNTIME = auto()
    UPDATE = auto()


@dataclass
class ErrorContext:
    category: ErrorCategory
    code: str
    message: str
    recoverable: bool
    retryable: bool
    max_retries: int
    retry_delay_sec: float
    suggested_action: Optional[str] = None


class SpeedZException(Exception):
    """Base exception with structured error context."""

    def __init__(self, context: ErrorContext, original: Optional[Exception] = None):
        self.context = context
        self.original = original
        super().__init__(context.message)

    def __str__(self):
        return f"[{self.context.code}] {self.context.message}"


class NetworkException(SpeedZException):
    """Connection failures with automatic retry logic."""
    pass


class ValidationException(SpeedZException):
    """Data integrity failures—non-recoverable."""
    pass


class FilesystemException(SpeedZException):
    """Disk/permission issues with space-check recovery."""
    pass


class ErrorHandler:
    """Centralized error processing with recovery attempts and user notification."""

    def __init__(self, logger, max_retries: int = 3):
        self.logger = logger
        self.max_retries = max_retries
        self._retry_counts: dict[str, int] = {}
        self._fallback_chain: list[Callable] = []

    def register_fallback(self, handler: Callable):
        self._fallback_chain.append(handler)

    def handle(self, exc: SpeedZException, operation: str) -> Any:
        """Process exception through recovery chain. Returns result if recovered, re-raises if unrecoverable."""
        ctx = exc.context
        self.logger.error("ErrorHandler", 
            f"{operation} failed: {ctx.message}",
            {"code": ctx.code, "recoverable": ctx.recoverable})

        if ctx.retryable:
            key = f"{operation}:{ctx.code}"
            current = self._retry_counts.get(key, 0)

            if current < min(ctx.max_retries, self.max_retries):
                self._retry_counts[key] = current + 1
                self.logger.info("ErrorHandler", 
                    f"Retrying {operation} in {ctx.retry_delay_sec}s (attempt {current + 1})")
                time.sleep(ctx.retry_delay_sec)
                return "RETRY"

        if ctx.recoverable:
            for fallback in self._fallback_chain:
                try:
                    result = fallback(exc)
                    self.logger.info("ErrorHandler", f"Recovered via fallback: {fallback.__name__}")
                    return result
                except Exception as e:
                    continue

        self.logger.fatal("ErrorHandler", f"Unrecoverable error in {operation}", exc)
        raise exc

    def check_disk_space(self, path: str, required_mb: int) -> bool:
        """Pre-flight check for available disk space."""
        try:
            import shutil
            usage = shutil.disk_usage(path)
            available_mb = usage.free // (1024 * 1024)
            return available_mb >= required_mb
        except Exception:
            return False

    def check_process_lock(self, process_name: str) -> bool:
        """Verify target application is not running before update."""
        try:
            import subprocess
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {process_name}"],
                capture_output=True, text=True
            )
            return process_name.lower() in result.stdout.lower()
        except Exception:
            return False

    def sanitize_path(self, path: str) -> str:
        """Prevent path traversal in update packages."""
        import os
        normalized = os.path.normpath(os.path.expandvars(path))
        if ".." in normalized.split(os.sep):
            raise ValidationException(ErrorContext(
                category=ErrorCategory.VALIDATION,
                code="PATH_TRAVERSAL",
                message="Path contains traversal sequences",
                recoverable=False,
                retryable=False,
                max_retries=0,
                retry_delay_sec=0.0
            ))
        return normalized


class GracefulDegradation:
    """Fallback behaviors when full functionality is unavailable."""

    def __init__(self, logger):
        self.logger = logger
        self._offline_mode = False

    def enable_offline_mode(self):
        """Switch to cached manifest and skip network operations."""
        self._offline_mode = True
        self.logger.warn("GracefulDegradation", "Entering offline mode")

    def is_offline(self) -> bool:
        return self._offline_mode

    def get_manifest_fallback(self, cached: Optional[str]) -> Optional[str]:
        """Return cached manifest if available, None otherwise."""
        if self._offline_mode and cached:
            self.logger.info("GracefulDegradation", "Using cached manifest")
            return cached
        return None
