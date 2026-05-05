from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings


def append_agent_log(run_id: str | int, event_type: str, payload: dict[str, Any]) -> str:
    settings.agent_log_dir.mkdir(parents=True, exist_ok=True)
    path = settings.agent_log_dir / f"{run_id}.jsonl"
    event = {
        "type": event_type,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, default=str))
        f.write("\n")
    return str(path)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
