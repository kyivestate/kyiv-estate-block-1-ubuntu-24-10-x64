from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from commercial_v1.persistence import get_connection


def main() -> None:
    schema = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(schema.read_text())
    print("commercial_v1 schema is ready")


if __name__ == "__main__":
    main()
