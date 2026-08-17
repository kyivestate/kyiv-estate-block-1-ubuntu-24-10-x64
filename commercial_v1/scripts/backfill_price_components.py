from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from commercial_v1.normalizers import price_from_listing
from commercial_v1.persistence import get_connection
from parser_v2.services.currency import currency_service


def main() -> None:
    with get_connection() as connection:
        with connection.cursor() as read, connection.cursor() as write:
            read.execute("""
                SELECT id, source_price_raw, title, description, operation, area_total_m2
                FROM commercial_listings
                WHERE source_price_raw <> ''
            """)
            updated = skipped = 0
            for listing_id, raw_price, title, description, operation, area_m2 in read.fetchall():
                total, currency, total_period, per_m2, per_m2_currency, per_m2_period = price_from_listing(raw_price, title or "", description or "", operation, float(area_m2) if area_m2 else None)
                if (currency not in {"UAH", "USD", "EUR"} and per_m2_currency not in {"UAH", "USD", "EUR"}) or (total is None and per_m2 is None):
                    skipped += 1
                    continue
                total_values = currency_service.convert(total, currency) if total is not None and currency in {"UAH", "USD", "EUR"} else (None, None, None)
                per_m2_values = currency_service.convert(per_m2, per_m2_currency) if per_m2 is not None and per_m2_currency in {"UAH", "USD", "EUR"} else (None, None, None)
                write.execute("""
                    UPDATE commercial_listings
                    SET price_amount=%s, price_currency=%s, price_period=%s,
                        price_uah=%s, price_usd=%s, price_eur=%s,
                        price_per_m2=%s, price_per_m2_currency=%s, price_per_m2_uah=%s, price_per_m2_usd=%s, price_per_m2_eur=%s,
                        price_per_m2_period=%s, updated_at=NOW()
                    WHERE id=%s
                """, (total, currency, total_period, *total_values, per_m2, per_m2_currency, *per_m2_values, per_m2_period, listing_id))
                updated += 1
    print(f"price_components_updated={updated} skipped={skipped}")


if __name__ == "__main__":
    main()
