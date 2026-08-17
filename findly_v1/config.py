"""Configuration for the isolated Findly collector."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name('.env'))


@dataclass(frozen=True)
class FindlyConfig:
    base_url: str = os.getenv('FINDLY_BASE_URL', 'https://app.findly.com.ua')
    cookie_file: Path = Path(os.getenv('FINDLY_COOKIE_FILE', '')).expanduser()
    per_page: int = int(os.getenv('FINDLY_PER_PAGE', '20'))
    request_timeout: float = float(os.getenv('FINDLY_REQUEST_TIMEOUT', '30'))
    page_delay: float = float(os.getenv('FINDLY_PAGE_DELAY', '1.5'))
    retries: int = int(os.getenv('FINDLY_RETRIES', '3'))
    active_sheet_id: str = os.getenv('FINDLY_ACTIVE_SHEET_ID', '')
    lifecycle_sheet_id: str = os.getenv('FINDLY_LIFECYCLE_SHEET_ID', '')
    credentials_file: Path = Path(os.getenv('GOOGLE_CREDENTIALS_FILE', '')).expanduser()


cfg = FindlyConfig()
