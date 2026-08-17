"""Parser V2 configuration."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv
load_dotenv()

@dataclass(frozen=True)
class DBConfig:
    host: str = os.getenv("PG_HOST", "localhost")
    port: int = int(os.getenv("PG_PORT", "5432"))
    dbname: str = os.getenv("PG_DBNAME", "real_estate")
    user: str = os.getenv("PG_USER", "admin")
    password: str = os.getenv("PG_PASSWORD", "")

@dataclass(frozen=True)
class CloudinaryConfig:
    cloud_name: str = os.getenv("CLOUDINARY_CLOUD_NAME", "df1b1rbhd")
    api_key: str = os.getenv("CLOUDINARY_API_KEY", "")
    api_secret: str = os.getenv("CLOUDINARY_API_SECRET", "")
    folder: str = os.getenv("CLOUDINARY_FOLDER", "kyiv_estate_v2")

@dataclass(frozen=True)
class SheetsConfig:
    credentials_file: str = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    active_sheet_id: str = os.getenv("ACTIVE_SHEET_ID", "")
    general_sheet_id: str = os.getenv("GENERAL_SHEET_ID", "")
    rent_tab: str = os.getenv("SHEET_TAB_RENT", "Оренда")
    sale_tab: str = os.getenv("SHEET_TAB_SALE", "Продаж")

@dataclass(frozen=True)
class CurrencyConfig:
    api_url: str = os.getenv("CURRENCY_API_URL", "https://api.monobank.ua/bank/currency")
    fallback_usd_uah: float = float(os.getenv("FALLBACK_USD_UAH", "41.5"))
    fallback_eur_uah: float = float(os.getenv("FALLBACK_EUR_UAH", "45.0"))
    cache_ttl_seconds: int = int(os.getenv("CURRENCY_CACHE_TTL", "3600"))

@dataclass(frozen=True)
class ParserConfig:
    rent_min_uah: int = int(os.getenv("RENT_MIN_UAH", "20000"))
    sale_min_usd: int = int(os.getenv("SALE_MIN_USD", "60000"))
    olx_workers: int = int(os.getenv("OLX_WORKERS", "5"))
    rieltor_workers: int = int(os.getenv("RIELTOR_WORKERS", "3"))
    batch_size: int = int(os.getenv("PARSER_BATCH_SIZE", "50"))
    olx_max_pages: int = int(os.getenv("OLX_MAX_PAGES", "999"))
    rieltor_max_pages: int = int(os.getenv("RIELTOR_MAX_PAGES", "999"))
    request_timeout: int = int(os.getenv("REQUEST_TIMEOUT", "30"))
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    retry_base_delay: float = float(os.getenv("RETRY_BASE_DELAY", "2.0"))
    dry_run: bool = os.getenv("DRY_RUN", "false").lower() == "true"
    upload_photos: bool = os.getenv("UPLOAD_PHOTOS", "true").lower() == "true"
    max_photos_per_listing: int = int(os.getenv("MAX_PHOTOS_PER_LISTING", "20"))

@dataclass
class AppConfig:
    db: DBConfig = field(default_factory=DBConfig)
    cloudinary: CloudinaryConfig = field(default_factory=CloudinaryConfig)
    sheets: SheetsConfig = field(default_factory=SheetsConfig)
    currency: CurrencyConfig = field(default_factory=CurrencyConfig)
    parser: ParserConfig = field(default_factory=ParserConfig)

cfg = AppConfig()
