"""Shared storage for human-entered listings and notes.

Parser fields remain owned by the pipelines.  A user's comment is deliberately
kept in a separate table so quality/status markers can never overwrite it.
"""
from __future__ import annotations
import json
import uuid
from typing import Any

import psycopg2.extras
from parser_v2.services.ai_listing_copy import build_description as residential_ai_summary
from parser_v2.services.ai_listing_copy import build_title as residential_ai_title
from parser_v2.services.ai_listing_copy import fallback_detailed_description
from commercial_v1.services.ai_listing_copy import build_description as commercial_ai_description
from commercial_v1.services.ai_listing_copy import build_title as commercial_ai_title

MANUAL_TAB = "Ручне додавання"
MANUAL_HEADERS = [
    "Manual ID", "Операція", "Тип", "Заголовок", "URL", "Ціна", "Валюта",
    "Район", "Вулиця", "Площа", "Опис", "Коментарі", "Статус", "Створено",
]

def apply_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS manual_listings (
          id UUID PRIMARY KEY, catalog TEXT NOT NULL CHECK (catalog IN ('apartments','houses','commercial')),
          operation TEXT NOT NULL CHECK (operation IN ('rent','buy')), payload JSONB NOT NULL,
          status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive','archived')),
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS manual_listings_catalog_operation_active_idx
          ON manual_listings(catalog, operation, status, updated_at DESC);
        CREATE TABLE IF NOT EXISTS listing_user_notes (
          catalog TEXT NOT NULL CHECK (catalog IN ('apartments','houses','commercial')),
          listing_id TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', edited_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          PRIMARY KEY (catalog, listing_id)
        );
        CREATE TABLE IF NOT EXISTS listing_system_notes (
          id BIGSERIAL PRIMARY KEY, catalog TEXT NOT NULL, listing_id TEXT NOT NULL,
          code TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)
    conn.commit()

def _manual_ai(catalog: str, operation: str, kind: str, title: str, description: str, district: str, street: str, area: str) -> tuple[str, str, str]:
    """Build the same safe, contact-free AI copy used by parsed listings."""
    if catalog == 'commercial':
        aliases={'офіс':'office','магазин':'retail','склад':'warehouse','виробництво':'industrial','horeca':'horeca','медичне':'medical','будівля':'building'}
        commercial_type=aliases.get(kind.strip().lower(),'multifunctional')
        row={'operation':operation,'commercial_type':commercial_type,'title':title,'description':description,
             'district':district,'street':street,'area_total_m2':area}
        return commercial_type, commercial_ai_title(row), commercial_ai_description(row)
    property_type='Будинок' if catalog == 'houses' else 'Квартира'
    row={'operation':operation,'property_type':property_type,'title':title,'description':description,
         'district':district,'street':street,'area':area}
    # The AI description keeps the source description as "Деталі об’єкта" and
    # adds a structured introduction/location block rather than replacing it.
    ai_description=fallback_detailed_description(row,description) if description.strip() else residential_ai_summary(row)
    return property_type, residential_ai_title(row), ai_description

def ingest_manual_rows(conn, catalog: str, values: list[list[str]]) -> list[tuple[int, str]]:
    """Persist new/edited input rows, returning (sheet row, id) for UI marks."""
    apply_schema(conn)
    accepted: list[tuple[int, str]] = []
    with conn.cursor() as cur:
        for row_number, row in enumerate(values[1:], 2):
            row = list(row) + [""] * max(0, len(MANUAL_HEADERS) - len(row))
            manual_id, operation, kind, title, url, price, currency, district, street, area, description, comment = row[:12]
            if not (title.strip() or url.strip()):
                continue
            operation = {'Оренда': 'rent', 'Продаж': 'buy', 'rent': 'rent', 'buy': 'buy'}.get(operation.strip(), '')
            if operation not in ('rent', 'buy'):
                continue
            identifier = manual_id.strip() or str(uuid.uuid4())
            normalized_kind, ai_title, ai_description = _manual_ai(catalog,operation,kind,title.strip(),description.strip(),district.strip(),street.strip(),area.strip())
            payload = {"property_type": normalized_kind, "title": title.strip(), "url": url.strip(), "price": price.strip(),
                       "currency": currency.strip().upper(), "district": district.strip(), "street": street.strip(),
                       "area": area.strip(), "description": description.strip(), "ai_title": ai_title,
                       "ai_description": ai_description, "comments": comment.strip()}
            cur.execute("""
              INSERT INTO manual_listings(id,catalog,operation,payload,status)
              VALUES(%s,%s,%s,%s::jsonb,'active')
              ON CONFLICT(id) DO UPDATE SET operation=EXCLUDED.operation,payload=EXCLUDED.payload,updated_at=NOW()
            """, (identifier,catalog,operation,json.dumps(payload,ensure_ascii=False)))
            if comment.strip():
                cur.execute("""INSERT INTO listing_user_notes(catalog,listing_id,note)
                  VALUES(%s,%s,%s) ON CONFLICT(catalog,listing_id) DO UPDATE SET note=EXCLUDED.note,edited_at=NOW()""",
                  (catalog, f"manual:{identifier}", comment.strip()))
            accepted.append((row_number, identifier))
    conn.commit()
    return accepted

def capture_sheet_notes(conn, catalog: str, rows: list[list[str]], id_column: int, comment_column: int) -> int:
    """Capture only non-empty user notes; parser/system rows never overwrite them."""
    apply_schema(conn)
    count = 0
    with conn.cursor() as cur:
        for row in rows[1:]:
            if len(row) <= max(id_column, comment_column):
                continue
            identifier, note = str(row[id_column]).strip(), str(row[comment_column]).strip()
            if not identifier or not note:
                continue
            cur.execute("""INSERT INTO listing_user_notes(catalog,listing_id,note)
              VALUES(%s,%s,%s) ON CONFLICT(catalog,listing_id) DO UPDATE
              SET note=EXCLUDED.note,edited_at=NOW() WHERE listing_user_notes.note IS DISTINCT FROM EXCLUDED.note""",
              (catalog, identifier, note))
            count += 1
    conn.commit()
    return count

def active_records(conn, catalog: str, operation: str) -> list[dict[str, Any]]:
    """Normalize human-entered records for the same read-only Active view."""
    apply_schema(conn)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id,payload,created_at,updated_at FROM manual_listings WHERE catalog=%s AND operation=%s AND status='active' ORDER BY updated_at DESC",(catalog,operation))
        stored=cur.fetchall()
    result=[]
    for item in stored:
        p=dict(item['payload']); price=p.get('price','')
        common={'id':f"manual:{item['id']}",'external_id':f"manual:{item['id']}",'source':'manual','operation':operation,
          'title':p.get('title',''),'description':p.get('description',''),'url':p.get('url',''),'district':p.get('district',''),
          'street':p.get('street',''),'area':p.get('area',''),'ai_title':p.get('ai_title',''),
          'ai_description':p.get('ai_description',''),'comments':p.get('comments',''),'created_at':item['created_at'],'updated_at':item['updated_at']}
        currency=p.get('currency','').upper()
        if currency=='UAH': common['price_uah']=price
        elif currency in ('USD','$'): common['price_usd']=price
        elif currency in ('EUR','€'): common['price_eur']=price
        if catalog=='apartments': common['property_type']='Квартира'
        elif catalog=='houses': common['property_type']='Будинок'
        else:
            common.update({'commercial_type':p.get('property_type','Комерція'),'status':'active','area_total_m2':p.get('area',''),
                           'validation_errors':[],'phones':[]})
        result.append(common)
    return result
