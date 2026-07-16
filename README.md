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
- Window sizes itself to fit your actual screen on launch (rather than a
  fixed size that could exceed smaller/laptop displays), and the Server
  and Scheduler & Alerts tabs scroll if their content is taller than the
  visible window — so nothing (like the Game Port field) can end up
  stranded off-screen with no way to reach it
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
- **Persistent status bar** — visible at the bottom no matter which tab
  you're on: green "Server Running", red "Server Stopped", orange
  "Checking for updates...", or gray "Not Installed".
- **Server tab** — install/update on demand, start/stop the server, open
  the install folder, toggle hourly auto-updates, and toggle auto-start-
  after-check (same setting as in Scheduler & Alerts, shown here too
  since it's closely tied to the update flow), plus the Quick Setup
  panel for name/passwords/ports/common toggles. A progress bar appears
  during installs/updates showing SteamCMD's actual download/verify
  percentage (parsed from its own progress output), not just a spinner.
  **The server automatically starts (or restarts) when any of these are
  true, unless you've manually stopped it (see below):** a brand-new
  install just finished; an update check found and applied an update; or
  the "auto-start after checking" toggle is on and a check simply found
  it not running. Each of these works independently of the others.
- **In-game announcements: REST API (recommended) vs. RCON.** Palworld
  has two remote-admin interfaces. RCON is deprecated by Pocketpair, and
  its `Broadcast`/`Shutdown` message text is documented as unreliable —
  independent reports confirm messages getting silently dropped or
  truncated even with correct syntax. The **REST API** is Pocketpair's
  actively maintained, officially recommended replacement, and its
  `/announce` and `/shutdown` endpoints reliably display messages
  in-game. Enable it in Quick Setup ("REST API Enabled" + port, default
  `8212`) — same `AdminPassword` as RCON. **Countdown warnings and
  scheduled/update-triggered restarts automatically use the REST API
  when it's enabled**, falling back to RCON only if the REST API isn't
  enabled or fails, and falling back further to an immediate stop if
  neither works.
- **RCON Console tab** — type any RCON command and press Enter, or use
  the quick buttons (Info, Show Players, Save World, Broadcast). Click
  "Use Config Values" to pull the host/port/password from the current
  profile's config. Requires `RCONEnabled=True` (toggle it in Quick
  Setup) and a server restart. The **Shutdown** button uses the same
  REST-API-first, repeating-every-30s countdown system as scheduled and
  update-triggered restarts (not a single raw RCON command) — so it gets
  reliable in-game announcements if the REST API is enabled. Sending
  `Shutdown` or `DoExit` as a raw *typed* command (not the button) stays
  a genuine passthrough for testing raw RCON, but still marks the
  profile as manually stopped, same as clicking Stop Server — so crash
  auto-restart and auto-start-after-check won't bring it back up just
  because you shut it down through RCON instead of the button.
- **Backups tab** — automatic backups run on the interval you set (default
  hourly, keeping the last 12); "Backup Now" triggers one immediately.
  When checking for game updates, it also does a quick, no-download check
  of Steam's latest build ID first, and if a real update is actually
  available it takes a labeled `pre_update` backup before applying it
  (toggleable) — so a bad update doesn't cost you your world. It won't
  back up on checks where nothing changed. Restore requires the server to
  be stopped first.
- **Scheduler & Alerts tab** — set a Discord webhook URL for start/stop/
  crash/update notifications, enable crash auto-restart, enable
  restart-after-update (on by default: if the server was running when an
  update lands, it's stopped and restarted automatically so it isn't left
  running on stale binaries), enable auto-start-after-check (off by
  default: starts the server once any update check finishes if it isn't
  already running — including the very first check when the app opens,
  so you can have it come up on its own — **unless you stopped it
  yourself**, see below), set daily restart times (24h, e.g.
  `04:00, 16:00`) with in-game advance warnings at the minutes-before you
  configure (default `15, 5, 1` — set it to just `2` for a single
  2-minute warning), and set the **shutdown countdown** (default 60s)
  used by both scheduled and update-triggered restarts. Both the advance
  warnings and the final countdown prefer the REST API when it's enabled
  (reliable in-game display), falling back to RCON, falling back to a
  log-only note if neither is enabled. During the final countdown we
  broadcast our own in-game reminder every 30 seconds (Palworld's native
  Shutdown command only announces once, not repeatedly), then trigger
  the actual shutdown, which also lets the world save before exiting.
  Needs to be at least ~60s for more than one reminder to actually fit —
  at 60s you get one reminder plus the final countdown; at 90s, two
  reminders plus the final one. Falls back to an immediate stop if
  nothing is enabled/reachable or the server doesn't exit in time.
- **Manually stopping the server sticks, with no exceptions.** Clicking
  **Stop Server** (or sending `Shutdown`/`DoExit` via RCON) marks the
  profile as manually stopped, and nothing — crash auto-restart,
  auto-start-after-check, fresh-install auto-start, not even the very
  first check right after the app launches — will bring it back up
  again until you explicitly click **Start Server**, or use the
  **Clear (allow auto-start)** button described below. A red warning
  with that button appears right on the Server tab whenever this flag is
  active, so it's never an invisible reason auto-start "just isn't
  working" — but it also never gets silently overridden just because
  you happened to relaunch the app.
- **Ports tab** — shows `PublicPort` (game port, default `8211`) and
  `RCONPort` (if RCON is enabled), each with a live "Listening /
  Not listening" status checked every 15 seconds, a button to open an
  external port-reachability check, and an "Open in Firewall" button that
  adds a Windows Firewall inbound rule for that port (Windows only, may
  need the app run as Administrator). Remember: "Listening" confirms
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
- **Server not showing up in Palworld's Community Server browser?**
  Palworld's in-game server browser is well documented as unreliable —
  even correctly configured, reachable servers can just fail to appear or
  take a long time to show up. That said, in rough order of how often
  each one is the actual cause:
  1. **The `-publiclobby` launch flag is what actually registers a server
     as a Community Server** rather than a private one — without it, the
     server may work perfectly for direct-IP connections but will never
     appear in the browser at all. Toggle "Add -publiclobby launch flag"
     in Quick Setup → Server Visibility.
  2. Confirm the port is actually reachable from outside (Ports tab →
     "External check"), not just "Listening" locally, and use "Open in
     Firewall" (Ports tab) to add a Windows Firewall inbound rule for
     `PublicPort` — a blocked firewall is one of the most common actual
     causes.
  3. Try setting **Public IP** explicitly (Quick Setup → Server
     Visibility → "Auto-Detect" fills in your actual external IP) —
     most guidance says leave it blank for a typical home router, but
     several working setups pair an explicit `PublicIP` with
     `-publiclobby`, particularly behind double-NAT or unusual routing.
  4. Try the "Add EpicApp=PalServer launch flag" toggle too — a separate,
     also community-reported fix, safe to combine with `-publiclobby`.
  5. Console/crossplay players (Xbox, PS5, Game Pass PC) can *only* join
     via the Community Server browser — there's no direct-connect option
     for them, so `-publiclobby` isn't optional if you want them to join.
  6. Some sources report a **second port (27015, TCP+UDP, Steam query)**
     also needs forwarding specifically for browser visibility, separate
     from the main `PublicPort` (8211) game port — worth trying if
     everything else checks out and it's still not appearing.
  7. If the world already existed before you changed settings, a
     `WorldOptions.sav` file can override `PalWorldSettings.ini` — check
     `Pal/Saved/SaveGames/.../WorldOptions.sav` if changes don't seem to
     take effect.
  8. Verify with a third-party tracker like
     [BattleMetrics](https://www.battlemetrics.com/servers/palworld) —
     if you show up there, your server is fine; it's the in-game browser
     that's lagging.
  9. As a reliable fallback for Steam/PC players, share
     `your-ip:PublicPort` and have them connect directly rather than
     searching — this always works regardless of browser flakiness.

## File overview

| File | Purpose |
|---|---|
| `Run Nexara's Palworld Server Manager.bat` | **Double-click this.** Self-installs a private Python runtime and launches the app — no manual Python/pip needed. |
| `main.py` | GUI (customtkinter): profiles, tabs, wiring |
| `assets/icon.ico`, `assets/icon.png` | App icon (window/taskbar icon + in-app logo) |
| `generate_icon.py` | Regenerates the icon files from scratch if you want to tweak the design |
| `steam_manager.py` | SteamCMD bootstrap, install/update, start/stop server process |
| `profiles.py` | Multi-profile management + per-profile settings (JSON) |
| `rcon_client.py` | Source RCON protocol client used by the RCON Console tab (fallback path for countdowns) |
| `rest_api_client.py` | Palworld REST API client -- primary path for reliable in-game announcements/shutdowns |
| `backup_manager.py` | Backup/restore of each profile's save data |
| `scheduler.py` | Background loop: crash detection/auto-restart, scheduled restarts, periodic backups |
| `discord_notifier.py` | Discord webhook sender |
| `config_editor.py` | Generic `PalWorldSettings.ini` parser/serializer |
| `port_checker.py` | Local port-listening checks + external check helper |
| `requirements.txt` | Runtime Python dependencies |
| `requirements-dev.txt` | Extra dependency (PyInstaller) only needed if building a standalone `.exe` |
