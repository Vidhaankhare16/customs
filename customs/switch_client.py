"""A small Switch agent-protocol client, standard library only.

The clerk only needs the parts of the protocol that every server version supports: registering, reading a
room's history, room details and posting. It polls rather than holding an event stream open. That makes it
`session_passive` in Switch's terms: messages addressed to it wait until its next read (every couple of
seconds), and a restart loses nothing because history is read from the server.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone


class SwitchError(RuntimeError):
    def __init__(self, status: int, detail: str, path: str):
        super().__init__(f"{path}: HTTP {status}: {detail[:300]}")
        self.status = status
        self.detail = detail
        self.path = path


@dataclass
class Credentials:
    base_url: str
    agent_id: str
    api_key: str


def _request(method: str, url: str, token: str | None, body: dict | None = None, timeout: float = 30) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json", "User-Agent": "customs-clerk/0.1"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raise SwitchError(exc.code, exc.read().decode("utf-8", "replace"), url) from None


def health(base_url: str) -> bool:
    try:
        _request("GET", base_url.rstrip("/") + "/health", None, timeout=5)
        return True
    except (SwitchError, OSError):
        return False


def register(base_url: str, registration_key: str, name: str, description: str, overwrite: bool = False) -> Credentials:
    body = {
        "name": name,
        "description": description,
        "connector_type": "customs-clerk",
        "integration_profile": {
            "connection_model": "session_passive",
            "message_exchange": True,
            "pre_invocation_mediation": [],
            "post_invocation_mediation": [],
            "event_reporting": [],
        },
    }
    if overwrite:
        body["overwrite"] = True
    result = _request("POST", base_url.rstrip("/") + "/agents", registration_key, body)
    return Credentials(base_url.rstrip("/"), result["id"], result["api_key"])


class SwitchClient:
    def __init__(self, creds: Credentials):
        self.creds = creds

    def _url(self, path: str) -> str:
        return f"{self.creds.base_url}/agents/{self.creds.agent_id}{path}"

    def op(self, name: str, **args) -> object:
        return _request("POST", self._url(f"/ops/{name}"), self.creds.api_key, args).get("result")

    def list_rooms(self) -> list[dict]:
        return self.op("list_rooms")

    def room_detail(self, room_id: str) -> dict:
        return self.op("get_room_detail", room_id=room_id)

    def read_context(self, room_id: str, since: datetime | None = None, limit: int = 50) -> dict:
        args: dict = {"room_id": room_id, "limit": limit}
        if since is not None:
            args["since"] = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return self.op("read_context", **args)

    def post(self, room_id: str, content: str) -> dict:
        return _request("POST", self._url("/message"), self.creds.api_key, {"room_id": room_id, "content": content})


def flatten(context: dict) -> list[dict]:
    """read_context groups messages into threads; the clerk wants them in time order."""
    entries = []
    for thread in context.get("threads", []):
        entries.append(thread["root"])
        entries.extend(thread.get("replies", []))
    return sorted((e for e in entries if e.get("kind", "message") == "message"), key=lambda e: e.get("timestamp", 0))
