# Kyiv Estate data platform

## Runtime

- `parser_v2/parsers/` — OLX and Rieltor collection and detailed extraction.
- `parser_v2/services/` — normalization, address rules, AI-safe copy, persistence, locks, currency and transport.
- `parser_v2/scripts/` — controlled maintenance, quality, lifecycle, audit, backup and verification jobs.
- `scripts/run_incremental_parser.sh` — the single 30-minute collection workflow.
- `scripts_guard.sh` — controlled background enrichment and quality supervision.
- `com.realestate.incremental_parser`, `com.realestate.guard`, `com.realestate.backup` — the only supported LaunchAgents.

## Data lifecycle

`source page → raw HTML → normalized listing → active_listings → AI-safe copy → Active Google Sheets → lifecycle Google Sheets`

Active Sheets contains only `active` records. Inactive, quarantined, archived and migrated orphan records are preserved in the lifecycle workbook.

## Archived components

`ARCHIVED_LEGACY/` contains the Telegram bot, Telegraph work, old manual writers, previous installers and obsolete recovery scripts. They are intentionally excluded from the production parser runtime.
