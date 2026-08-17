
"""Professional listing quality filter — validates ALL active listings.
Rules -> quarantine with reason. Run anytime, idempotent."""
import sys, os, time, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import psycopg2, psycopg2.extras

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("qfilter")

conn = psycopg2.connect(host="localhost", port=5432, dbname="real_estate", user="admin")
cur = conn.cursor()

RULES = [

    ("rent_price_too_high",
     "operation='rent' AND price_uah > 500000"),
    ("rent_price_too_low",
     "operation='rent' AND price_uah < 20000"),
    ("buy_price_too_low",
     "operation='buy' AND price_usd < 60000"),
    ("buy_price_too_high",
     "operation='buy' AND price_usd > 5000000"),
    ("no_price",
     "price_uah IS NULL AND price_usd IS NULL"),

    ("rent_price_per_m2_anomaly",
     "operation='rent' AND area IS NOT NULL AND area > 10 AND (price_uah/area < 150 OR price_uah/area > 6000)"),
    ("buy_price_per_m2_anomaly",
     "operation='buy' AND area IS NOT NULL AND area > 10 AND (price_usd/area < 500 OR price_usd/area > 15000)"),

    ("area_rooms_mismatch",
     "rooms >= 3 AND area IS NOT NULL AND area < 40"),
    ("area_too_small",
     "area IS NOT NULL AND area < 11"),
    ("area_too_big",
     "area IS NOT NULL AND area > 800"),

    ("floor_above_total",
     "floor IS NOT NULL AND floors_total IS NOT NULL AND floor > floors_total"),

    ("garbage_title",
     "title IS NOT NULL AND (LENGTH(TRIM(title)) < 10 OR title ILIKE '%%тест%%' OR title ILIKE '%%test%%')"),

    ("not_kyiv",
     "city IS NOT NULL AND city NOT IN ('Київ','Киев','Kyiv','') AND city NOT LIKE 'Київ%%'"),

    ("not_apartment",
     "property_type IS NOT NULL AND property_type NOT IN ('Квартира','apartment','квартира','Будинок','house','будинок','')"),
]

log.info("=" * 60)
log.info("PROFESSIONAL QUALITY FILTER — %s", time.strftime("%Y-%m-%d %H:%M"))
log.info("=" * 60)

total_q = 0
for name, cond in RULES:
    cur.execute(f"""UPDATE active_listings
        SET status='quarantine', comments=%s
        WHERE status='active' AND source NOT LIKE 'findly%%' AND ({cond})""", (name,))
    n = cur.rowcount
    total_q += n
    if n > 0:
        log.info("  🔸 %s: %d -> quarantine", name, n)
conn.commit()


cur.execute("""UPDATE active_listings SET status='active', comments=NULL
    WHERE status='quarantine' AND source NOT LIKE 'findly%%'
      AND comments IN ('rent_price_too_high','buy_price_too_low','no_price','price_anomaly_rent_high','price_below_filter','price_anomaly_buy_high')
      AND price_uah IS NOT NULL
      AND ((operation='rent' AND price_uah BETWEEN 20000 AND 500000)
        OR (operation='buy' AND price_usd BETWEEN 60000 AND 5000000))""")
restored = cur.rowcount
conn.commit()

cur.execute("""UPDATE active_listings SET status='active', comments=NULL
    WHERE status='quarantine' AND source NOT LIKE 'findly%%'
      AND comments='not_apartment'
      AND property_type IN ('Будинок','house','будинок')""")
restored += cur.rowcount
conn.commit()


cur.execute("""UPDATE active_listings SET status='quarantine', comments='cross_source_duplicate'
    WHERE id IN (
      SELECT a.id FROM active_listings a
      JOIN active_listings b ON a.title = b.title
        AND COALESCE(a.area,0) = COALESCE(b.area,0)
        AND COALESCE(a.district,'') = COALESCE(b.district,'')
        AND COALESCE(a.price_uah,0) = COALESCE(b.price_uah,0)
        AND regexp_replace(COALESCE(a.agent_phone,''), '\\D', '', 'g') = regexp_replace(COALESCE(b.agent_phone,''), '\\D', '', 'g')
        AND length(regexp_replace(COALESCE(a.agent_phone,''), '\\D', '', 'g')) >= 10
        AND a.operation = b.operation
        AND a.id > b.id
        AND a.source != b.source
      WHERE a.status='active' AND b.status='active'
        AND a.source NOT LIKE 'findly%%' AND b.source NOT LIKE 'findly%%'
        AND LENGTH(a.title) > 20
    )""")
dupes = cur.rowcount
conn.commit()


log.info("-" * 60)
log.info("  Quarantined: %d | Restored: %d | Cross-source dupes: %d", total_q, restored, dupes)

cur.execute("SELECT status, count(*) FROM active_listings GROUP BY 1 ORDER BY 2 DESC")
log.info("  STATUS: %s", ", ".join(f"{r[0]}={r[1]}" for r in cur.fetchall()))

cur.execute("""SELECT comments, count(*) FROM active_listings
    WHERE status='quarantine' GROUP BY 1 ORDER BY 2 DESC LIMIT 10""")
log.info("  QUARANTINE REASONS:")
for r in cur.fetchall():
    log.info("    %s: %d", r[0], r[1])


cur.execute("""SELECT count(*) as total,
    round(avg(data_completeness),1) as avg_q,
    count(*) FILTER (WHERE data_completeness >= 90) as premium
    FROM active_listings WHERE status='active' AND source NOT LIKE 'findly%%'""")
r = cur.fetchone()
log.info("  ACTIVE BASE: %d listings, avg quality %s, premium %d", r[0], r[1], r[2])

cur.close(); conn.close()
log.info("✅ FILTER COMPLETE")
