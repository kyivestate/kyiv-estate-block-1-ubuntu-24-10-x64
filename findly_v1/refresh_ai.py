"""Build safe public text for Findly records without using contact data."""
from __future__ import annotations

import re

import psycopg2.extras

from findly_v1.persistence import get_conn

PHONE = re.compile(r'(?:\+?38)?[\s()\-]*0\d(?:[\s()\-]*\d){8,}')
CONTACT = re.compile(r'\b(?:телефон|дзвон|дзвін|пишіть|telegram|viber|whatsapp|агент|ріелтор|комісі\w*)\b[^.!?\n]*', re.I)


def clean_description(value: object) -> str:
    text = PHONE.sub('', str(value or ''))
    text = CONTACT.sub('', text)
    return re.sub(r'\s+', ' ', text).strip()[:49_000]


def ai_title(row: dict) -> str:
    action = 'Оренда' if row['operation'] == 'rent' else 'Продаж'
    parts = [action]
    if row.get('property_type'):
        parts.append(str(row['property_type']))
    elif row.get('title'):
        parts.append(str(row['title']))
    if row.get('area'):
        parts.append(f"{row['area']} м²")
    if row.get('district'):
        parts.append(f"у {row['district']} районі")
    return ' '.join(parts)[:160]


def ai_description(row: dict) -> str:
    intro = ai_title(row) + '.'
    details = clean_description(row.get('description'))
    return (intro + ('\n\nДеталі об’єкта:\n' + details if details else ''))[:49_000]


def main() -> None:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as read, conn.cursor() as write:
        read.execute("SELECT * FROM findly_listings WHERE status='active' AND (ai_title IS NULL OR ai_description IS NULL)")
        rows = [dict(row) for row in read.fetchall()]
        for row in rows:
            public_description = ai_description(row)
            score = 100 if len(public_description) >= 100 else 60
            write.execute('UPDATE findly_listings SET ai_title=%s, ai_description=%s, ai_quality_score=%s, updated_at=NOW() WHERE id=%s', (ai_title(row), public_description, score, row['id']))
    print(f'ai_refreshed={len(rows)}')


if __name__ == '__main__':
    main()
