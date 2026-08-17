from __future__ import annotations
import os
import re
import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

def get_client():
    creds_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_path:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set")
    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return gspread.authorize(creds)

def find_header_map(headers: list[str]) -> dict[str, int]:
    out = {}
    for idx, value in enumerate(headers):
        key = (value or "").strip().lower()
        if key:
            out[key] = idx
    return out

def pick_url_column(header_map: dict[str, int]) -> int:
    candidates = [
        "url", "source_url", "listing_url", "ad_url", "link", "посилання", "url olx", "olx url"
    ]
    for name in candidates:
        if name in header_map:
            return header_map[name]
    raise RuntimeError("Could not detect URL column in sheet")

def is_olx_url(value: str) -> bool:
    if not value:
        return False
    v = value.strip().lower()
    return "olx.ua/" in v or "olx.com/" in v

def read_olx_rows(spreadsheet_id: str, worksheet_name: str):
    gc = get_client()
    sh = gc.open_by_key(spreadsheet_id)
    ws = sh.worksheet(worksheet_name)
    values = ws.get_all_values()
    if not values:
        return []
    headers = values[0]
    header_map = find_header_map(headers)
    url_idx = pick_url_column(header_map)
    rows = []
    for i, row in enumerate(values[1:], start=2):
        url = row[url_idx].strip() if url_idx < len(row) else ""
        if is_olx_url(url):
            rows.append({
                "sheet_name": worksheet_name,
                "row_number": i,
                "url": url,
            })
    return rows
