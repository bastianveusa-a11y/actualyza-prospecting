import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "videos.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# EST = UTC-5  (covers Miami/Dallas/Orlando)
EST = timezone(timedelta(hours=-5))

# Fixed daily slots: EN at 8am EST, ES at 8pm EST
SLOT_HOURS = {"en": 8, "es": 20}

PLATFORMS = [
    {"id": "instagram", "label": "Instagram Reels", "icon": "📸", "color": "#E1306C",
     "url": "https://buffer.com/instagram"},
    {"id": "facebook",  "label": "Facebook Page",   "icon": "👥", "color": "#1877F2",
     "url": "https://buffer.com/facebook"},
    {"id": "tiktok",    "label": "TikTok",          "icon": "🎵", "color": "#010101",
     "url": "https://buffer.com/tiktok"},
    {"id": "youtube",   "label": "YouTube Shorts",  "icon": "▶️", "color": "#FF0000",
     "url": "https://buffer.com/youtube"},
]


def _conn():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def init_db():
    with _conn() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                slug                TEXT NOT NULL,
                concept             TEXT,
                lang                TEXT NOT NULL,
                config              TEXT NOT NULL,
                created_at          TEXT DEFAULT (datetime('now')),
                published           INTEGER DEFAULT 0,
                published_platforms TEXT DEFAULT '[]',
                published_at        TEXT,
                cloud_url           TEXT,
                scheduled_at        TEXT,
                buffer_post_id      TEXT
            )
        """)
        for col in ("cloud_url TEXT", "scheduled_at TEXT", "buffer_post_id TEXT"):
            try:
                db.execute(f"ALTER TABLE videos ADD COLUMN {col}")
            except Exception:
                pass
        db.commit()


def save_video(slug: str, concept: str, lang: str, config: dict):
    init_db()
    with _conn() as db:
        existing = db.execute(
            "SELECT id FROM videos WHERE slug=? AND lang=?", (slug, lang)
        ).fetchone()
        if existing:
            db.execute(
                "UPDATE videos SET concept=?, config=?, created_at=datetime('now') WHERE id=?",
                (concept, json.dumps(config), existing["id"])
            )
        else:
            db.execute(
                "INSERT INTO videos (slug, concept, lang, config) VALUES (?,?,?,?)",
                (slug, concept, lang, json.dumps(config))
            )
        db.commit()


def get_videos(limit=50):
    init_db()
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM videos ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    result = []
    for r in rows:
        v = dict(r)
        v["config"] = json.loads(v["config"])
        v["published_platforms"] = json.loads(v["published_platforms"] or "[]")
        result.append(v)
    return result


def mark_published(video_id: int, platforms: list):
    init_db()
    with _conn() as db:
        db.execute(
            """UPDATE videos
               SET published=1, published_platforms=?, published_at=datetime('now')
               WHERE id=?""",
            (json.dumps(platforms), video_id)
        )
        db.commit()


def save_cloud_url(video_id: int, cloud_url: str):
    init_db()
    with _conn() as db:
        db.execute("UPDATE videos SET cloud_url=? WHERE id=?", (cloud_url, video_id))
        db.commit()


def save_scheduled(video_id: int, scheduled_at: str, buffer_post_id: str = ""):
    init_db()
    with _conn() as db:
        db.execute(
            "UPDATE videos SET scheduled_at=?, buffer_post_id=? WHERE id=?",
            (scheduled_at, buffer_post_id, video_id)
        )
        db.commit()


def get_next_slot(lang: str) -> datetime:
    """Returns next free Buffer slot for this lang in UTC.
    EN = 8:00 AM EST daily, ES = 8:00 PM EST daily.
    Skips dates already taken.
    """
    init_db()
    hour = SLOT_HOURS.get(lang, 8)
    now_est = datetime.now(EST)

    # Build candidate starting today or tomorrow
    candidate = now_est.replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate <= now_est + timedelta(hours=1):
        candidate += timedelta(days=1)

    # Collect already-scheduled dates for this lang
    with _conn() as db:
        rows = db.execute(
            "SELECT scheduled_at FROM videos WHERE scheduled_at IS NOT NULL AND lang=?", (lang,)
        ).fetchall()
    taken = {r["scheduled_at"][:10] for r in rows if r["scheduled_at"]}

    while candidate.strftime("%Y-%m-%d") in taken:
        candidate += timedelta(days=1)

    return candidate.astimezone(timezone.utc)


def get_platforms():
    return PLATFORMS
