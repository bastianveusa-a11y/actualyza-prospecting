import os
import requests

BASE = "https://api.bufferapp.com/1"


def _token():
    return os.getenv("BUFFER_ACCESS_TOKEN", "")


def get_profiles() -> list:
    """Returns list of connected Buffer profiles/channels."""
    r = requests.get(f"{BASE}/profiles.json", params={"access_token": _token()}, timeout=15)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, list):
        return [
            {
                "id": p["id"],
                "service": p.get("service", ""),
                "name": p.get("formatted_service", p.get("service_username", p["id"])),
                "username": p.get("service_username", ""),
            }
            for p in data
        ]
    return []


def create_post(profile_ids: list, text: str, video_url: str, now: bool = False) -> dict:
    """
    Create a Buffer post with a video URL.
    profile_ids: list of Buffer profile IDs to post to.
    now: True = publish immediately, False = add to queue.
    """
    data = {
        "text": text,
        "now": "true" if now else "false",
        "access_token": _token(),
    }
    # Buffer v1 accepts repeated keys for arrays
    for pid in profile_ids:
        data.setdefault("profile_ids[]", [])
        if isinstance(data["profile_ids[]"], list):
            data["profile_ids[]"].append(pid)
        else:
            data["profile_ids[]"] = [data["profile_ids[]"], pid]

    if video_url:
        data["media[video]"] = video_url

    r = requests.post(
        f"{BASE}/updates/create.json",
        data=_flatten(data),
        timeout=30,
    )
    return r.json()


def _flatten(d: dict) -> list:
    """Convert dict with list values into list of (key, value) tuples for requests."""
    items = []
    for k, v in d.items():
        if isinstance(v, list):
            for item in v:
                items.append((k, item))
        else:
            items.append((k, v))
    return items
