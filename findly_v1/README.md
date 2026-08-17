# Findly v1

This is an isolated production contour for Findly. It writes only `findly_*` tables and dedicated Findly workbooks. It never imports or writes the legacy `ads-collector` tables, `active_listings`, `houses_listings`, `commercial_listings`, or their Google Sheets books.

## One-time setup

1. Copy `.env.example` to `.env` and set a secure path to a current authenticated Findly browser-cookie file. Do not place the cookie file in this repository.
2. Create new, dedicated Google Sheets workbooks for Findly Active and (optionally) Findly Lifecycle. Give the configured service account access, then set their IDs in `.env`.
3. Apply `sql/schema.sql` with the production PostgreSQL role.
4. Verify credentials without writing data:

```bash
cd /Users/admin/Projects/real-estate-platform/telegram-bot
source venv/bin/activate
python -m findly_v1.pipeline --dry-run --operation all
```

## First controlled collection

```bash
python -m findly_v1.pipeline --operation all
python -m findly_v1.refresh_ai
python -m findly_v1.audit
python -m findly_v1.sync_sheets
```

The collector retrieves only listing metadata by default. `--fetch-contacts` is deliberately opt-in because Findly's contact endpoint may consume subscription credits. An active listing becomes inactive only after it is absent from two complete successful collections; a failed or partial collection does not change statuses.

`launchd/com.realestate.findly.incremental_parser.plist.template` is a template for a 30-minute schedule. It is intentionally not installed automatically; first confirm the dry run, database schema and dedicated Sheets IDs.
