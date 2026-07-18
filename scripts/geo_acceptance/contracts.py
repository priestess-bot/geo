"""Configuration and immutable channel contracts for GEO acceptance."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path


CHANNELS: tuple[dict[str, str], ...] = (
    {
        "channel": "owned_site",
        "key": "simulated.advinsys.example",
        "url": "https://simulated.advinsys.example/",
    },
    {
        "channel": "productreview",
        "key": "productreview.com.au/advinsys",
        "url": "https://www.productreview.com.au/",
    },
    {
        "channel": "youtube",
        "key": "channel/UCmyUEh-krsFHszEC8XFKtuQ",
        "url": "https://www.youtube.com/",
    },
    {
        "channel": "reddit",
        "key": "disclosed-brand-participation",
        "url": "https://www.reddit.com/",
    },
    {
        "channel": "amazon",
        "key": "ADVINSYS-AU-store",
        "url": "https://www.amazon.com.au/",
    },
    {
        "channel": "ozbargain",
        "key": "authorised-merchant-deals",
        "url": "https://www.ozbargain.com.au/",
    },
    {
        "channel": "tiktok",
        "key": "@advinsys27",
        "url": "https://www.tiktok.com/",
    },
    {
        "channel": "instagram",
        "key": "@advinsysau",
        "url": "https://www.instagram.com/",
    },
    {
        "channel": "quora",
        "key": "disclosed-expert-answers",
        "url": "https://www.quora.com/",
    },
)

PRODUCT_URL = "https://www.advinsys.com.au/products/triple-cam-ai-vision-robot-mower-v600"
MODEL = "deepseek-v4-flash"
MODEL_POLICY_HASH = hashlib.sha256(b"geo-acceptance-model-policy-v1").hexdigest()


@dataclass(frozen=True)
class AcceptanceConfig:
    app_database_url: str
    worker_database_url: str
    run_id: str
    output_path: Path
    live_deepseek: bool = False
    deepseek_key_file: Path | None = None
    runtime_object_store: bool = False
    environment: str = "staging"
    target_manifest: Path | None = None
    customer_invitation_output: Path | None = None

    def validate(self) -> None:
        if self.environment not in {"staging", "test"}:
            raise ValueError("controlled acceptance may run only in staging or test")
        if not self.app_database_url.strip() or not self.worker_database_url.strip():
            raise ValueError("app and worker PostgreSQL URLs are required")
        if not self.run_id.strip() or len(self.run_id) > 100:
            raise ValueError("run_id must contain between 1 and 100 characters")
        if self.live_deepseek:
            if self.deepseek_key_file is None:
                raise ValueError("--live-deepseek requires --deepseek-key-file")
            if not self.deepseek_key_file.is_file():
                raise ValueError("the DeepSeek key file does not exist")
        if self.target_manifest is not None:
            if not self.target_manifest.is_file():
                raise ValueError("the target company manifest does not exist")
            payload = json.loads(self.target_manifest.read_text(encoding="utf-8"))
            if payload.get("schema_version") != 1:
                raise ValueError("the target company manifest schema is unsupported")
