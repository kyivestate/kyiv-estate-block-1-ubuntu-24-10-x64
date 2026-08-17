# Kyiv Estate — безпечне підключення Windows до Блоку 1

Дата перевірки: 19 липня 2026 року.

## Призначення

Цей документ дає Windows-проєкту Блоку 2 доступ до **перевірених актуальних оголошень** Kyiv Estate на Mac. Блок 2 може читати дані для створення Telegraph-сторінок, але не може змінювати базу, парсери чи Google Sheets.

**Ігнорувати ці обмеження не можна.** Блок 1 є production-контуром і джерелом істини. Будь-який зовнішній компонент має бути ізольованим та отримувати лише read-only дані.

## Що вже підготовлено на Mac

- Джерело даних: PostgreSQL база `real_estate`.
- Безпечний інтерфейс для Блоку 2: `block2.publish_listings`.
- У представлення потрапляють тільки записи зі статусом `active` і без технічного джерела `findly%`.
- Підготовлена роль `kyiv_estate_block2_reader` з правом входу, без прав адміністратора, створення БД, ролей чи запису даних.
- PostgreSQL слухає лише `localhost`; прямий доступ до порту БД з локальної мережі відсутній.
- На момент перевірки у безпечному представленні є 36 070 активних оголошень.

Блок 2 отримує тільки такі поля:

`id`, `external_id`, `source`, `operation`, `property_type`, `url`, `ai_title`, `ai_description`, `title`, `description`, `price_uah`, `price_usd`, `price_eur`, `rooms`, `area`, `floor`, `floors_total`, `district`, `city`, `street`, `residential_complex`, `metro_station`, `photo_url`, `photos`, `created_at`, `updated_at`, `parsed_at`.

Він **не** отримує доступ до Google Sheets, парсерів, `.env`, raw HTML, резервних копій, сервісних ключів або таблиці `active_listings` напряму.

## Архітектура

```text
Windows / Block 2 (Telegraph)
        |
        | SSH, ключ Ed25519
        v
Mac: localhost SSH tunnel
        |
        | 127.0.0.1:55432 -> 127.0.0.1:5432
        v
PostgreSQL: block2.publish_listings (SELECT only)
```

Публікація Telegraph має зберігати власний журнал і власний стан на Windows. Вона не має записувати назад у Блок 1. Ідентифікатором оголошення для дедуплікації у Блоці 2 є `source + external_id`.

## 1. Увімкнути захищений SSH-доступ на Mac

На Mac відкрийте **System Settings → General → Sharing → Remote Login** і увімкніть його. У полі доступу залиште **Only these users** та додайте лише користувача `admin`.

Альтернатива в Terminal на Mac:

```bash
sudo systemsetup -setremotelogin on
```

Ця команда потребує пароль користувача Mac і навмисно не виконується автоматично скриптами Блоку 1.

Дізнатися локальну IP-адресу Mac:

```bash
ipconfig getifaddr en0 || ipconfig getifaddr en1
```

Для роботи поза домашньою/офісною мережею не відкривайте порт 22 у роутері. Краще використати приватну VPN-мережу на кшталт Tailscale; тоді в командах нижче застосовуйте приватну VPN-адресу Mac.

## 2. Створити окремий SSH-ключ на Windows

У PowerShell **на Windows** виконайте:

```powershell
ssh-keygen -t ed25519 -a 64 -f "$env:USERPROFILE\.ssh\kyiv_estate_block2" -C "kyiv-estate-block2-windows"
```

Задайте надійний пароль для приватного ключа. Передайте на Mac лише файл:

```text
%USERPROFILE%\.ssh\kyiv_estate_block2.pub
```

Ніколи не передавайте файл без розширення `.pub`: це приватний ключ Windows.

На Mac додайте один рядок із цього `.pub`-файлу до `~/.ssh/authorized_keys` користувача `admin`, а потім виконайте:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
touch ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Перевірка підключення з Windows:

```powershell
ssh -i "$env:USERPROFILE\.ssh\kyiv_estate_block2" admin@MAC_IP
```

Замініть `MAC_IP` на LAN- або VPN-адресу Mac. Після успішної перевірки вийдіть командою `exit`.

## 3. Read-only роль бази

Роль уже активна та має ліміт до двох одночасних з'єднань. За поточної конфігурації PostgreSQL доступний лише на `localhost`, а вхід до БД відбувається всередині SSH-тунелю. Тому окремий пароль PostgreSQL для першого запуску не потрібен: мережеву автентифікацію забезпечує SSH-ключ Windows.

Перевірка прав на Mac:

```bash
psql -U admin -d real_estate -c "SELECT rolcanlogin, rolconnlimit FROM pg_roles WHERE rolname='kyiv_estate_block2_reader';"
psql -U admin -d real_estate -c "SELECT has_table_privilege('kyiv_estate_block2_reader', 'block2.publish_listings', 'SELECT') AS can_read, has_table_privilege('kyiv_estate_block2_reader', 'active_listings', 'INSERT') AS can_write;"
```

Очікуваний результат: `can_read = t`, `can_write = f`.

## 4. Створити SSH-тунель з Windows

У окремому вікні PowerShell, яке має залишатися відкритим під час роботи Блоку 2:

```powershell
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 `
  -L 127.0.0.1:55432:127.0.0.1:5432 `
  -i "$env:USERPROFILE\.ssh\kyiv_estate_block2" admin@MAC_IP
```

Це не відкриває PostgreSQL у мережу. Блок 2 звертається лише до `127.0.0.1:55432` на своєму Windows-комп’ютері, а SSH безпечно передає з’єднання до локальної БД на Mac.

Для постійної роботи тунель слід запускати окремим Windows Scheduled Task з параметром `Run whether user is logged on or not`; приватний ключ лишається в профілі Windows і має бути захищений паролем.

## 5. Конфігурація Блоку 2 на Windows

Створіть окрему папку, наприклад `C:\KyivEstate\block2-telegraph`, та локальний файл `.env.block2`:

```dotenv
PG_HOST=127.0.0.1
PG_PORT=55432
PG_DBNAME=real_estate
PG_USER=kyiv_estate_block2_reader
PG_PASSWORD=
BLOCK2_SOURCE_VIEW=block2.publish_listings
```

Додайте `.env.block2` до `.gitignore`. У цій папці **не повинно бути** копій `venv`, `.env`, Google service-account JSON, Cloudinary/API-ключів, SSH-ключів, raw HTML, дампів БД або резервних копій з Mac.

Приклад read-only запиту, який повинен використовувати Блок 2:

```sql
SELECT id, source, external_id, ai_title, ai_description, photo_url, photos, updated_at
FROM block2.publish_listings
ORDER BY updated_at DESC NULLS LAST
LIMIT 100;
```

Блок 2 не має виконувати `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, DDL або запити до `public.active_listings`.

## 6. Фінальна перевірка на Windows

Після запуску тунелю, якщо на Windows установлено PostgreSQL client (`psql`), виконайте:

```powershell
psql "host=127.0.0.1 port=55432 dbname=real_estate user=kyiv_estate_block2_reader sslmode=disable" -c "SELECT count(*) FROM block2.publish_listings;"
```

Команда має повернути кількість активних записів. Зміна цього числа між циклами парсингу є нормальною.

Додаткова безпекова перевірка:

```powershell
psql "host=127.0.0.1 port=55432 dbname=real_estate user=kyiv_estate_block2_reader sslmode=disable" -c "UPDATE public.active_listings SET status='inactive' WHERE false;"
```

Команда має завершитися помилкою `permission denied`. Не запускайте її без `WHERE false`.

## Заборонені інтеграції Блоку 2

- Не читати й не змінювати Active або lifecycle Google Sheets.
- Не запускати `run_all.py`, `scripts_guard.sh`, `run_incremental_parser.sh`, quality filter або status-check з Windows.
- Не читати `active_listings` напряму та не змінювати PostgreSQL Блоку 1.
- Не копіювати на Windows секрети Блоку 1.
- Не підключати автопублікацію до production-потоку, доки health-report Блоку 1 не має `strict_issues`.

**Ігнорувати ці заборони не можна.** Вони захищають базу, історію статусів і Google Sheets від очищення, дублів та випадкових змін.

## Відкликання доступу

Якщо Windows-комп’ютер втрачено, змінено або доступ більше не потрібен, на Mac виконайте:

```bash
psql -U admin -d real_estate -c "ALTER ROLE kyiv_estate_block2_reader NOLOGIN;"
```

Потім видаліть відповідний рядок ключа Windows із `~/.ssh/authorized_keys`. За потреби вимкніть Remote Login у System Settings.

## Чекліст запуску

- [ ] SSH увімкнено тільки для `admin`.
- [ ] Для Windows створено окремий Ed25519-ключ з паролем.
- [ ] До `authorized_keys` додано лише публічний ключ Windows.
- [ ] Увімкнено `kyiv_estate_block2_reader` з лімітом у два з'єднання.
- [ ] SSH-тунель слухає лише `127.0.0.1:55432` на Windows.
- [ ] Блок 2 читає лише `block2.publish_listings`.
- [ ] `.env.block2` не потрапляє у Git чи месенджери.
- [ ] Блок 2 не має доступу до Google Sheets і не записує в Блок 1.
