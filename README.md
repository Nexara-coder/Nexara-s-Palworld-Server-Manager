# Nexara's Palworld Server Manager

A desktop GUI for installing, running, and maintaining Palworld dedicated
servers, with support for running several servers side by side.

**What it does:**
- **Multi-server profiles** — run and manage several independently
  configured Palworld servers from one app, each with its own install,
  ports, settings, backups, and schedule
- Downloads SteamCMD and installs each profile's Palworld Dedicated Server
  (App ID `2394010`) automatically into
  `Documents\PalworldServerManager\server` (Default profile) or
  `...\profiles\<name>\server` (additional profiles)
- Checks for game updates every hour in the background (toggleable), and
  only reports/reinstalls when the Steam build ID actually changes
- Light / Dark / System theme toggle
- **Quick Setup** panel: name, description, passwords, ports, max players,
  and the common gameplay toggles (PvP, friendly fire, raids, fast travel,
  etc.), plus a full auto-generated editor for every other key in
  `PalWorldSettings.ini`
- **RCON Console** — send any RCON command, with quick buttons for Info,
  Show Players, Save World, Broadcast, and Shutdown
- **Automated backups** of world/save data on a configurable interval,
  with one-click restore, plus on-demand "Backup Now"
- **Scheduler & Alerts** — daily restart times with in-game countdown
  warnings broadcast over RCON, crash detection with automatic restart,
  and Discord webhook notifications for start/stop/crash/update events
- Shows configured Game Port and RCON Port, and whether the server is
  actively listening on them locally, plus a one-click link to an external
  reachability checker (canyouseeme.org) for true outside-in testing
- Start / Stop controls and a per-profile-tagged log panel

Built primarily for **Windows** (matches the "Documents" folder
convention and how most people run Palworld dedicated servers). It will
also run on Linux, using `~/Documents` (or your home folder) and the
Linux SteamCMD/server build.

**Not included:** mod management/Curseforge integration (Palworld's mod
ecosystem is much smaller than ARK's and doesn't have an equivalent API),
cluster map transfer, and CPU affinity controls.

---

## 1. First-time setup (no Python/pip needed)

Just unzip the folder and double-click:

**`Run Nexara's Palworld Server Manager.bat`**

That's the only step. It's fine to hand the whole unzipped folder to
someone else, put it on a USB stick, etc. — they double-click the same
file and it works the same way for them, with zero setup knowledge
required.

The first time it's run, that file:
1. Silently downloads and installs a **private** copy of Python into a
   `runtime\` folder next to the app (doesn't touch or conflict with any
   Python already on the PC, no admin rights needed)
2. Installs the couple of small components the app needs (quietly, no
   typing required)
3. Launches the app

This takes a few minutes depending on your connection — you'll see
progress in the console window. Every launch after that is instant:
double-click the same `.bat` file and the app just opens.

Once the app itself is open, it takes over from there:
1. Creates `Documents\PalworldServerManager\`
2. Downloads and unpacks SteamCMD into `...\steamcmd\`
3. Anonymously logs into Steam and installs the Palworld Dedicated Server
   into `...\server\`
4. Generates a default `PalWorldSettings.ini` if one doesn't exist yet,
   so the Config Editor and Ports tabs have something to work with
   immediately

Watch the **Log** panel on the Server tab for progress on this part.

> **Antivirus / SmartScreen note:** because the `.bat` file downloads an
> installer and runs it, Windows SmartScreen or some antivirus tools may
> flag it the first time — this is normal for unsigned scripts that
> install software. Choose "More info → Run anyway" if you trust the
> source (i.e., you got it from yourself/me and haven't modified it).

> **If setup fails:** the launcher installs Python to the standard
> per-user location (`%LocalAppData%\Programs\Python\Python312`) rather
> than a custom folder — this is the same path/method the official
> python.org installer uses for a normal "install for me only" run, so
> it's the most reliable option. If it still fails, it now saves a
> detailed log to `%TEMP%\pwsm_python_install_312.log` and prints the
> installer's exit code — open that log in Notepad and check the end for
> the real error. It also automatically attempts one self-repair
> (uninstall + reinstall) if Windows has a stale record claiming Python
> is already installed somewhere it no longer exists — the most common
> cause of a "silent success that isn't actually installed."

### Running it from source instead (developers)

If you'd rather run it directly with your own Python install:

```bash
cd palworld_server_manager
pip install -r requirements.txt
python main.py
```

## 2. Using it

- **Profile selector** (top bar) — switch between servers, or click
  **+ New** to create another profile (each gets its own install, ports,
  and settings) or **Delete** to remove one (Default can't be deleted).
  Every profile keeps running independently even while you're looking at
  a different one's tabs.
- **Server tab** — install/update on demand, start/stop the server, open
  the install folder, toggle hourly auto-updates, and the Quick Setup
  panel for name/passwords/ports/common toggles.
- **RCON Console tab** — type any RCON command and press Enter, or use
  the quick buttons (Info, Show Players, Save World, Broadcast, Shutdown).
  Click "Use Config Values" to pull the host/port/password from the
  current profile's config. Requires `RCONEnabled=True` (toggle it in
  Quick Setup) and a server restart.
- **Backups tab** — automatic backups run on the interval you set (default
  hourly, keeping the last 12); "Backup Now" triggers one immediately.
  Restore requires the server to be stopped first.
- **Scheduler & Alerts tab** — set a Discord webhook URL for start/stop/
  crash/update notifications, enable crash auto-restart, and set daily
  restart times (24h, e.g. `04:00, 16:00`) with in-game countdown warnings
  broadcast via RCON before each one.
- **Ports tab** — shows `PublicPort` (game port, default `8211`) and
  `RCONPort` (if RCON is enabled), each with a live "Listening /
  Not listening" status checked every 15 seconds, plus a button to open
  an external port-reachability check. Remember: "Listening" confirms
  the server is bound to the port on this machine — it does **not**
  confirm your router is forwarding it. You'll still need to port-forward
  `PublicPort` (UDP) on your router if you're hosting from home.
- **Config Editor tab** — every key from `PalWorldSettings.ini` *except*
  what Quick Setup already covers gets its own row (checkbox for booleans,
  text field for everything else). Use the filter box to jump to a
  setting. Click **Save Changes** to write back to the ini file. The
  server must be restarted for changes to take effect.
- **Log tab** — install/update/server output and scheduler/backup/Discord
  activity, tagged with `[ProfileName]` so multi-server logs stay
  readable.

## 3. Packaging as a true standalone .exe (optional, for distributing without even the .bat)

The `.bat` launcher above already means nobody needs to install Python
manually. If you'd prefer a single literal `.exe` file instead (e.g. to
avoid the SmartScreen prompt or the first-run download), you can build
one yourself on a Windows machine:

```bash
pip install -r requirements.txt -r requirements-dev.txt
pyinstaller --noconsole --onefile --name "PalworldServerManager" main.py
```

The finished executable will be in `dist\PalworldServerManager.exe` —
share just that one file. Note: PyInstaller builds are platform-specific,
so build it on Windows to get a Windows executable.

## 4. Notes / troubleshooting

- **Anonymous Steam login** is used since the Palworld Dedicated Server
  doesn't require an owned Steam account — this is standard practice for
  dedicated server tools.
- If the update check fails partway, just click **Install / Check for
  Updates Now** again — SteamCMD resumes/validates rather than
  re-downloading everything.
- If Windows Firewall prompts you when the server starts, allow access
  on Private (and Public, if hosting to the internet) networks.
- RCON port only shows a real listening status once `RCONEnabled=True`
  is set in the config and the server has been restarted.
- The hourly **game update** check (Server tab) applies to whichever
  profile is currently selected when the timer fires. If you're running
  multiple servers unattended, click into each profile occasionally, or
  trigger "Install / Check for Updates Now" manually per profile.
- Scheduled restarts and automated backups (Scheduler & Alerts / Backups
  tabs), by contrast, run continuously in the background **per profile**
  regardless of which tab or profile you currently have open.

## File overview

| File | Purpose |
|---|---|
| `Run Nexara's Palworld Server Manager.bat` | **Double-click this.** Self-installs a private Python runtime and launches the app — no manual Python/pip needed. |
| `main.py` | GUI (customtkinter): profiles, tabs, wiring |
| `assets/icon.ico`, `assets/icon.png` | App icon (window/taskbar icon + in-app logo) |
| `generate_icon.py` | Regenerates the icon files from scratch if you want to tweak the design |
| `steam_manager.py` | SteamCMD bootstrap, install/update, start/stop server process |
| `profiles.py` | Multi-profile management + per-profile settings (JSON) |
| `rcon_client.py` | Source RCON protocol client used by the RCON Console and scheduler warnings |
| `backup_manager.py` | Backup/restore of each profile's save data |
| `scheduler.py` | Background loop: crash detection/auto-restart, scheduled restarts, periodic backups |
| `discord_notifier.py` | Discord webhook sender |
| `config_editor.py` | Generic `PalWorldSettings.ini` parser/serializer |
| `port_checker.py` | Local port-listening checks + external check helper |
| `requirements.txt` | Runtime Python dependencies |
| `requirements-dev.txt` | Extra dependency (PyInstaller) only needed if building a standalone `.exe` |
