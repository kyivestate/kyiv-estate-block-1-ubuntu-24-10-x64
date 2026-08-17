# Data contract

## Listing identity

`source + external_id` is the immutable deduplication key. URLs, titles and prices may change, but a record is never duplicated when this key already exists.

## Statuses

- `active` — visible in the Active workbook.
- `inactive` — source absence confirmed twice; retained in the lifecycle workbook.
- `quarantine` — inconsistent or anomalous data; retained for review and excluded from Active.
- `archived` — retained historical record.

## Field rules

- Structured data from the source page has priority over text extraction.
- Raw HTML is retained and used for local backfill before any additional source request.
- Missing facts remain missing. The platform must not invent a floor, area, room count, phone number, owner or address.
- Agent and phone fields are filled only when the source exposes them. OLX phone data is not bypassed when it is intentionally hidden by the source.
- AI title and AI description are deterministic Ukrainian copy built from verified fields and the cleaned source description. Contacts, commission, intermediaries and calls to action are removed.

## Google Sheets lifecycle

The Active workbook receives only database rows with `status='active'`. Before a non-active or orphaned Active row is removed, its data is present in the lifecycle workbook. Deletion is bounded per cycle to prevent a mass-clear event.
