import os
import sys
import shutil
import zipfile
import tempfile
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Tuple, Callable
from dataclasses import asdict

from speed_z_models import (
    VersionManifest, LocalInstallation, UpdatePackage,
    LauncherConfig, UpdateStatus, InstallPhase
)


class SemanticVersion:
    """Three-segment version parser with build number support."""

    def __init__(self, version_string: str):
        self.raw = version_string.strip()
        parts = self.raw.replace("-", ".").replace("_", ".").split(".")
        self.major = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 0
        self.minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        self.patch = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        self.build = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0

    def __eq__(self, other: "SemanticVersion") -> bool:
        return (self.major, self.minor, self.patch, self.build) == (other.major, other.minor, other.patch, other.build)

    def __lt__(self, other: "SemanticVersion") -> bool:
        return (self.major, self.minor, self.patch, self.build) < (other.major, other.minor, other.patch, other.build)

    def __gt__(self, other: "SemanticVersion") -> bool:
        return other < self

    def __le__(self, other: "SemanticVersion") -> bool:
        return self == other or self < other

    def __ge__(self, other: "SemanticVersion") -> bool:
        return self == other or self > other

    def __repr__(self) -> str:
        return f"SemanticVersion({self.raw})"


class UpdateResolver:
    """Determines update necessity and selects optimal delivery mechanism."""

    def __init__(self, config: LauncherConfig):
        self.config = config
        self._current_manifest: Optional[VersionManifest] = None

    def check(self, local: LocalInstallation, remote_manifest: VersionManifest) -> Tuple[UpdateStatus, Optional[VersionManifest]]:
        """Compare local vs remote. Returns status and manifest if update needed."""
        local_ver = SemanticVersion(local.installed_version)
        remote_ver = SemanticVersion(remote_manifest.version)

        if remote_ver <= local_ver:
            return UpdateStatus.CURRENT, None

        min_launcher = SemanticVersion(remote_manifest.min_launcher_version)
        launcher_ver = SemanticVersion("1.0.7")
        if launcher_ver < min_launcher:
            return UpdateStatus.FAILED, None

        status = UpdateStatus.MANDATORY if remote_manifest.is_mandatory else UpdateStatus.AVAILABLE
        return status, remote_manifest

    def select_delivery_method(self, local: LocalInstallation, manifest: VersionManifest) -> str:
        """Choose between full package or delta patch based on gap analysis."""
        local_build = SemanticVersion(local.installed_version).build
        target_build = manifest.build_number

        for patch in manifest.delta_patches:
            if patch.get("from_build") == local_build and patch.get("to_build") == target_build:
                return "delta"

        return "full"


class InstallOrchestrator:
    """Atomic update installation with rollback capability."""

    def __init__(self, config: LauncherConfig):
        self.config = config
        self.phase: InstallPhase = InstallPhase.PENDING
        self._backup_path: Optional[str] = None
        self._progress_callback: Optional[Callable[[InstallPhase, float, str], None]] = None

    def register_progress(self, callback: Callable[[InstallPhase, float, str], None]):
        self._progress_callback = callback

    def _notify(self, phase: InstallPhase, percent: float, message: str):
        self.phase = phase
        if self._progress_callback:
            self._progress_callback(phase, percent, message)

    def execute(self, package: UpdatePackage, install_dir: str) -> bool:
        """Full installation pipeline: backup, verify, extract, replace, cleanup. Returns True on success, triggers rollback on failure."""
        install_path = Path(os.path.expandvars(install_dir))
        temp_path = Path(os.path.expandvars(self.config.temp_dir))
        temp_path.mkdir(parents=True, exist_ok=True)

        try:
            if self.config.backup_before_update:
                self._notify(InstallPhase.PENDING, 0.0, "Creating backup...")
                self._backup_path = self._create_backup(install_path)

            self._notify(InstallPhase.VERIFYING, 10.0, "Verifying package integrity...")
            if not package.verify():
                raise RuntimeError("Package checksum verification failed")

            self._notify(InstallPhase.EXTRACTING, 20.0, "Extracting update package...")
            extract_dir = temp_path / f"extract_{package.manifest.build_number}"
            self._extract_package(package.local_path, extract_dir)

            self._notify(InstallPhase.REPLACING, 60.0, "Installing new files...")
            self._atomic_replace(install_path, extract_dir)

            self._notify(InstallPhase.CLEANUP, 90.0, "Cleaning temporary files...")
            self._cleanup(temp_path, extract_dir)

            self._notify(InstallPhase.COMPLETE, 100.0, "Installation complete")
            return True

        except Exception as e:
            self._notify(InstallPhase.ROLLBACK, 0.0, f"Installation failed: {e}. Rolling back...")
            self._rollback(install_path)
            return False

    def _create_backup(self, install_path: Path) -> str:
        """Snapshot current installation to temp directory."""
        backup_dir = Path(os.path.expandvars(self.config.temp_dir)) / f"backup_{int(time.time())}"
        if install_path.exists():
            shutil.copytree(install_path, backup_dir, dirs_exist_ok=True)
        return str(backup_dir)

    def _extract_package(self, package_path: str, extract_dir: Path):
        """Extract ZIP payload to staging directory."""
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(package_path, 'r') as zf:
            zf.extractall(extract_dir)

    def _atomic_replace(self, install_path: Path, extract_dir: Path):
        """Replace installation files atomically using staging. Uses rename operations where possible for atomicity."""
        if not install_path.exists():
            extract_dir.rename(install_path)
            return

        staging = install_path.parent / f"{install_path.name}_staging"
        if staging.exists():
            shutil.rmtree(staging)

        extract_dir.rename(staging)

        old_backup = install_path.parent / f"{install_path.name}_old"
        if old_backup.exists():
            shutil.rmtree(old_backup)

        install_path.rename(old_backup)
        staging.rename(install_path)
        shutil.rmtree(old_backup)

    def _cleanup(self, temp_path: Path, extract_dir: Path):
        """Remove temporary extraction and download artifacts."""
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        backup_dirs = sorted(
            [d for d in temp_path.iterdir() if d.name.startswith("backup_")],
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        for old_backup in backup_dirs[3:]:
            shutil.rmtree(old_backup)

    def _rollback(self, install_path: Path):
        """Restore from backup on failure."""
        if self._backup_path and Path(self._backup_path).exists():
            if install_path.exists():
                shutil.rmtree(install_path)
            shutil.copytree(self._backup_path, install_path, dirs_exist_ok=True)
