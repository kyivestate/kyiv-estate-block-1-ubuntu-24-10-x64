from __future__ import annotations

import sys
from pathlib import Path

import psycopg2.extras

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from commercial_v1.persistence import get_connection
from commercial_v1.services.ai_listing_copy import build_description, build_title


def main() -> None:
    with get_connection() as connection:
        with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as read, connection.cursor() as write:
            read.execute("SELECT * FROM commercial_listings WHERE status='active' ORDER BY id")
            rows = read.fetchall()
            for index, row in enumerate(rows, 1):
                values = dict(row)
                write.execute(
                    "UPDATE commercial_listings SET ai_title=%s, ai_description=%s, updated_at=NOW() WHERE id=%s",
                    (build_title(values), build_description(values), row["id"]),
                )
                if index % 200 == 0:
                    connection.commit()
            connection.commit()
    print(f"commercial_ai_rebuilt={len(rows)}")


if __name__ == "__main__":
    main()
