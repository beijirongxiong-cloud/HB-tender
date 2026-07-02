import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from datetime import datetime, timedelta
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
from src.scraper.ctbpsp import CtbpspScraper
from src.scraper.iccec import IccecScraper
from src.scraper.chng import ChngScraper
from src.scraper.chnenergy import ChnenergyScraper

from src.processor.filter import apply_blacklist, apply_keyword_strict_filter, apply_bid_result_filter
from src.processor.dedup import deduplicate
from src.processor.formatter import format_for_feishu
from src.output.feishu_sheet import FeishuSpreadsheetClient
from src.llm.client import LLMClient
from src.llm.screener import LLMScreener
from src.llm.extractor import LLMExtractor
from src.utils.logger import setup_logger
from src.utils.notify import send_feishu_alert

logger = setup_logger("full_scrape")

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
    "ctbpsp": CtbpspScraper,
    "iccec": IccecScraper,
    "chng": ChngScraper,
    "chnenergy": ChnenergyScraper,
}


async def run_full_scrape():
    logger.info("=== Starting FULL scrape ===")

    with open("config/sites.yaml", "r", encoding="utf-8") as f:
        sites_config = yaml.safe_load(f)["sites"]
    with open("config/keywords.yaml", "r", encoding="utf-8") as f:
        keywords_config = yaml.safe_load(f)

    keywords_by_category = keywords_config["categories"]
    blacklist = keywords_config.get("blacklist", {})
    since = datetime.now() - timedelta(days=1)

    # Step 1: Scrape all sites (parallel for speed, with concurrency limit)
    all_items: list[TenderItem] = []
    scrapers: dict[str, BaseScraper] = {}

    semaphore = asyncio.Semaphore(3)

    async def scrape_one(cfg):
        scraper_cls = SCRAPER_MAP.get(cfg["id"])
        if not scraper_cls:
            logger.warning(f"Unknown site: {cfg['id']}")
            return [], None
        scraper = scraper_cls(cfg)
        async with semaphore:
            logger.info(f"--- Scraping {scraper.site_name} ---")
            try:
                items = await scraper.run(keywords_by_category, since)
                logger.info(f"  {scraper.site_name}: got {len(items)} items")
                all_items.extend(items)
                scrapers[scraper.site_name] = scraper
                import pickle
                with open("data/raw_items.pkl", "wb") as f:
                    pickle.dump(all_items, f)
                logger.info(f"  Saved incremental raw items ({len(all_items)} total)")
                return items, scraper
            except Exception as e:
                logger.error(f"  {scraper.site_name} FAILED: {e}")
                return [], scraper

    await asyncio.gather(*[scrape_one(cfg) for cfg in sites_config])

    logger.info(f"Total raw items: {len(all_items)}")

    if not all_items:
        logger.error("No items scraped at all. Aborting.")
        return

    import pickle
    with open("data/raw_items.pkl", "wb") as f:
        pickle.dump(all_items, f)
    logger.info("Saved raw items to data/raw_items.pkl")

    # Step 2: Layer 1 - regex coarse filter
    filtered = apply_blacklist(all_items, blacklist)
    logger.info(f"After blacklist: {len(filtered)}")
    filtered = apply_keyword_strict_filter(filtered, keywords_by_category)
    logger.info(f"After keyword filter: {len(filtered)}")
    filtered = apply_bid_result_filter(filtered)
    logger.info(f"After bid result filter: {len(filtered)}")

    # Step 3: Layer 2 - LLM semantic screening
    llm_client = LLMClient()
    screener = LLMScreener(llm_client, keywords_by_category, blacklist)
    screened = await screener.screen(filtered)
    logger.info(f"After LLM screen: {len(screened)}")

    import pickle
    with open("data/screened.pkl", "wb") as f:
        pickle.dump(screened, f)
    logger.info("Saved screened items to data/screened.pkl")

    for i, item in enumerate(screened):
        logger.info(f"  Screened [{i+1}] [{item.category}] {item.project_name}")
        logger.info(f"    URL: {item.link}")

    # Step 4: Layer 3 - fetch details only for screened items
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

    # Step 5: Layer 4 - LLM extraction
    if screened:
        items_with_text = [(item, item._detail_text) for item in screened]
        extractor = LLMExtractor(llm_client)
        screened = await extractor.extract_batch(items_with_text)
        logger.info(f"After LLM extract: {len(screened)} items")

    # Step 6: Layer 5 - write to feishu (skip dedup)
    unique = screened
    logger.info(f"Writing {len(unique)} items to Feishu (no dedup)")

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

    logger.info("=== FULL scrape completed ===")


if __name__ == "__main__":
    asyncio.run(run_full_scrape())
