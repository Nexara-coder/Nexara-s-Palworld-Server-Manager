"""
backup_manager.py

Zips up the Palworld server's "Saved" folder (world data, player data,
config) into timestamped archives, prunes old ones, and can restore a
selected backup.
"""

import time
import zipfile
from pathlib import Path


class BackupManager:
    def __init__(self, server_dir: Path, backups_dir: Path, log_callback=None):
        self.server_dir = Path(server_dir)
        self.backups_dir = Path(backups_dir)
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        self._log = log_callback or (lambda msg: None)

    def _find_saved_dir(self):
        for d in self.server_dir.rglob("Saved"):
            if d.is_dir() and (d / "Config").exists():
                return d
        # Fall back to any "Saved" dir at all if the Config check misses
        for d in self.server_dir.rglob("Saved"):
            if d.is_dir():
                return d
        return None

    def create_backup(self, label: str = ""):
        saved_dir = self._find_saved_dir()
        if not saved_dir:
            self._log("Backup skipped: no Saved folder found yet (server hasn't run).")
            return None

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        suffix = f"_{label}" if label else ""
        dest = self.backups_dir / f"backup_{timestamp}{suffix}.zip"
        self._log(f"Creating backup: {dest.name} ...")
        try:
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
                for file in saved_dir.rglob("*"):
                    if file.is_file():
                        zf.write(file, file.relative_to(saved_dir.parent))
        except Exception as e:
            self._log(f"Backup failed: {e}")
            dest.unlink(missing_ok=True)
            return None

        size_mb = dest.stat().st_size / (1024 * 1024)
        self._log(f"Backup complete: {dest.name} ({size_mb:.1f} MB)")
        return dest

    def list_backups(self):
        return sorted(self.backups_dir.glob("backup_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)

    def prune_backups(self, keep_count: int):
        backups = self.list_backups()
        for old in backups[keep_count:]:
            try:
                old.unlink()
                self._log(f"Pruned old backup: {old.name}")
            except Exception as e:
                self._log(f"Could not prune {old.name}: {e}")

    def restore_backup(self, backup_path: Path):
        saved_dir = self._find_saved_dir()
        if not saved_dir:
            raise RuntimeError("Cannot find a Saved folder to restore into.")
        with zipfile.ZipFile(backup_path, "r") as zf:
            zf.extractall(saved_dir.parent)
        self._log(f"Restored backup: {backup_path.name} "
                   f"(restart the server for this to take effect)")
