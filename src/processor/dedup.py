import json
import os
import re
from src.scraper.base import TenderItem
from src.utils.logger import setup_logger

logger = setup_logger("dedup")


def _normalize_key(s: str) -> str:
    s = re.sub(r'\s+', '', s)
    return s[:30]


def deduplicate(items: list[TenderItem], seen_file: str = "data/seen.json") -> list[TenderItem]:
    seen = set()
    if os.path.exists(seen_file):
        try:
            with open(seen_file, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
                if isinstance(data, list):
                    seen = set(data)
                elif isinstance(data, dict):
                    seen = set(data.keys())
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Could not load seen file, starting fresh: {e}")

    unique = []
    new_keys = []
    for item in items:
        key = item.link or _normalize_key(item.project_name + item.bidder)
        if not key or key in seen:
            continue
        seen.add(key)
        new_keys.append(key)
        unique.append(item)

    os.makedirs(os.path.dirname(seen_file), exist_ok=True)
    with open(seen_file, "w", encoding="utf-8") as f:
        json.dump(list(seen), f, ensure_ascii=False)

    logger.info(f"Dedup: {len(items)} -> {len(unique)} (removed {len(items) - len(unique)})")
    return unique
