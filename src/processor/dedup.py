import json
import os
from src.scraper.base import TenderItem
from src.utils.logger import setup_logger

logger = setup_logger("dedup")


def deduplicate(items: list[TenderItem], seen_file: str = "data/seen.json") -> list[TenderItem]:
    seen = set()
    if os.path.exists(seen_file):
        with open(seen_file, "r", encoding="utf-8-sig") as f:
            seen = set(json.load(f))

    unique = []
    for item in items:
        key = item.link or (item.project_name + item.bidder)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    os.makedirs(os.path.dirname(seen_file), exist_ok=True)
    with open(seen_file, "w", encoding="utf-8") as f:
        json.dump(list(seen), f, ensure_ascii=False)

    logger.info(f"Dedup: {len(items)} -> {len(unique)} (removed {len(items) - len(unique)})")
    return unique
