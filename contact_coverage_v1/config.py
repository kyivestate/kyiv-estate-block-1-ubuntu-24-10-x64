"""Configuration for the isolated contact-coverage contour."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv



load_dotenv(Path(__file__).parents[1] / ".env")


@dataclass(frozen=True)
class ContactCoverageConfig:
    db_host: str = os.getenv("PG_HOST", os.getenv("DB_HOST", "localhost"))
    db_port: int = int(os.getenv("PG_PORT", os.getenv("DB_PORT", "5432")))
    db_name: str = os.getenv("PG_DBNAME", os.getenv("DB_NAME", "real_estate"))
    db_user: str = os.getenv("PG_USER", os.getenv("DB_USER", "admin"))
    db_password: str = os.getenv("PG_PASSWORD", os.getenv("DB_PASSWORD", ""))
    credentials_file: Path = Path(os.getenv("GOOGLE_CREDENTIALS_FILE", "")).expanduser()


cfg = ContactCoverageConfig()
