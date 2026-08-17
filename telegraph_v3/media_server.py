#!/usr/bin/env python3
"""Read-only local web server for the durable Kyiv Estate media archive."""
from __future__ import annotations

import mimetypes
import os
import html
from pathlib import Path

import psycopg2
import psycopg2.extras
from flask import Flask, abort, make_response, send_file

ROOT = Path(os.getenv("MEDIA_ARCHIVE_ROOT", "/Users/admin/KyivEstateMedia")).resolve()
PUBLIC_BASE = os.getenv("MEDIA_PUBLIC_BASE", "https://macbook-pro-4.taila50e89.ts.net").rstrip("/")
TABLES = {
    "apartments": "active_listings",
    "houses": "houses_listings",
    "commercial": "commercial_listings",
}
app = Flask(__name__)


def database():
    return psycopg2.connect(
        host=os.getenv("PG_HOST", "/tmp"), port=os.getenv("PG_PORT", "5432"),
        dbname=os.getenv("PG_DBNAME", "real_estate"), user=os.getenv("PG_USER", "admin"),
        password=os.getenv("PG_PASSWORD", ""),
    )


def text(value: object) -> str:
    """Escape listing text for HTML without trusting a source page."""
    return html.escape(str(value or "").strip())


def photo_urls(row: dict) -> list[str]:
    values = row.get("photos") or []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        values = []
    if row.get("photo_url"):
        values.append(row["photo_url"])
    result, seen = [], set()
    for value in values:
        value = str(value or "").strip()
        if value.startswith("https://") and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def listing_row(catalog: str, listing_id: int) -> dict:
    table = TABLES.get(catalog)
    if not table:
        abort(404)
    try:
        with database() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"SELECT to_jsonb(l) AS item FROM {table} l WHERE l.id=%s AND l.status='active'", (listing_id,))
            found = cur.fetchone()
            if not found:
                abort(404)
            return dict(found["item"])
    except psycopg2.Error:
        abort(503)


def durable_photos(urls: list[str]) -> dict[str, str]:
    if not urls:
        return {}
    try:
        with database() as conn, conn.cursor() as cur:
            cur.execute("""SELECT source_url,storage_key FROM block3.media_archive
                           WHERE status='archived' AND source_url = ANY(%s)""", (urls,))
            return {source: f"{PUBLIC_BASE}/files/{key.lstrip('/')}" for source, key in cur.fetchall() if key}
    except psycopg2.Error:
        return {}


@app.get("/healthz")
def healthz():
    return {"ok": True, "root": str(ROOT)}


@app.get("/files/<path:key>")
def image(key: str):
    path = (ROOT / "files" / key).resolve()
    if ROOT not in path.parents or not path.is_file():
        abort(404)
    return send_file(path, mimetype=mimetypes.guess_type(path.name)[0], conditional=True, max_age=31536000)


@app.get("/listing/<catalog>/<int:listing_id>")
def listing(catalog: str, listing_id: int):
    """Public, read-only listing card backed by the authoritative database."""
    row = listing_row(catalog, listing_id)
    urls = photo_urls(row)
    archived = durable_photos(urls)
    images = [archived.get(source, source) for source in urls]
    title = str(row.get("ai_title") or row.get("title") or f"KYIV ESTATE #{listing_id}")
    description = str(row.get("ai_description") or row.get("description") or "")
    price = next((row.get(key) for key in ("price_uah", "price_usd", "price_eur") if row.get(key) is not None), "За запитом")
    facts = [
        ("Тип", {"apartments": "Квартира", "houses": "Будинок", "commercial": "Комерційна нерухомість"}[catalog]),
        ("Операція", "Оренда" if row.get("operation") == "rent" else "Продаж"),
        ("Ціна", price),
        ("Площа", row.get("area_total_m2") or row.get("area")),
        ("Кімнати", row.get("rooms")),
        ("Адреса", row.get("full_address") or row.get("street") or row.get("district") or row.get("city")),
    ]
    facts_html = "".join(f"<div><b>{text(label)}</b><span>{text(value)}</span></div>" for label, value in facts if value not in (None, ""))
    photos_html = "".join(f'<img loading="lazy" src="{html.escape(source, quote=True)}" alt="{text(title)}">' for source in images)
    page = f"""<!doctype html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{text(title)} | KYIV ESTATE</title><style>
body{{margin:0;background:#f6f7f9;color:#18202a;font:16px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}main{{max-width:1100px;margin:auto;padding:24px}}h1{{font-size:clamp(24px,4vw,42px);margin:8px 0}}.brand{{color:#7a5718;font-weight:700;letter-spacing:.08em}}.facts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin:20px 0}}.facts div{{background:#fff;border-radius:10px;padding:12px;box-shadow:0 1px 3px #0001}}.facts b,.facts span{{display:block}}.facts b{{font-size:12px;color:#687381;text-transform:uppercase;margin-bottom:4px}}.description{{white-space:pre-line;line-height:1.6;background:#fff;padding:20px;border-radius:12px}}.photos{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin-top:20px}}.photos img{{width:100%;height:260px;object-fit:cover;border-radius:12px;background:#e8ebef}}footer{{padding:28px 0;color:#687381}}@media(max-width:600px){{main{{padding:14px}}.photos{{grid-template-columns:1fr}}}}</style></head>
<body><main><div class="brand">KYIV ESTATE</div><h1>{text(title)}</h1><div class="facts">{facts_html}</div><section class="description">{text(description) or 'Деталі об’єкта уточнюються.'}</section><section class="photos">{photos_html or '<p>Фотографії тимчасово відсутні.</p>'}</section><footer>Оголошення №{listing_id} · дані оновлюються автоматично</footer></main></body></html>"""
    response = make_response(page)
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


if __name__ == "__main__":

    app.run(host="0.0.0.0", port=int(os.getenv("MEDIA_ARCHIVE_PORT", "8787")), threaded=True)
