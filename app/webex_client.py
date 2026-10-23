"""Part 4 student implementation."""

import os
import requests

WEBEX_API_BASE = "https://webexapis.com/v1"


class WebexClient:
    def __init__(self, token=None, session=None):
        tok = token if token is not None else os.environ.get("WEBEX_BOT_TOKEN")
        if not tok:
            raise PermissionError("Webex bot token is unavailable")
        self.token = tok
        self.session = session or requests.Session()

    @property
    def headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
        }

    def get_me(self):
        url = f"{WEBEX_API_BASE}/people/me"
        resp = self.session.get(url, headers=self.headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_message(self, message_id):
        url = f"{WEBEX_API_BASE}/messages/{message_id}"
        resp = self.session.get(url, headers=self.headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def download_file(self, file_url):
        resp = self.session.get(file_url, headers=self.headers, timeout=10)
        resp.raise_for_status()
        return resp.content

    def send_message(self, room_id, text):
        url = f"{WEBEX_API_BASE}/messages"
        headers = {
            **self.headers,
            "Content-Type": "application/json",
        }
        payload = {
            "roomId": room_id,
            "text": text,
        }
        resp = self.session.post(url, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()
