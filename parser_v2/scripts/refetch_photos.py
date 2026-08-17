
import sys, os, time, re, logging, argparse, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import psycopg2, psycopg2.extras
from parser_v2.services.http_client import OlxHttpClient, RieltorHttpClient
from bs4 import BeautifulSoup
from parser_v2.services.photo_selection import select_property_photo, select_property_photos

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("refetch")

def photos_from_html(html, source):
    soup = BeautifulSoup(html, "lxml")
    urls = []
    if source == "rieltor":
        for img in soup.select("img"):
            src = img.get("src") or img.get("data-src") or ""
            if "riel" in src and src.startswith("http") and src not in urls:
                urls.append(src)
        for og in soup.find_all("meta", property="og:image"):
            cx = og.get("content","")
            if cx.startswith("http") and cx not in urls: urls.insert(0, cx)
    else:
        raw = html.replace("\\u002F","/").replace("\\/","/")
        for m in re.finditer(r"https://ireland\.apollo\.olxcdn\.com:?\d*/v1/files/[A-Za-z0-9\-_]+/image(?:;s=\d+x\d+)?", raw):
            u = m.group(0)
            base = u.split(";")[0]
            full = base + ";s=1000x700"
            if full not in urls: urls.append(full)
        for og in soup.find_all("meta", property="og:image"):
            cx = og.get("content","")
            if cx.startswith("http") and cx.split(";")[0]+";s=1000x700" not in urls and cx not in urls:
                urls.insert(0, cx)
    return select_property_photos(urls)[:30]

def run(source, empty_only: bool = False, limit: int | None = None):
    conn = psycopg2.connect(host="localhost", port=5432, dbname="real_estate", user="admin")
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    w = conn.cursor()
    condition = "(coalesce(photo_url,'')='')" if empty_only else "(photos IS NULL OR array_length(photos,1) IS NULL OR array_length(photos,1) < 3)"
    query = "SELECT id, url FROM active_listings WHERE status='active' AND source=%s AND url LIKE 'http%%' AND " + condition + " ORDER BY data_completeness DESC NULLS LAST"
    params = [source]
    if limit:
        query += " LIMIT %s"; params.append(limit)
    cur.execute(query, params)
    rows = cur.fetchall()
    log.info("%s: %d need photo refetch", source, len(rows))
    http = OlxHttpClient(timeout=30) if source=="olx" else RieltorHttpClient(timeout=30)
    http._min_delay = 0.5 if source=="olx" else 4.0
    st = {"upd":0,"dead":0,"f":0}
    t0 = time.time()
    for i, r in enumerate(rows, 1):
        try:
            status, html = http.get(r["url"])
            if status in (404, 410):
                w.execute("UPDATE active_listings SET status='inactive' WHERE id=%s", (r["id"],))
                conn.commit(); st["dead"] += 1; continue
            if status != 200: st["f"] += 1; continue
            ph = photos_from_html(html, source)
            if ph:
                w.execute("UPDATE active_listings SET photos=%s, photo_url=%s WHERE id=%s", (ph, select_property_photo(ph), r["id"]))
                conn.commit(); st["upd"] += 1
        except Exception: st["f"] += 1
        if i % 50 == 0:
            rate = i/(time.time()-t0)
            log.info("%s [%d/%d] upd=%d dead=%d f=%d (%.1f/s ETA %.0fm)", source, i, len(rows), st["upd"], st["dead"], st["f"], rate, (len(rows)-i)/rate/60)
    log.info("%s DONE %s", source, st)
    conn.close()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--empty-only", action="store_true", help="Repair only listings with no usable primary image.")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    run(args.source, args.empty_only, args.limit)
