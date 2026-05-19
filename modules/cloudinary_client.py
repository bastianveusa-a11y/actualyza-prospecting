import os
import requests
from urllib.parse import urlparse

def _creds():
    url = os.getenv("CLOUDINARY_URL", "")
    # cloudinary://api_key:api_secret@cloud_name
    parsed = urlparse(url)
    return parsed.username, parsed.password, parsed.hostname


def upload_video(file_storage, public_id: str) -> str:
    """Upload a video file to Cloudinary. Returns secure_url."""
    api_key, api_secret, cloud_name = _creds()
    endpoint = f"https://api.cloudinary.com/v1_1/{cloud_name}/video/upload"

    file_storage.seek(0)
    r = requests.post(
        endpoint,
        data={"upload_preset": "actualyza_videos", "public_id": public_id},
        files={"file": (public_id + ".mp4", file_storage, "video/mp4")},
        auth=(api_key, api_secret),
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["secure_url"]


def upload_video_unsigned(file_storage, public_id: str) -> str:
    """Upload using signed auth (no preset needed)."""
    import hashlib, time

    api_key, api_secret, cloud_name = _creds()
    timestamp = int(time.time())

    params = {"public_id": public_id, "resource_type": "video", "timestamp": timestamp}
    to_sign = "&".join(f"{k}={v}" for k, v in sorted(params.items())) + api_secret
    sig = hashlib.sha1(to_sign.encode()).hexdigest()

    endpoint = f"https://api.cloudinary.com/v1_1/{cloud_name}/video/upload"
    file_storage.seek(0)
    r = requests.post(
        endpoint,
        data={
            "api_key": api_key,
            "timestamp": timestamp,
            "signature": sig,
            "public_id": public_id,
            "resource_type": "video",
        },
        files={"file": (public_id + ".mp4", file_storage, "video/mp4")},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["secure_url"]
