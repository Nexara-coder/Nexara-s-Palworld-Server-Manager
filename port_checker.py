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
