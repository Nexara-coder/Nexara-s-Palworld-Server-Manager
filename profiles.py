"""
profiles.py

Multi-server-profile support -- lets you run and manage several
independently-configured Palworld servers from one app. Each profile is
just a named folder with its own Palworld install and its own manager
settings (Discord webhook, restart schedule, backup policy, etc). SteamCMD
itself is shared across profiles -- only install targets differ.

'Default' keeps the original single-server layout for backward
compatibility with installs that predate multi-profile support.
"""

import json
from pathlib import Path

from steam_manager import get_base_dir, get_server_dir_for_profile

DEFAULT_SETTINGS = {
    "discord_webhook_url": "",
    "notify_start": True,
    "notify_stop": True,
    "notify_crash": True,
    "notify_update": True,
    "auto_restart_on_crash": True,
    # 24h "HH:MM" local-time strings, checked daily
    "restart_times": [],
    # Minutes-before-restart to broadcast in-game warnings at
    "restart_warning_minutes": [15, 5, 1],
    "backup_enabled": True,
    "backup_interval_minutes": 60,
    "backup_keep_count": 12,
}


def _settings_path_for(profile_name: str) -> Path:
    base = get_base_dir()
    if profile_name == "Default":
        return base / "manager_settings.json"
    return base / "profiles" / profile_name / "manager_settings.json"


def _backups_dir_for(profile_name: str) -> Path:
    base = get_base_dir()
    if profile_name == "Default":
        return base / "backups"
    return base / "profiles" / profile_name / "backups"


class ProfileSettings:
    """Loads/saves the small JSON settings file for one profile."""

    def __init__(self, profile_name: str):
        self.profile_name = profile_name
        self.path = _settings_path_for(profile_name)
        self.data = dict(DEFAULT_SETTINGS)
        self.load()

    def load(self):
        if self.path.exists():
            try:
                on_disk = json.loads(self.path.read_text(encoding="utf-8"))
                self.data = {**DEFAULT_SETTINGS, **on_disk}
            except Exception:
                self.data = dict(DEFAULT_SETTINGS)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


class ProfileManager:
    """Lists, creates, and deletes server profiles."""

    def __init__(self):
        self.base_dir = get_base_dir()
        self.profiles_dir = self.base_dir / "profiles"
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

    def list_profiles(self):
        names = ["Default"]
        for d in sorted(self.profiles_dir.iterdir()):
            if d.is_dir():
                names.append(d.name)
        return names

    def create_profile(self, name: str):
        name = name.strip()
        if not name:
            raise ValueError("Profile name can't be empty.")
        if name in self.list_profiles():
            raise ValueError(f"A profile named '{name}' already exists.")
        invalid_chars = '<>:"/\\|?*'
        if any(c in name for c in invalid_chars):
            raise ValueError(f"Profile name can't contain any of: {invalid_chars}")
        get_server_dir_for_profile(name).mkdir(parents=True, exist_ok=True)
        _backups_dir_for(name).mkdir(parents=True, exist_ok=True)
        ProfileSettings(name).save()
        return name

    def delete_profile(self, name: str):
        if name == "Default":
            raise ValueError("The Default profile can't be deleted -- rename/reuse it instead.")
        import shutil
        profile_dir = self.profiles_dir / name
        if profile_dir.exists():
            shutil.rmtree(profile_dir, ignore_errors=True)

    def backups_dir(self, name: str) -> Path:
        return _backups_dir_for(name)
