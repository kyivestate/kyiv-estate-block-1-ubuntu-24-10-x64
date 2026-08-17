from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from commercial_v1.persistence import get_connection
from parser_v2.services.currency import currency_service


def main() -> None:
    with get_connection() as connection:
        with connection.cursor() as read, connection.cursor() as write:
            read.execute("""
                SELECT id, price_amount, price_currency
                FROM commercial_listings
                WHERE price_amount IS NOT NULL AND price_currency IN ('UAH', 'USD', 'EUR')
                  AND (price_uah IS NULL OR price_usd IS NULL OR price_eur IS NULL)
            """)
            rows = read.fetchall()
            updated = 0
            for listing_id, amount, currency in rows:
                uah, usd, eur = currency_service.convert(float(amount), currency)
                write.execute(
                    "UPDATE commercial_listings SET price_uah=%s, price_usd=%s, price_eur=%s, updated_at=NOW() WHERE id=%s",
                    (uah, usd, eur, listing_id),
                )
                updated += 1
        print(f"price_backfill_updated={updated}")


if __name__ == "__main__":
    main()
