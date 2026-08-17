# Блок 2 — Windows і Telegraph

## Призначення

Блок 2 створює Telegraph-сторінки на Windows із перевірених активних даних Kyiv Estate. Він ізольований від production-парсерів: не збирає OLX/Rieltor, не змінює описів, цін, статусів чи Google Sheets напряму.

Його роль — отримати підготовлені дані, створити сторінку Telegraph, зберегти власний журнал публікацій і передати назад тільки валідний URL сторінки. Mac перевіряє відповідність запису та сам оновлює одну потрібну клітинку в Google Sheets.

```text
Windows Block 2
  → SSH key + localhost tunnel
  → PostgreSQL on Mac
  → SELECT block2.publish_listings
  → Telegraph publication on Windows
  → INSERT/UPDATE block2.telegraph_publications
  → Mac Telegraph sync every 5 minutes
  → Telegraph UA / Telegraph EN cell in Active Sheets
```

## Дані, які можна читати

Роль `kyiv_estate_block2_reader` має лише `SELECT` на view `block2.publish_listings`.

View повертає тільки актуальні нетехнічні оголошення з полями, потрібними для публікації: `id`, `external_id`, `source`, `operation`, `property_type`, `url`, оригінальні та AI-тексти, ціни, кімнати, площа, поверхи, локація, фото й часові мітки.

Windows не отримує raw HTML, PostgreSQL-адміністратора, `.env`, service-account JSON, backup, доступ до `active_listings` напряму або доступ до парсерів.

## Мережа і SSH

PostgreSQL на Mac слухає лише localhost. Windows підключається через SSH-тунель:

```text
Windows 127.0.0.1:55432
  → SSH tunnel
  → Mac 127.0.0.1:5432
```

Використовується окремий Ed25519-ключ Windows. Приватний ключ лишається тільки на Windows; на Mac додається тільки публічний ключ у `~/.ssh/authorized_keys`. Для віддаленої роботи використовується приватна VPN-адреса, а не відкриття порту 22 у роутері.

Конфігурація Windows не містить паролів Блоку 1:

```dotenv
PG_HOST=127.0.0.1
PG_PORT=55432
PG_DBNAME=real_estate
PG_READER_USER=kyiv_estate_block2_reader
PG_TELEGRAPH_WRITER_USER=kyiv_estate_block2_writer
PG_PASSWORD=
```

## Дії Windows-процесу

1. Підтримує SSH-тунель до Mac.
2. Читає `block2.publish_listings` лише через `kyiv_estate_block2_reader`.
3. Дедуплікує свою роботу за `source + external_id + operation + locale`.
4. Створює або оновлює Telegraph-сторінку тільки зі схвалених полів.
5. Веде власний локальний журнал Windows про успіхи, помилки й повторні спроби.
6. Передає тільки URL виду `https://telegra.ph/...` у staging-таблицю Mac.
7. Не вважає публікацію завершеною, доки `synced_at` не заповнено на Mac.

## Єдиний дозволений запис

Роль `kyiv_estate_block2_writer` має `SELECT`, колонкові `INSERT` і `UPDATE` тільки на `block2.telegraph_publications`. Таблиця містить:

`catalog`, `source`, `external_id`, `operation`, `locale`, `telegraph_url`, `published_at`, `updated_at`, `synced_at`, `sync_error`.

`catalog` може бути тільки `residential` або `commercial`; `operation` — `rent` або `buy`; `locale` — `ua` або `en`. URL проходить перевірку формату Telegraph.

```sql
INSERT INTO block2.telegraph_publications
    (catalog, source, external_id, operation, locale, telegraph_url, published_at)
VALUES
    ('residential', 'olx', 'olx_IDOJjOh', 'rent', 'ua', 'https://telegra.ph/example-07-30', now())
ON CONFLICT (catalog, source, external_id, operation, locale)
DO UPDATE SET
    telegraph_url = EXCLUDED.telegraph_url,
    published_at = EXCLUDED.published_at;
```

Жодні `DELETE`, `TRUNCATE`, DDL, зміни `active_listings`, прямі Google Sheets API-виклики або доступ до секретів з Windows не дозволені.

## Mac-сторона повернення URL

LaunchAgent `com.realestate.telegraph_sheet_sync` запускає `scripts/run_telegraph_sheet_sync.sh` кожні 300 секунд. Він викликає `parser_v2/scripts/sync_telegraph_to_sheets.py`.

Послідовність на Mac:

1. Читає staging-рядки, де `synced_at` відсутній або старший за `updated_at`.
2. Перевіряє `catalog`, URL, джерело, external ID, операцію та активний статус об'єкта.
3. Знаходить відповідний рядок Active Sheets за `ID`.
4. Записує URL лише у `Telegraph UA` або `Telegraph EN`.
5. Проставляє `synced_at`; якщо запис неактивний, не знайдений або URL некоректний — записує `sync_error` і не змінює Sheets.

Скрипт бере `SheetsLock`. Якщо житловий sync уже пише в Google, Telegraph-задача завершується успішно зі станом `busy` і повторюється наступні п'ять хвилин. Вона не має права обійти lock.

## Перевірка стану

На Windows або через безпечний тунель:

```sql
SELECT catalog, source, external_id, operation, locale,
       telegraph_url, published_at, synced_at, sync_error
FROM block2.telegraph_publications
ORDER BY updated_at DESC
LIMIT 100;
```

- `synced_at` заповнено — URL відображено в Google Sheets.
- `sync_error` заповнено — URL не застосовано; Windows має виправити причину, а не змінювати таблиці напряму.
- порожні обидва поля — Mac очікує вільний Sheets lock або наступний 5-хвилинний запуск.

## Межі та відкликання доступу

**Ці правила не можна ігнорувати.** Вони захищають production-базу й Google Sheets від очищення, дублів та випадкових записів.

Щоб вимкнути доступ Windows на Mac:

```bash
psql -U admin -d real_estate -c "ALTER ROLE kyiv_estate_block2_reader NOLOGIN;"
psql -U admin -d real_estate -c "ALTER ROLE kyiv_estate_block2_writer NOLOGIN;"
launchctl bootout "gui/$(id -u)/com.realestate.telegraph_sheet_sync"
```

Після відкликання також видаляється відповідний публічний ключ Windows із `~/.ssh/authorized_keys`. Не потрібно й не можна передавати Windows повний доступ до Google Drive, PostgreSQL admin чи файлової системи Mac.
