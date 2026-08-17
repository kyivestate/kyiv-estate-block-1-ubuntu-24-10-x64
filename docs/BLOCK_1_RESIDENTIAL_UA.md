# Блок 1 — житлова нерухомість Києва

## Призначення і межі

Блок 1 — production-контур квартир і будинків Києва. Він збирає оголошення з OLX і Rieltor, зберігає першоджерело, нормалізує факти, контролює актуальність, створює безпечні AI-тексти та синхронізує активну й історичну Google Sheets.

Блок 1 не створює Telegraph-сторінки, не керує Telegram-ботом і не виконує Windows-код. Його дані можуть читатися Блоком 2 тільки через підготовлене представлення `block2.publish_listings`.

```text
OLX / Rieltor
  → parser_v2/parsers
  → parser_v2_raw_listings
  → normalizers + validators + persistence
  → active_listings
  → AI-safe title/description + quality filter
  → Active Google Sheets
  → Lifecycle Google Sheets
  ↘ health / audit / backup
```

## Файли і відповідальність

| Компонент | Файл або таблиця | Дія |
|---|---|---|
| Збір OLX | `parser_v2/parsers/olx_v2.py` | Знаходить URL квартир/будинків Києва для оренди й продажу; витягує деталі сторінки. |
| Збір Rieltor | `parser_v2/parsers/rieltor_v2.py` | Збирає й детально розбирає URL Rieltor. |
| Pipeline | `parser_v2/pipeline_v2.py` | Керує collection, завантаженням, normalizing, upsert і фільтрацією. |
| Первинні дані | `parser_v2_raw_listings` | Зберігає URL, HTTP-стан, raw HTML/JSON, хеш і помилки. Це база для повторного локального розбору. |
| Нормалізовані дані | `parser_v2_normalized_listings` | Проміжний нормалізований результат перед production-upsert. |
| Production-дані | `active_listings` | Єдине джерело істини для житлових записів. |
| Запис у БД | `parser_v2/services/persistence.py` | Upsert за `source + external_id`; оновлює дані одного й того самого оголошення без створення дубля. |
| AI-тексти | `parser_v2/services/ai_listing_copy.py` | Будує український AI-title та AI-description тільки з перевірених полів і очищеного опису. |
| Синхронізація Active | `parser_v2/scripts/run_all.py` | Формує рядки й оновлює Active Sheets під спільним lock. |
| Синхронізація історії | `parser_v2/scripts/sync_listing_lifecycle.py` | Зберігає історичні статуси та записи у lifecycle-книзі. |

## Ідентичність, URL та статуси

Ключ дедуплікації — `source + external_id`.

- OLX: `olx_ID…`, де `ID…` витягується з URL оголошення.
- Rieltor: `rieltor_…`, де номер витягується з URL сторінки.
- URL, ціна, заголовок або опис можуть змінитися, але це не створює новий запис при тому самому ключі.

Статуси:

| Статус | Значення | Відображення |
|---|---|---|
| `active` | Джерело підтверджує доступність і дані пройшли правила якості. | Active Sheets і lifecycle Sheets. |
| `inactive` | Оголошення стало недоступним або це підтверджений дубль. | Лише lifecycle/БД. |
| `quarantine` | Дані аномальні, суперечливі або недостатні. | БД і lifecycle, не Active. |
| `archived` | Історичний запис, який не бере участі в актуальному потоці. | БД і lifecycle. |

Перед зміною ідентифікаторів активних записів створена таблиця відкату `external_id_active_migration_20260724`: вона зберігає старий і новий ID, дію та ID запису-переможця при дедуплікації.

## Дані в `active_listings`

Групи полів:

- ідентичність: `id`, `source`, `external_id`, `operation`, `url`, `status`;
- джерельний текст: `title`, `description`, `photos`, `photo_url`, `parsed_at`;
- ціна: `price_uah`, `price_usd`, `price_eur`;
- об'єкт: `property_type`, `rooms`, `area`, `floor`, `floors_total`;
- локація: `district`, `city`, `street`, `residential_complex`, `metro_station`;
- контактні джерельні поля: `agent_type`, `agent_name`, `agent_phone`, `commission`;
- публічний текст: `ai_title`, `ai_description`, `ai_quality_score`;
- службові поля: `created_at`, `updated_at`, `comments`, `data_completeness`.

Порожнє поле означає «джерело не підтвердило значення». Система не вигадує площу, поверх, номер телефону, адресу, агента чи метро. Приховані OLX-телефони не обходяться.

## Парсинг: один 30-хвилинний цикл

LaunchAgent `com.realestate.incremental_parser` викликає `scripts/run_incremental_parser.sh` кожні 1 800 секунд. Скрипт ставить lock `/tmp/kyiv_estate_incremental_parser.lock`; повторний запуск під час активного циклу завершується без змін.

Послідовність:

1. `parser_v2.pipeline_v2 --source all --operation all --no-rebuild-sheets --no-dead-check` збирає OLX і Rieltor для оренди/продажу. На pipeline накладено 900-секундний дедлайн.
2. Знайдений URL завантажується через контрольований HTTP-клієнт; raw HTML фіксується в `parser_v2_raw_listings`.
3. Парсер витягує структуровані поля, normalizer приводить формати, а persistence виконує upsert у `active_listings`.
4. `deduplicate_listings.py` прибирає технічні дублікати; `fill_new_listings.py` дозаповнює нові фактичні поля.
5. `check_listing_statuses.py` запускається у фоні; результат не блокує Sheets-синхронізацію.
6. `run_all.py` оновлює Active Sheets. У разі тимчасової помилки Google API виконуються повторні спроби.
7. `sync_listing_lifecycle.py` передає статуси й історичні записи до lifecycle-книги.

## Дозбагачення, AI і quality control

`com.realestate.guard` підтримує `scripts_guard.sh` у режимі KeepAlive. Він не пише в Sheets напряму.

| Крок | Скрипт | Що робить |
|---|---|---|
| Raw backfill | `backfill_from_raw.py` | Витягує пропущені поля зі збереженого HTML без нового мережевого запиту. |
| Live enrichment | `enrich_missing_live.py` | Повторно відкриває лише записи з пропусками й додає лише підтверджені факти. |
| AI fast repair | `generate_ai_fast.py` | Відновлює відсутній або невалідний AI-контент. |
| AI full rebuild | `rebuild_ai_content.py` | Контрольовано оновлює версію AI-описів. |
| Quality filter | `quality_filter.py` | Виявляє аномальні ціни, площі, поверхи, сміттєві заголовки та переводить ризикові дані в quarantine. |

AI-title описує тільки об'єкт: операція, тип, кімнати, площа й підтверджена локація. AI-description спочатку подає стислий фактологічний вступ, після нього — очищені деталі з джерела. З тексту вилучаються комісія, контакти, телефони, посередники, власники, агенти та заклики до зв'язку.

## Google Sheets

| Книга | ID | Вкладки | Вміст |
|---|---|---|---|
| Active | `1RY4BiRospnPYLFoW2LLJleDgi08yomwhtUlKKvSpkr8` | `Оренда`, `Продаж` | Лише `status='active'`. |
| Lifecycle | `1B0O2rTAcbfrrMxE1XX-lHDhqi2qt_Mg-U5usql975gg` | `Оренда`, `Продаж` | Повна історія та статуси. |

`run_all.py` відображає URL-ID у колонці `Ext ID`, навіть коли старий технічний запис раніше мав числовий ключ. Він не використовує масове очищення листів: читає існуючі ID, оновлює змінені рядки та додає тільки нові. `SheetsLock` у `/tmp/kyiv_estate_sheets_writer.lock` не допускає паралельний запис із lifecycle або Telegraph sync.

Google може відмовити в редагуванні надто великої lifecycle-книги. Це не дає права очищати чи перезаписувати книгу. Такий випадок фіксується в логах, а Active Sheets та БД лишаються джерелами актуального стану до окремої контрольованої архівації lifecycle-даних.

## Надійність, backup і аудит

| Процес | Запуск | Результат |
|---|---|---|
| Backup | `com.realestate.backup`, 03:15 щодня | PostgreSQL custom dump, SHA-256, CSV-експорти Sheets у `backups/production/`. |
| Health | `parser_v2/scripts/production_health.py` | Стан служб, свіжість логів, статуси, дублікати, AI, статус-перевірки. |
| Strict health | `production_health.py --strict` | Код помилки за наявності production-проблем. |
| Audit | `platform_audit.py` | Порівнює БД, Active Sheets і lifecycle Sheets; рахує покриття полів і різницю ID. |
| Backup Sheets | `backup_sheets.py` | Експортує житлові й комерційні вкладки з retry для 429/5xx. |

## Взаємодії й заборони

- Блок 1 може читати й писати лише свої житлові таблиці та книги.
- Блок 1.2 не може писати в `active_listings` або житлові Sheets.
- Блок 2 читає тільки `block2.publish_listings`; він не має прямого запису у Блок 1.
- Telegraph URL повертається через staging `block2.telegraph_publications`, після чого Mac записує тільки відповідну клітинку `Telegraph UA/EN` під Sheets lock.
- Не запускайте вручну кілька writer-скриптів паралельно, не видаляйте lock-файли, якщо їх власник активний, і не передавайте Mac-секрети у Windows.

## Операційні перевірки

```bash
cd /Users/admin/Projects/real-estate-platform/telegram-bot
source venv/bin/activate
python parser_v2/scripts/production_health.py --strict
python parser_v2/scripts/platform_audit.py
launchctl print "gui/$(id -u)/com.realestate.incremental_parser"
```

Очікувано: немає `strict_issues`, немає дублів `source + external_id`, лог parser-а оновлюється щонайменше раз на 65 хвилин, а в Active Sheets присутні лише ID активних записів.
