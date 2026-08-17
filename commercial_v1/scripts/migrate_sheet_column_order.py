from __future__ import annotations

import json
import sys
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from commercial_v1.scripts.create_commercial_sheets import CONFIG_PATH, CREDS, HEADERS, SCOPES
from commercial_v1.scripts.sync_commercial_sheets import column_name


PREVIOUS_HEADERS = [
    "Фото", "ID", "Ext ID", "Джерело", "Операція", "Статус", "Тип комерції", "Підтип", "URL",
    "Заголовок", "Опис", "Ціна за приміщення, грн", "Ціна за приміщення, $", "Ціна за приміщення, €", "Період ціни", "Ціна за м², грн", "Ціна за м², $", "Ціна за м², €", "Період ціни за м²",
    "Площа, м²", "Корисна площа, м²", "Поверх", "Висота стелі, м", "Район", "Місто", "Вулиця", "Повна адреса", "Призначення", "Стан", "Планування", "Потужність, кВт",
    "Генератор", "Резервне живлення", "Вентиляція", "Кондиціонування", "Фасад", "Окремий вхід", "Вітрини", "Рампа", "Док", "Паркомісць", "Хто розміщує", "Ім'я", "Агенція", "Телефони", "Комісія",
    "ПДВ включено", "OPEX", "Комунальні включено", "Створено", "Оновлено", "Розібрано", "Помилки валідації",
]


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text())
    book = gspread.authorize(Credentials.from_service_account_file(str(CREDS), scopes=SCOPES)).open_by_key(config["active"]["id"])
    migrated = []
    for worksheet in book.worksheets():
        values = worksheet.get_all_values(value_render_option="FORMULA")
        header = values[0] if values else []
        if header == HEADERS:
            continue
        if header != PREVIOUS_HEADERS:
            raise RuntimeError(f"{worksheet.title}: unexpected schema; refusing to reorder")
        positions = {name: index for index, name in enumerate(header)}
        rows = []
        for source in values[1:]:
            row = {name: source[index] if index < len(source) else "" for name, index in positions.items()}
            rows.append([row.get(name, "") for name in HEADERS])
        worksheet.clear()
        worksheet.update(range_name=f"A1:{column_name(len(HEADERS))}1", values=[HEADERS], value_input_option="USER_ENTERED")
        for offset in range(0, len(rows), 300):
            start = offset + 2
            end = start + len(rows[offset:offset + 300]) - 1
            worksheet.update(range_name=f"A{start}:{column_name(len(HEADERS))}{end}", values=rows[offset:offset + 300], value_input_option="USER_ENTERED")
        migrated.append(worksheet.title)
    print(json.dumps({"migrated_tabs": migrated, "columns": len(HEADERS)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
