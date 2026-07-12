"""
steam_manager.py

Handles:
- Downloading & bootstrapping SteamCMD into Documents/PalworldServerManager/steamcmd
- Installing / validating / updating the Palworld Dedicated Server (App ID 2394010)
- Reading the installed build id so the app can tell whether an update actually happened
- Starting / stopping the PalServer.exe process
"""

import os
import re
import sys
import zipfile
import subprocess
import platform
import threading
from pathlib import Path

import requests

PALWORLD_APP_ID = "2394010"

# Try each of these in order -- akamaihd.net is occasionally blocked by
# ISPs/firewalls/AV, so we fall back to Valve's other mirror.
STEAMCMD_WIN_URLS = [
    "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip",
    "https://media.steampowered.com/installer/steamcmd.zip",
]
STEAMCMD_LINUX_URLS = [
    "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz",
    "https://media.steampowered.com/installer/steamcmd_linux.tar.gz",
]

MAX_INSTALL_ATTEMPTS = 3


def get_base_dir() -> Path:
    """Documents/PalworldServerManager -- created on first run."""
    docs = Path(os.path.expanduser("~")) / "Documents"
    if not docs.exists():
        # Fallback for non-Windows systems without a Documents folder
        docs = Path(os.path.expanduser("~"))
    base = docs / "PalworldServerManager"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_server_dir_for_profile(profile_name: str) -> Path:
    """
    'Default' keeps the original (pre-multi-profile) path for backward
    compatibility with existing installs. Any other profile gets its own
    folder under profiles/<name>/server.
    """
    base = get_base_dir()
    if profile_name == "Default":
        return base / "server"
    return base / "profiles" / profile_name / "server"


class SteamManager:
    def __init__(self, log_callback=None, profile_name="Default"):
        self.is_windows = platform.system() == "Windows"
        self.profile_name = profile_name
        self.base_dir = get_base_dir()
        # SteamCMD itself is shared across all profiles -- only the
        # install target (force_install_dir) differs per profile.
        self.steamcmd_dir = self.base_dir / "steamcmd"
        self.server_dir = get_server_dir_for_profile(profile_name)
        self.steamcmd_dir.mkdir(parents=True, exist_ok=True)
        self.server_dir.mkdir(parents=True, exist_ok=True)
        self._log = log_callback or (lambda msg: None)

    # ------------------------------------------------------------------ #
    # SteamCMD bootstrap
    # ------------------------------------------------------------------ #
    def steamcmd_exe_path(self) -> Path:
        if self.is_windows:
            return self.steamcmd_dir / "steamcmd.exe"
        return self.steamcmd_dir / "steamcmd.sh"

    def ensure_steamcmd(self):
        exe = self.steamcmd_exe_path()
        if exe.exists():
            self._log(f"SteamCMD already present at {exe}")
            return

        self._log("SteamCMD not found. Downloading...")
        if self.is_windows:
            archive_path = self.steamcmd_dir / "steamcmd.zip"
            self._download_with_fallback(STEAMCMD_WIN_URLS, archive_path)
            self._log("Extracting SteamCMD...")
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(self.steamcmd_dir)
            archive_path.unlink(missing_ok=True)
        else:
            import tarfile
            archive_path = self.steamcmd_dir / "steamcmd_linux.tar.gz"
            self._download_with_fallback(STEAMCMD_LINUX_URLS, archive_path)
            self._log("Extracting SteamCMD...")
            with tarfile.open(archive_path, "r:gz") as tf:
                tf.extractall(self.steamcmd_dir)
            archive_path.unlink(missing_ok=True)
            os.chmod(self.steamcmd_exe_path(), 0o755)

        self._log("SteamCMD ready.")

    def _download_with_fallback(self, urls, dest: Path):
        last_error = None
        for i, url in enumerate(urls):
            try:
                self._log(f"  trying source {i + 1}/{len(urls)}: {url}")
                self._download(url, dest)
                return
            except Exception as e:
                last_error = e
                self._log(f"  source failed ({e}), trying next mirror...")
        raise RuntimeError(
            f"Could not download SteamCMD from any mirror. Last error: {last_error}"
        )

    def _download(self, url: str, dest: Path):
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            written = 0
            last_pct = -1
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        written += len(chunk)
                        if total:
                            pct = int(written * 100 / total)
                            if pct != last_pct and pct % 10 == 0:
                                self._log(f"  download: {pct}%")
                                last_pct = pct
        if dest.stat().st_size == 0:
            raise RuntimeError("downloaded file was empty")

    # ------------------------------------------------------------------ #
    # Install / update / validate the Palworld dedicated server
    # ------------------------------------------------------------------ #
    def install_or_update(self) -> bool:
        """
        Runs steamcmd to install/validate the server. Returns True if the
        build id changed (i.e. an actual update was applied), False if it
        was already up to date (or this was the first install, which also
        counts as True).

        SteamCMD has a well-known quirk: on its very first run (or right
        after updating itself), it updates its own client and disconnects
        WITHOUT running the app_update command that follows it. So a
        single invocation can silently "do nothing" on a fresh install.
        We detect that (no success line, no error either) and simply
        retry a couple of times, which is the standard workaround.
        """
        self.ensure_steamcmd()
        before = self.get_installed_buildid()

        exe = str(self.steamcmd_exe_path())
        args = [
            exe,
            "+force_install_dir", str(self.server_dir),
            "+login", "anonymous",
            "+app_update", PALWORLD_APP_ID, "validate",
            "+quit",
        ]

        succeeded = False
        for attempt in range(1, MAX_INSTALL_ATTEMPTS + 1):
            self._log(f"Running SteamCMD update/validate for Palworld Dedicated Server "
                      f"(attempt {attempt}/{MAX_INSTALL_ATTEMPTS})...")
            output = self._run_streamed(args)

            if self._output_indicates_success(output):
                succeeded = True
                break
            if self._output_indicates_hard_failure(output):
                self._log("SteamCMD reported an error -- see the lines above for details.")
                break

            self._log("SteamCMD didn't confirm the install this time (common on the very "
                      "first run, since it updates itself first). Retrying...")

        if not succeeded and not self.is_installed():
            self._log("Install/update did not complete after "
                      f"{MAX_INSTALL_ATTEMPTS} attempts. Click "
                      "'Install / Check for Updates Now' again, or check the log above "
                      "for a specific SteamCMD error.")

        after = self.get_installed_buildid()
        if before != after:
            self._log(f"Update applied. Build ID {before or 'none'} -> {after}")
            return True
        else:
            if succeeded:
                self._log(f"Already up to date. Build ID {after}")
            return False

    @staticmethod
    def _output_indicates_success(output: str) -> bool:
        low = output.lower()
        return ("fully installed" in low) or ("success! app" in low)

    @staticmethod
    def _output_indicates_hard_failure(output: str) -> bool:
        low = output.lower()
        failure_markers = [
            "no subscription",
            "invalid password",
            "disk write failure",
            "not enough disk space",
            "connection to steam servers failed",
            "failed to install app",
        ]
        return any(marker in low for marker in failure_markers)

    def _run_streamed(self, args) -> str:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        collected = []
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                self._log(line)
                collected.append(line)
        proc.wait()
        return "\n".join(collected)

    def get_installed_buildid(self):
        manifest = self.server_dir / "steamapps" / f"appmanifest_{PALWORLD_APP_ID}.acf"
        if not manifest.exists():
            return None
        try:
            text = manifest.read_text(errors="ignore")
            m = re.search(r'"buildid"\s*"(\d+)"', text)
            return m.group(1) if m else None
        except Exception:
            return None

    def is_installed(self) -> bool:
        exe_name = "PalServer.exe" if self.is_windows else "PalServer.sh"
        candidates = list(self.server_dir.rglob(exe_name))
        return len(candidates) > 0

    def get_server_exe(self):
        exe_name = "PalServer.exe" if self.is_windows else "PalServer.sh"
        candidates = list(self.server_dir.rglob(exe_name))
        return candidates[0] if candidates else None

    def get_config_path(self):
        """Locate PalWorldSettings.ini regardless of Win/Linux server build."""
        candidates = list(self.server_dir.rglob("PalWorldSettings.ini"))
        return candidates[0] if candidates else None

    def get_default_config_path(self):
        """Where the ini SHOULD live once the server has been run once."""
        subdir = "WindowsServer" if self.is_windows else "LinuxServer"
        return self.server_dir / "Pal" / "Saved" / "Config" / subdir / "PalWorldSettings.ini"


class ServerProcess:
    """Starts/stops the actual PalServer game process."""

    def __init__(self, steam_manager: SteamManager, log_callback=None):
        self.sm = steam_manager
        self._log = log_callback or (lambda msg: None)
        self.proc = None

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, extra_args=None):
        if self.is_running():
            self._log("Server is already running.")
            return
        exe = self.sm.get_server_exe()
        if not exe:
            self._log("Cannot start: server executable not found. Install it first.")
            return
        args = [str(exe)] + (extra_args or [])
        self._log(f"Starting server: {' '.join(args)}")
        creationflags = 0
        if self.sm.is_windows:
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        self.proc = subprocess.Popen(
            args,
            cwd=str(exe.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=creationflags,
        )
        # Continuously drain stdout in the background. If nobody reads this
        # pipe, a chatty server can eventually fill the OS pipe buffer and
        # stall -- which can look like "the server froze" or make it
        # unresponsive to a later stop request.
        threading.Thread(target=self._drain_output, daemon=True).start()

    def _drain_output(self):
        proc = self.proc
        if not proc or not proc.stdout:
            return
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    self._log(line)
        except Exception:
            pass

    def stop(self):
        if not self.is_running():
            self._log("Server is not running.")
            return
        self._log("Stopping server...")
        pid = self.proc.pid

        # PalServer.exe frequently launches the actual game binary
        # (PalServer-Win64-Shipping.exe) as a CHILD process. Calling
        # terminate() only signals the top-level handle we hold, which can
        # leave the real game process running -- which looks exactly like
        # "the Stop button doesn't work." Killing the whole process tree
        # fixes that.
        try:
            if self.sm.is_windows:
                result = subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True, text=True, timeout=20,
                )
                if result.stdout.strip():
                    self._log(result.stdout.strip())
                if result.returncode not in (0, 128):  # 128 = process already gone
                    self._log(f"taskkill exit code {result.returncode}: {result.stderr.strip()}")
            else:
                import signal
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except Exception:
                    self.proc.terminate()
            self.proc.wait(timeout=15)
        except Exception as e:
            self._log(f"Graceful stop failed ({e}), forcing kill...")
            try:
                self.proc.kill()
                self.proc.wait(timeout=10)
            except Exception as e2:
                self._log(f"Could not confirm the process was killed: {e2}")

        if self.is_running():
            self._log("Warning: the server process may still be running. "
                       "Check Task Manager for PalServer-Win64-Shipping.exe.")
        else:
            self._log("Server stopped.")

    def read_available_output(self):
        """Kept for compatibility -- output is now drained continuously by
        _drain_output(), so this will normally return nothing."""
        lines = []
        if self.proc and self.proc.stdout:
            try:
                while True:
                    line = self.proc.stdout.readline()
                    if not line:
                        break
                    lines.append(line.rstrip())
            except Exception:
                pass
        return lines
