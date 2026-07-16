"""
port_checker.py

Local port-status checking + helpers for reading the ports Palworld is
configured to use out of PalWorldSettings.ini.

NOTE ON "OPEN" vs "LISTENING":
True external reachability depends on your router/firewall (NAT), which
can't be verified from the same machine that's hosting the server. What
we CAN verify locally and reliably is whether the game process is
actually bound to and listening on the configured port. We surface that
as "Listening" and give a one-click link to an external checker
(canyouseeme.org) for a true outside-in test.
"""

import socket
import webbrowser


def get_external_ip(timeout: float = 6.0):
    """
    Looks up this machine's actual public/external IP address (not the
    LAN IP get_local_ip() returns) -- used to fill in PublicIP for people
    whose server isn't auto-detecting it correctly. Tries a couple of
    independent services in case one is down. Returns None on failure;
    callers should treat that as "couldn't determine it", not "no IP".
    """
    import requests

    services = ["https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com"]
    for url in services:
        try:
            resp = requests.get(url, timeout=timeout)
            ip = resp.text.strip()
            # Sanity-check it looks like an IPv4 address before trusting it.
            parts = ip.split(".")
            if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
                return ip
        except Exception:
            continue
    return None


def is_port_listening(port: int, host: str = "127.0.0.1") -> bool:
    """Returns True if something on this machine is listening on `port`."""
    if not port:
        return False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            result = s.connect_ex((host, int(port)))
            return result == 0
    except Exception:
        return False


def open_external_check(port: int):
    """Opens a browser tab to externally test whether a port is reachable."""
    webbrowser.open("https://canyouseeme.org/")


def get_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def add_firewall_rule(port: int, protocol: str, rule_name: str):
    """
    Adds an inbound Windows Firewall rule allowing the given port/protocol.
    Returns (success: bool, message: str). A Windows Firewall rule blocking
    inbound traffic is the single most common reason a working, correctly
    forwarded server still isn't reachable from the internet -- this saves
    a trip to Windows Settings for that specific case. No-op with a clear
    message on non-Windows platforms. Requires admin rights on Windows;
    callers should surface the returned message if it fails so the person
    knows to re-run as Administrator.
    """
    import platform
    import subprocess

    if platform.system() != "Windows":
        return False, "Firewall rule creation is only supported on Windows."
    try:
        result = subprocess.run(
            ["netsh", "advfirewall", "firewall", "add", "rule",
             f"name={rule_name}", "dir=in", "action=allow",
             f"protocol={protocol}", f"localport={port}"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return True, f"Firewall rule '{rule_name}' added for {protocol} port {port}."
        detail = (result.stderr or result.stdout or "").strip()
        return False, (f"Windows Firewall rejected the request ({detail or 'no details given'}) "
                        "-- try right-clicking the app/launcher and choosing "
                        "'Run as administrator', then retry.")
    except Exception as e:
        return False, f"Could not add the firewall rule: {e}"
