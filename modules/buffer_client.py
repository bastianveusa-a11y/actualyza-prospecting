import os
import requests

BASE = "https://api.bufferapp.com/1"


def _headers():
    token = os.getenv("BUFFER_ACCESS_TOKEN", "")
    return {"Authorization": f"Bearer {token}"}


def get_profiles() -> list:
    """Returns list of connected Buffer profiles/channels."""
    r = requests.get(f"{BASE}/profiles.json", headers=_headers(), timeout=15)
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


def create_post(profile_ids: list, text: str, video_url: str,
                now: bool = False, scheduled_at: str = None) -> dict:
    """Create a Buffer post. scheduled_at is ISO 8601 string; if None and now=False, adds to queue."""
    params = [("text", text)]
    for pid in profile_ids:
        params.append(("profile_ids[]", pid))
    if video_url:
        params.append(("media[video]", video_url))
    if scheduled_at:
        params.append(("scheduled_at", scheduled_at))
        params.append(("now", "false"))
    else:
        params.append(("now", "true" if now else "false"))

    r = requests.post(
        f"{BASE}/updates/create.json",
        data=params,
        headers=_headers(),
        timeout=30,
    )
    return r.json()
