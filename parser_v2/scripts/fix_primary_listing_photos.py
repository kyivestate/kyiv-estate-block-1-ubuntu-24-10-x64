from __future__ import annotations

import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from commercial_v1.persistence import get_connection as commercial_connection
from parser_v2.services.photo_selection import select_property_photo, select_property_photos


RESIDENTIAL_DB = {"host": "localhost", "port": 5432, "dbname": "real_estate", "user": "admin"}


def repair_residential() -> int:
    with psycopg2.connect(**RESIDENTIAL_DB) as connection:
        with connection.cursor() as read, connection.cursor() as write:
            read.execute("""
                SELECT id, photo_url, photos
                FROM active_listings WHERE status='active'
            """)
            updated = 0
            for listing_id, photo_url, photos in read.fetchall():
                ordered = select_property_photos(photos or [], photo_url)
                primary = select_property_photo(ordered)
                if not primary and not photo_url:
                    continue
                if primary == photo_url and ordered == (photos or []):
                    continue
                write.execute(
                    "UPDATE active_listings SET photo_url=%s, photos=%s, updated_at=NOW() WHERE id=%s",
                    (primary, ordered, listing_id),
                )
                updated += 1
    return updated


def repair_commercial() -> int:
    with commercial_connection() as connection:
        with connection.cursor() as read, connection.cursor() as write:
            read.execute("SELECT id, photo_url, photos FROM commercial_listings WHERE status='active'")
            updated = 0
            for listing_id, photo_url, photos in read.fetchall():
                ordered = select_property_photos(photos or [], photo_url)
                primary = select_property_photo(ordered)
                if not primary and not photo_url:
                    continue
                if primary == photo_url and ordered == (photos or []):
                    continue
                write.execute(
                    "UPDATE commercial_listings SET photo_url=%s, photos=%s, updated_at=NOW() WHERE id=%s",
                    (primary, ordered, listing_id),
                )
                updated += 1
    return updated


def repair_houses() -> int:
    with psycopg2.connect(**RESIDENTIAL_DB) as connection:
        with connection.cursor() as read, connection.cursor() as write:
            read.execute("SELECT id, photo_url, photos FROM houses_listings WHERE status='active'")
            updated = 0
            for listing_id, photo_url, photos in read.fetchall():
                ordered = select_property_photos(photos or [], photo_url)
                primary = select_property_photo(ordered)
                if primary == photo_url and ordered == (photos or []):
                    continue
                write.execute("UPDATE houses_listings SET photo_url=%s, photos=%s, updated_at=NOW() WHERE id=%s", (primary, ordered, listing_id))
                updated += 1
    return updated


def prune_gone_sources() -> dict[str, int]:
    """Remove only source images confirmed 404/410 by the local archivist."""
    with psycopg2.connect(**RESIDENTIAL_DB) as connection:
        with connection.cursor() as cur:
            cur.execute("SELECT source_url FROM block3.media_archive WHERE status='gone'")
            gone = {row[0] for row in cur.fetchall()}
        result = {}
        for table in ("active_listings", "houses_listings", "commercial_listings"):
            with connection.cursor() as read, connection.cursor() as write:
                read.execute(f"SELECT id,photo_url,photos FROM {table} WHERE status='active'")
                changed = 0
                for listing_id, photo_url, photos in read.fetchall():
                    remaining = [url for url in (photos or []) if url not in gone]
                    preferred = "" if photo_url in gone else photo_url
                    ordered = select_property_photos(remaining, preferred)
                    primary = select_property_photo(ordered)
                    if primary == photo_url and ordered == (photos or []):
                        continue
                    write.execute(f"UPDATE {table} SET photo_url=%s, photos=%s, updated_at=NOW() WHERE id=%s", (primary, ordered, listing_id))
                    changed += 1
                result[table] = changed
    return result


def main() -> None:
    print(f"residential_photo_primary_fixed={repair_residential()}")
    print(f"houses_photo_primary_fixed={repair_houses()}")
    print(f"commercial_photo_primary_fixed={repair_commercial()}")
    print(f"gone_source_photos_pruned={prune_gone_sources()}")


if __name__ == "__main__":
    main()
