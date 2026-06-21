from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Callable
from enum import Enum, auto
import json
import hashlib
import time


class UpdateStatus(Enum):
    CURRENT = auto()
    AVAILABLE = auto()
    MANDATORY = auto()
    FAILED = auto()
    OFFLINE = auto()


class InstallPhase(Enum):
    PENDING = auto()
    DOWNLOADING = auto()
    VERIFYING = auto()
    EXTRACTING = auto()
    REPLACING = auto()
    CLEANUP = auto()
    COMPLETE = auto()
    ROLLBACK = auto()


@dataclass
class VersionManifest:
    """Canonical version descriptor from update server."""
    version: str
    build_number: int
    release_date: str
    download_url: str
    checksum_sha256: str
    file_size_bytes: int
    min_launcher_version: str
    release_notes: str = ""
    is_mandatory: bool = False
    delta_patches: List[Dict] = field(default_factory=list)
    changelog_url: str = ""  # Discord webhook or changelog link

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "VersionManifest":
        data = json.loads(raw)
        return cls(**data)

    def __hash__(self) -> int:
        return hash((self.version, self.build_number, self.checksum_sha256))


@dataclass
class LocalInstallation:
    """Current state of the SPEED-Z installation on this host."""
    installed_version: str
    install_path: str
    install_date: str
    last_launch: Optional[str] = None
    launch_count: int = 0
    config: Dict = field(default_factory=dict)
    key_expires: str = "9999-02-12T00:00:00Z"  # Never expires

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "LocalInstallation":
        data = json.loads(raw)
        return cls(**data)

    def bump_launch(self):
        self.launch_count += 1
        self.last_launch = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def is_key_valid(self) -> bool:
        """Key never expires. Always returns True."""
        return True


@dataclass
class UpdatePackage:
    """Downloaded update payload with verification metadata."""
    manifest: VersionManifest
    local_path: str
    verified_checksum: bool = False
    download_timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def verify(self) -> bool:
        """SHA-256 verification against manifest."""
        hasher = hashlib.sha256()
        try:
            with open(self.local_path, "rb") as f:
                while chunk := f.read(8192):
                    hasher.update(chunk)
            self.verified_checksum = hasher.hexdigest().lower() == self.manifest.checksum_sha256.lower()
            return self.verified_checksum
        except Exception:
            self.verified_checksum = False
            return False


@dataclass
class LauncherConfig:
    """Runtime configuration for the launcher itself."""
    app_name: str = "SPEED-Z"
    server_endpoint: str = "https://t25015982-coder.github.io/Speed-z-Updates"
    check_interval_hours: int = 24
    auto_update: bool = True
    backup_before_update: bool = True
    max_download_retries: int = 3
    temp_dir: str = "%LOCALAPPDATA%\SPEED-Z\temp"
    install_dir: str = "%LOCALAPPDATA%\SPEED-Z"
    log_level: str = "INFO"
    theme: str = "crimson"  # red/gold theme preset
    webhook_url: str = "https://discord.com/api/webhooks/1518038577681006602/_Exf6rfuf7Ylrq0G13y-t4dpo4dqSm81AAXCbix-wP-0wI8cId-fB-8-Lo-2uPINzp9t"

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "LauncherConfig":
        data = json.loads(raw)
        return cls(**data)
