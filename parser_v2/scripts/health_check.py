
"""Daily health report — run every morning."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import psycopg2, psycopg2.extras, subprocess, glob, time

conn = psycopg2.connect(host="localhost", port=5432, dbname="real_estate", user="admin")
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

print("=" * 60)
print(f"  KYIV ESTATE — DAILY HEALTH  {time.strftime('%Y-%m-%d %H:%M')}")
print("=" * 60)


cur.execute("""SELECT status, count(*) FROM active_listings GROUP BY 1 ORDER BY 2 DESC""")
print("\n📊 STATUS:")
for r in cur.fetchall(): print(f"  {r['status']}: {r['count']}")

cur.execute("""SELECT
  round(avg(data_completeness),1) as avg_score,
  count(*) FILTER (WHERE data_completeness >= 90) as premium,
  count(*) FILTER (WHERE data_completeness < 50) as weak
FROM active_listings WHERE status='active'""")
r = cur.fetchone()
print(f"\n💎 QUALITY: avg={r['avg_score']} premium={r['premium']} weak={r['weak']}")

cur.execute("""SELECT count(*) as stale FROM active_listings
  WHERE status='active' AND updated_at < NOW() - INTERVAL '7 days'""")
print(f"⏰ STALE >7d: {cur.fetchone()['stale']}")

cur.execute("""SELECT count(*) FILTER (WHERE ai_title IS NOT NULL AND ai_title != '') as ai,
  count(*) as total FROM active_listings WHERE status='active'""")
r = cur.fetchone()
print(f"📝 AI: {r['ai']}/{r['total']}")


print("\n🚩 RED FLAGS:")
flags = 0
cur.execute("SELECT count(*) as c FROM active_listings WHERE status='active' AND price_uah IS NULL")
c = cur.fetchone()['c']
if c > 0: print(f"  ❌ {c} без ціни"); flags += 1
cur.execute("""SELECT count(*) as c FROM (SELECT url FROM active_listings WHERE status='active' AND url IS NOT NULL GROUP BY url HAVING count(*)>1) x""")
c = cur.fetchone()['c']
if c > 0: print(f"  ❌ {c} URL дублікатів"); flags += 1


project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
backups = glob.glob(os.path.join(project_root, "backups", "production", "*.dump"))
if not backups: print("  ❌ НЕМАЄ БЕКАПІВ"); flags += 1
else:
    newest = max(backups, key=os.path.getmtime)
    age_h = (time.time() - os.path.getmtime(newest)) / 3600
    if age_h > 48: print(f"  ⚠️ Бекап старіше 48г ({age_h:.0f}г)"); flags += 1
if flags == 0: print("  ✅ Все чисто")

cur.close(); conn.close()
print("=" * 60)
