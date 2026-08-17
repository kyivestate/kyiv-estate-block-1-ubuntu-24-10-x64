from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from commercial_v1.normalizers import _areas
from commercial_v1.persistence import get_connection


def main() -> None:
    with get_connection() as connection:
        with connection.cursor() as read, connection.cursor() as write:
            read.execute("""
                SELECT id, title, description, area_total_m2, area_usable_m2
                FROM commercial_listings
            """)
            updated = 0
            for listing_id, title, description, total, usable in read.fetchall():
                extracted_total, extracted_usable = _areas({}, f"{title or ''} {description or ''}")
                new_total = total if total is not None and total >= 5 else extracted_total
                new_usable = extracted_usable if extracted_usable is not None else usable
                if extracted_usable is None and usable == total:
                    new_usable = None
                if new_total != total or new_usable != usable:
                    write.execute(
                        "UPDATE commercial_listings SET area_total_m2=%s, area_usable_m2=%s, updated_at=NOW() WHERE id=%s",
                        (new_total, new_usable, listing_id),
                    )
                    updated += 1
    print(f"areas_from_text_updated={updated}")


if __name__ == "__main__":
    main()
