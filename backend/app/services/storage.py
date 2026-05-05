from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from app.config import settings


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write_email_blob(email_id: int | str, name: str, content: bytes | str) -> str:
    base = settings.storage_dir / "emails" / str(email_id)
    base.mkdir(parents=True, exist_ok=True)
    path = base / name
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)
    return str(path)


def read_text_ref(path: str | None) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="ignore")


def remove_ref(path: str | None) -> bool:
    if not path:
        return False
    p = Path(path)
    if not _is_allowed_storage_path(p) or not p.exists():
        return False
    if p.is_dir():
        shutil.rmtree(p)
    else:
        p.unlink()
    return True


def remove_email_blob_dir(email_id: int | str) -> bool:
    base = settings.storage_dir / "emails" / str(email_id)
    if not base.exists():
        return False
    shutil.rmtree(base)
    return True


def _is_allowed_storage_path(path: Path) -> bool:
    try:
        path.resolve().relative_to(settings.storage_dir.resolve())
    except ValueError:
        return False
    return True
