"""
rest_api_client.py

Client for Palworld's built-in REST API -- Pocketpair's actively
maintained, officially recommended replacement for RCON. RCON (including
its Broadcast command) is documented as deprecated and unreliable for
displaying messages in-game; the REST API's /v1/api/announce and
/v1/api/shutdown endpoints are the supported way to do this instead.

Enable with, in PalWorldSettings.ini:
    RESTAPIEnabled=True
    RESTAPIPort=8212   (default)
Auth is HTTP Basic with username "admin" and the server's AdminPassword.

Reference: https://docs.palworldgame.com/api/rest-api/
"""

import requests


class RestApiError(Exception):
    pass


class PalRestClient:
    def __init__(self, host: str, port: int, admin_password: str, timeout: float = 6.0):
        self.base_url = f"http://{host}:{port}/v1/api"
        self.auth = ("admin", admin_password)
        self.timeout = timeout

    def _request(self, method: str, path: str, json_body=None):
        try:
            resp = requests.request(
                method, f"{self.base_url}/{path}",
                auth=self.auth, json=json_body, timeout=self.timeout,
            )
        except Exception as e:
            raise RestApiError(f"Could not reach the REST API: {e}")
        if resp.status_code == 401:
            raise RestApiError("REST API rejected the AdminPassword.")
        if resp.status_code >= 300:
            raise RestApiError(f"REST API returned {resp.status_code}: {resp.text[:200]}")
        return resp

    def info(self):
        return self._request("GET", "info").json()

    def players(self):
        return self._request("GET", "players").json()

    def metrics(self):
        return self._request("GET", "metrics").json()

    def announce(self, message: str):
        """Broadcasts `message` to all connected players -- reliably, unlike RCON's Broadcast."""
        self._request("POST", "announce", {"message": message})

    def save(self):
        self._request("POST", "save")

    def shutdown(self, waittime_seconds: int, message: str):
        """Graceful shutdown after a delay, with a warning message -- saves the world on exit."""
        self._request("POST", "shutdown", {"waittime": int(waittime_seconds), "message": message})

    def stop(self):
        """Force stop -- immediate, no countdown, no save."""
        self._request("POST", "stop")

    def kick(self, userid: str, message: str = ""):
        self._request("POST", "kick", {"userid": userid, "message": message})

    def ban(self, userid: str, message: str = ""):
        self._request("POST", "ban", {"userid": userid, "message": message})

    def unban(self, userid: str):
        self._request("POST", "unban", {"userid": userid})
