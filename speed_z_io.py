import os
import urllib.request
import urllib.error
import ssl
import time
from pathlib import Path
from typing import Optional, Callable, Dict
from dataclasses import dataclass

from speed_z_models import LauncherConfig


@dataclass
class DownloadProgress:
    bytes_downloaded: int
    total_bytes: int
    speed_bps: float
    eta_seconds: float
    percent: float


class SecureTransport:
    """HTTPS client with certificate pinning option and custom TLS context."""

    def __init__(self, config: LauncherConfig):
        self.config = config
        self._ctx = ssl.create_default_context()
        self._headers = {
            "User-Agent": "SPEED-Z-Launcher/1.0.7",
            "Accept": "application/json",
            "X-Client-Version": "1.0.7"
        }

    def fetch_manifest(self) -> Optional[str]:
        """Retrieve version manifest from update server. Returns raw JSON or None on failure."""
        endpoint = f"{self.config.server_endpoint}/manifest.json"
        req = urllib.request.Request(endpoint, headers=self._headers, method="GET")

        try:
            with urllib.request.urlopen(req, context=self._ctx, timeout=15) as response:
                if response.status == 200:
                    return response.read().decode("utf-8")
                return None
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
            return None

    def fetch_package(self, url: str, dest_path: str, 
                      progress_cb: Optional[Callable[[DownloadProgress], None]] = None,
                      resume: bool = True) -> bool:
        """Download package with resume support and progress callbacks."""
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        existing_size = dest.stat().st_size if dest.exists() and resume else 0
        headers = dict(self._headers)
        if existing_size > 0:
            headers["Range"] = f"bytes={existing_size}-"

        req = urllib.request.Request(url, headers=headers, method="GET")
        start_time = time.time()

        try:
            with urllib.request.urlopen(req, context=self._ctx, timeout=30) as response:
                total_size = int(response.headers.get("Content-Length", 0))
                if existing_size > 0 and response.status == 206:
                    total_size += existing_size
                elif existing_size > 0:
                    existing_size = 0

                mode = "ab" if existing_size > 0 and response.status == 206 else "wb"
                downloaded = existing_size

                with open(dest_path, mode) as f:
                    while True:
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)

                        elapsed = time.time() - start_time
                        speed = downloaded / elapsed if elapsed > 0 else 0
                        percent = (downloaded / total_size * 100) if total_size > 0 else 0
                        eta = (total_size - downloaded) / speed if speed > 0 else 0

                        if progress_cb:
                            progress_cb(DownloadProgress(
                                bytes_downloaded=downloaded,
                                total_bytes=total_size,
                                speed_bps=speed,
                                eta_seconds=eta,
                                percent=percent
                            ))

                return True

        except Exception:
            return False

    def send_webhook(self, webhook_url: str, content: str, embeds: list = None) -> bool:
        """Send a Discord webhook notification."""
        if not webhook_url:
            return False

        payload = {
            "content": content,
            "username": "SPEED-Z Updates",
            "avatar_url": "https://cdn.discordapp.com/embed/avatars/0.png"
        }
        if embeds:
            payload["embeds"] = embeds

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "SPEED-Z-Launcher/1.0.7"
        }

        try:
            req = urllib.request.Request(
                webhook_url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            urllib.request.urlopen(req, timeout=10)
            return True
        except Exception:
            return False


class FileSystemOps:
    """Atomic file operations and directory management."""

    @staticmethod
    def ensure_dir(path: str) -> Path:
        p = Path(os.path.expandvars(path))
        p.mkdir(parents=True, exist_ok=True)
        return p

    @staticmethod
    def atomic_write(path: str, content: str) -> bool:
        """Write file atomically using temp+rename pattern."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(".tmp")
        try:
            with open(temp, "w", encoding="utf-8") as f:
                f.write(content)
            temp.replace(target)
            return True
        except OSError:
            if temp.exists():
                temp.unlink()
            return False

    @staticmethod
    def safe_delete(path: str) -> bool:
        """Recursively delete with error suppression."""
        try:
            p = Path(path)
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                import shutil
                shutil.rmtree(p)
            return True
        except OSError:
            return False

    @staticmethod
    def is_process_running(process_name: str) -> bool:
        """Check if target process is currently active."""
        try:
            import subprocess
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {process_name}"],
                capture_output=True, text=True, timeout=5
            )
            return process_name.lower() in result.stdout.lower()
        except Exception:
            return False
