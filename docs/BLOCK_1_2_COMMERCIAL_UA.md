# Блок 1.2 — комерційна нерухомість Києва

## Призначення і ізоляція

Блок 1.2 збирає комерційні об'єкти Києва: офіси, магазини, склади, виробничі, HoReCa, медичні, багатофункціональні приміщення, комерційні будівлі та готельні об'єкти як нерухомість. Він підтримує оренду (`rent`) і продаж (`buy`) лише з OLX та Rieltor.

Це окремий production-контур. Він не пише в житлову `active_listings`, не запускає житловий parser, не змінює житлові Google Sheets, SSH-міст або Windows-проєкт. Спільними є лише базові безпечні механізми: Python-оточення, PostgreSQL-сервер, логування та ОС.

```text
OLX commercial / Rieltor commercial
  → commercial_v1/parsers.py
  → commercial_raw_listings
  → commercial_v1/normalizers.py
  → commercial_listings
  → commercial AI-copy and price normalization
  → Commercial Active Google Sheets
  ↘ commercial health and resumable backfill
```

## Джерела і маршрути

| Джерело | Оренда | Продаж | Ідентичність |
|---|---|---|---|
| OLX | Комерційна нерухомість Київ / оренда | Комерційна нерухомість Київ / продаж | `olx_ID…` із URL. |
| Rieltor | `commercials-rent` | `commercials-sale` | `rieltor_…` із URL. |

Адреса та текст проходять київський валідатор. Київська область, передмістя, адреса без достатнього підтвердження або явно некиївський об'єкт отримує `outside_kyiv` і не потрапляє в Active.

## Файли, таблиці та дії

| Компонент | Розташування | Дія |
|---|---|---|
| Конфігурація | `commercial_v1/config.py` | Ліміти сторінок і параметри комерційного runtime. |
| Парсери | `commercial_v1/parsers.py` | Збір URL та детальне витягування OLX/Rieltor комерції. |
| Нормалізація | `commercial_v1/normalizers.py` | Тип об'єкта, ціни, площа, інженерія, адреса, advertiser та київська валідація. |
| Raw | `commercial_raw_listings` | HTML, HTTP-статус, хеш, помилки й дані джерела. |
| Production | `commercial_listings` | Єдина таблиця актуальних комерційних даних. |
| Persistence | `commercial_v1/persistence.py` | Upsert за `source + external_id`; захищає від дублів. |
| Incremental | `commercial_v1/scripts/run_commercial.py` | Обробляє нові URL та, за потреби, обмежено refresh-ить відомі. |
| Full backfill | `commercial_v1/scripts/full_backfill.py` | Відновлюваний прохід сторінками зі state-файлами в `logs/`. |
| Google sync | `commercial_v1/scripts/sync_commercial_sheets.py` | Append/update активних рядків із блокуванням і без clear. |
| Health | `commercial_v1/scripts/health.py` | Перевіряє статуси, дублікати, некиївські активні записи, негативні ціни та поверхи. |

## Модель даних

`commercial_listings` має чотири групи даних.

1. Ідентичність і стан: `id`, `source`, `external_id`, `operation`, `status`, `url`, `published_at`, `parsed_at`, `last_seen_at`, `created_at`, `updated_at`.
2. Опис об'єкта: `commercial_type`, `commercial_subtype`, `area_total_m2`, `area_usable_m2`, `floor`, `floors_total`, `floor_label`, `ceiling_height_m`, `layout_type`, `condition`, `fitout`, `building_class`, `year_built`, `permitted_use`.
3. Ціна й умови: повна ціна та ціна за м² у source-, UAH-, USD- і EUR-полях, `price_period`, `price_per_m2_period`, ПДВ, OPEX, комунальні, депозит, індексація та строк оренди.
4. Інженерія й контакти: електропотужність, генератор, резервне живлення, вентиляція, кондиціонування, вхід, фасад, вітрини, рампа, док, парковка, advertiser, агентство й тільки відкрито опубліковані телефони.

Площа та ціна за м² не змішуються: `price_amount`/`price_uah|usd|eur` означають повну вартість, а `price_per_m2`/`price_per_m2_uah|usd|eur` — ставку за квадратний метр. Якщо одиницю ціни не можна підтвердити, її не можна порівнювати з іншими ставками.

## Автоматичні служби

| LaunchAgent | Інтервал / режим | Виконує | Захист |
|---|---|---|---|
| `com.realestate.commercial.incremental_parser` | 30 хвилин | `run_incremental_commercial.sh` | Не запускається, якщо full backfill тримає lock. |
| `com.realestate.commercial.full_backfill` | RunAtLoad, завершуваний supervisor | `run_full_backfill_all.sh` | Чотири незалежні потоки: OLX/Rieltor × rent/buy; прогрес зберігається. |
| `com.realestate.commercial.sheets_sync` | 5 хвилин | `run_sheets_sync.sh` | Окремий Sheets lock, синхронізація лише комерційної книги. |

Incremental-скрипт ставить `/tmp/kyiv_estate_commercial_incremental.lock`, збирає обмежену кількість записів для кожного джерела/операції, синхронізує Sheets і пише health-звіт. Full backfill очікує завершення incremental, ставить `/tmp/kyiv_estate_commercial_full_backfill.lock`, запускає чотири комбінації та після завершення запускає Sheets sync і health.

## Google Sheets

Книга: `Активна нерухомість комерційна`, ID `15eFtcBjMYRAHLgDFP0u6Bo57ORVy8RWZ954Hp6bDDtw`.

Вкладки:

- `Оренда`
- `Продаж`

У ній є 55 production-полів: ID, Ext ID, фото, джерело, операція, статус, тип, URL, оригінальні та AI-тексти, повна ціна у трьох валютах, ставка за м² у трьох валютах, площа, поверх, адреса, технічні характеристики, контакти, податки/витрати, дати та валідаційні помилки.

`sync_commercial_sheets.py` перевіряє, що базовий заголовок не змінений, зіставляє рядки за `ID`, додає нові, оновлює лише змінені й видаляє зі Active лише записи, що вже не мають статусу `active`. Зміни заголовка або неочікувана структура зупиняють sync, а не перезаписують книгу.

## Якість і AI-тексти

AI-title і AI-description містять лише об'єкт, площу, адресу/район та підтверджені характеристики. Вони не містять комісію, рекламу агенції, контакти, власника, агента чи заклик до зв'язку. Оригінальний опис зберігається окремо для перевірки.

Критичні правила:

- місто тільки Київ;
- від'ємні ціни, поверх понад кількість поверхів і дублікати заборонені;
- значення «фасад», «генератор», «укриття», «50 кВт» заповнюються лише коли їх прямо підтвердило джерело;
- приховані телефони й антибот-захист не обходяться;
- земля, паркомісця, франшизи й готовий бізнес без нерухомості не змішуються з моделлю приміщень.

## Перевірка та безпечна експлуатація

```bash
cd /Users/admin/Projects/real-estate-platform/telegram-bot
source venv/bin/activate
python commercial_v1/scripts/health.py
launchctl print "gui/$(id -u)/com.realestate.commercial.incremental_parser"
launchctl print "gui/$(id -u)/com.realestate.commercial.sheets_sync"
```

Health очікувано показує нуль `duplicate_source_external`, нуль `active_outside_kyiv`, нуль негативних цін і нуль некоректних поверхів. Помилка одного джерела не повинна змінювати житлову базу чи Sheets.

## Взаємодії з іншими блоками

- Блок 1.2 пише тільки `commercial_*` таблиці та свою Google-книгу.
- Блок 1.2 не змінює `active_listings`, `parser_v2_raw_listings`, житлові LaunchAgent-и чи житловий lifecycle.
- Блок 2 може читати комерційні активні записи через захищений механізм і повернути URL Telegraph тільки в staging `block2.telegraph_publications` із `catalog='commercial'`.
- Спільний Google service account зберігається лише на Mac; він не передається у Windows.
