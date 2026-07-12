"""
main.py - Nexara's Palworld Server Manager

A desktop GUI (customtkinter) for managing Palworld dedicated servers:
  - Multi-server profiles (run/manage several independently-configured
    Palworld servers from one app)
  - Auto-installs each profile's Palworld Dedicated Server via SteamCMD
  - Checks for game updates every hour (and on demand)
  - Light / Dark / System appearance
  - Quick Setup panel (name, passwords, ports, common gameplay toggles)
    plus a full dynamically-generated editor for every other key in
    PalWorldSettings.ini
  - Ports tab: configured ports + live local listening status
  - RCON Console: send commands, quick buttons for common ones
  - Backups: automated + on-demand backup/restore of world save data
  - Scheduler & Alerts: daily restart times with in-game countdown
    warnings, crash detection with auto-restart, and Discord webhook
    notifications
  - Log tab: install/update/server output, tagged per profile

Run with:  python main.py
"""

import queue
import threading
import time
import datetime
from pathlib import Path
from collections import OrderedDict
from tkinter import messagebox

import customtkinter as ctk
from PIL import Image

from steam_manager import SteamManager, ServerProcess
from config_editor import PalConfig, classify_value, format_value
from port_checker import is_port_listening, open_external_check, get_local_ip
from profiles import ProfileManager, ProfileSettings
from backup_manager import BackupManager
from scheduler import ServerScheduler
from rcon_client import RconClient, RconError
from discord_notifier import send_discord_message

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
ICON_ICO = ASSETS_DIR / "icon.ico"
ICON_PNG = ASSETS_DIR / "icon.png"

# Amber accent (matches the app icon) used to give primary actions and
# section headers a bit more identity than the stock theme colors.
ACCENT = ("#e0972e", "#f0a53c")
ACCENT_HOVER = ("#c47f22", "#d68f2e")

UPDATE_CHECK_INTERVAL_SECONDS = 60 * 60  # 1 hour

QUICK_SETUP_TEXT_KEYS = [
    "ServerName", "ServerDescription", "ServerPassword", "AdminPassword",
    "ServerPlayerMaxNum", "PublicPort", "RCONPort",
]
QUICK_SETUP_BOOL_KEYS = ["RCONEnabled"]

QUICK_TOGGLES = [
    ("bIsPvP", "PvP Enabled"),
    ("bEnableFriendlyFire", "Friendly Fire"),
    ("bEnableInvaderEnemy", "Enable Raids / Invaders"),
    ("bEnableFastTravel", "Fast Travel"),
    ("bEnableAimAssistPad", "Aim Assist (Controller)"),
    ("bEnableNonLoginPenalty", "Offline Player Penalty"),
    ("bExistPlayerAfterLogout", "Keep Body After Logout"),
    ("bUseAuth", "Require Steam Authentication"),
]

HIDDEN_FROM_FULL_EDITOR = (
    set(QUICK_SETUP_TEXT_KEYS)
    | set(QUICK_SETUP_BOOL_KEYS)
    | {key for key, _ in QUICK_TOGGLES}
)


class ProfileRuntime:
    """Bundles the live backend objects for one server profile."""

    def __init__(self, name, log_queue, profile_manager):
        self.name = name
        self.settings = ProfileSettings(name)

        def log(msg, n=name):
            log_queue.put(f"[{n}] {msg}")

        self.sm = SteamManager(log_callback=log, profile_name=name)
        self.server_proc = ServerProcess(self.sm, log_callback=log)
        self.backup_manager = BackupManager(
            self.sm.server_dir, profile_manager.backups_dir(name), log_callback=log)
        self.busy = threading.Event()
        self.scheduler = None  # wired up by the app after construction


class PalworldManagerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Nexara's Palworld Server Manager")
        self.geometry("1080x780")
        self.minsize(900, 660)

        self.logo_image = None
        if ICON_PNG.exists():
            try:
                self.logo_image = ctk.CTkImage(Image.open(ICON_PNG), size=(34, 34))
            except Exception:
                self.logo_image = None
        self._apply_window_icon()

        self.log_queue = queue.Queue()
        self.rcon_output_queue = queue.Queue()
        self.ui_action_queue = queue.Queue()

        self.profile_manager = ProfileManager()
        self.runtimes = {}
        self.current_profile_name = "Default"

        self.pal_config: PalConfig | None = None
        self.config_widgets = {}

        self._stop_event = threading.Event()
        self._next_check_at = time.time() + UPDATE_CHECK_INTERVAL_SECONDS
        self.auto_update_enabled = ctk.BooleanVar(value=True)

        self._build_ui()
        self._switch_profile("Default")
        self._start_background_updater()

        self.after(150, self._poll_log_queue)
        self.after(150, self._poll_rcon_queue)
        self.after(150, self._poll_ui_actions)
        self.after(1000, self._tick_countdown)
        self.after(2000, self._refresh_ports)
        self.after(2000, self._refresh_status_loop)

        # Kick off first-run install automatically for the Default profile.
        self.after(300, self.on_install_or_update_clicked)

    def _apply_window_icon(self):
        """Sets the taskbar/title-bar icon on Windows. CTk has a known quirk
        where it resets the icon shortly after window creation, so this is
        (re)applied on a short delay; harmless no-op on platforms where
        .ico icons aren't supported (macOS/Linux)."""
        if not ICON_ICO.exists():
            return

        def apply():
            try:
                self.iconbitmap(str(ICON_ICO))
            except Exception:
                pass

        apply()
        self.after(250, apply)


    # ------------------------------------------------------------------ #
    # Profile plumbing
    # ------------------------------------------------------------------ #
    def _get_runtime(self, name) -> ProfileRuntime:
        if name not in self.runtimes:
            rt = ProfileRuntime(name, self.log_queue, self.profile_manager)
            rt.scheduler = ServerScheduler(
                rt.sm, rt.server_proc, rt.settings, rt.backup_manager,
                get_rcon_info=lambda rt=rt: self._get_rcon_info_for(rt),
                log_callback=lambda m, n=name: self.log_queue.put(f"[{n}] {m}"),
                on_restart_requested=lambda rt=rt: self._scheduler_restart(rt),
            )
            rt.scheduler.start()
            self.runtimes[name] = rt
        return self.runtimes[name]

    @property
    def rt(self) -> ProfileRuntime:
        return self._get_runtime(self.current_profile_name)

    @property
    def sm(self) -> SteamManager:
        return self.rt.sm

    @property
    def server_proc(self) -> ServerProcess:
        return self.rt.server_proc

    def _get_rcon_info_for(self, rt: ProfileRuntime):
        cfg = self._load_config_for(rt)
        if cfg is None:
            return ("127.0.0.1", 25575, "", False)
        port = cfg.get_port("RCONPort", 25575)
        password = cfg.pairs.get("AdminPassword", '""')
        if password.startswith('"') and password.endswith('"'):
            password = password[1:-1]
        enabled = cfg.get_bool("RCONEnabled", False)
        return ("127.0.0.1", port, password, enabled)

    def _load_config_for(self, rt: ProfileRuntime):
        path = rt.sm.get_config_path() or rt.sm.get_default_config_path()
        cfg = PalConfig(path)
        try:
            cfg.load()
            return cfg
        except Exception:
            return None

    def _load_config_silent(self):
        return self._load_config_for(self.rt)

    def _scheduler_restart(self, rt: ProfileRuntime):
        rt.server_proc.stop()
        time.sleep(2)
        rt.server_proc.start()

    def _switch_profile(self, name):
        self.current_profile_name = name
        _ = self.rt  # ensure the runtime (and its scheduler) exists
        self._reload_config_ui()
        self._populate_rcon_defaults()
        self._populate_backup_settings()
        self._refresh_backups_list()
        self._populate_scheduler_settings()
        self._update_status_label()
        self.install_path_label.configure(text=f"Install folder: {self.sm.server_dir}")

    def _on_profile_selected(self, value):
        self._switch_profile(value)

    def _on_new_profile_clicked(self):
        dialog = ctk.CTkInputDialog(text="Profile name (e.g. 'PvP Server'):", title="New Profile")
        name = dialog.get_input()
        if not name:
            return
        try:
            created = self.profile_manager.create_profile(name)
        except ValueError as e:
            messagebox.showwarning("Could not create profile", str(e))
            return
        self.profile_menu.configure(values=self.profile_manager.list_profiles())
        self.profile_var.set(created)
        self._switch_profile(created)
        self.log_queue.put(f"Created new profile: {created}")

    def _on_delete_profile_clicked(self):
        name = self.current_profile_name
        if name == "Default":
            messagebox.showwarning("Can't delete", "The Default profile can't be deleted.")
            return
        rt = self.runtimes.get(name)
        if rt and rt.server_proc.is_running():
            messagebox.showwarning("Server running", "Stop this server before deleting its profile.")
            return
        if not messagebox.askyesno(
            "Delete profile",
            f"Delete profile '{name}' and ALL its files (server install, backups, "
            "settings)? This can't be undone."
        ):
            return
        if rt and rt.scheduler:
            rt.scheduler.shutdown()
        self.runtimes.pop(name, None)
        self.profile_manager.delete_profile(name)
        self.profile_menu.configure(values=self.profile_manager.list_profiles())
        self.profile_var.set("Default")
        self._switch_profile("Default")
        self.log_queue.put(f"Deleted profile: {name}")

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        top_bar = ctk.CTkFrame(self, corner_radius=0, height=64,
                                fg_color=("#e5e5e5", "#161b1e"))
        top_bar.pack(side="top", fill="x")
        top_bar.pack_propagate(False)

        title_frame = ctk.CTkFrame(top_bar, fg_color="transparent")
        title_frame.pack(side="left", padx=(18, 10), pady=8)

        if self.logo_image is not None:
            ctk.CTkLabel(title_frame, image=self.logo_image, text="") \
                .pack(side="left", padx=(0, 10))

        text_frame = ctk.CTkFrame(title_frame, fg_color="transparent")
        text_frame.pack(side="left")
        ctk.CTkLabel(
            text_frame, text="Nexara's Palworld Server Manager",
            font=ctk.CTkFont(size=18, weight="bold"), anchor="w"
        ).pack(anchor="w")
        ctk.CTkLabel(
            text_frame, text="Install, run, and manage Palworld dedicated servers",
            font=ctk.CTkFont(size=11), text_color=("gray35", "gray65"), anchor="w"
        ).pack(anchor="w")

        divider = ctk.CTkFrame(top_bar, width=1, fg_color=("gray75", "gray30"))
        divider.pack(side="left", fill="y", padx=(6, 14), pady=12)

        profile_frame = ctk.CTkFrame(top_bar, fg_color="transparent")
        profile_frame.pack(side="left", pady=8)
        ctk.CTkLabel(profile_frame, text="Profile", font=ctk.CTkFont(size=11),
                     text_color=("gray35", "gray65")).pack(side="left", padx=(0, 8))
        self.profile_var = ctk.StringVar(value="Default")
        self.profile_menu = ctk.CTkOptionMenu(
            profile_frame, values=self.profile_manager.list_profiles(),
            variable=self.profile_var, command=self._on_profile_selected, width=160,
            fg_color=ACCENT, button_color=ACCENT_HOVER, button_hover_color=ACCENT_HOVER
        )
        self.profile_menu.pack(side="left")
        ctk.CTkButton(profile_frame, text="+ New", width=58,
                      command=self._on_new_profile_clicked).pack(side="left", padx=(6, 0))
        ctk.CTkButton(profile_frame, text="Delete", width=68,
                      fg_color="#8b2e2e", hover_color="#6e2424",
                      command=self._on_delete_profile_clicked).pack(side="left", padx=(6, 0))

        appearance_frame = ctk.CTkFrame(top_bar, fg_color="transparent")
        appearance_frame.pack(side="right", padx=18, pady=8)
        appearance_menu = ctk.CTkOptionMenu(
            appearance_frame, values=["System", "Light", "Dark"],
            command=lambda v: ctk.set_appearance_mode(v),
            width=110
        )
        appearance_menu.set("System")
        appearance_menu.pack(side="right")
        ctk.CTkLabel(appearance_frame, text="Theme", font=ctk.CTkFont(size=11),
                     text_color=("gray35", "gray65")).pack(side="right", padx=(0, 8))

        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_server = self.tabview.add("Server")
        self.tab_rcon = self.tabview.add("RCON Console")
        self.tab_backups = self.tabview.add("Backups")
        self.tab_scheduler = self.tabview.add("Scheduler & Alerts")
        self.tab_ports = self.tabview.add("Ports")
        self.tab_config = self.tabview.add("Config Editor")
        self.tab_log = self.tabview.add("Log")

        self._build_server_tab()
        self._build_rcon_tab()
        self._build_backups_tab()
        self._build_scheduler_tab()
        self._build_ports_tab()
        self._build_config_tab()
        self._build_log_tab()

    # ---------------------------- Server tab -------------------------- #
    def _build_server_tab(self):
        tab = self.tab_server

        info = ctk.CTkFrame(tab)
        info.pack(fill="x", padx=8, pady=8)

        self.status_label = ctk.CTkLabel(
            info, text="Status: checking...", font=ctk.CTkFont(size=14, weight="bold")
        )
        self.status_label.grid(row=0, column=0, sticky="w", padx=10, pady=6)

        self.install_path_label = ctk.CTkLabel(info, text="Install folder: --")
        self.install_path_label.grid(row=1, column=0, sticky="w", padx=10, pady=2)

        self.next_check_label = ctk.CTkLabel(info, text="Next update check: --")
        self.next_check_label.grid(row=2, column=0, sticky="w", padx=10, pady=2)

        btns = ctk.CTkFrame(tab)
        btns.pack(fill="x", padx=8, pady=4)

        ctk.CTkButton(btns, text="Install / Check for Updates Now",
                      command=self.on_install_or_update_clicked).pack(side="left", padx=6, pady=8)
        ctk.CTkButton(btns, text="\u25b6  Start Server", fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color="#1a1a1a", command=self.on_start_clicked).pack(side="left", padx=6, pady=8)
        ctk.CTkButton(btns, text="\u25a0  Stop Server", fg_color="#8b2e2e", hover_color="#6e2424",
                      command=self.on_stop_clicked).pack(side="left", padx=6, pady=8)
        ctk.CTkButton(btns, text="Open Server Folder", fg_color="transparent",
                      border_width=1, text_color=("gray10", "gray90"),
                      command=self.on_open_folder_clicked).pack(side="left", padx=6, pady=8)

        auto_frame = ctk.CTkFrame(tab)
        auto_frame.pack(fill="x", padx=8, pady=4)
        ctk.CTkCheckBox(
            auto_frame, text="Automatically check for game updates every hour "
                              "(applies to whichever profile is selected)",
            variable=self.auto_update_enabled
        ).pack(side="left", padx=10, pady=6)

        self._build_quick_setup(tab)

        hint = ctk.CTkLabel(
            tab, text="See the Log tab for install/update progress and server output.",
            text_color=("gray30", "gray70")
        )
        hint.pack(anchor="w", padx=10, pady=(4, 8))

    def _build_quick_setup(self, tab):
        frame = ctk.CTkFrame(tab)
        frame.pack(fill="x", padx=8, pady=(4, 8))
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(frame, text="Quick Setup", font=ctk.CTkFont(size=13, weight="bold"), text_color=ACCENT) \
            .grid(row=0, column=0, columnspan=4, sticky="w", padx=10, pady=(8, 4))

        self.quick_vars = {}

        def add_field(row, col, key, label, show=None, width=200):
            ctk.CTkLabel(frame, text=label, anchor="w").grid(
                row=row, column=col, sticky="w", padx=(10, 6), pady=4)
            var = ctk.StringVar()
            entry = ctk.CTkEntry(frame, textvariable=var, width=width, show=show or "")
            entry.grid(row=row, column=col + 1, sticky="w", padx=(0, 10), pady=4)
            self.quick_vars[key] = var

        add_field(1, 0, "ServerName", "Server Name")
        add_field(1, 2, "ServerDescription", "Description")
        add_field(2, 0, "ServerPassword", "Server Password", show="*")
        add_field(2, 2, "AdminPassword", "Admin Password", show="*")
        add_field(3, 0, "ServerPlayerMaxNum", "Max Players", width=100)
        add_field(3, 2, "PublicPort", "Game Port", width=100)

        rcon_row = ctk.CTkFrame(frame, fg_color="transparent")
        rcon_row.grid(row=4, column=0, columnspan=4, sticky="w", padx=4, pady=(2, 8))
        ctk.CTkLabel(rcon_row, text="RCON Enabled").pack(side="left", padx=(6, 6))
        self.quick_rcon_var = ctk.StringVar(value="False")
        ctk.CTkOptionMenu(rcon_row, values=["True", "False"], variable=self.quick_rcon_var, width=90) \
            .pack(side="left", padx=(0, 20))
        ctk.CTkLabel(rcon_row, text="RCON Port").pack(side="left", padx=(0, 6))
        self.quick_vars["RCONPort"] = ctk.StringVar()
        ctk.CTkEntry(rcon_row, textvariable=self.quick_vars["RCONPort"], width=100) \
            .pack(side="left")

        ctk.CTkLabel(frame, text="Common Toggles", font=ctk.CTkFont(size=13, weight="bold"), text_color=ACCENT) \
            .grid(row=5, column=0, columnspan=4, sticky="w", padx=10, pady=(4, 4))

        self.quick_toggle_vars = {}
        toggles_frame = ctk.CTkFrame(frame, fg_color="transparent")
        toggles_frame.grid(row=6, column=0, columnspan=4, sticky="w", padx=6, pady=(0, 10))
        for i, (key, label) in enumerate(QUICK_TOGGLES):
            r, c = divmod(i, 2)
            var = ctk.StringVar(value="False")
            self.quick_toggle_vars[key] = var
            ctk.CTkSwitch(
                toggles_frame, text=label, variable=var,
                onvalue="True", offvalue="False", width=200
            ).grid(row=r, column=c, sticky="w", padx=10, pady=4)

        btn_row = ctk.CTkFrame(frame, fg_color="transparent")
        btn_row.grid(row=7, column=0, columnspan=4, sticky="w", padx=4, pady=(0, 10))
        ctk.CTkButton(btn_row, text="Save Quick Settings", command=self._save_quick_setup) \
            .pack(side="left", padx=6)
        self.quick_status_label = ctk.CTkLabel(btn_row, text="", text_color=("gray30", "gray70"))
        self.quick_status_label.pack(side="left", padx=10)

    def _populate_quick_setup(self):
        if self.pal_config is None:
            return
        for key, var in self.quick_vars.items():
            raw = self.pal_config.pairs.get(key, "")
            if raw.startswith('"') and raw.endswith('"'):
                raw = raw[1:-1]
            var.set(raw)
        self.quick_rcon_var.set(self.pal_config.pairs.get("RCONEnabled", "False"))
        for key, var in self.quick_toggle_vars.items():
            var.set(self.pal_config.pairs.get(key, "False"))

    def _save_quick_setup(self):
        if self.pal_config is None:
            self.quick_status_label.configure(text="No config loaded yet.")
            return
        updated = OrderedDict(self.pal_config.pairs)
        for key, var in self.quick_vars.items():
            if key not in updated:
                continue
            updated[key] = format_value(updated[key], var.get())
        if "RCONEnabled" in updated:
            updated["RCONEnabled"] = self.quick_rcon_var.get()
        for key, var in self.quick_toggle_vars.items():
            if key in updated:
                updated[key] = var.get()
        try:
            self.pal_config.save(updated)
            self.quick_status_label.configure(text=f"Saved at {time.strftime('%H:%M:%S')}")
            self.log_queue.put(f"[{self.rt.name}] Quick settings saved "
                                "(restart the server for changes to take effect).")
            self._reload_config_ui()
            self._populate_rcon_defaults()
        except Exception as e:
            self.quick_status_label.configure(text=f"Save failed: {e}")

    # ---------------------------- RCON Console tab ---------------------------- #
    def _build_rcon_tab(self):
        tab = self.tab_rcon

        header = ctk.CTkFrame(tab)
        header.pack(fill="x", padx=8, pady=8)
        ctk.CTkLabel(header, text="RCON Console", font=ctk.CTkFont(size=14, weight="bold"), text_color=ACCENT) \
            .pack(side="left", padx=10, pady=6)

        conn_frame = ctk.CTkFrame(tab)
        conn_frame.pack(fill="x", padx=8, pady=(0, 8))
        ctk.CTkLabel(conn_frame, text="Host").grid(row=0, column=0, padx=(10, 4), pady=6, sticky="w")
        self.rcon_host_var = ctk.StringVar(value="127.0.0.1")
        ctk.CTkEntry(conn_frame, textvariable=self.rcon_host_var, width=110) \
            .grid(row=0, column=1, padx=(0, 10), pady=6)
        ctk.CTkLabel(conn_frame, text="Port").grid(row=0, column=2, padx=(0, 4), pady=6, sticky="w")
        self.rcon_port_var = ctk.StringVar(value="25575")
        ctk.CTkEntry(conn_frame, textvariable=self.rcon_port_var, width=80) \
            .grid(row=0, column=3, padx=(0, 10), pady=6)
        ctk.CTkLabel(conn_frame, text="Password").grid(row=0, column=4, padx=(0, 4), pady=6, sticky="w")
        self.rcon_password_var = ctk.StringVar()
        ctk.CTkEntry(conn_frame, textvariable=self.rcon_password_var, width=140, show="*") \
            .grid(row=0, column=5, padx=(0, 10), pady=6)
        ctk.CTkButton(conn_frame, text="Use Config Values", width=140,
                      command=self._populate_rcon_defaults) \
            .grid(row=0, column=6, padx=(0, 10), pady=6)

        quick_frame = ctk.CTkFrame(tab)
        quick_frame.pack(fill="x", padx=8, pady=(0, 8))
        ctk.CTkButton(quick_frame, text="Info", width=90,
                      command=lambda: self._rcon_run("Info")).pack(side="left", padx=4, pady=6)
        ctk.CTkButton(quick_frame, text="Show Players", width=110,
                      command=lambda: self._rcon_run("ShowPlayers")).pack(side="left", padx=4, pady=6)
        ctk.CTkButton(quick_frame, text="Save World", width=100,
                      command=lambda: self._rcon_run("Save")).pack(side="left", padx=4, pady=6)
        ctk.CTkButton(quick_frame, text="Broadcast...", width=100,
                      command=self._rcon_broadcast_dialog).pack(side="left", padx=4, pady=6)
        ctk.CTkButton(quick_frame, text="Shutdown...", width=100,
                      fg_color="#8b2e2e", hover_color="#6e2424",
                      command=self._rcon_shutdown_dialog).pack(side="left", padx=4, pady=6)

        cmd_frame = ctk.CTkFrame(tab)
        cmd_frame.pack(fill="x", padx=8, pady=(0, 8))
        self.rcon_cmd_var = ctk.StringVar()
        entry = ctk.CTkEntry(cmd_frame, textvariable=self.rcon_cmd_var,
                              placeholder_text="Type an RCON command and press Enter...")
        entry.pack(side="left", fill="x", expand=True, padx=(10, 6), pady=6)
        entry.bind("<Return>", lambda e: self._rcon_run(self.rcon_cmd_var.get()))
        ctk.CTkButton(cmd_frame, text="Send", width=80,
                      command=lambda: self._rcon_run(self.rcon_cmd_var.get())) \
            .pack(side="left", padx=(0, 10), pady=6)

        self.rcon_output = ctk.CTkTextbox(tab, wrap="word")
        self.rcon_output.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.rcon_output.configure(state="disabled")

    def _populate_rcon_defaults(self):
        cfg = self._load_config_silent()
        if cfg is None:
            return
        self.rcon_port_var.set(str(cfg.get_port("RCONPort", 25575)))
        pw = cfg.pairs.get("AdminPassword", '""')
        if pw.startswith('"') and pw.endswith('"'):
            pw = pw[1:-1]
        self.rcon_password_var.set(pw)
        if not cfg.get_bool("RCONEnabled", False):
            self._rcon_log("Note: RCONEnabled is False in the config for this profile -- "
                            "enable it (Quick Setup) and restart the server for RCON to work.")

    def _rcon_run(self, cmd):
        cmd = cmd.strip()
        if not cmd:
            return
        self.rcon_cmd_var.set("")
        host = self.rcon_host_var.get().strip() or "127.0.0.1"
        try:
            port = int(self.rcon_port_var.get().strip())
        except ValueError:
            self._rcon_log("Invalid RCON port.")
            return
        password = self.rcon_password_var.get()
        self._rcon_log(f"> {cmd}")
        threading.Thread(target=self._rcon_worker, args=(host, port, password, cmd), daemon=True).start()

    def _rcon_worker(self, host, port, password, cmd):
        try:
            with RconClient(host, port, password) as rcon:
                result = rcon.command(cmd)
            self.rcon_output_queue.put(result if result else "(empty response)")
        except RconError as e:
            self.rcon_output_queue.put(f"ERROR: {e}")
        except Exception as e:
            self.rcon_output_queue.put(f"ERROR: {e}")

    def _rcon_log(self, text):
        self.rcon_output_queue.put(text)

    def _rcon_broadcast_dialog(self):
        dialog = ctk.CTkInputDialog(text="Message to broadcast to all players:", title="Broadcast")
        msg = dialog.get_input()
        if msg:
            self._rcon_run(f"Broadcast {msg.replace(' ', '_')}")

    def _rcon_shutdown_dialog(self):
        dialog = ctk.CTkInputDialog(
            text="Shutdown countdown in seconds:", title="Shutdown Server")
        secs = dialog.get_input()
        if secs and secs.strip().isdigit():
            self._rcon_run(f"Shutdown {secs.strip()} Server_shutting_down")

    # ---------------------------- Backups tab ---------------------------- #
    def _build_backups_tab(self):
        tab = self.tab_backups

        header = ctk.CTkFrame(tab)
        header.pack(fill="x", padx=8, pady=8)
        ctk.CTkLabel(header, text="Automated Backups", font=ctk.CTkFont(size=14, weight="bold"), text_color=ACCENT) \
            .pack(side="left", padx=10, pady=6)
        ctk.CTkButton(header, text="Backup Now", width=110,
                      command=self._on_backup_now_clicked).pack(side="right", padx=6, pady=6)
        ctk.CTkButton(header, text="Refresh List", width=110,
                      command=self._refresh_backups_list).pack(side="right", padx=6, pady=6)

        settings_frame = ctk.CTkFrame(tab)
        settings_frame.pack(fill="x", padx=8, pady=(0, 8))
        self.backup_enabled_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(settings_frame, text="Automatic backups enabled",
                         variable=self.backup_enabled_var) \
            .grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=6)
        ctk.CTkLabel(settings_frame, text="Interval (minutes)") \
            .grid(row=1, column=0, sticky="w", padx=10, pady=4)
        self.backup_interval_var = ctk.StringVar(value="60")
        ctk.CTkEntry(settings_frame, textvariable=self.backup_interval_var, width=80) \
            .grid(row=1, column=1, sticky="w", padx=(0, 20), pady=4)
        ctk.CTkLabel(settings_frame, text="Keep last N backups") \
            .grid(row=1, column=2, sticky="w", padx=10, pady=4)
        self.backup_keep_var = ctk.StringVar(value="12")
        ctk.CTkEntry(settings_frame, textvariable=self.backup_keep_var, width=80) \
            .grid(row=1, column=3, sticky="w", padx=(0, 10), pady=4)
        ctk.CTkButton(settings_frame, text="Save Backup Settings", command=self._save_backup_settings) \
            .grid(row=2, column=0, columnspan=2, sticky="w", padx=10, pady=8)
        self.backup_settings_status = ctk.CTkLabel(settings_frame, text="", text_color=("gray30", "gray70"))
        self.backup_settings_status.grid(row=2, column=2, columnspan=2, sticky="w", padx=10, pady=8)

        self.backups_list_frame = ctk.CTkScrollableFrame(tab)
        self.backups_list_frame.pack(fill="both", expand=True, padx=8, pady=8)
        self.backups_list_frame.grid_columnconfigure(0, weight=1)

    def _populate_backup_settings(self):
        s = self.rt.settings
        self.backup_enabled_var.set(bool(s.get("backup_enabled", True)))
        self.backup_interval_var.set(str(s.get("backup_interval_minutes", 60)))
        self.backup_keep_var.set(str(s.get("backup_keep_count", 12)))

    def _save_backup_settings(self):
        s = self.rt.settings
        try:
            interval = int(self.backup_interval_var.get())
            keep = int(self.backup_keep_var.get())
        except ValueError:
            self.backup_settings_status.configure(text="Interval and keep count must be numbers.")
            return
        s.set("backup_enabled", bool(self.backup_enabled_var.get()))
        s.set("backup_interval_minutes", interval)
        s.set("backup_keep_count", keep)
        s.save()
        self.backup_settings_status.configure(text=f"Saved at {time.strftime('%H:%M:%S')}")

    def _on_backup_now_clicked(self):
        rt = self.rt
        threading.Thread(target=self._backup_now_worker, args=(rt,), daemon=True).start()

    def _backup_now_worker(self, rt):
        rt.backup_manager.create_backup()
        if rt.name == self.current_profile_name:
            self.ui_action_queue.put(self._refresh_backups_list)

    def _refresh_backups_list(self):
        for child in self.backups_list_frame.winfo_children():
            child.destroy()
        rt = self.rt
        backups = rt.backup_manager.list_backups()
        if not backups:
            ctk.CTkLabel(self.backups_list_frame, text="No backups yet.",
                         text_color=("gray30", "gray70")).grid(row=0, column=0, sticky="w", padx=6, pady=6)
            return
        for i, b in enumerate(backups):
            stat = b.stat()
            size_mb = stat.st_size / (1024 * 1024)
            mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            row = ctk.CTkFrame(self.backups_list_frame, fg_color="transparent")
            row.grid(row=i, column=0, sticky="ew", padx=4, pady=2)
            ctk.CTkLabel(row, text=f"{b.name}   ({size_mb:.1f} MB, {mtime})", anchor="w") \
                .pack(side="left", fill="x", expand=True, padx=6)
            ctk.CTkButton(row, text="Restore", width=80,
                          command=lambda p=b: self._on_restore_backup_clicked(p)).pack(side="right", padx=4)
            ctk.CTkButton(row, text="Delete", width=70, fg_color="#8b2e2e", hover_color="#6e2424",
                          command=lambda p=b: self._on_delete_backup_clicked(p)).pack(side="right", padx=4)

    def _on_restore_backup_clicked(self, path):
        if self.server_proc.is_running():
            messagebox.showwarning("Server running", "Stop the server before restoring a backup.")
            return
        if not messagebox.askyesno("Restore backup",
                                    f"Restore '{path.name}'? This overwrites current save data."):
            return
        rt = self.rt
        try:
            rt.backup_manager.restore_backup(path)
        except Exception as e:
            messagebox.showerror("Restore failed", str(e))

    def _on_delete_backup_clicked(self, path):
        if not messagebox.askyesno("Delete backup", f"Delete '{path.name}'? This can't be undone."):
            return
        try:
            path.unlink()
        except Exception as e:
            messagebox.showerror("Delete failed", str(e))
        self._refresh_backups_list()

    # ---------------------------- Scheduler & Alerts tab ---------------------------- #
    def _build_scheduler_tab(self):
        tab = self.tab_scheduler

        header = ctk.CTkFrame(tab)
        header.pack(fill="x", padx=8, pady=8)
        ctk.CTkLabel(header, text="Scheduled Restarts & Discord Alerts",
                     font=ctk.CTkFont(size=14, weight="bold"), text_color=ACCENT) \
            .pack(side="left", padx=10, pady=6)

        discord_frame = ctk.CTkFrame(tab)
        discord_frame.pack(fill="x", padx=8, pady=(0, 8))
        ctk.CTkLabel(discord_frame, text="Discord Webhook URL") \
            .grid(row=0, column=0, sticky="w", padx=10, pady=6)
        self.discord_webhook_var = ctk.StringVar()
        ctk.CTkEntry(discord_frame, textvariable=self.discord_webhook_var, width=380) \
            .grid(row=0, column=1, sticky="w", padx=(0, 10), pady=6)
        ctk.CTkButton(discord_frame, text="Send Test Message", width=140,
                      command=self._on_discord_test_clicked).grid(row=0, column=2, padx=(0, 10), pady=6)

        notify_frame = ctk.CTkFrame(tab)
        notify_frame.pack(fill="x", padx=8, pady=(0, 8))
        ctk.CTkLabel(notify_frame, text="Notify on:").grid(row=0, column=0, sticky="w", padx=10, pady=(6, 2))
        self.notify_start_var = ctk.BooleanVar(value=True)
        self.notify_stop_var = ctk.BooleanVar(value=True)
        self.notify_crash_var = ctk.BooleanVar(value=True)
        self.notify_update_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(notify_frame, text="Server Start", variable=self.notify_start_var) \
            .grid(row=1, column=0, sticky="w", padx=10, pady=2)
        ctk.CTkCheckBox(notify_frame, text="Server Stop", variable=self.notify_stop_var) \
            .grid(row=1, column=1, sticky="w", padx=10, pady=2)
        ctk.CTkCheckBox(notify_frame, text="Crash Detected", variable=self.notify_crash_var) \
            .grid(row=2, column=0, sticky="w", padx=10, pady=2)
        ctk.CTkCheckBox(notify_frame, text="Update Installed", variable=self.notify_update_var) \
            .grid(row=2, column=1, sticky="w", padx=10, pady=2)

        crash_frame = ctk.CTkFrame(tab)
        crash_frame.pack(fill="x", padx=8, pady=(0, 8))
        self.auto_restart_crash_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(crash_frame, text="Automatically restart the server if it crashes",
                         variable=self.auto_restart_crash_var).pack(side="left", padx=10, pady=6)

        restart_frame = ctk.CTkFrame(tab)
        restart_frame.pack(fill="x", padx=8, pady=(0, 8))
        ctk.CTkLabel(restart_frame, text="Daily restart times (24h, comma-separated, e.g. 04:00, 16:00)") \
            .grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(6, 2))
        self.restart_times_var = ctk.StringVar()
        ctk.CTkEntry(restart_frame, textvariable=self.restart_times_var, width=300) \
            .grid(row=1, column=0, sticky="w", padx=10, pady=(0, 6))
        ctk.CTkLabel(restart_frame, text="In-game warnings, minutes before restart (comma-separated)") \
            .grid(row=2, column=0, columnspan=2, sticky="w", padx=10, pady=(6, 2))
        self.restart_warn_var = ctk.StringVar()
        ctk.CTkEntry(restart_frame, textvariable=self.restart_warn_var, width=300) \
            .grid(row=3, column=0, sticky="w", padx=10, pady=(0, 6))

        ctk.CTkButton(tab, text="Save Scheduler & Alert Settings", command=self._save_scheduler_settings) \
            .pack(anchor="w", padx=16, pady=10)
        self.scheduler_status_label = ctk.CTkLabel(tab, text="", text_color=("gray30", "gray70"))
        self.scheduler_status_label.pack(anchor="w", padx=16)

    def _populate_scheduler_settings(self):
        s = self.rt.settings
        self.discord_webhook_var.set(s.get("discord_webhook_url", ""))
        self.notify_start_var.set(bool(s.get("notify_start", True)))
        self.notify_stop_var.set(bool(s.get("notify_stop", True)))
        self.notify_crash_var.set(bool(s.get("notify_crash", True)))
        self.notify_update_var.set(bool(s.get("notify_update", True)))
        self.auto_restart_crash_var.set(bool(s.get("auto_restart_on_crash", True)))
        self.restart_times_var.set(", ".join(s.get("restart_times", [])))
        self.restart_warn_var.set(", ".join(str(x) for x in s.get("restart_warning_minutes", [15, 5, 1])))

    def _save_scheduler_settings(self):
        s = self.rt.settings
        raw_times = [t.strip() for t in self.restart_times_var.get().split(",") if t.strip()]
        valid_times = []
        bad = []
        for t in raw_times:
            parts = t.split(":")
            if (len(parts) == 2 and all(p.isdigit() for p in parts)
                    and 0 <= int(parts[0]) < 24 and 0 <= int(parts[1]) < 60):
                valid_times.append(f"{int(parts[0]):02d}:{int(parts[1]):02d}")
            else:
                bad.append(t)
        try:
            warn_minutes = [int(x.strip()) for x in self.restart_warn_var.get().split(",") if x.strip()]
        except ValueError:
            warn_minutes = [15, 5, 1]

        s.set("discord_webhook_url", self.discord_webhook_var.get().strip())
        s.set("notify_start", bool(self.notify_start_var.get()))
        s.set("notify_stop", bool(self.notify_stop_var.get()))
        s.set("notify_crash", bool(self.notify_crash_var.get()))
        s.set("notify_update", bool(self.notify_update_var.get()))
        s.set("auto_restart_on_crash", bool(self.auto_restart_crash_var.get()))
        s.set("restart_times", valid_times)
        s.set("restart_warning_minutes", warn_minutes)
        s.save()

        status = f"Saved at {time.strftime('%H:%M:%S')}"
        if bad:
            status += f"  (ignored invalid time(s): {', '.join(bad)})"
        self.scheduler_status_label.configure(text=status)

    def _on_discord_test_clicked(self):
        url = self.discord_webhook_var.get().strip()
        if not url:
            self.scheduler_status_label.configure(text="Enter a webhook URL first.")
            return
        profile_name = self.current_profile_name
        threading.Thread(
            target=send_discord_message,
            args=(url, f"Test message from Nexara's Palworld Server Manager ({profile_name})."),
            kwargs={"log_callback": lambda m: self.log_queue.put(m)},
            daemon=True,
        ).start()
        self.scheduler_status_label.configure(text="Test message sent (check Discord / Log tab for errors).")

    # ---------------------------- Ports tab ---------------------------- #
    def _build_ports_tab(self):
        tab = self.tab_ports

        header = ctk.CTkFrame(tab)
        header.pack(fill="x", padx=8, pady=8)
        ctk.CTkLabel(
            header, text="Configured ports & local listening status",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=ACCENT
        ).pack(side="left", padx=10, pady=6)
        ctk.CTkButton(header, text="Refresh", command=self._refresh_ports, width=90) \
            .pack(side="right", padx=10, pady=6)

        note = ctk.CTkLabel(
            tab,
            text=("\"Listening\" means the server process is actively bound to that port "
                  "on this machine. It does NOT confirm your router/firewall is forwarding "
                  "it to the internet -- use \"External check\" for that."),
            wraplength=880, justify="left", text_color=("gray30", "gray70")
        )
        note.pack(fill="x", padx=10, pady=(0, 8))

        self.ports_frame = ctk.CTkFrame(tab)
        self.ports_frame.pack(fill="both", expand=True, padx=8, pady=8)

        self.local_ip_label = ctk.CTkLabel(tab, text="Local IP: --")
        self.local_ip_label.pack(anchor="w", padx=10, pady=(0, 8))

        self._port_rows = {}

    def _make_port_row(self, parent, row_index, display_name, key):
        frame = parent
        ctk.CTkLabel(frame, text=display_name, width=160, anchor="w") \
            .grid(row=row_index, column=0, sticky="w", padx=10, pady=6)
        port_val_label = ctk.CTkLabel(frame, text="--", width=80, anchor="w")
        port_val_label.grid(row=row_index, column=1, sticky="w", padx=10, pady=6)
        status_label = ctk.CTkLabel(frame, text="Unknown", width=100, anchor="w")
        status_label.grid(row=row_index, column=2, sticky="w", padx=10, pady=6)
        ext_btn = ctk.CTkButton(
            frame, text="External check", width=120,
            command=lambda: open_external_check(None)
        )
        ext_btn.grid(row=row_index, column=3, sticky="w", padx=10, pady=6)
        self._port_rows[key] = {"port_label": port_val_label, "status_label": status_label}

    def _refresh_ports(self):
        if not self._port_rows:
            self._make_port_row(self.ports_frame, 0, "Game Port (PublicPort)", "PublicPort")
            self._make_port_row(self.ports_frame, 1, "RCON Port", "RCONPort")

        self.local_ip_label.configure(text=f"Local IP: {get_local_ip()}")

        cfg = self._load_config_silent()
        if cfg is None:
            for key, widgets in self._port_rows.items():
                widgets["port_label"].configure(text="--")
                widgets["status_label"].configure(text="No config yet", text_color=("gray30", "gray70"))
            self.after(15000, self._refresh_ports)
            return

        game_port = cfg.get_port("PublicPort", 8211)
        rcon_enabled = cfg.get_bool("RCONEnabled", False)
        rcon_port = cfg.get_port("RCONPort", 25575)

        self._update_port_row("PublicPort", game_port, is_port_listening(game_port))
        if rcon_enabled:
            self._update_port_row("RCONPort", rcon_port, is_port_listening(rcon_port))
        else:
            self._port_rows["RCONPort"]["port_label"].configure(text=str(rcon_port))
            self._port_rows["RCONPort"]["status_label"].configure(
                text="RCON disabled", text_color=("gray30", "gray70"))

        self.after(15000, self._refresh_ports)

    def _update_port_row(self, key, port, listening):
        widgets = self._port_rows[key]
        widgets["port_label"].configure(text=str(port))
        if listening:
            widgets["status_label"].configure(text="\u25cf Listening", text_color=("#1a7f37", "#3fb950"))
        else:
            widgets["status_label"].configure(text="\u25cb Not listening", text_color=("#b02a2a", "#f85149"))

    # -------------------------- Config editor tab ----------------------- #
    def _build_config_tab(self):
        tab = self.tab_config

        header = ctk.CTkFrame(tab)
        header.pack(fill="x", padx=8, pady=8)

        ctk.CTkLabel(
            header, text="PalWorldSettings.ini -- full configuration editor",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=ACCENT
        ).pack(side="left", padx=10, pady=6)

        ctk.CTkButton(header, text="Reload", command=self._reload_config_ui, width=90) \
            .pack(side="right", padx=6, pady=6)
        ctk.CTkButton(header, text="Save Changes", command=self._save_config_ui, width=110) \
            .pack(side="right", padx=6, pady=6)

        search_frame = ctk.CTkFrame(tab)
        search_frame.pack(fill="x", padx=8, pady=(0, 8))
        ctk.CTkLabel(search_frame, text="Filter:").pack(side="left", padx=(10, 4))
        self.filter_var = ctk.StringVar()
        self.filter_var.trace_add("write", lambda *a: self._apply_filter())
        ctk.CTkEntry(search_frame, textvariable=self.filter_var, placeholder_text="type to filter settings...") \
            .pack(side="left", fill="x", expand=True, padx=(0, 10), pady=6)

        ctk.CTkLabel(
            tab,
            text=("Name, description, passwords, ports, max players, and the common "
                  "gameplay toggles live on the Server tab's Quick Setup panel and "
                  "aren't duplicated here."),
            text_color=("gray30", "gray70"), wraplength=880, justify="left"
        ).pack(fill="x", padx=10, pady=(0, 4))

        self.config_status_label = ctk.CTkLabel(tab, text="", text_color=("gray30", "gray70"))
        self.config_status_label.pack(anchor="w", padx=10)

        self.config_scroll = ctk.CTkScrollableFrame(tab)
        self.config_scroll.pack(fill="both", expand=True, padx=8, pady=8)
        self.config_scroll.grid_columnconfigure(1, weight=1)

    def _reload_config_ui(self):
        for child in self.config_scroll.winfo_children():
            child.destroy()
        self.config_widgets.clear()

        path = self.sm.get_config_path()
        creating_default = path is None
        if path is None:
            path = self.sm.get_default_config_path()

        self.pal_config = PalConfig(path)
        try:
            self.pal_config.load()
        except Exception as e:
            self.config_status_label.configure(text=f"Could not load config: {e}")
            return

        if creating_default:
            self.config_status_label.configure(
                text=f"No existing config found -- created a default one at:\n{path}")
        else:
            self.config_status_label.configure(text=f"Editing: {path}")

        row = 0
        for key, raw_value in self.pal_config.pairs.items():
            if key in HIDDEN_FROM_FULL_EDITOR:
                continue
            self._add_config_row(row, key, raw_value)
            row += 1

        if hasattr(self, "quick_vars"):
            self._populate_quick_setup()

    def _add_config_row(self, row, key, raw_value):
        label = ctk.CTkLabel(self.config_scroll, text=key, anchor="w")
        label.grid(row=row, column=0, sticky="w", padx=(6, 12), pady=3)

        kind = classify_value(raw_value)
        if kind == "bool":
            var = ctk.StringVar(value=raw_value)
            widget = ctk.CTkOptionMenu(self.config_scroll, values=["True", "False"], variable=var, width=140)
        else:
            display_value = raw_value
            if kind == "string" and display_value.startswith('"') and display_value.endswith('"'):
                display_value = display_value[1:-1]
            var = ctk.StringVar(value=display_value)
            widget = ctk.CTkEntry(self.config_scroll, textvariable=var)

        widget.grid(row=row, column=1, sticky="ew", padx=(0, 6), pady=3)
        self.config_widgets[key] = {"var": var, "raw": raw_value, "label": label, "widget": widget, "row": row}

    def _apply_filter(self):
        needle = self.filter_var.get().strip().lower()
        for key, entry in self.config_widgets.items():
            visible = needle in key.lower()
            if visible:
                entry["label"].grid()
                entry["widget"].grid()
            else:
                entry["label"].grid_remove()
                entry["widget"].grid_remove()

    def _save_config_ui(self):
        if self.pal_config is None:
            return
        updated = OrderedDict(self.pal_config.pairs)
        for key, entry in self.config_widgets.items():
            new_value = entry["var"].get()
            updated[key] = format_value(entry["raw"], new_value)
        try:
            self.pal_config.save(updated)
            self.config_status_label.configure(text=f"Saved: {self.pal_config.path}")
            self.log_queue.put(f"[{self.rt.name}] Config saved to {self.pal_config.path}")
        except Exception as e:
            self.config_status_label.configure(text=f"Save failed: {e}")

    # ---------------------------- Log tab ---------------------------- #
    def _build_log_tab(self):
        tab = self.tab_log
        ctk.CTkLabel(tab, text="Log", font=ctk.CTkFont(size=14, weight="bold"), text_color=ACCENT) \
            .pack(anchor="w", padx=10, pady=(8, 4))
        self.log_box = ctk.CTkTextbox(tab, wrap="word")
        self.log_box.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.log_box.configure(state="disabled")

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #
    def on_install_or_update_clicked(self):
        rt = self.rt
        if rt.busy.is_set():
            self.log_queue.put(f"[{rt.name}] An install/update is already running.")
            return
        threading.Thread(target=self._run_install_or_update, args=(rt,), daemon=True).start()

    def _run_install_or_update(self, rt: ProfileRuntime):
        rt.busy.set()
        try:
            if rt.name == self.current_profile_name:
                self.status_label.configure(text=f"Status: installing / updating... ({rt.name})")
            changed = rt.sm.install_or_update()
            if rt.name == self.current_profile_name:
                self._next_check_at = time.time() + UPDATE_CHECK_INTERVAL_SECONDS
                self._update_status_label()
            if changed:
                self.log_queue.put(f"[{rt.name}] Server files were installed/updated.")
                if rt.settings.get("notify_update", True):
                    send_discord_message(
                        rt.settings.get("discord_webhook_url"),
                        f"\U0001F4E6 Palworld server '{rt.name}' was installed/updated.",
                        lambda m: self.log_queue.put(f"[{rt.name}] {m}"),
                    )
                if rt.name == self.current_profile_name:
                    self.ui_action_queue.put(self._reload_config_ui)
        except Exception as e:
            self.log_queue.put(f"[{rt.name}] ERROR during install/update: {e}")
        finally:
            rt.busy.clear()

    def on_start_clicked(self):
        rt = self.rt
        if not rt.sm.is_installed():
            self.log_queue.put(f"[{rt.name}] Install the server before starting it.")
            return
        rt.scheduler.should_be_running = True
        threading.Thread(target=rt.server_proc.start, daemon=True).start()
        if rt.settings.get("notify_start", True):
            threading.Thread(
                target=send_discord_message,
                args=(rt.settings.get("discord_webhook_url"),
                      f"\u25b6\ufe0f Palworld server '{rt.name}' starting."),
                kwargs={"log_callback": lambda m: self.log_queue.put(f"[{rt.name}] {m}")},
                daemon=True,
            ).start()
        self._update_status_label()

    def on_stop_clicked(self):
        rt = self.rt
        rt.scheduler.should_be_running = False
        threading.Thread(target=rt.server_proc.stop, daemon=True).start()
        if rt.settings.get("notify_stop", True):
            threading.Thread(
                target=send_discord_message,
                args=(rt.settings.get("discord_webhook_url"),
                      f"\u23f9\ufe0f Palworld server '{rt.name}' stopping."),
                kwargs={"log_callback": lambda m: self.log_queue.put(f"[{rt.name}] {m}")},
                daemon=True,
            ).start()
        self._update_status_label()

    def on_open_folder_clicked(self):
        import os, sys, subprocess as sp
        path = str(self.sm.server_dir)
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            sp.Popen(["open", path])
        else:
            sp.Popen(["xdg-open", path])

    def _update_status_label(self):
        rt = self.rt
        if rt.server_proc.is_running():
            text = f"Status: running ({rt.name})"
        elif rt.sm.is_installed():
            text = f"Status: stopped ({rt.name})"
        else:
            text = f"Status: not installed ({rt.name})"
        self.status_label.configure(text=text)

    def _refresh_status_loop(self):
        self._update_status_label()
        self.after(2000, self._refresh_status_loop)

    # ------------------------------------------------------------------ #
    # Background game-update checker (hourly, applies to whichever
    # profile is currently selected when the timer fires)
    # ------------------------------------------------------------------ #
    def _start_background_updater(self):
        def loop():
            while not self._stop_event.is_set():
                time.sleep(5)
                if not self.auto_update_enabled.get():
                    continue
                if time.time() >= self._next_check_at:
                    rt = self.rt
                    if not rt.busy.is_set():
                        self.log_queue.put(f"[{rt.name}] Hourly auto-update check triggered.")
                        self._run_install_or_update(rt)
                    else:
                        self._next_check_at = time.time() + 60

        threading.Thread(target=loop, daemon=True).start()

    def _tick_countdown(self):
        remaining = max(0, int(self._next_check_at - time.time()))
        mins, secs = divmod(remaining, 60)
        hrs, mins = divmod(mins, 60)
        self.next_check_label.configure(
            text=f"Next update check: {hrs:02d}:{mins:02d}:{secs:02d} "
                 f"({'enabled' if self.auto_update_enabled.get() else 'disabled'})"
        )
        self.after(1000, self._tick_countdown)

    # ------------------------------------------------------------------ #
    # Queue draining (thread-safe UI updates)
    # ------------------------------------------------------------------ #
    def _poll_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_box.configure(state="normal")
                self.log_box.insert("end", msg + "\n")
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(150, self._poll_log_queue)

    def _poll_rcon_queue(self):
        try:
            while True:
                msg = self.rcon_output_queue.get_nowait()
                self.rcon_output.configure(state="normal")
                self.rcon_output.insert("end", msg + "\n")
                self.rcon_output.see("end")
                self.rcon_output.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(150, self._poll_rcon_queue)

    def _poll_ui_actions(self):
        """
        Background threads (install/update workers, backup workers, the
        scheduler) must never touch widgets or call self.after() directly --
        Tk is not thread-safe. They instead drop a zero-arg callable here,
        and this main-thread-only loop runs it.
        """
        try:
            while True:
                action = self.ui_action_queue.get_nowait()
                try:
                    action()
                except Exception as e:
                    self.log_queue.put(f"UI update error: {e}")
        except queue.Empty:
            pass
        self.after(150, self._poll_ui_actions)

    def on_closing(self):
        self._stop_event.set()
        for rt in self.runtimes.values():
            if rt.scheduler:
                rt.scheduler.shutdown()
            if rt.server_proc.is_running():
                rt.server_proc.stop()
        self.destroy()


if __name__ == "__main__":
    app = PalworldManagerApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
