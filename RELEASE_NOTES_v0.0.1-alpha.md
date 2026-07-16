# Nexara's Palworld Server Manager — Alpha v0.0.1

First public alpha. This is a desktop app for installing, running, and maintaining Palworld dedicated servers — including support for running several servers side by side.

⚠️ **Alpha software.** Core flows have been tested (install/update, start/stop, config save/load, backup/restore, scheduler timing, RCON packet framing), but this hasn't been through broad real-world use yet. Back up your saves before pointing this at a server you care about, and expect rough edges.

## Highlights

- **Multi-server profiles** — create, switch between, and delete independently configured Palworld servers from one app. Each profile has its own install, ports, config, backups, and schedule, and keeps running in the background even while you're looking at a different one.
- **One-click install & updates** — bootstraps SteamCMD automatically and installs the Palworld Dedicated Server (App ID `2394010`). Hourly auto-update checks compare Steam build IDs so it only touches the install when something actually changed.
- **Quick Setup panel** — server name, description, passwords, ports, max players, and the common gameplay toggles (PvP, friendly fire, raids, fast travel, offline penalty, etc.) without digging through a giant settings list.
- **Full config editor** — every other key in `PalWorldSettings.ini` gets its own row, auto-generated from whatever's actually in the file (so it won't go stale as Palworld patches add settings), with a filter box to find what you need.
- **RCON Console** — a real Source RCON client, with quick buttons for Info, Show Players, Save World, Broadcast, and Shutdown, plus a free-form command line.
- **Automated backups** — interval-based backups of world/save data with pruning, one-click restore, and on-demand "Backup Now."
- **Scheduler & Alerts** — daily restart times with in-game countdown warnings broadcast over RCON, crash detection with automatic restart (capped to avoid restart-loops), and Discord webhook notifications for start/stop/crash/update events.
- **Ports tab** — shows your configured game and RCON ports with live local listening status, plus a link to an external reachability checker.
- **No Python required to run it** — double-click `Run Nexara's Palworld Server Manager.bat` and it silently provisions its own private Python runtime and dependencies. Nothing to install manually, nothing touches any Python already on your system.
- Light / Dark / System theme, and a proper app icon.

## Installation

1. Download and unzip the release.
2. Double-click **`Run Nexara's Palworld Server Manager.bat`**.
3. First run takes a few minutes (downloads a private Python runtime + sets up the app); every run after that is instant.

Full details, troubleshooting, and the manual `pip install` path for anyone who'd rather run it from source are in `README.md`.

## Known limitations (alpha)

- The hourly **game update** check only applies to whichever profile is currently selected when the timer fires. Scheduled restarts and backups, by contrast, run continuously per-profile in the background regardless of which tab you have open.
- No mod management/Curseforge-style integration, no cluster map transfer, no CPU affinity controls — Palworld's mod ecosystem doesn't have an equivalent API to plug into for the first two, and the third was out of scope for this pass.
- Built and tested primarily on Windows. It will run on Linux (`~/Documents` + the Linux SteamCMD/server build), but that path has seen less real-world testing.
- Antivirus/SmartScreen may flag the `.bat` launcher on first run since it downloads and runs an installer — this is expected for unsigned scripts that install software, not a sign anything's wrong.

## What's next

Planning to harden multi-profile concurrent operation, expand Linux testing, and look at packaging this as a standalone `.exe` build to skip the first-run Python bootstrap entirely. Feedback and bug reports welcome.

---

*Not affiliated with Pocketpair or the Palworld team. Uses SteamCMD for anonymous dedicated-server installation, same as any other third-party Palworld server tool.*
