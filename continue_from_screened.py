import asyncio
import os
import sys
import pickle
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import yaml

from src.scraper.base import TenderItem, BaseScraper
from src.scraper.chinabidding import ChinaBiddingScraper
from src.scraper.mobile import MobileScraper
from src.scraper.tower import TowerScraper
from src.scraper.csg import CsgScraper
from src.scraper.sgcc import SgccScraper
from src.scraper.scbid import ScbidScraper
from src.scraper.unicom import UnicomScraper
from src.scraper.telecom import TelecomScraper
from src.scraper.cnncecp import CnncecpScraper

from src.processor.filter import apply_blacklist, apply_keyword_strict_filter, apply_bid_result_filter
from src.processor.dedup import deduplicate
from src.processor.formatter import format_for_feishu
from src.output.feishu_sheet import FeishuSpreadsheetClient
from src.llm.client import LLMClient
from src.llm.screener import LLMScreener
from src.llm.extractor import LLMExtractor
from src.utils.logger import setup_logger
from src.utils.notify import send_feishu_alert

logger = setup_logger("continue_scrape")

SCRAPER_MAP = {
    "chinabidding": ChinaBiddingScraper,
    "mobile": MobileScraper,
    "tower": TowerScraper,
    "csg": CsgScraper,
    "sgcc": SgccScraper,
    "scbid": ScbidScraper,
    "unicom": UnicomScraper,
    "telecom": TelecomScraper,
    "cnncecp": CnncecpScraper,
}


async def continue_scrape():
    logger.info("=== Continuing from screened.pkl ===")

    # Load screened items
    with open("data/screened.pkl", "rb") as f:
        screened = pickle.load(f)
    logger.info(f"Loaded {len(screened)} screened items")

    # Load configs for scraper init
    with open("config/sites.yaml", "r", encoding="utf-8") as f:
        sites_config = yaml.safe_load(f)["sites"]

    # Init scrapers
    scrapers: dict[str, BaseScraper] = {}
    for cfg in sites_config:
        scraper_cls = SCRAPER_MAP.get(cfg["id"])
        if scraper_cls:
            scraper = scraper_cls(cfg)
            scrapers[scraper.site_name] = scraper

    # Step 1: Fetch details for screened items
    if screened:
        by_site: dict[str, list[TenderItem]] = {}
        for item in screened:
            by_site.setdefault(item.source_site, []).append(item)

        detailed_items: list[TenderItem] = []
        for site_name, site_items in by_site.items():
            scraper = scrapers.get(site_name)
            if scraper and len(site_items) > 0:
                logger.info(f"Fetching details for {len(site_items)} items from {site_name}")
                try:
                    enriched = await scraper.fetch_details(site_items)
                    detailed_items.extend(enriched)
                    logger.info(f"  Got details for {len(enriched)} items")
                except Exception as e:
                    logger.error(f"  fetch_details failed for {site_name}: {e}")
                    detailed_items.extend(site_items)
                await asyncio.sleep(2)
            else:
                detailed_items.extend(site_items)

        screened = detailed_items

    # Step 2: LLM extraction
    if screened:
        llm_client = LLMClient()
        items_with_text = [(item, item._detail_text) for item in screened]
        extractor = LLMExtractor(llm_client)
        screened = await extractor.extract_batch(items_with_text)
        logger.info(f"After LLM extract: {len(screened)} items")

    # Step 3: Write to feishu
    unique = screened
    logger.info(f"Writing {len(unique)} items to Feishu")

    if unique:
        for item in unique:
            logger.info(f"  [{item.category}] {item.project_name[:50]} | {item.bidder} | budget={item.budget}")

        records = format_for_feishu(unique)
        sheet_client = FeishuSpreadsheetClient()
        success = sheet_client.create_records(records, insert_at_top=True)
        if success:
            logger.info(f"Wrote {len(records)} records to Feishu: {sheet_client.spreadsheet_url()}")
        else:
            logger.error("Failed to write to Feishu")
    else:
        logger.info("No new items to write")

    logger.info("=== Continue scrape completed ===")


if __name__ == "__main__":
    asyncio.run(continue_scrape())
