# Kyiv Estate Block 2

Production platform for collecting, validating and publishing Kyiv real-estate listings.

## Components

- `parser_v2` — apartment listings from OLX and Rieltor.
- `houses_v1` — house listings.
- `commercial_v1` — commercial-property listings.
- `telegraph_v3` — Telegraph publication and media archive.
- `cleaning` — active/archive lifecycle processing.
- `scripts` — Google Sheets sync, reconciliation, backups and operational tasks.

## Requirements

- Python 3.12+
- PostgreSQL
- Google service-account credentials with access to the required spreadsheets
- Environment configuration for Telegram, Telegraph and external APIs

## Local setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create local environment files from the provided examples and keep credentials outside Git. Apply the SQL schemas from each component before running a parser.

## Operations

The production installation uses macOS `launchd` agents for incremental collection, full backfills, sheet reconciliation, backups and cleanup. Agent templates are stored with the relevant component. Runtime logs, database dumps, local photos and user data are intentionally excluded from this repository.
