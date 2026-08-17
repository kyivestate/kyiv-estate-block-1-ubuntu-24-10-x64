"""Photo upload via Cloudinary."""
from __future__ import annotations
import cloudinary, cloudinary.uploader
from parser_v2.config import cfg
from parser_v2.services.logging_setup import get_logger
log = get_logger("photo")

class PhotoUploader:
    def __init__(self) -> None:
        cloudinary.config(cloud_name=cfg.cloudinary.cloud_name,
            api_key=cfg.cloudinary.api_key, api_secret=cfg.cloudinary.api_secret)
        self._ok = bool(cfg.cloudinary.api_key and cfg.cloudinary.api_secret)
        if not self._ok: log.warning("Cloudinary creds not set; upload disabled")

    def upload_url(self, source_url: str, public_id: str | None = None) -> str | None:
        if not self._ok or not source_url: return None
        try:
            opts: dict = {"folder": cfg.cloudinary.folder, "overwrite": True, "resource_type": "image"}
            if public_id: opts["public_id"] = public_id
            result = cloudinary.uploader.upload(source_url, **opts)
            return result.get("secure_url", "")
        except Exception as e:
            log.warning("Upload failed %s: %s", source_url[:60], e); return None

    def upload_batch(self, urls: list[str], prefix: str = "") -> list[str]:
        out: list[str] = []
        for i, url in enumerate(urls):
            cdn = self.upload_url(url, f"{prefix}_{i}" if prefix else None)
            if cdn: out.append(cdn)
        return out

photo_uploader = PhotoUploader()
