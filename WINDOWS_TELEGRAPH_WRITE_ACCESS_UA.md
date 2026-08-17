# Kyiv Estate — доступ Windows для Telegraph і Google Sheets

Дата: 20 липня 2026 року.

## Готовий контур

Windows має два окремі права через наявний SSH-тунель до Mac:

- `kyiv_estate_block2_reader` читає лише `block2.publish_listings` для створення Telegraph-сторінок;
- `kyiv_estate_block2_writer` записує лише посилання Telegraph до `block2.telegraph_publications`.

Mac кожні 5 хвилин переносить тільки коректні посилання у клітинки `Telegraph UA` або `Telegraph EN` відповідного активного оголошення. Контур працює для квартир і будинків та для комерційної нерухомості.

Windows не має і не потребує доступу до Google service-account ключа, парсерів, production-бази напряму, `.env`, резервних копій або прав на очищення/видалення рядків. Це принципово: один неправильно написаний Windows-скрипт не може стерти чи перебудувати Google Sheets.

## Дані для `.env.block2` на Windows

```dotenv
PG_HOST=127.0.0.1
PG_PORT=55432
PG_DBNAME=real_estate
PG_READER_USER=kyiv_estate_block2_reader
PG_TELEGRAPH_WRITER_USER=kyiv_estate_block2_writer
PG_PASSWORD=
```

`PG_PASSWORD` навмисно порожній: доступ забезпечує окремий Ed25519 SSH-ключ через тунель, що слухає лише `127.0.0.1` на Windows. Не додавайте сюди пароль macOS, PostgreSQL адміністратора або ключ Google.

## Єдиний дозволений запис з Windows

Ідентифікатор оголошення: `catalog + source + external_id + operation + locale`.

- `catalog`: `residential` для квартир/будинків або `commercial` для комерційної нерухомості;
- `operation`: `rent` або `buy`;
- `locale`: `ua` або `en`;
- `telegraph_url`: тільки повний URL формату `https://telegra.ph/...`.

```sql
INSERT INTO block2.telegraph_publications
    (catalog, source, external_id, operation, locale, telegraph_url, published_at)
VALUES
    ('residential', 'olx', 'ZZR46', 'buy', 'ua', 'https://telegra.ph/example-07-20', now())
ON CONFLICT (catalog, source, external_id, operation, locale)
DO UPDATE SET
    telegraph_url = EXCLUDED.telegraph_url,
    published_at = EXCLUDED.published_at;
```

Для комерційного оголошення змінюється лише `catalog`:

```sql
INSERT INTO block2.telegraph_publications
    (catalog, source, external_id, operation, locale, telegraph_url)
VALUES
    ('commercial', 'rieltor', '12814261', 'rent', 'ua', 'https://telegra.ph/example-commercial-07-20')
ON CONFLICT (catalog, source, external_id, operation, locale)
DO UPDATE SET telegraph_url = EXCLUDED.telegraph_url;
```

Посилання потрапляє в Google Sheets лише коли відповідне оголошення є активним і знайдене за джерелом, зовнішнім ID та операцією. Оновлення змінює одну клітинку, не змінює порядок рядків, заголовки, фото, ціни чи будь-які інші поля.

## Перевірка статусу

```sql
SELECT catalog, source, external_id, operation, locale, telegraph_url, published_at, synced_at, sync_error
FROM block2.telegraph_publications
ORDER BY updated_at DESC
LIMIT 100;
```

`synced_at` означає час успішного запису до Google Sheets. Якщо оголошення неактивне, не знайдене або URL не відповідає формату Telegraph, поле `sync_error` міститиме причину, а таблиці не зміняться.

## Автоматизація на Mac

LaunchAgent `com.realestate.telegraph_sheet_sync` запущений з інтервалом 300 секунд. Його виконуваний сценарій:

```text
/Users/admin/Projects/real-estate-platform/telegram-bot/parser_v2/scripts/sync_telegraph_to_sheets.py
```

Він використовує той самий process-safe lock, що основний синхронізатор. Якщо основний pipeline у цей момент оновлює Google Sheets, Telegraph-синхронізація завершується без помилки та повторюється наступного циклу.

## Заборонені дії

- Не передавати Windows приватний SSH-ключ Mac, Google service-account JSON, пароль PostgreSQL адміністратора або `.env` Блоку 1.
- Не надавати Windows Google Drive Editor/Owner для production-таблиць.
- Не виконувати `DELETE`, `TRUNCATE`, DDL, `UPDATE` інших таблиць або прямі Google Sheets API-операції з Windows.
- Не змінювати `ID`, `Ext ID`, `Source`, `Operation`, назви вкладок чи порядок колонок.

Ці обмеження не можна ігнорувати. Вони гарантують, що Windows-компонент Telegraph є ізольованим доповненням, а не ризиком для production-контуру Kyiv Estate.

## Відкликання доступу

```bash
psql -U admin -d real_estate -c "ALTER ROLE kyiv_estate_block2_writer NOLOGIN;"
launchctl bootout "gui/$(id -u)/com.realestate.telegraph_sheet_sync"
```

Для повернення доступу достатньо виконати:

```bash
psql -U admin -d real_estate -c "ALTER ROLE kyiv_estate_block2_writer LOGIN;"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.realestate.telegraph_sheet_sync.plist"
```
