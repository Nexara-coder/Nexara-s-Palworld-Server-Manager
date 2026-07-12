"""
rcon_client.py

A minimal Source RCON protocol client. Palworld's dedicated server exposes
RCON over this same protocol (Valve's original spec) once RCONEnabled=True
in PalWorldSettings.ini -- same protocol ARK, Minecraft, and most Source
games use.

Known useful Palworld RCON commands (sent as plain text via command()):
  Info                          -- server version/name
  ShowPlayers                   -- CSV of connected players
  Save                          -- force a world save
  Broadcast <message>           -- some Palworld versions require
                                    underscores instead of spaces in the
                                    message; noted in the UI
  Shutdown <seconds> <message>  -- graceful timed shutdown with a message
  DoExit                        -- immediate shutdown, no warning
  KickPlayer <steamid>
  BanPlayer <steamid>
  UnBanPlayer <steamid>
"""

import socket
import struct

SERVERDATA_AUTH = 3
SERVERDATA_AUTH_RESPONSE = 2
SERVERDATA_EXECCOMMAND = 2
SERVERDATA_RESPONSE_VALUE = 0


class RconError(Exception):
    pass


class RconClient:
    def __init__(self, host: str, port: int, password: str, timeout: float = 6.0):
        self.host = host
        self.port = int(port)
        self.password = password
        self.timeout = timeout
        self.sock = None
        self._req_id = 0

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def connect(self):
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as e:
            raise RconError(f"Could not connect to {self.host}:{self.port} -- {e}")
        self._authenticate()

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def _next_id(self):
        self._req_id += 1
        return self._req_id

    def _send_packet(self, pkt_type, body: str):
        req_id = self._next_id()
        payload = struct.pack("<ii", req_id, pkt_type) + body.encode("utf-8") + b"\x00\x00"
        packet = struct.pack("<i", len(payload)) + payload
        self.sock.sendall(packet)
        return req_id

    def _recvall(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise RconError("Connection closed by server.")
            buf += chunk
        return buf

    def _read_packet(self):
        raw_len = self._recvall(4)
        length = struct.unpack("<i", raw_len)[0]
        data = self._recvall(length)
        req_id, pkt_type = struct.unpack("<ii", data[:8])
        body = data[8:-2].decode("utf-8", errors="ignore")
        return req_id, pkt_type, body

    def _authenticate(self):
        sent_id = self._send_packet(SERVERDATA_AUTH, self.password)
        req_id, pkt_type, _ = self._read_packet()
        # Some server implementations send an empty SERVERDATA_RESPONSE_VALUE
        # packet before the actual auth response -- read once more if so.
        if pkt_type != SERVERDATA_AUTH_RESPONSE:
            req_id, pkt_type, _ = self._read_packet()
        if req_id == -1:
            raise RconError("RCON authentication failed -- check the RCON password.")

    def command(self, cmd: str) -> str:
        if not self.sock:
            raise RconError("Not connected.")
        self._send_packet(SERVERDATA_EXECCOMMAND, cmd)
        _, _, body = self._read_packet()
        return body
