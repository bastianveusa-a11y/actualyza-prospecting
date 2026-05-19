import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "videos.db"

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
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                slug       TEXT NOT NULL,
                concept    TEXT,
                lang       TEXT NOT NULL,
                config     TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                published  INTEGER DEFAULT 0,
                published_platforms TEXT DEFAULT '[]',
                published_at TEXT
            )
        """)
        db.commit()


def save_video(slug: str, concept: str, lang: str, config: dict):
    """Called when Studio generates a video. Saves to DB."""
    init_db()
    with _conn() as db:
        # upsert by slug+lang
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


def get_platforms():
    return PLATFORMS
