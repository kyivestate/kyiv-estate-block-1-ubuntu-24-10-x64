# Розділ X — Contact Coverage

Це повністю ізольований контур Блоку 1 для способів зв'язку з активними оголошеннями. Він **лише читає** `active_listings`, `houses_listings` і `commercial_listings`; єдина таблиця, у яку він може писати — `contact_coverage_listings`.

## Правила

- `public_phone` — номер уже збережений як відкритий контакт у джерельному полі.
- `source_link` — безпечний спосіб зв'язку через первинний URL; контакт не приховується і не намагається розкриватись.
- `public_text_candidate` — лише позначка для ручної перевірки явного номера в уже збереженому тексті OLX. Скрипт не переносить цей номер у власну таблицю автоматично.
- Жодних браузерних кліків «показати номер», CAPTCHA, авторизації, сторонніх номерних баз, пошуку за адресою або обхідних запитів.
- Для Google Sheets використовується тільки наявна колонка контактів: `Agent Phone` у книгах квартир/будинків і `Телефони` у книзі комерції. Скрипт оновлює лише порожні клітинки, не створює книги, вкладки або колонки та не використовує `clear()`.

## Контрольований запуск

```bash
cd /Users/admin/Projects/real-estate-platform/telegram-bot
source venv/bin/activate

# Спочатку read-only перевірка.
python -m contact_coverage_v1.refresh

# Одноразово, після перевірки, створити лише власну схему.
psql -d real_estate -f contact_coverage_v1/sql/schema.sql

# Записати projection лише в contact_coverage_listings.
python -m contact_coverage_v1.refresh --apply
python -m contact_coverage_v1.audit

# Знайти номери, які вже явно надруковані в тексті OLX (без мережевих запитів).
python -m contact_coverage_v1.backfill_public_text_phones
python -m contact_coverage_v1.backfill_public_text_phones --apply
python -m contact_coverage_v1.refresh --apply

# Перевірити, які лише порожні клітинки буде заповнено.
python -m contact_coverage_v1.sync_existing_phone_columns

# Після перевірки виконати точкове заповнення наявних колонок номерів.
python -m contact_coverage_v1.sync_existing_phone_columns --apply
```

Поточна ціль — 100% **contactability**, а не 100% телефонів: кожен активний рядок матиме або підтверджений публічний номер, або канонічний URL джерела.
