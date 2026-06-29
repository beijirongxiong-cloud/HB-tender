import re
import yaml
from src.scraper.base import TenderItem
from src.utils.logger import setup_logger

logger = setup_logger("filter")


def load_blacklist(config_path: str = "config/keywords.yaml") -> dict[str, list[str]]:
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config.get("blacklist", {})


def apply_blacklist(items: list[TenderItem], blacklist: dict[str, list[str]]) -> list[TenderItem]:
    filtered = []
    for item in items:
        if item.category in blacklist:
            keywords = blacklist[item.category]
            combined_text = (item.bidder + item.project_name).lower()
            blacklisted = False
            for rule in keywords:
                words = [w.strip().lower() for w in rule.split() if w.strip()]
                if words and all(w in combined_text for w in words):
                    logger.info(f"Blacklisted: [{item.category}] {item.project_name} (rule: {rule})")
                    blacklisted = True
                    break
            if blacklisted:
                continue
        filtered.append(item)
    return filtered


def apply_keyword_strict_filter(items: list[TenderItem], keywords_by_category: dict[str, list[str]]) -> list[TenderItem]:
    all_keywords = set()
    for cat, kws in keywords_by_category.items():
        for kw in kws:
            parts = [p.strip() for p in kw.split("/") if len(p.strip()) >= 2]
            if not parts:
                parts = [kw]
            all_keywords.update(parts)

    filtered = []
    for item in items:
        title = item.project_name or ""
        project_part = _extract_project_part(title)
        if any(kw in project_part for kw in all_keywords):
            filtered.append(item)
        else:
            logger.info(f"Keyword filtered: {title[:60]}")
    return filtered


def _extract_project_part(title: str) -> str:
    m = re.match(r'^([\u4e00-\u9fa5]+(?:公司|集团|分局|中心|研究院|研究所|局|院|处|部|厅|委|办|站|所|学校|医院|协会|基金会))', title)
    if m:
        return title[m.end():]
    m = re.match(r'^(.{2,25}?)(?:\d{4}年|\d{4}[-/])', title)
    if m:
        return title[m.end():]
    return title


_BID_RESULT_TITLE_KEYWORDS = [
    '中标', '成交结果', '结果公告', '候选人公示', '中标候选人',
    '中标公示', '成交公示', '结果公示', '中标通知', '废标',
    '流标', '终止招标', '招标终止', '撤销招标', '更正公告',
    '变更公告', '终止公告', '合同公告', '合同公示', '履约验收',
    '中标结果', '评标结果', '定标', '签约', '成交供应商',
    '预中标', '拟中标', '成交候选人',
]


def apply_bid_result_filter(items: list[TenderItem]) -> list[TenderItem]:
    """筛除投标结果(中标公示)和非招标公告，只保留正在招标的项目。"""
    filtered = []
    for item in items:
        title = item.project_name or ""

        if any(kw in title for kw in _BID_RESULT_TITLE_KEYWORDS):
            logger.info(f"Bid result filtered (title): {title[:60]}")
            continue

        filtered.append(item)
    return filtered
