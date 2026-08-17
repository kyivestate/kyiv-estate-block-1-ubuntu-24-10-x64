# Block 3: масова публікація Telegraph

Цей контур читає **лише активні** записи трьох production-таблиць, створює двомовні Telegraph-сторінки та передає готові URL окремому Mac sync. Він не записує в `active_listings`, `houses_listings`, `commercial_listings` або Google Sheets напряму.

Фото завантажуються до контрольованого Cloudinary-акаунта перед публікацією. У Telegraph ніколи не потрапляють прямі URL OLX/Rieltor. Для кожного оголошення використовується весь дедуплікований список `photos` плюс `photo_url`, якщо його ще немає в списку. Логотип `assets/kyiv-estate-logo.jpg` є другим зображенням після головного фото.

## Безпечний запуск

```bash
cd /Users/admin/Projects/real-estate-platform/telegram-bot
venv/bin/python telegraph_v3/telegraph_batch.py --migrate
venv/bin/python telegraph_v3/telegraph_batch.py --dry-run --limit 10
venv/bin/python telegraph_v3/telegraph_batch.py --limit 10
```

За замовчуванням скрипт не виконує нескінченний масовий запуск: `--limit` обов'язковий. Планувальник може викликати його невеликими пакетами. Повторний запуск продовжує незавершені роботи та не створює нових сторінок, коли контент не змінився.

Після кожного успішного пакета script одразу запускає `sync_to_sheets.py`: UA і EN URL записуються у свій рядок Active Google Sheets. Опція `--no-sync` існує лише для технічного обслуговування. Якщо Sheets зайняті іншим штатним writer-процесом, sync повертає безпечний `busy`, а URL уже збережений у PostgreSQL та буде внесений наступним запуском.

Необхідні змінні середовища: `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`, `TELEGRAPH_ACCESS_TOKEN` (або доступ до створення Telegraph-акаунта). Не записуйте ці значення в код або документацію.
