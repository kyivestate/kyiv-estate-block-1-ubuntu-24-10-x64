
"""Post-run validation for Parser V2."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import psycopg2, psycopg2.extras
from parser_v2.services.persistence import get_conn
from parser_v2.services.logging_setup import get_logger
log = get_logger("validate")

def main():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    issues = []
    print("=" * 60)
    print("  PARSER V2 — VALIDATION REPORT")
    print("=" * 60)


    cur.execute("""SELECT source, operation, status, count(*) as cnt
        FROM active_listings GROUP BY 1,2,3 ORDER BY 1,2,3""")
    print("\n📊 active_listings:")
    for r in cur.fetchall():
        print(f"  {r['source']:12} {r['operation']:6} {r['status']:10} {r['cnt']:>6}")


    cur.execute("""SELECT source, operation, count(*) as total,
        count(*) FILTER (WHERE rooms IS NOT NULL) as rooms,
        count(*) FILTER (WHERE area IS NOT NULL) as area,
        count(*) FILTER (WHERE floor IS NOT NULL) as floor,
        count(*) FILTER (WHERE district != '') as district,
        count(*) FILTER (WHERE photo_url != '') as photo,
        count(*) FILTER (WHERE price_uah IS NOT NULL) as price
        FROM parser_v2_normalized_listings WHERE is_valid=true GROUP BY 1,2""")
    rows = cur.fetchall()
    print("\n📊 v2_normalized (is_valid=true):")
    print(f"  {'source':12} {'op':6} {'total':>6} {'rooms':>6} {'area':>6} {'floor':>6} {'dist':>6} {'photo':>6} {'price':>6}")
    for r in rows:
        print(f"  {r['source']:12} {r['operation']:6} {r['total']:>6} {r['rooms']:>6} {r['area']:>6} {r['floor']:>6} {r['district']:>6} {r['photo']:>6} {r['price']:>6}")
        if r['total'] > 0:
            pct_rooms = r['rooms'] / r['total'] * 100
            pct_price = r['price'] / r['total'] * 100
            if pct_rooms < 50: issues.append(f"{r['source']}/{r['operation']}: rooms fill rate {pct_rooms:.0f}%")
            if pct_price < 90: issues.append(f"{r['source']}/{r['operation']}: price fill rate {pct_price:.0f}%")


    cur.execute("""SELECT count(*) as cnt FROM active_listings WHERE source LIKE 'findly%'""")
    findly = cur.fetchone()['cnt']
    print(f"\n🛡️ Findly rows: {findly} (NEVER modified by v2)")
    if findly == 0:
        print("  ⚠️  No findly rows found (expected if project never had findly)")


    cur.execute("""SELECT count(*) as cnt FROM active_listings
        WHERE operation NOT IN ('rent','buy')""")
    bad_ops = cur.fetchone()['cnt']
    if bad_ops > 0:
        issues.append(f"{bad_ops} rows with invalid operation (not rent/buy)")
    print(f"\n🔍 Invalid operations: {bad_ops}")


    cur.execute("""SELECT source, operation, count(*) as cnt
        FROM active_listings WHERE status='active' AND price_uah IS NULL
        GROUP BY 1,2""")
    null_prices = cur.fetchall()
    if null_prices:
        print("\n⚠️ Active listings without price_uah:")
        for r in null_prices:
            print(f"  {r['source']:12} {r['operation']:6} {r['cnt']:>6}")


    cur.execute("""SELECT source,
        count(*) as total,
        count(*) FILTER (WHERE photo_url IS NOT NULL AND photo_url != '') as has_photo
        FROM active_listings WHERE status='active' GROUP BY 1""")
    print("\n📸 Photo coverage:")
    for r in cur.fetchall():
        pct = r['has_photo'] / r['total'] * 100 if r['total'] > 0 else 0
        print(f"  {r['source']:12} {r['has_photo']:>6}/{r['total']:>6} ({pct:.0f}%)")


    cur.execute("""SELECT source, count(*) as cnt, max(parsed_at)::text as last_parsed
        FROM parser_v2_normalized_listings GROUP BY 1""")
    print("\n🕐 V2 parse activity:")
    for r in cur.fetchall():
        print(f"  {r['source']:12} {r['cnt']:>6} listings, last: {r['last_parsed'] or 'never'}")


    print("\n" + "=" * 60)
    if issues:
        print(f"⚠️  {len(issues)} ISSUES:")
        for i in issues: print(f"  - {i}")
    else:
        print("✅ ALL CHECKS PASSED")
    print("=" * 60)

    cur.close(); conn.close()

if __name__ == "__main__": main()
