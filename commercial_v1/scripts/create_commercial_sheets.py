from __future__ import annotations

import json
import sys
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


CREDS = ROOT.parent / "olx-parser" / "ads-collector" / "real-estate-platform-484610-a5a172df3957.json"
REFERENCE_SHEET_ID = "1RY4BiRospnPYLFoW2LLJleDgi08yomwhtUlKKvSpkr8"
CONFIG_PATH = ROOT / "commercial_v1" / ".sheets.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
ACTIVE_TITLE = "Активна нерухомість комерційна"
LIFECYCLE_TITLE = "Загальна нерухомість — Комерційна"
TABS = ("Оренда", "Продаж")
HEADERS = [
    "ID", "Ext ID", "Фото", "Джерело", "Операція", "Статус", "Тип комерції", "Підтип", "URL",
    "Заголовок", "AI заголовок", "Опис", "AI опис",
    "Ціна за приміщення, грн", "Ціна за приміщення, $", "Ціна за приміщення, €", "Період ціни", "Ціна за м², грн", "Ціна за м², $", "Ціна за м², €", "Період ціни за м²",
    "Площа, м²", "Корисна площа, м²", "Поверх", "Висота стелі, м", "Район", "Місто", "Вулиця", "Повна адреса",
    "Призначення", "Стан", "Планування", "Потужність, кВт",
    "Генератор", "Резервне живлення", "Вентиляція", "Кондиціонування", "Фасад", "Окремий вхід", "Вітрини",
    "Рампа", "Док", "Паркомісць", "Хто розміщує", "Ім'я", "Агенція", "Телефони", "Комісія",
    "ПДВ включено", "OPEX", "Комунальні включено", "Створено", "Оновлено", "Розібрано", "Помилки валідації", "Коментарі",
]


def credentials() -> Credentials:
    if not CREDS.is_file():
        raise RuntimeError("Google service-account credentials were not found")
    return Credentials.from_service_account_file(str(CREDS), scopes=SCOPES)


def setup_sheet(book, title: str) -> None:
    worksheet = book.sheet1
    worksheet.update_title(title)
    worksheet.update(range_name="A1:BC1", values=[HEADERS], value_input_option="USER_ENTERED")
    second = book.add_worksheet(title=TABS[1], rows=1000, cols=len(HEADERS))
    second.update(range_name="A1:BC1", values=[HEADERS], value_input_option="USER_ENTERED")
    for tab in TABS:
        ws = book.worksheet(tab)
        requests = [
            {"updateSheetProperties": {"properties": {"sheetId": ws.id, "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}},
            {
                "repeatCell": {
                    "range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": 1},
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": 0.10, "green": 0.25, "blue": 0.45},
                            "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1}, "bold": True},
                            "horizontalAlignment": "CENTER",
                            "wrapStrategy": "WRAP",
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,wrapStrategy)",
                }
            },
            {"updateDimensionProperties": {"range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1}, "properties": {"pixelSize": 150}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 1, "endIndex": len(HEADERS)}, "properties": {"pixelSize": 130}, "fields": "pixelSize"}},
        ]
        book.batch_update({"requests": requests})


def create_book(drive, client, title: str, parent_id: str | None):
    metadata = {"name": title, "mimeType": "application/vnd.google-apps.spreadsheet"}
    if parent_id:
        metadata["parents"] = [parent_id]
    file = drive.files().create(body=metadata, fields="id,webViewLink").execute()
    book = client.open_by_key(file["id"])
    setup_sheet(book, TABS[0])
    return {"id": file["id"], "url": file["webViewLink"], "title": title}


def main() -> None:
    if CONFIG_PATH.exists():
        raise RuntimeError(f"{CONFIG_PATH} already exists; refusing to create duplicate commercial workbooks")
    creds = credentials()
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    reference = drive.files().get(fileId=REFERENCE_SHEET_ID, fields="parents").execute()
    parent_id = (reference.get("parents") or [None])[0]
    client = gspread.authorize(creds)
    result = {
        "active": create_book(drive, client, ACTIVE_TITLE, parent_id),
        "lifecycle": create_book(drive, client, LIFECYCLE_TITLE, parent_id),
        "tabs": list(TABS),
        "headers": HEADERS,
    }
    CONFIG_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
