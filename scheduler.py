"""
scheduler.py

Background loop per active profile that:
  - Detects an unexpected server exit ("crash") and optionally auto-restarts
  - Broadcasts in-game countdown warnings and performs scheduled daily
    restarts ("graceful shutdown")
  - Triggers periodic automated backups

The actual stop/start calls are delegated back to the caller via
on_restart_requested() so the GUI thread stays in control of its own
status labels rather than this background thread touching widgets.
"""

import threading
import time
import datetime

from rcon_client import RconClient, RconError
from discord_notifier import send_discord_message


class ServerScheduler:
    POLL_SECONDS = 15

    def __init__(self, sm, server_proc, settings, backup_manager,
                 get_rcon_info, log_callback, on_restart_requested):
        self.sm = sm
        self.server_proc = server_proc
        self.settings = settings
        self.backup_manager = backup_manager
        self.get_rcon_info = get_rcon_info  # callable -> (host, port, password, enabled)
        self._log = log_callback or (lambda msg: None)
        self.on_restart_requested = on_restart_requested

        # Set True/False by the UI right after Start/Stop is clicked, so the
        # crash detector knows whether an exit was intentional.
        self.should_be_running = False

        self._stop_event = threading.Event()
        self._triggered_today = set()
        self._last_backup_at = 0.0
        self._last_crash_restart_at = 0.0
        self._crash_restart_count = 0

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def shutdown(self):
        self._stop_event.set()

    def broadcast(self, message: str):
        host, port, password, enabled = self.get_rcon_info()
        if not enabled:
            self._log(f"(RCON disabled, warning not broadcast in-game): {message}")
            return
        try:
            with RconClient(host, port, password) as rcon:
                # Some Palworld versions have historically mangled spaces in
                # Broadcast payloads -- underscores are the safe fallback.
                rcon.command(f"Broadcast {message.replace(' ', '_')}")
        except RconError as e:
            self._log(f"Could not broadcast warning via RCON: {e}")

    def _loop(self):
        while not self._stop_event.is_set():
            time.sleep(self.POLL_SECONDS)
            try:
                self._check_crash()
                self._check_scheduled_restarts()
                self._check_backup()
            except Exception as e:
                self._log(f"Scheduler error: {e}")

    def _check_crash(self):
        if not (self.should_be_running and not self.server_proc.is_running()):
            return

        self._log("Detected the server process is no longer running while it "
                   "was expected to be up (possible crash).")
        if self.settings.get("notify_crash", True):
            send_discord_message(
                self.settings.get("discord_webhook_url"),
                f"\u26a0\ufe0f Palworld server '{self.sm.profile_name}' appears to have crashed.",
                self._log,
            )

        if not self.settings.get("auto_restart_on_crash", True):
            self.should_be_running = False
            return

        now = time.time()
        if now - self._last_crash_restart_at > 600:
            self._crash_restart_count = 0
        if self._crash_restart_count >= 3:
            self._log("Auto-restart skipped: too many crashes in a short window. "
                       "Fix the underlying issue, then start the server manually.")
            self.should_be_running = False
            return

        self._log("Auto-restarting the server...")
        self._crash_restart_count += 1
        self._last_crash_restart_at = now
        self.on_restart_requested()

    def _today_key(self, suffix):
        return f"{datetime.date.today().isoformat()}_{suffix}"

    def _check_scheduled_restarts(self):
        restart_times = self.settings.get("restart_times", [])
        if not restart_times:
            return
        now = datetime.datetime.now()

        for t_str in restart_times:
            try:
                hh, mm = (int(x) for x in t_str.split(":"))
            except Exception:
                continue
            target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            delta_minutes = (target - now).total_seconds() / 60.0

            for warn_min in self.settings.get("restart_warning_minutes", []):
                key = self._today_key(f"warn_{t_str}_{warn_min}")
                if key not in self._triggered_today and 0 <= delta_minutes <= warn_min:
                    self._triggered_today.add(key)
                    msg = f"Server restarting in {warn_min} minute{'s' if warn_min != 1 else ''}."
                    self._log(f"Scheduled restart warning: {msg}")
                    self.broadcast(msg)

            restart_key = self._today_key(f"restart_{t_str}")
            if restart_key not in self._triggered_today and -1 <= delta_minutes <= 0:
                self._triggered_today.add(restart_key)
                self._log(f"Scheduled restart time reached ({t_str}). Restarting server...")
                send_discord_message(
                    self.settings.get("discord_webhook_url"),
                    f"\U0001F504 Scheduled restart for '{self.sm.profile_name}' starting now.",
                    self._log,
                )
                self.on_restart_requested()

        # Keep the dedupe set from growing forever across days.
        today_prefix = datetime.date.today().isoformat()
        self._triggered_today = {k for k in self._triggered_today if k.startswith(today_prefix)}

    def _check_backup(self):
        if not self.settings.get("backup_enabled", True):
            return
        interval = max(5, int(self.settings.get("backup_interval_minutes", 60))) * 60
        now = time.time()
        if now - self._last_backup_at >= interval:
            self._last_backup_at = now
            self.backup_manager.create_backup()
            self.backup_manager.prune_backups(int(self.settings.get("backup_keep_count", 12)))
