"""
discord_notifier.py

Fire-and-forget Discord webhook notifications for server lifecycle events
(start, stop, crash, update installed, scheduled-restart warnings).
"""

import requests


def send_discord_message(webhook_url: str, content: str, log_callback=None) -> bool:
    log = log_callback or (lambda msg: None)
    if not webhook_url:
        return False
    try:
        resp = requests.post(webhook_url, json={"content": content}, timeout=10)
        if resp.status_code >= 300:
            log(f"Discord webhook returned {resp.status_code}: {resp.text[:200]}")
            return False
        return True
    except Exception as e:
        log(f"Discord webhook failed: {e}")
        return False
