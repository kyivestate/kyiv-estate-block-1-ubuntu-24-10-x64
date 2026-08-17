from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from commercial_v1.config import cfg
from commercial_v1.normalizers import normalize_commercial
from commercial_v1.parsers import OlxCommercialParser, RieltorCommercialParser
from commercial_v1.persistence import existing_external_ids, get_connection, save_listing, save_raw


def build_parser(source: str, operation: str, max_pages: int):
    return OlxCommercialParser(operation, max_pages) if source == "olx" else RieltorCommercialParser(operation, max_pages)


def main() -> None:
    parser = argparse.ArgumentParser(description="Isolated Kyiv commercial real-estate parser")
    parser.add_argument("--source", choices=("olx", "rieltor", "all"), default="all")
    parser.add_argument("--operation", choices=("rent", "buy", "all"), default="all")
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--max-listings", type=int, default=None)
    parser.add_argument("--full-refresh", action="store_true")
    parser.add_argument("--refresh-known", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sources = ("olx", "rieltor") if args.source == "all" else (args.source,)
    operations = ("rent", "buy") if args.operation == "all" else (args.operation,)
    stats = {"collected": 0, "raw": 0, "saved": 0, "outside_kyiv_region": 0, "failed": 0}
    connection = None if args.dry_run else get_connection()
    try:
        for source in sources:
            for operation in operations:
                default_pages = cfg.olx_max_pages if source == "olx" else cfg.rieltor_max_pages
                worker = build_parser(source, operation, args.max_pages or default_pages)
                try:
                    urls = worker.collect_listing_urls()
                    known = set() if args.dry_run or args.full_refresh else existing_external_ids(connection, source, operation)
                    new_urls = [item for item in urls if item["external_id"] not in known]
                    known_urls = [item for item in urls if item["external_id"] in known][:max(args.refresh_known, 0)]
                    urls = new_urls + known_urls
                    if args.max_listings is not None:
                        urls = urls[:args.max_listings]
                    stats["collected"] += len(urls)
                    print(f"{source}/{operation}: queued={len(urls)} new={len(new_urls)} known={len(known)}")
                    for item in urls:
                        raw, payload = worker.fetch_and_parse(item["url"], item["external_id"])
                        if payload and item.get("source_catalog"):
                            payload["source_catalog"] = item["source_catalog"]
                        if not args.dry_run:
                            raw_id = save_raw(connection, raw)
                            stats["raw"] += 1
                        else:
                            raw_id = None
                        if raw.parse_status != "parsed":
                            stats["failed"] += 1
                            continue
                        listing = normalize_commercial(raw, payload)
                        if "outside_kyiv_region" in listing.validation_errors:
                            stats["outside_kyiv_region"] += 1
                            continue
                        if not args.dry_run:
                            listing.raw_listing_id = raw_id
                            save_listing(connection, listing)
                            stats["saved"] += 1
                finally:
                    worker.close()
        if connection:
            connection.commit()
    except Exception:
        if connection:
            connection.rollback()
        raise
    finally:
        if connection:
            connection.close()
    print(" ".join(f"{key}={value}" for key, value in stats.items()))


if __name__ == "__main__":
    main()
