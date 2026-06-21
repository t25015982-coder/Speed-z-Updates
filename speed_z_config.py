import os
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any

from speed_z_models import LauncherConfig, LocalInstallation


class ConfigManager:
    """Handles all persistent state: launcher config, installation records, and cached remote manifests. Thread-safe file operations."""

    CONFIG_FILENAME = "launcher_config.json"
    INSTALL_RECORD_FILENAME = "installation.json"
    MANIFEST_CACHE_FILENAME = "cached_manifest.json"
    LOCK_FILENAME = ".config_lock"

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = Path(os.path.expandvars(base_dir or "%LOCALAPPDATA%\SPEED-Z"))
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._config_path = self.base_dir / self.CONFIG_FILENAME
        self._install_path = self.base_dir / self.INSTALL_RECORD_FILENAME
        self._manifest_cache = self.base_dir / self.MANIFEST_CACHE_FILENAME
        self._lock_path = self.base_dir / self.LOCK_FILENAME

    def _acquire_lock(self) -> bool:
        """Simple file-based lock. Returns False if locked by another process."""
        if self._lock_path.exists():
            try:
                mtime = self._lock_path.stat().st_mtime
                if time.time() - mtime > 30:
                    self._lock_path.unlink()
                else:
                    return False
            except OSError:
                return False
        self._lock_path.touch()
        return True

    def _release_lock(self):
        try:
            if self._lock_path.exists():
                self._lock_path.unlink()
        except OSError:
            pass

    def load_config(self) -> LauncherConfig:
        """Load or create default launcher configuration."""
        if self._config_path.exists():
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    return LauncherConfig.from_json(f.read())
            except (json.JSONDecodeError, TypeError):
                pass

        default = LauncherConfig()
        self.save_config(default)
        return default

    def save_config(self, config: LauncherConfig) -> bool:
        """Atomic write of configuration to disk."""
        if not self._acquire_lock():
            return False
        try:
            temp_path = self._config_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(config.to_json())
            temp_path.replace(self._config_path)
            return True
        finally:
            self._release_lock()

    def load_installation(self) -> Optional[LocalInstallation]:
        """Load current installation record if it exists."""
        if not self._install_path.exists():
            return None
        try:
            with open(self._install_path, "r", encoding="utf-8") as f:
                return LocalInstallation.from_json(f.read())
        except (json.JSONDecodeError, TypeError):
            return None

    def save_installation(self, install: LocalInstallation) -> bool:
        """Persist installation state."""
        if not self._acquire_lock():
            return False
        try:
            temp_path = self._install_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(install.to_json())
            temp_path.replace(self._install_path)
            return True
        finally:
            self._release_lock()

    def cache_manifest(self, manifest_json: str) -> bool:
        """Cache remote manifest for offline reference."""
        try:
            with open(self._manifest_cache, "w", encoding="utf-8") as f:
                f.write(manifest_json)
            return True
        except OSError:
            return False

    def load_cached_manifest(self) -> Optional[str]:
        """Retrieve cached manifest if available."""
        if not self._manifest_cache.exists():
            return None
        try:
            with open(self._manifest_cache, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    def get_install_dir(self) -> str:
        """Resolved installation directory with env expansion."""
        config = self.load_config()
        return os.path.expandvars(config.install_dir)

    def initialize_first_install(self, version: str, path: str) -> LocalInstallation:
        """Create initial installation record."""
        install = LocalInstallation(
            installed_version=version,
            install_path=path,
            install_date=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            launch_count=0,
            config={}
        )
        self.save_installation(install)
        return install
