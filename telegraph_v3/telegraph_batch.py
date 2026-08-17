#!/usr/bin/env python3
"""Resumable Block 3 publisher for apartments, houses and commercial listings.

The script owns no Block 1 data: it reads active listings, stores publication
state in block3, and lets the separate Sheets synchronizer write final URLs.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import cloudinary
import cloudinary.api
import cloudinary.uploader
import psycopg2
import psycopg2.extras
import requests
from requests.adapters import HTTPAdapter
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
TELEGRAPH_API = "https://api.telegra.ph"
# Telegraph accepts public requests but can throttle bursts.  This short,
# configurable pause maximises normal throughput; create_or_edit() still
# honours any server-provided FLOOD_WAIT before retrying.
TELEGRAPH_PAGE_INTERVAL_SECONDS = float(os.getenv("TELEGRAPH_PAGE_INTERVAL_SECONDS", "1.5"))
# A long provider cooldown must never hold the only publisher process hostage.
# It is persisted as retry_after and a later cycle resumes safely instead.
MAX_INLINE_FLOOD_WAIT_SECONDS = int(os.getenv("TELEGRAPH_MAX_INLINE_FLOOD_WAIT_SECONDS", "15"))

# Publishing a complete bilingual card requires several HTTPS calls (translation
# plus two Telegraph pages).  Reusing connections avoids a fresh DNS/TLS
# negotiation for every call, which was the dominant bottleneck in large runs.
HTTP = requests.Session()
HTTP.mount("https://", HTTPAdapter(pool_connections=32, pool_maxsize=32, max_retries=0))
ACCOUNT_FILE = ROOT / "telegraph_v3" / "data" / "telegraph-account.json"
LOGO = ROOT / "telegraph_v3" / "assets" / "kyiv-estate-logo.jpg"
MEDIA_FOLDER = os.getenv("CLOUDINARY_FOLDER", "kyiv-estate").strip("/") or "kyiv-estate"
MEDIA_PUBLIC_BASE = os.getenv("MEDIA_PUBLIC_BASE", "").rstrip("/")
TEMPLATE_VERSION = "2026-08-01-agency-v2"
PUBLICATION_TABLES = {
    "apartments": "active_listings",
    "houses": "houses_listings",
    "commercial": "commercial_listings",
}
SENSITIVE_SENTENCE = re.compile(r"(?:\bolx\b|\brieltor\b|рієлтор|риелтор|\bагент\w*|\bвласник\w*|\bвладелец\w*|комісі|комисси|\bтелефон\w*|\bзателеф\w*|\bдзвон\w*|whatsapp|telegram|\+?38[\s()\-]*0\d{2}[\s()\-]*\d{3}[\s()\-]*\d{2}[\s()\-]*\d{2})", re.I)
FLOOD_WAIT = re.compile(r"FLOOD_WAIT_(\d+)", re.I)


def db():
    return psycopg2.connect(
        host=os.getenv("PG_HOST", os.getenv("POSTGRES_HOST", "/tmp")),
        port=os.getenv("PG_PORT", os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("PG_DBNAME", os.getenv("POSTGRES_DB", "real_estate")),
        user=os.getenv("PG_USER", os.getenv("POSTGRES_USER", "admin")),
        password=os.getenv("PG_PASSWORD", os.getenv("POSTGRES_PASSWORD", "")),
    )


def ensure_publisher_control(conn) -> None:
    """Create a tiny durable circuit breaker for provider-wide cooldowns."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS block3.publisher_control (
                name text PRIMARY KEY,
                cooldown_until timestamptz,
                updated_at timestamptz NOT NULL DEFAULT now()
            )
        """)
    conn.commit()


def provider_cooldown(conn) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute("""SELECT cooldown_until FROM block3.publisher_control
                       WHERE name='telegraph' AND cooldown_until > now()""")
        row = cur.fetchone()
    return row[0] if row else None


def sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def clean_text(value: Any) -> str:
    value = html.unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    paragraphs = []
    for paragraph in re.split(r"\n{2,}", value):
        sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", paragraph).strip())
        kept = [sentence.strip() for sentence in sentences if sentence.strip() and not SENSITIVE_SENTENCE.search(sentence)]
        if kept:
            paragraphs.append(" ".join(kept))
    return "\n\n".join(paragraphs)[:18000]


def agency_description(row: dict[str, Any]) -> str:
    source = clean_text(row.get("ai_description") or row.get("description"))
    kind = "об’єкт" if row["catalog"] == "commercial" else "будинок" if row["catalog"] == "houses" else "квартира"
    location = next((str(row.get(key)).strip() for key in ("full_address", "street", "district", "city") if row.get(key)), "Києві")
    area = row.get("area_total_m2") if row["catalog"] == "commercial" else row.get("area")
    facts = f" Площа — {area} м²." if area else ""
    opening = f"Представляємо ретельно відібрану пропозицію KYIV ESTATE — {kind} у локації {location}.{facts}"
    closing = "Зверніть увагу на деталі нижче: ми залишили тільки підтверджені характеристики, щоб ви могли об’єктивно оцінити простір і його потенціал."
    return "\n\n".join(part for part in (opening, source, closing) if part)


def clean_title(value: Any, listing_id: int) -> str:
    title = clean_text(value).replace("\n", " ")
    title = re.sub(r"\s*(?:[-–—]|\|)\s*(?:оголошення|объявление)\s*№?\s*\d+.*$", "", title, flags=re.I)
    title = re.sub(r"\s+", " ", title).strip()[:220]
    return f"{title} · #{listing_id}" if title else f"KYIV ESTATE · #{listing_id}"


def unique_urls(row: dict[str, Any]) -> list[str]:
    candidates = list(row.get("photos") or []) + [row.get("photo_url")]
    answer: list[str] = []
    for value in candidates:
        url = str(value or "").strip()
        if url.startswith("https://") and url not in answer:
            answer.append(url)
    return answer


def money(value: Any, currency: str) -> str:
    if value in (None, ""):
        return ""
    try:
        rendered = f"{float(value):,.0f}".replace(",", " ")
    except (TypeError, ValueError):
        rendered = str(value)
    return f"{rendered} {currency}"


def fact_rows(row: dict[str, Any], language: str) -> list[tuple[str, str]]:
    commercial = row["catalog"] == "commercial"
    pairs: list[tuple[str, Any, str, str]] = [
        ("Ціна", row.get("price_uah"), "Price", "UAH"),
        ("Ціна", row.get("price_usd"), "Price", "USD"),
        ("Ціна", row.get("price_eur"), "Price", "EUR"),
        ("Загальна площа", row.get("area_total_m2") if commercial else row.get("area"), "Total area", "m²"),
        ("Поверх", row.get("floor"), "Floor", ""),
        ("Поверхів", row.get("floors_total"), "Total floors", ""),
        ("Кімнат", row.get("rooms"), "Rooms", ""),
        ("Район", row.get("district"), "District", ""),
        ("Адреса", row.get("full_address") or row.get("street"), "Address", ""),
    ]
    if commercial:
        pairs += [
            ("Тип", row.get("commercial_subtype") or row.get("commercial_type"), "Type", ""),
            ("Висота стелі", row.get("ceiling_height_m"), "Ceiling height", "m"),
            ("Потужність", row.get("electric_power_kw"), "Power", "kW"),
        ]
    result = []
    for uk, value, en, suffix in pairs:
        if value in (None, ""):
            continue
        label = uk if language == "ua" else en
        if suffix in {"UAH", "USD", "EUR"}:
            rendered = money(value, suffix)
        else:
            rendered = f"{value} {suffix}".strip()
        result.append((label, rendered))
    return result


def telegraph_token() -> str:
    configured = os.getenv("TELEGRAPH_ACCESS_TOKEN", "").strip()
    if configured:
        return configured
    if ACCOUNT_FILE.is_file():
        return json.loads(ACCOUNT_FILE.read_text(encoding="utf-8"))["access_token"]
    response = HTTP.post(TELEGRAPH_API + "/createAccount", json={"short_name": "KYIVESTATE", "author_name": "KYIV ESTATE"}, timeout=20)
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError("Telegraph account creation failed")
    ACCOUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACCOUNT_FILE.write_text(json.dumps({"access_token": result["result"]["access_token"]}), encoding="utf-8")
    return result["result"]["access_token"]


def retry(call, attempts: int = 4):
    error = None
    for attempt in range(attempts):
        try:
            return call()
        except (requests.RequestException, RuntimeError) as exc:
            error = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (2 ** attempt))
    raise error  # type: ignore[misc]


def translate(conn, text: str) -> str:
    if not text:
        return ""
    digest = sha(text)
    with conn.cursor() as cur:
        cur.execute("SELECT english_text FROM block3.translations WHERE source_sha256=%s", (digest,))
        cached = cur.fetchone()
        if cached:
            return cached[0]
    parts = []
    # The free Google endpoint uses GET; a Ukrainian paragraph can expand to a
    # URL that it rejects. Preserve every word by translating small natural
    # chunks instead of truncating at an unsafe request length.
    chunks: list[str] = []
    for paragraph in text.splitlines() or [text]:
        words = paragraph.split()
        if not words:
            chunks.append("")
            continue
        chunk, size = [], 0
        for word in words:
            if chunk and size + len(word) + 1 > 900:
                chunks.append(" ".join(chunk))
                chunk, size = [], 0
            chunk.append(word)
            size += len(word) + (1 if size else 0)
        if chunk:
            chunks.append(" ".join(chunk))
    for paragraph in chunks:
        if not paragraph.strip():
            parts.append("")
            continue
        def request_translation():
            response = HTTP.get("https://translate.googleapis.com/translate_a/single", params={"client": "gtx", "sl": "uk", "tl": "en", "dt": "t", "q": paragraph}, timeout=20)
            response.raise_for_status()
            return "".join(piece[0] for piece in response.json()[0] if piece[0])
        parts.append(retry(request_translation))
    result = "\n".join(parts)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO block3.translations(source_sha256,source_text,english_text) VALUES(%s,%s,%s) ON CONFLICT(source_sha256) DO NOTHING", (digest, text, result))
    return result


def secret(name: str) -> str:
    """Read Block 3 credentials from the macOS Keychain before legacy .env values."""
    preferred = os.getenv("BLOCK3_" + name, "").strip()
    if preferred:
        return preferred
    keychain_name = {
        "CLOUDINARY_CLOUD_NAME": "cloud-name",
        "CLOUDINARY_API_KEY": "api-key",
        "CLOUDINARY_API_SECRET": "api-secret",
    }.get(name, name.lower().replace("_", "-"))
    result = subprocess.run(["security", "find-generic-password", "-a", "kyivestate-block3", "-s", f"kyivestate-block3-{keychain_name}", "-w"], text=True, capture_output=True)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return os.getenv(name, "").strip()


def configure_cloudinary() -> None:
    cloud_name, api_key, api_secret = (secret(name) for name in ("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"))
    if not all((cloud_name, api_key, api_secret)):
        raise RuntimeError("Block 3 Cloudinary credentials are not configured")
    cloudinary.config(cloud_name=cloud_name, api_key=api_key, api_secret=api_secret, secure=True)


def cloudinary_credit_usage() -> dict[str, float]:
    """Return account credits without exposing any credential or account secret."""
    configure_cloudinary()
    credits = cloudinary.api.usage().get("credits") or {}
    return {
        "used": float(credits.get("usage") or 0),
        "limit": float(credits.get("limit") or 0),
    }


def media_url(conn, url: str, public_id: str) -> str:
    digest = sha(url)
    with conn.cursor() as cur:
        cur.execute("SELECT secure_url FROM block3.media_assets WHERE sha256=%s", (digest,))
        found = cur.fetchone()
        if found:
            return found[0]
    def upload():
        return cloudinary.uploader.upload(url, public_id=public_id, resource_type="image", overwrite=True, unique_filename=False, invalidate=False, tags=["kyiv-estate", "block3"])
    result = retry(upload)
    stable = result["secure_url"]
    with conn.cursor() as cur:
        cur.execute("INSERT INTO block3.media_assets(sha256,source_url,cloudinary_public_id,secure_url) VALUES(%s,%s,%s,%s) ON CONFLICT(sha256) DO UPDATE SET secure_url=EXCLUDED.secure_url", (digest, url, result["public_id"], stable))
    return stable


def publication_media(conn, urls: list[str], catalog: str, listing_id: int, mode: str) -> list[str]:
    """Return page image URLs without silently dropping any source image.

    ``archive`` uses content-addressed local copies through the permanent
    public media endpoint.  A page is held for retry until every photo has a
    durable archived copy, rather than falling back to an expiring source.
    ``source`` is retained only for diagnostics: Telegraph reads the HTTPS
    image straight from OLX/Rieltor and those URLs may expire.
    ``cloudinary`` remains available only when durable copies are explicitly
    wanted and an account with sufficient credits is configured.
    """
    if mode == "source":
        return urls
    if mode == "archive":
        if not MEDIA_PUBLIC_BASE.startswith("https://"):
            raise RuntimeError("MEDIA_PUBLIC_BASE must be an HTTPS URL for archive mode")
        hashes = [sha(url) for url in urls]
        with conn.cursor() as cur:
            cur.execute(
                """SELECT source_sha256,storage_key FROM block3.media_archive
                   WHERE status='archived' AND source_sha256 = ANY(%s)""",
                (hashes,),
            )
            archived = {digest: key for digest, key in cur.fetchall() if key}
        missing = [url for url, digest in zip(urls, hashes) if digest not in archived]
        if missing:
            raise RuntimeError(f"Media archive pending for {len(missing)} photo(s)")
        return [f"{MEDIA_PUBLIC_BASE}/{archived[digest].lstrip('/')}" for digest in hashes]
    configure_cloudinary()
    return [
        media_url(conn, source, f"{MEDIA_FOLDER}/block3/{catalog}/{listing_id}/{sha(source)[:20]}")
        for source in urls
    ]


def logo_url(conn) -> str:
    if not LOGO.is_file():
        raise RuntimeError(f"Logo missing: {LOGO}")
    digest = sha(LOGO.read_bytes())
    with conn.cursor() as cur:
        cur.execute("SELECT secure_url FROM block3.media_assets WHERE sha256=%s", (digest,))
        found = cur.fetchone()
        if found:
            return found[0]
    result = retry(lambda: cloudinary.uploader.upload(str(LOGO), public_id=f"{MEDIA_FOLDER}/block3/branding/logo-v1", resource_type="image", overwrite=True, unique_filename=False, invalidate=False, tags=["kyiv-estate", "block3", "logo"]))
    with conn.cursor() as cur:
        cur.execute("INSERT INTO block3.media_assets(sha256,source_url,cloudinary_public_id,secure_url) VALUES(%s,%s,%s,%s)", (digest, "local:kyiv-estate-logo", result["public_id"], result["secure_url"]))
    return result["secure_url"]


def content(row: dict[str, Any], language: str, title: str, description: str, photos: list[str], logo: str, other_url: str = "") -> list[dict[str, Any]]:
    page: list[dict[str, Any]] = []
    if photos:
        page.append({"tag": "img", "attrs": {"src": photos[0]}})
    if logo:
        page.append({"tag": "img", "attrs": {"src": logo}})
    labels = ("Ціна", "Характеристики", "Опис", "🌐 English") if language == "ua" else ("Price", "Details", "Description", "🌐 Українська")
    if other_url:
        page.append({"tag": "p", "children": [{"tag": "a", "attrs": {"href": other_url}, "children": [labels[3]]}]})
    phone_url = "https://api.whatsapp.com/send/?phone=380981559900&text&type=phone_number&app_absent=0"
    page.append({"tag": "p", "children": [{"tag": "b", "children": ["Контакти: " if language == "ua" else "Contacts: "]}, {"tag": "a", "attrs": {"href": phone_url}, "children": ["+380 98 155 9900"]}]})
    for label, value in fact_rows(row, language):
        page.append({"tag": "p", "children": [{"tag": "b", "children": [label + ": "]}, value]})
    if description:
        page.append({"tag": "h3", "children": [labels[2]]})
        page.extend({"tag": "p", "children": [part]} for part in description.splitlines() if part.strip())
    if len(photos) > 1:
        page.append({"tag": "h3", "children": ["Фотографії" if language == "ua" else "Photos"]})
        page.extend({"tag": "img", "attrs": {"src": photo}} for photo in photos[1:])
    socials = [
        ("KYIV ESTATE", "https://kyiv.estate/"),
        ("Telegram", "https://t.me/Real_Estate_Agency_premium"),
        ("WhatsApp", phone_url),
        ("Email", "mailto:info@kyiv.estate"),
    ]
    social_nodes: list[Any] = [{"tag": "b", "children": ["Контакти: " if language == "ua" else "Contacts: "]}]
    for index, (label, href) in enumerate(socials):
        if index:
            social_nodes.append(" · ")
        social_nodes.append({"tag": "a", "attrs": {"href": href}, "children": [label]})
    page.append({"tag": "p", "children": social_nodes})
    page.append({"tag": "p", "children": [{"tag": "b", "children": ["🏛 Kyiv.Estate — Агентство нерухомості №1 в Києві." if language == "ua" else "🏛 Kyiv.Estate — Kyiv’s No. 1 Real Estate Agency."]}]})
    return page


def create_or_edit(token: str, url: str | None, title: str, nodes: list[dict[str, Any]]) -> str:
    payload = {"access_token": token, "title": title[:256], "author_name": "KYIV ESTATE", "content": json.dumps(nodes, ensure_ascii=False), "return_content": False}
    endpoint = "/editPage/" + url.rsplit("/", 1)[-1] if url else "/createPage"
    # Telegraph does not document a fixed rate.  Use a short normal spacing for
    # throughput, but obey an explicit FLOOD_WAIT immediately when it appears.
    error = None
    for attempt in range(4):
        result = retry(lambda: HTTP.post(TELEGRAPH_API + endpoint, json=payload, timeout=45))
        response = result.json()
        if response.get("ok"):
            time.sleep(max(0.0, TELEGRAPH_PAGE_INTERVAL_SECONDS))
            return response["result"]["url"]
        error = str(response.get("error", "Telegraph rejected the page"))
        flood = FLOOD_WAIT.search(error)
        if flood and attempt < 3:
            seconds = int(flood.group(1))
            if seconds > MAX_INLINE_FLOOD_WAIT_SECONDS:
                print(json.dumps({"event": "telegraph_cooldown_deferred", "seconds": seconds}, ensure_ascii=False), file=sys.stderr, flush=True)
                break
            time.sleep(seconds + 1)
            continue
        break
    raise RuntimeError(error or "Telegraph rejected the page")


def fetch_batch(conn, limit: int, catalogs: Iterable[str], refresh: bool = False,
                retry_failed: bool = False, media_mode: str = "cloudinary") -> list[dict[str, Any]]:
    """Select a fair batch that is actually publishable.

    In durable-archive mode, selecting a listing before all of its photos are
    local only burns a Telegraph slot and creates a retry.  Filter at the
    database boundary and round-robin the catalogues so the publisher always
    spends its quota on ready pages.
    """
    rows = []
    catalogs = list(catalogs)
    per_catalog = max(1, (limit + len(catalogs) - 1) // len(catalogs))
    buckets: dict[str, list[dict[str, Any]]] = {}
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for catalog in catalogs:
            table = PUBLICATION_TABLES[catalog]
            # jsonb lets one renderer safely consume the distinct production schemas.
            # Initial mass publishing must always advance to new listings.
            # Page refreshes are explicit (`--refresh`), so a routine source
            # touch in Block 1 cannot consume Cloudinary/Telegraph capacity by
            # repeatedly rebuilding an already-published page.
            work_filter = "TRUE" if refresh else """(
                p.listing_id IS NULL
                OR (p.status IN ('pending','retry') AND (p.retry_after IS NULL OR p.retry_after <= now()))
            )"""
            if retry_failed and not refresh:
                # Retry transient Cloudinary-era failures in the free source
                # mode, but never loop forever on a listing with no images.
                work_filter = """(
                    p.listing_id IS NULL
                    OR (p.status IN ('pending','retry') AND (p.retry_after IS NULL OR p.retry_after <= now()))
                    OR (p.status='failed' AND coalesce(p.last_error,'') NOT LIKE 'Listing has no usable HTTPS photos%%')
                )"""
            archive_filter = ""
            if media_mode == "archive" and not refresh:
                # Use the durable source_url index.  This intentionally
                # requires every HTTPS listing photo to be present, matching
                # the promise that a Telegraph page never references a
                # temporary source image.
                archive_filter = """
                    AND EXISTS (
                        SELECT 1
                        FROM unnest(coalesce(l.photos, ARRAY[]::text[]) || ARRAY[l.photo_url]) AS photo(url)
                        WHERE photo.url LIKE 'https://%%'
                    )
                    AND NOT EXISTS (
                        SELECT 1
                        FROM unnest(coalesce(l.photos, ARRAY[]::text[]) || ARRAY[l.photo_url]) AS photo(url)
                        LEFT JOIN block3.media_archive media
                          ON media.source_url = photo.url
                         AND media.status = 'archived'
                        WHERE photo.url LIKE 'https://%%'
                          AND media.source_url IS NULL
                    )
                """
            cur.execute(f"""
                SELECT to_jsonb(l) || jsonb_build_object('catalog', %s) AS listing
                FROM {table} l
                LEFT JOIN block3.publications p ON p.catalog=%s AND p.listing_id=l.id
                WHERE l.status='active' AND {work_filter} {archive_filter}
                ORDER BY l.updated_at NULLS LAST, l.id
                LIMIT %s
            """, (catalog, catalog, per_catalog))
            buckets[catalog] = [dict(item["listing"]) for item in cur.fetchall()]
    # Keep the three catalogues fair when all have ready records, but let a
    # productive catalogue consume unused slots when another is still being
    # archived.  This prevents 16/24 empty batch slots seen in production.
    while len(rows) < limit and any(buckets.values()):
        for catalog in catalogs:
            if buckets.get(catalog):
                rows.append(buckets[catalog].pop(0))
                if len(rows) >= limit:
                    break
    return rows


def record_failure(conn, row: dict[str, Any], error: Exception) -> None:
    """Persist one retryable failure without affecting the source listing."""
    message = str(error)[:1800]
    flood = FLOOD_WAIT.search(message)
    # A source image that OLX has deleted cannot be made durable. It remains
    # visible for audit but is not retried until the authoritative listing is
    # updated with new images.
    terminal = "Resource not found" in message or "Listing has no usable HTTPS photos" in message
    if flood:
        retry_after = datetime.now(timezone.utc) + timedelta(seconds=int(flood.group(1)) + 15)
    elif "Media archive pending" in message:
        # The archive runs independently every few minutes; avoid selecting
        # the same listing on every publisher tick while its photos arrive.
        retry_after = datetime.now(timezone.utc) + timedelta(minutes=10)
    else:
        retry_after = None
    status = "failed" if terminal else "retry"
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO block3.publications(catalog,listing_id,source,external_id,operation,source_updated_at,status,attempts,last_error,retry_after)
            VALUES(%s,%s,%s,%s,%s,%s,%s,1,%s,%s)
            ON CONFLICT(catalog,listing_id) DO UPDATE SET status=EXCLUDED.status,attempts=block3.publications.attempts+1,last_error=EXCLUDED.last_error,retry_after=EXCLUDED.retry_after,updated_at=now()
        """, (row["catalog"], row["id"], row["source"], row["external_id"], row["operation"], row.get("updated_at"), status, message, retry_after))
        if flood:
            cur.execute("""
                INSERT INTO block3.publisher_control(name,cooldown_until,updated_at)
                VALUES('telegraph',%s,now())
                ON CONFLICT(name) DO UPDATE SET
                    cooldown_until=GREATEST(block3.publisher_control.cooldown_until, EXCLUDED.cooldown_until),
                    updated_at=now()
            """, (retry_after,))


def fingerprint(row: dict[str, Any], photo_urls: list[str]) -> str:
    watched = {key: row.get(key) for key in ("title", "ai_title", "description", "ai_description", "price_uah", "price_usd", "price_eur", "area", "area_total_m2", "floor", "floors_total", "rooms", "street", "full_address", "updated_at")}
    return sha(json.dumps({"template": TEMPLATE_VERSION, "row": watched, "photos": photo_urls}, sort_keys=True, default=str))


def publish_one(conn, row: dict[str, Any], dry_run: bool, media_mode: str) -> dict[str, Any]:
    catalog, listing_id = row["catalog"], int(row["id"])
    original_photos = unique_urls(row)
    if not original_photos:
        raise RuntimeError("Listing has no usable HTTPS photos")
    with conn.cursor() as cur:
        cur.execute("SELECT ua_url,en_url,content_fingerprint FROM block3.publications WHERE catalog=%s AND listing_id=%s", (catalog, listing_id))
        prior = cur.fetchone() or (None, None, None)
    content_hash = fingerprint(row, original_photos)
    if prior[0] and prior[1] and prior[2] == content_hash:
        return {"status": "unchanged", "listing_id": listing_id}
    if dry_run:
        return {"status": "dry-run", "listing_id": listing_id, "photos": len(original_photos)}
    stable = publication_media(conn, original_photos, catalog, listing_id, media_mode)
    # The branding image is already durable and shared by all pages; do not
    # require an image-hosting account in the free source-photo mode.
    logo = logo_url(conn) if media_mode == "cloudinary" else ""
    ua_title = clean_title(row.get("ai_title") or row.get("title"), listing_id)
    ua_text = agency_description(row)
    en_title, en_text = translate(conn, ua_title), translate(conn, ua_text)
    token = telegraph_token()
    # Keep page writes sequential. Telegraph has applied a provider-wide
    # cooldown after parallel bursts; a stable UA->EN sequence is resumable
    # and retains the reciprocal language link on every newly created card.
    ua = create_or_edit(token, prior[0], ua_title, content(row, "ua", ua_title, ua_text, stable, logo))
    en = create_or_edit(token, prior[1], en_title, content(row, "en", en_title, en_text, stable, logo, ua))
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO block3.publications(catalog,listing_id,source,external_id,operation,ua_url,en_url,source_updated_at,content_fingerprint,status,attempts,last_error,published_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'published',1,NULL,now())
            ON CONFLICT(catalog,listing_id) DO UPDATE SET ua_url=EXCLUDED.ua_url,en_url=EXCLUDED.en_url,source_updated_at=EXCLUDED.source_updated_at,content_fingerprint=EXCLUDED.content_fingerprint,status='published',attempts=block3.publications.attempts+1,last_error=NULL,published_at=now(),updated_at=now()
        """, (catalog, listing_id, row["source"], row["external_id"], row["operation"], ua, en, row.get("updated_at"), content_hash))
    return {"status": "published", "listing_id": listing_id, "photos": len(stable), "ua": ua, "en": en}


def prewarm_translations(rows: list[dict[str, Any]], workers: int) -> None:
    """Fill the persistent translation cache concurrently before publishing.

    Translation has no dependency on the Telegraph write and is idempotently
    cached by source SHA.  Keeping this bounded separates the slow external
    read path from the ordered page-write path without changing content.
    """
    if workers < 2 or not rows:
        return

    def warm(row: dict[str, Any]) -> None:
        with db() as worker_conn:
            translate(worker_conn, clean_title(row.get("ai_title") or row.get("title"), int(row["id"])))
            translate(worker_conn, agency_description(row))

    with ThreadPoolExecutor(max_workers=min(workers, len(rows)), thread_name_prefix="translation") as pool:
        for future in [pool.submit(warm, row) for row in rows]:
            # Failed cache warming is harmless: publish_one will make the
            # normal retrying translation call and record any real failure.
            try:
                future.result()
            except Exception:
                pass


def publish_task(row: dict[str, Any], media_mode: str) -> dict[str, Any]:
    """Publish one isolated listing transaction for a bounded worker pool."""
    with db() as worker_conn:
        try:
            result = publish_one(worker_conn, row, False, media_mode)
            worker_conn.commit()
            return result
        except Exception as error:
            worker_conn.rollback()
            record_failure(worker_conn, row, error)
            worker_conn.commit()
            return {"status": "failed", "listing_id": row.get("id"), "catalog": row.get("catalog"), "error": str(error)[:1000]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--migrate", action="store_true", help="Apply the non-destructive Block 3 schema.")
    parser.add_argument("--dry-run", action="store_true", help="Validate selection only; no network or database writes.")
    parser.add_argument("--limit", type=int, help="Maximum listings to process; required unless --migrate is used.")
    parser.add_argument("--catalog", action="append", choices=sorted(PUBLICATION_TABLES), help="Restrict to a catalog; repeatable.")
    parser.add_argument("--no-sync", action="store_true", help="Do not immediately copy completed URLs to Google Sheets.")
    parser.add_argument("--audit", action="store_true", help="Read-only publication, media and active-listing audit.")
    parser.add_argument("--usage", action="store_true", help="Read-only Cloudinary credit usage check.")
    parser.add_argument("--refresh", action="store_true", help="Rebuild already-published pages with the current template.")
    parser.add_argument("--media-mode", choices=("archive", "source", "cloudinary"), default="cloudinary",
                        help="archive uses durable public local copies; cloudinary is legacy; source embeds temporary originals.")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Retry transient failed pages (never no-photo listings).")
    parser.add_argument("--translation-workers", type=int,
                        default=int(os.getenv("TELEGRAPH_TRANSLATION_WORKERS", "8")),
                        help="Bounded concurrent cache warming before Telegraph writes (default: 8).")
    parser.add_argument("--publish-workers", type=int,
                        default=int(os.getenv("TELEGRAPH_PUBLISH_WORKERS", "2")),
                        help="Concurrent isolated listing writers (default: 2).")
    parser.add_argument("--credit-ceiling", type=float, default=23.5, help="Stop a batch before this many Cloudinary credits are used (default: 23.5).")
    args = parser.parse_args()
    if not args.migrate and not args.audit and not args.usage and (not args.limit or args.limit < 1):
        parser.error("--limit is required to prevent an accidental mass publish")
    if args.credit_ceiling <= 0:
        parser.error("--credit-ceiling must be positive")
    if args.translation_workers < 1 or args.publish_workers < 1:
        parser.error("worker counts must be positive")
    if args.usage:
        print(json.dumps({"cloudinary_credits": cloudinary_credit_usage()}, ensure_ascii=False))
        return
    with db() as conn:
        ensure_publisher_control(conn)
        if args.audit:
            with conn.cursor() as cur:
                cur.execute("SELECT catalog,status,count(*) FROM block3.publications GROUP BY catalog,status ORDER BY catalog,status")
                publications = cur.fetchall()
                cur.execute("SELECT count(*) FROM block3.media_assets")
                media = cur.fetchone()[0]
                active = {}
                for catalog, table in PUBLICATION_TABLES.items():
                    cur.execute(f"SELECT count(*) FROM {table} WHERE status='active'")
                    active[catalog] = cur.fetchone()[0]
            print(json.dumps({"active": active, "publications": publications, "durable_media": media}, ensure_ascii=False, default=str))
            return
        if args.migrate:
            conn.cursor().execute((ROOT / "telegraph_v3" / "sql" / "001_schema.sql").read_text(encoding="utf-8"))
            print(json.dumps({"migrated": True}))
            if not args.limit:
                return
        catalogs = args.catalog or list(PUBLICATION_TABLES)
        usage_before = cloudinary_credit_usage() if args.media_mode == "cloudinary" else None
        # This is deliberately below the provider's hard limit: it ensures a
        # page is never created with transient source images after storage is
        # exhausted. The launcher will simply become idle at the ceiling.
        if usage_before and usage_before["used"] >= min(args.credit_ceiling, usage_before["limit"]):
            print(json.dumps({"selected": 0, "summary": {"quota_reached": 1}, "cloudinary_credits": usage_before}, ensure_ascii=False))
            return
        cooldown = provider_cooldown(conn)
        if cooldown:
            print(json.dumps({"selected": 0, "summary": {"telegraph_cooldown": 1}, "retry_at": cooldown.isoformat()}, ensure_ascii=False))
            return
        rows = fetch_batch(conn, args.limit, catalogs, refresh=args.refresh,
                           retry_failed=args.retry_failed, media_mode=args.media_mode)
        if not args.dry_run:
            prewarm_translations(rows, args.translation_workers)
        if args.dry_run:
            results = [publish_one(conn, row, True, args.media_mode) for row in rows]
        elif args.publish_workers == 1:
            results = [publish_task(row, args.media_mode) for row in rows]
        else:
            # A small fixed pool increases throughput while retaining one
            # transaction per listing.  Provider cooldowns are persisted by
            # each task, so a single delayed page cannot stall the batch.
            with ThreadPoolExecutor(max_workers=min(args.publish_workers, len(rows)), thread_name_prefix="publisher") as pool:
                results = [future.result() for future in [pool.submit(publish_task, row, args.media_mode) for row in rows]]
        summary = {state: sum(item["status"] == state for item in results) for state in {item["status"] for item in results}}
        output: dict[str, Any] = {"selected": len(rows), "summary": summary, "results": results, "media_mode": args.media_mode}
        if usage_before:
            output["cloudinary_credits_before"] = usage_before
    # Run after the transaction closes: Google Sheets never participates in the
    # PostgreSQL transaction, and the dedicated writer still owns SheetsLock.
    if not args.dry_run and not args.no_sync and summary.get("published", 0):
        completed = subprocess.run([sys.executable, str(ROOT / "telegraph_v3" / "sync_to_sheets.py")], text=True, capture_output=True)
        output["sheets_sync"] = json.loads(completed.stdout) if completed.returncode == 0 and completed.stdout.strip() else {"ok": False, "error": completed.stderr.strip()[:1000]}
    # A usage check after the batch makes the persistent runner auditable and
    # lets the next invocation stop safely at the configured ceiling.
    if not args.dry_run and args.media_mode == "cloudinary":
        output["cloudinary_credits_after"] = cloudinary_credit_usage()
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
