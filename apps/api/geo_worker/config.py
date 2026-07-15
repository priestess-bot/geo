from __future__ import annotations

import os
from pathlib import Path


def secret_setting(name: str) -> str:
    direct = os.getenv(name, "").strip()
    file_name = os.getenv(f"{name}_FILE", "").strip()
    if direct and file_name:
        raise RuntimeError(f"configure {name} directly or by file, not both")
    if file_name:
        try:
            direct = Path(file_name).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(f"{name}_FILE cannot be read") from exc
    if not direct:
        raise RuntimeError(f"{name} or {name}_FILE is required")
    return direct
