from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class CommercialConfig:
    db_host: str = os.getenv("DB_HOST", "localhost")
    db_port: int = int(os.getenv("DB_PORT", "5432"))
    db_name: str = os.getenv("DB_NAME", "real_estate")
    db_user: str = os.getenv("DB_USER", "admin")
    db_password: str = os.getenv("DB_PASSWORD", "")
    olx_max_pages: int = int(os.getenv("COMMERCIAL_OLX_MAX_PAGES", "10"))
    rieltor_max_pages: int = int(os.getenv("COMMERCIAL_RIELTOR_MAX_PAGES", "10"))


cfg = CommercialConfig()
