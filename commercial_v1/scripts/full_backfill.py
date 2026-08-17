from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from commercial_v1.normalizers import normalize_commercial
from commercial_v1.parsers import OlxCommercialParser, RieltorCommercialParser
from commercial_v1.persistence import existing_external_ids, get_connection, save_listing, save_raw


def worker(source: str, operation: str, page: int):
    return OlxCommercialParser(operation, 1, page) if source == "olx" else RieltorCommercialParser(operation, 1, page)


def state_path(source: str, operation: str) -> Path:
    return ROOT / "logs" / f"commercial_backfill_{source}_{operation}.json"


def load_state(source: str, operation: str) -> dict:
    path = state_path(source, operation)
    if path.exists():
        return json.loads(path.read_text())
    return {"source": source, "operation": operation, "next_page": 1, "pages_done": 0, "saved": 0, "failed": 0, "done": False}


def save_state(state: dict) -> None:
    path = state_path(state["source"], state["operation"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def is_transient_network_error(error: Exception) -> bool:
    """Return true for recoverable source/network failures.

    A complete backfill can run for many hours.  A temporary rate limit,
    exhausted local socket pool or broken connection must retry the current
    checkpointed page instead of ending the whole source/operation pass.
    """
    messages: list[str] = []
    current: BaseException | None = error
    while current is not None:
        messages.append(f"{type(current).__name__}: {current}".lower())
        current = current.__cause__ or current.__context__
    text = " | ".join(messages)
    return isinstance(error, (ConnectionError, TimeoutError)) or any(marker in text for marker in (
        "httpx.", "requestserror", "connection reset", "connection aborted",
        "connecterror", "timeout", "temporarily unavailable", "can't assign requested address",
        "too many requests", "429",
    ))


def main() -> None:
    parser = argparse.ArgumentParser(description="Resumable full commercial backfill")
    parser.add_argument("--source", choices=("olx", "rieltor"), required=True)
    parser.add_argument("--operation", choices=("rent", "buy"), required=True)
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--until-complete", action="store_true")
    parser.add_argument("--restart", action="store_true", help="start a new complete pass from page 1")
    parser.add_argument("--refresh-existing", action="store_true", help="re-fetch known listings as well as new ones")
    args = parser.parse_args()
    if args.restart:
        path = state_path(args.source, args.operation)
        if path.exists():
            path.unlink()
    state = load_state(args.source, args.operation)
    if state["done"]:
        print(json.dumps(state, ensure_ascii=False))
        return
    connection = get_connection()
    try:
        pages_left = max(args.pages, 1)
        reconnect_attempts = 0
        network_attempts = 0
        while (args.until_complete or pages_left > 0) and not state["done"]:
            page = int(state["next_page"])
            parser_instance = worker(args.source, args.operation, page)
            try:
                urls = parser_instance.collect_listing_urls()
                if not urls:
                    state["done"] = True
                    save_state(state)
                    break
                known = set() if args.refresh_existing else existing_external_ids(connection, args.source, args.operation)
                for item in urls:
                    if item["external_id"] in known:
                        continue
                    raw, payload = parser_instance.fetch_and_parse(item["url"], item["external_id"])
                    if payload and item.get("source_catalog"):
                        payload["source_catalog"] = item["source_catalog"]
                    raw_id = save_raw(connection, raw)
                    if raw.parse_status != "parsed":
                        state["failed"] += 1
                        continue
                    listing = normalize_commercial(raw, payload)
                    if "outside_kyiv_region" in listing.validation_errors:
                        continue
                    listing.raw_listing_id = raw_id
                    save_listing(connection, listing)
                    state["saved"] += 1
                connection.commit()
                state["pages_done"] += 1
                state["next_page"] = page + 1
                state.pop("last_error", None)
                state.pop("last_transient_error", None)
                save_state(state)
                print(json.dumps(state, ensure_ascii=False), flush=True)
                pages_left -= 1
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as exc:




                state["last_error"] = str(exc)[:500]
                save_state(state)
                reconnect_attempts += 1
                try:
                    connection.close()
                except Exception:
                    pass
                if reconnect_attempts > 5:
                    raise
                time.sleep(min(30, reconnect_attempts * 3))
                connection = get_connection()
                continue
            except Exception as exc:
                if is_transient_network_error(exc):
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                    network_attempts += 1
                    state["last_transient_error"] = str(exc)[:500]
                    state["network_attempts"] = network_attempts
                    save_state(state)
                    if network_attempts > 8:
                        raise RuntimeError(
                            f"network retry budget exhausted for {args.source}/{args.operation} page {page}"
                        ) from exc
                    delay = min(300, 10 * (2 ** (network_attempts - 1)))
                    print(json.dumps({
                        "source": args.source, "operation": args.operation, "page": page,
                        "transient_error": type(exc).__name__, "retry_in_seconds": delay,
                    }, ensure_ascii=False), flush=True)
                    time.sleep(delay)
                    continue
                try:
                    connection.rollback()
                except Exception:
                    pass
                state["last_error"] = str(exc)[:500]
                save_state(state)
                raise
            finally:
                parser_instance.close()
            reconnect_attempts = 0
            network_attempts = 0
            if not args.until_complete:
                break
    finally:
        connection.close()


if __name__ == "__main__":
    main()
