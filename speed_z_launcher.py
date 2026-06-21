import os
import sys
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
import urllib.request
import json

from speed_z_models import (
    VersionManifest, LocalInstallation, UpdatePackage,
    LauncherConfig, UpdateStatus, InstallPhase
)
from speed_z_core import SemanticVersion, UpdateResolver, InstallOrchestrator
from speed_z_config import ConfigManager
from speed_z_io import SecureTransport, DownloadProgress, FileSystemOps
from speed_z_logging import DiagnosticLogger, LogLevel, TelemetryCollector
from speed_z_errors import (
    ErrorHandler, ErrorContext, ErrorCategory,
    SpeedZException, NetworkException, ValidationException,
    GracefulDegradation
)


class CrimsonTheme:
    """Red and gold theme matching the executor aesthetic."""

    BG_PRIMARY = "#0a0a0f"
    BG_SECONDARY = "#12121a"
    BG_TERTIARY = "#1a1a25"
    BG_CARD = "#16161f"
    BG_INPUT = "#0f0f15"

    FG_PRIMARY = "#e8e8e8"
    FG_SECONDARY = "#a0a0b0"
    FG_MUTED = "#555566"

    ACCENT_CRIMSON = "#dc143c"
    ACCENT_CRIMSON_HOVER = "#b01030"
    ACCENT_GOLD = "#ffd700"
    ACCENT_GOLD_DIM = "#c9a227"
    ACCENT_GOLD_MUTED = "#8a7020"

    STATUS_ACTIVE = "#ffd700"      # Gold for active/undetected
    STATUS_WARNING = "#ff4444"     # Red for not running
    STATUS_IDLE = "#555566"      # Gray for neutral

    BORDER_COLOR = "#2a2a3a"
    BORDER_RADIUS = 6

    FONT_TITLE = ("Segoe UI", 24, "bold")
    FONT_HEADER = ("Segoe UI", 12, "bold")
    FONT_BODY = ("Segoe UI", 10)
    FONT_MONO = ("Consolas", 9)
    FONT_BUTTON = ("Segoe UI", 11, "bold")
    FONT_SMALL = ("Segoe UI", 8)
    FONT_TAG = ("Segoe UI", 9, "bold")


class LauncherGUI:
    """SPEED-Z Executor Launcher — Red/Gold theme, no expiry, webhook integration."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("SPEED-Z")
        self.root.geometry("700x580")
        self.root.configure(bg=CrimsonTheme.BG_PRIMARY)
        self.root.resizable(False, False)

        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - (700 // 2)
        y = (self.root.winfo_screenheight() // 2) - (580 // 2)
        self.root.geometry(f"+{x}+{y}")

        self.config_mgr = ConfigManager()
        self.config = self.config_mgr.load_config()
        self.logger = DiagnosticLogger(
            os.path.expandvars(f"{self.config.install_dir}\logs"),
            LogLevel[self.config.log_level.upper()]
        )
        self.transport = SecureTransport(self.config)
        self.resolver = UpdateResolver(self.config)
        self.orchestrator = InstallOrchestrator(self.config)
        self.errors = ErrorHandler(self.logger)
        self.degradation = GracefulDegradation(self.logger)
        self.telemetry = TelemetryCollector(
            self.config.server_endpoint,
            self.logger,
            enabled=True
        )

        self.current_install: Optional[LocalInstallation] = None
        self.remote_manifest: Optional[VersionManifest] = None
        self.download_thread: Optional[threading.Thread] = None
        self._cancelled = False
        self._detected_branch = "unknown"

        self._build_ui()
        self._initialize()

    def _build_ui(self):
        """Construct the executor-style launcher interface."""
        main_frame = tk.Frame(self.root, bg=CrimsonTheme.BG_PRIMARY)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # ===== HEADER: Title + Status Tag =====
        header = tk.Frame(main_frame, bg=CrimsonTheme.BG_PRIMARY)
        header.pack(fill=tk.X, pady=(0, 16))

        title_left = tk.Frame(header, bg=CrimsonTheme.BG_PRIMARY)
        title_left.pack(side=tk.LEFT)

        # Gold accent bar
        gold_bar = tk.Frame(title_left, bg=CrimsonTheme.ACCENT_GOLD, width=3, height=32)
        gold_bar.pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(
            title_left,
            text="SPEED-Z",
            font=CrimsonTheme.FONT_TITLE,
            bg=CrimsonTheme.BG_PRIMARY,
            fg=CrimsonTheme.FG_PRIMARY
        ).pack(side=tk.LEFT)

        # Status tag (Free + Active in gold)
        self.status_tag = tk.Label(
            header,
            text="Free + Active",
            font=CrimsonTheme.FONT_TAG,
            bg=CrimsonTheme.BG_SECONDARY,
            fg=CrimsonTheme.ACCENT_GOLD,
            padx=10,
            pady=3
        )
        self.status_tag.pack(side=tk.RIGHT)

        # Subtitle
        tk.Label(
            main_frame,
            text="Cold coffee, warm LO, let's write. Cozy up and let the scripts run wild.",
            font=CrimsonTheme.FONT_BODY,
            bg=CrimsonTheme.BG_PRIMARY,
            fg=CrimsonTheme.FG_MUTED,
            wraplength=660
        ).pack(anchor=tk.W, pady=(0, 16))

        # ===== STATUS CARD =====
        status_card = tk.Frame(main_frame, bg=CrimsonTheme.BG_CARD, padx=16, pady=12)
        status_card.pack(fill=tk.X, pady=(0, 12))

        status_header = tk.Label(
            status_card,
            text="Status",
            font=CrimsonTheme.FONT_HEADER,
            bg=CrimsonTheme.BG_CARD,
            fg=CrimsonTheme.FG_PRIMARY
        )
        status_header.pack(anchor=tk.W, pady=(0, 8))

        # Status row 1: Status label + value
        row1 = tk.Frame(status_card, bg=CrimsonTheme.BG_CARD)
        row1.pack(fill=tk.X, pady=2)
        tk.Label(row1, text="Status", font=CrimsonTheme.FONT_BODY, 
                bg=CrimsonTheme.BG_CARD, fg=CrimsonTheme.FG_SECONDARY).pack(side=tk.LEFT)
        self.status_value = tk.Label(row1, text="Checking...", font=CrimsonTheme.FONT_BODY,
                                     bg=CrimsonTheme.BG_CARD, fg=CrimsonTheme.ACCENT_GOLD)
        self.status_value.pack(side=tk.RIGHT)

        # Status row 2: Key (no expiry)
        row2 = tk.Frame(status_card, bg=CrimsonTheme.BG_CARD)
        row2.pack(fill=tk.X, pady=2)
        tk.Label(row2, text="Key", font=CrimsonTheme.FONT_BODY,
                bg=CrimsonTheme.BG_CARD, fg=CrimsonTheme.FG_SECONDARY).pack(side=tk.LEFT)
        self.key_value = tk.Label(row2, text="Lifetime", font=CrimsonTheme.FONT_BODY,
                                  bg=CrimsonTheme.BG_CARD, fg=CrimsonTheme.ACCENT_GOLD)
        self.key_value.pack(side=tk.RIGHT)

        # ===== COMPATIBILITY CARD =====
        compat_card = tk.Frame(main_frame, bg=CrimsonTheme.BG_CARD, padx=16, pady=12)
        compat_card.pack(fill=tk.X, pady=(0, 12))

        tk.Label(compat_card, text="Compatibility", font=CrimsonTheme.FONT_HEADER,
                bg=CrimsonTheme.BG_CARD, fg=CrimsonTheme.FG_PRIMARY).pack(anchor=tk.W, pady=(0, 8))

        # speed-z Version row
        row_v = tk.Frame(compat_card, bg=CrimsonTheme.BG_CARD)
        row_v.pack(fill=tk.X, pady=2)
        tk.Label(row_v, text="speed-z Version", font=CrimsonTheme.FONT_BODY,
                bg=CrimsonTheme.BG_CARD, fg=CrimsonTheme.FG_SECONDARY).pack(side=tk.LEFT)
        self.version_display = tk.Label(row_v, text="--", font=CrimsonTheme.FONT_BODY,
                                       bg=CrimsonTheme.BG_CARD, fg=CrimsonTheme.FG_PRIMARY)
        self.version_display.pack(side=tk.RIGHT)

        # Roblox Status row
        row_r = tk.Frame(compat_card, bg=CrimsonTheme.BG_CARD)
        row_r.pack(fill=tk.X, pady=2)
        tk.Label(row_r, text="Roblox Status", font=CrimsonTheme.FONT_BODY,
                bg=CrimsonTheme.BG_CARD, fg=CrimsonTheme.FG_SECONDARY).pack(side=tk.LEFT)
        self.roblox_status = tk.Label(row_r, text="Undetected", font=CrimsonTheme.FONT_BODY,
                                      bg=CrimsonTheme.BG_CARD, fg=CrimsonTheme.ACCENT_GOLD)
        self.roblox_status.pack(side=tk.RIGHT)

        # ===== EXECUTOR TEST RESULTS CARD =====
        test_card = tk.Frame(main_frame, bg=CrimsonTheme.BG_CARD, padx=16, pady=12)
        test_card.pack(fill=tk.X, pady=(0, 12))

        tk.Label(test_card, text="Executor Test Results", font=CrimsonTheme.FONT_HEADER,
                bg=CrimsonTheme.BG_CARD, fg=CrimsonTheme.FG_PRIMARY).pack(anchor=tk.W, pady=(0, 8))

        # Lua Version row
        row_lua = tk.Frame(test_card, bg=CrimsonTheme.BG_CARD)
        row_lua.pack(fill=tk.X, pady=2)
        tk.Label(row_lua, text="Lua Version", font=CrimsonTheme.FONT_BODY,
                bg=CrimsonTheme.BG_CARD, fg=CrimsonTheme.FG_SECONDARY).pack(side=tk.LEFT)
        self.lua_version = tk.Label(row_lua, text="Lua 0.6.0", font=CrimsonTheme.FONT_BODY,
                                    bg=CrimsonTheme.BG_CARD, fg=CrimsonTheme.FG_PRIMARY)
        self.lua_version.pack(side=tk.RIGHT)

        # Injection row
        row_inj = tk.Frame(test_card, bg=CrimsonTheme.BG_CARD)
        row_inj.pack(fill=tk.X, pady=2)
        tk.Label(row_inj, text="Injection", font=CrimsonTheme.FONT_BODY,
                bg=CrimsonTheme.BG_CARD, fg=CrimsonTheme.FG_SECONDARY).pack(side=tk.LEFT)
        self.injection_status = tk.Label(row_inj, text="Not Running", font=CrimsonTheme.FONT_BODY,
                                         bg=CrimsonTheme.BG_CARD, fg=CrimsonTheme.STATUS_WARNING)
        self.injection_status.pack(side=tk.RIGHT)

        # ===== PROGRESS BAR =====
        progress_frame = tk.Frame(main_frame, bg=CrimsonTheme.BG_PRIMARY)
        progress_frame.pack(fill=tk.X, pady=(0, 8))

        self.progress_label = tk.Label(progress_frame, text="Ready", font=CrimsonTheme.FONT_MONO,
                                       bg=CrimsonTheme.BG_PRIMARY, fg=CrimsonTheme.FG_MUTED)
        self.progress_label.pack(side=tk.LEFT)

        self.progress_percent = tk.Label(progress_frame, text="0%", font=CrimsonTheme.FONT_MONO,
                                         bg=CrimsonTheme.BG_PRIMARY, fg=CrimsonTheme.FG_SECONDARY)
        self.progress_percent.pack(side=tk.RIGHT)

        self.progress_container = tk.Frame(main_frame, bg=CrimsonTheme.BG_TERTIARY, height=4)
        self.progress_container.pack(fill=tk.X, pady=(0, 16))
        self.progress_container.pack_propagate(False)

        self.progress_fill = tk.Frame(self.progress_container, bg=CrimsonTheme.ACCENT_CRIMSON, width=0)
        self.progress_fill.place(x=0, y=0, relheight=1.0)

        # ===== BUTTONS ROW =====
        btn_frame = tk.Frame(main_frame, bg=CrimsonTheme.BG_PRIMARY)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)

        # INJECT NOW button (crimson, full width primary)
        self.inject_btn = tk.Button(
            btn_frame,
            text="Inject Now",
            font=CrimsonTheme.FONT_BUTTON,
            bg=CrimsonTheme.ACCENT_CRIMSON,
            fg="white",
            activebackground=CrimsonTheme.ACCENT_CRIMSON_HOVER,
            activeforeground="white",
            bd=0,
            padx=32,
            pady=14,
            cursor="hand2",
            command=self._on_launch,
            state=tk.DISABLED
        )
        self.inject_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        # UPDATE button (gold outline)
        self.update_btn = tk.Button(
            btn_frame,
            text="Update",
            font=CrimsonTheme.FONT_BUTTON,
            bg=CrimsonTheme.BG_TERTIARY,
            fg=CrimsonTheme.ACCENT_GOLD,
            activebackground=CrimsonTheme.BG_SECONDARY,
            activeforeground=CrimsonTheme.ACCENT_GOLD_DIM,
            bd=1,
            highlightbackground=CrimsonTheme.ACCENT_GOLD_MUTED,
            highlightcolor=CrimsonTheme.ACCENT_GOLD,
            padx=20,
            pady=14,
            cursor="hand2",
            command=self._on_update,
            state=tk.DISABLED
        )
        self.update_btn.pack(side=tk.LEFT, padx=(0, 8))

        # CHANGELOG button (dark)
        self.changelog_btn = tk.Button(
            btn_frame,
            text="Changelog",
            font=CrimsonTheme.FONT_BODY,
            bg=CrimsonTheme.BG_TERTIARY,
            fg=CrimsonTheme.FG_SECONDARY,
            activebackground=CrimsonTheme.BG_SECONDARY,
            bd=0,
            padx=16,
            pady=14,
            cursor="hand2",
            command=self._on_changelog
        )
        self.changelog_btn.pack(side=tk.RIGHT)

        # Footer
        footer = tk.Label(
            main_frame,
            text="SPEED-Z Executor  |  Build 1.0.7  |  Secure Update Channel",
            font=CrimsonTheme.FONT_SMALL,
            bg=CrimsonTheme.BG_PRIMARY,
            fg=CrimsonTheme.FG_MUTED
        )
        footer.pack(side=tk.BOTTOM, pady=(8, 0))

    def _initialize(self):
        """Detect installation and check for updates."""
        self.current_install = self.config_mgr.load_installation()

        if self.current_install:
            self._detect_branch(self.current_install.installed_version)
            self.version_display.config(text=self.current_install.installed_version)
            self.status_value.config(text="Installed", fg=CrimsonTheme.ACCENT_GOLD)
            self.logger.info("Launcher", f"Detected {self._detected_branch} branch, v{self.current_install.installed_version}")
            self._check_updates_async()
        else:
            self.version_display.config(text="Not Installed")
            self.status_value.config(text="Not Installed", fg=CrimsonTheme.STATUS_WARNING)
            self.update_btn.config(state=tk.NORMAL, text="Install")
            self.logger.info("Launcher", "No existing installation found")

    def _detect_branch(self, version: str):
        """Determine if this is the 2.x or 1.x branch."""
        major = int(version.split(".")[0]) if version[0].isdigit() else 0
        if major >= 2:
            self._detected_branch = "2.x"
        else:
            self._detected_branch = "1.x"

    def _check_updates_async(self):
        """Spawn background thread for version check."""
        def check():
            try:
                manifest_json = self.transport.fetch_manifest()
                if not manifest_json:
                    cached = self.config_mgr.load_cached_manifest()
                    if cached:
                        self.degradation.enable_offline_mode()
                        manifest_json = cached
                    else:
                        self.root.after(0, lambda: self._set_status(
                            "Update server unreachable",
                            enable_launch=True
                        ))
                        return

                self.config_mgr.cache_manifest(manifest_json)
                self.remote_manifest = VersionManifest.from_json(manifest_json)

                status, manifest = self.resolver.check(self.current_install, self.remote_manifest)

                if status == UpdateStatus.CURRENT:
                    self.root.after(0, lambda: self._set_status(
                        "Latest version installed",
                        enable_launch=True
                    ))
                elif status == UpdateStatus.AVAILABLE:
                    self.root.after(0, lambda: self._set_status(
                        f"Update v{manifest.version} available",
                        enable_launch=False,
                        enable_update=True
                    ))
                elif status == UpdateStatus.MANDATORY:
                    self.root.after(0, lambda: self._set_status(
                        f"Required update: v{manifest.version}",
                        enable_launch=False,
                        enable_update=True
                    ))
                else:
                    self.root.after(0, lambda: self._set_status(
                        "Update check failed",
                        enable_launch=True
                    ))

            except Exception as e:
                self.logger.error("UpdateCheck", str(e))
                self.root.after(0, lambda: self._set_status(
                    "Update check failed",
                    enable_launch=True
                ))

        threading.Thread(target=check, daemon=True).start()

    def _set_status(self, text: str, enable_launch=False, enable_update=False):
        """Thread-safe status update."""
        self.status_value.config(text=text)
        if enable_launch:
            self.inject_btn.config(state=tk.NORMAL)
        if enable_update:
            self.update_btn.config(state=tk.NORMAL)

    def _set_progress(self, percent: float, label: str = ""):
        """Update progress bar and label."""
        self.progress_fill.place_configure(relwidth=percent / 100.0)
        self.progress_percent.config(text=f"{percent:.0f}%")
        if label:
            self.progress_label.config(text=label)

    def _on_update(self):
        """Initiate download and installation."""
        if not self.remote_manifest:
            self.status_value.config(text="No update available")
            return

        self._cancelled = False
        self.update_btn.config(state=tk.DISABLED)
        self.inject_btn.config(state=tk.DISABLED)
        self._set_progress(0.0, "Starting...")

        self.orchestrator.register_progress(self._on_install_progress)

        def do_update():
            try:
                if FileSystemOps.is_process_running("RobloxPlayerBeta.exe"):
                    self.root.after(0, lambda: self.status_value.config(
                        text="Close Roblox before updating", fg=CrimsonTheme.STATUS_WARNING
                    ))
                    self.root.after(0, lambda: self.update_btn.config(state=tk.NORMAL))
                    return

                dest = os.path.expandvars(f"{self.config.temp_dir}\update_{self.remote_manifest.build_number}.zip")
                self.root.after(0, lambda: self._set_progress(0.0, "Downloading..."))

                success = self.transport.fetch_package(
                    self.remote_manifest.download_url,
                    dest,
                    progress_cb=self._on_download_progress,
                    resume=True
                )

                if self._cancelled:
                    self.root.after(0, self._reset_ui)
                    return

                if not success:
                    raise NetworkException(ErrorContext(
                        category=ErrorCategory.NETWORK,
                        code="DOWNLOAD_FAILED",
                        message="Failed to download update",
                        recoverable=True,
                        retryable=True,
                        max_retries=3,
                        retry_delay_sec=2.0
                    ))

                package = UpdatePackage(
                    manifest=self.remote_manifest,
                    local_path=dest
                )

                install_dir = self.config_mgr.get_install_dir()
                result = self.orchestrator.execute(package, install_dir)

                if result:
                    # VERSION BUMP
                    new_version = self.remote_manifest.version
                    new_install = LocalInstallation(
                        installed_version=new_version,
                        install_path=install_dir,
                        install_date=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        launch_count=0,
                        config=self.current_install.config if self.current_install else {}
                    )
                    self.config_mgr.save_installation(new_install)
                    self.current_install = new_install
                    self._detect_branch(new_version)

                    # Send webhook notification
                    self._send_changelog_webhook(new_version, self.remote_manifest.release_notes)

                    self.telemetry.record("update_success", True)
                    self.telemetry.record("updated_to_version", new_version)

                    self.root.after(0, lambda: self._set_status(
                        f"Updated to v{new_version}",
                        enable_launch=True
                    ))
                    self.root.after(0, lambda: self.version_display.config(text=new_version))
                else:
                    self.root.after(0, lambda: self._set_status(
                        "Installation failed — rollback completed",
                        enable_launch=True
                    ))

            except Exception as e:
                self.logger.error("Update", str(e))
                self.root.after(0, lambda: self.status_value.config(
                    text=f"Update failed: {str(e)}", fg=CrimsonTheme.STATUS_WARNING
                ))
            finally:
                self.root.after(0, lambda: self.update_btn.config(
                    state=tk.NORMAL,
                    text="Update" if self.current_install else "Install"
                ))

        self.download_thread = threading.Thread(target=do_update, daemon=True)
        self.download_thread.start()

    def _on_download_progress(self, progress: DownloadProgress):
        """Download progress callback."""
        if self._cancelled:
            return
        pct = min(progress.percent, 50.0)
        self.root.after(0, lambda: self._set_progress(
            pct,
            f"Downloading: {progress.speed_bps/1024:.0f} KB/s"
        ))

    def _on_install_progress(self, phase: InstallPhase, percent: float, message: str):
        """Installation progress callback."""
        if self._cancelled:
            return
        adjusted = 50.0 + (percent / 2.0)
        self.root.after(0, lambda: self._set_progress(adjusted, message))

    def _on_launch(self):
        """Launch the executor."""
        if not self.current_install:
            return

        install_path = Path(self.current_install.install_path)
        exe_path = install_path / "SPEED-Z.exe"

        if not exe_path.exists():
            self.status_value.config(text="Executable not found. Reinstall required.",
                                     fg=CrimsonTheme.STATUS_WARNING)
            self.update_btn.config(text="Reinstall", state=tk.NORMAL)
            return

        self.current_install.bump_launch()
        self.config_mgr.save_installation(self.current_install)
        self.telemetry.record("launch", True)
        self.telemetry.flush()

        try:
            self.injection_status.config(text="Injecting...", fg=CrimsonTheme.ACCENT_GOLD)
            subprocess.Popen(
                [str(exe_path)],
                cwd=str(install_path),
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
            self.injection_status.config(text="Active", fg=CrimsonTheme.ACCENT_GOLD)
        except Exception as e:
            self.logger.error("Launch", str(e))
            self.injection_status.config(text="Failed", fg=CrimsonTheme.STATUS_WARNING)

    def _on_changelog(self):
        """Open changelog or show release notes."""
        if self.remote_manifest and self.remote_manifest.release_notes:
            message = f"SPEED-Z Changelog\n\nVersion: {self.remote_manifest.version}\n\n{self.remote_manifest.release_notes}"
        else:
            message = "SPEED-Z Changelog\n\nNo release notes available."

        # Simple popup instead of browser
        popup = tk.Toplevel(self.root)
        popup.title("Changelog")
        popup.geometry("500x400")
        popup.configure(bg=CrimsonTheme.BG_PRIMARY)
        popup.transient(self.root)
        popup.grab_set()

        tk.Label(popup, text="CHANGELOG", font=CrimsonTheme.FONT_TITLE,
                bg=CrimsonTheme.BG_PRIMARY, fg=CrimsonTheme.ACCENT_GOLD).pack(pady=16)

        text = tk.Text(popup, bg=CrimsonTheme.BG_CARD, fg=CrimsonTheme.FG_PRIMARY,
                      font=CrimsonTheme.FONT_BODY, padx=16, pady=16, wrap=tk.WORD)
        text.pack(fill=tk.BOTH, expand=True, padx=16, pady=8)
        text.insert(tk.END, message)
        text.config(state=tk.DISABLED)

        tk.Button(popup, text="Close", command=popup.destroy,
                 bg=CrimsonTheme.ACCENT_CRIMSON, fg="white",
                 font=CrimsonTheme.FONT_BUTTON, bd=0, padx=24, pady=8).pack(pady=16)

    def _send_changelog_webhook(self, version: str, release_notes: str):
        """Send changelog update to Discord webhook."""
        webhook_url = self.config.webhook_url
        if not webhook_url:
            return

        embed = {
            "title": f"SPEED-Z v{version} Released",
            "description": release_notes or "No release notes provided.",
            "color": 16711680,  # Red
            "fields": [
                {
                    "name": "Version",
                    "value": version,
                    "inline": True
                },
                {
                    "name": "Status",
                    "value": "Available for download",
                    "inline": True
                }
            ],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "footer": {
                "text": "SPEED-Z Update Channel"
            }
        }

        payload = {
            "content": f"@everyone **SPEED-Z v{version}** is now available!",
            "embeds": [embed],
            "username": "SPEED-Z Updates",
            "avatar_url": "https://cdn.discordapp.com/embed/avatars/0.png"
        }

        try:
            req = urllib.request.Request(
                webhook_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            self.logger.debug("Webhook", f"Failed to send: {e}")

    def _on_cancel(self):
        """Cancel ongoing operations."""
        self._cancelled = True
        self.status_value.config(text="Cancelled")
        self._reset_ui()

    def _reset_ui(self):
        """Restore UI to idle state."""
        self._set_progress(0.0, "Ready")
        self.update_btn.config(state=tk.NORMAL)
        if self.current_install:
            self.inject_btn.config(state=tk.NORMAL)

    def run(self):
        self.root.mainloop()


def main():
    try:
        app = LauncherGUI()
        app.run()
    except Exception as e:
        crash_dir = Path(os.path.expandvars("%LOCALAPPDATA%\SPEED-Z\logs"))
        crash_dir.mkdir(parents=True, exist_ok=True)
        with open(crash_dir / f"crash_{int(time.time())}.txt", "w") as f:
            import traceback
            f.write(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
