"""Read-only audit for the apartments/houses split."""
from __future__ import annotations
import json
import psycopg2


def scalar(cur, sql, params=()):
    cur.execute(sql, params)
    return cur.fetchone()[0]


def main():
    report, issues = {}, []
    with psycopg2.connect(host='localhost', port=5432, dbname='real_estate', user='admin') as conn, conn.cursor() as cur:
        report['apartments_non_apartment_rows'] = scalar(cur, "SELECT count(*) FROM active_listings WHERE property_type <> 'Квартира'")
        report['houses_non_house_rows'] = scalar(cur, "SELECT count(*) FROM houses_listings WHERE property_type <> 'Будинок'")



        report['shared_active_identity'] = scalar(cur, """SELECT count(*) FROM active_listings apartment JOIN houses_listings house
            ON apartment.source=house.source AND apartment.external_id=house.external_id
            WHERE apartment.status='active' AND house.status='active'""")
        report['apartment_duplicate_identity'] = scalar(cur, """SELECT count(*) FROM (SELECT source,external_id FROM active_listings
            GROUP BY source,external_id HAVING count(*)>1) duplicates""")
        report['house_duplicate_identity'] = scalar(cur, """SELECT count(*) FROM (SELECT source,external_id FROM houses_listings
            GROUP BY source,external_id HAVING count(*)>1) duplicates""")
        report['house_active_invalid_price'] = scalar(cur, "SELECT count(*) FROM houses_listings WHERE status='active' AND (price_uah IS NULL OR price_uah <= 0)")
        report['house_invalid_floor'] = scalar(cur, "SELECT count(*) FROM houses_listings WHERE floor IS NOT NULL AND floors_total IS NOT NULL AND floor > floors_total")
        report['house_orphan_normalized_raw'] = scalar(cur, """SELECT count(*) FROM houses_normalized_listings n
            LEFT JOIN houses_raw_listings r ON r.id=n.raw_listing_id WHERE n.raw_listing_id IS NOT NULL AND r.id IS NULL""")
        report['house_active'] = scalar(cur, "SELECT count(*) FROM houses_listings WHERE status='active'")
        report['apartment_active'] = scalar(cur, "SELECT count(*) FROM active_listings WHERE status='active'")
    for key in ('apartments_non_apartment_rows','houses_non_house_rows','shared_active_identity','apartment_duplicate_identity',
                'house_duplicate_identity','house_active_invalid_price','house_invalid_floor','house_orphan_normalized_raw'):
        if report[key]: issues.append(f'{key}={report[key]}')
    report['issues'] = issues
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(1 if issues else 0)


if __name__ == '__main__': main()
