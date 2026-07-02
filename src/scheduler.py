import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Optional

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.scraper.base import BaseScraper, TenderItem
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
from src.processor.filter import apply_blacklist, apply_keyword_strict_filter, apply_bid_result_filter, load_blacklist
from src.processor.dedup import deduplicate
from src.processor.formatter import format_for_feishu
from src.output.feishu_sheet import FeishuSpreadsheetClient
from src.utils.logger import setup_logger
from src.utils.notify import send_feishu_alert
from src.llm.client import LLMClient
from src.llm.screener import LLMScreener
from src.llm.extractor import LLMExtractor

logger = setup_logger("scheduler")

SCRAPER_MAP: dict[str, type[BaseScraper]] = {
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

LAST_RUN_FILE = "data/last_run.json"


def get_last_run() -> Optional[datetime]:
    if os.path.exists(LAST_RUN_FILE):
        with open(LAST_RUN_FILE, "r") as f:
            ts = json.load(f).get("last_run")
            if ts:
                return datetime.fromisoformat(ts)
    return None


def save_last_run() -> None:
    os.makedirs(os.path.dirname(LAST_RUN_FILE), exist_ok=True)
    with open(LAST_RUN_FILE, "w") as f:
        json.dump({"last_run": datetime.now().isoformat()}, f)


async def run_scrape(is_first_run: bool = False) -> None:
    logger.info(f"Starting scrape job (first_run={is_first_run})")

    with open("config/sites.yaml", "r", encoding="utf-8") as f:
        sites_config = yaml.safe_load(f)["sites"]
    with open("config/keywords.yaml", "r", encoding="utf-8") as f:
        keywords_config = yaml.safe_load(f)

    keywords_by_category = keywords_config["categories"]
    blacklist = keywords_config.get("blacklist", {})

    since = None
    if is_first_run:
        since = datetime.now() - timedelta(days=1)
    else:
        since = get_last_run()

    all_items: list[TenderItem] = []

    scrapers: dict[str, BaseScraper] = {}
    tasks = []
    for cfg in sites_config:
        scraper_cls = SCRAPER_MAP.get(cfg["id"])
        if not scraper_cls:
            logger.warning(f"Unknown site: {cfg['id']}")
            continue
        scraper = scraper_cls(cfg)
        scrapers[scraper.site_name] = scraper
        async def _run(s):
            try:
                return await s.run(keywords_by_category, since)
            except Exception as e:
                logger.error(f"Scraper {s.site_id} failed: {e}")
                send_feishu_alert(f"爬虫 **{s.site_name}** 执行失败: {str(e)[:200]}")
                return []
        tasks.append(_run(scraper))

    results = await asyncio.gather(*tasks)
    for r in results:
        all_items.extend(r)

    logger.info(f"Total raw items: {len(all_items)}")

    # Layer 1: regex coarse filter
    filtered = apply_blacklist(all_items, blacklist)
    logger.info(f"After blacklist filter: {len(filtered)}")

    filtered = apply_keyword_strict_filter(filtered, keywords_by_category)
    logger.info(f"After keyword strict filter: {len(filtered)}")

    filtered = apply_bid_result_filter(filtered)
    logger.info(f"After bid result filter: {len(filtered)}")

    # Layer 2: LLM semantic screening
    llm_client = LLMClient()
    screener = LLMScreener(llm_client, keywords_by_category, blacklist)
    screened = await screener.screen(filtered)
    logger.info(f"After LLM screen: {len(screened)}")

    # Layer 3: fetch details only for screened items
    if screened:
        by_site: dict[str, list[TenderItem]] = {}
        for item in screened:
            by_site.setdefault(item.source_site, []).append(item)

        detailed_items: list[TenderItem] = []
        for site_name, site_items in by_site.items():
            scraper = scrapers.get(site_name)
            if scraper and len(site_items) > 0:
                try:
                    enriched = await scraper.fetch_details(site_items)
                    detailed_items.extend(enriched)
                    logger.info(f"Fetched details for {len(enriched)} items from {site_name}")
                except Exception as e:
                    logger.error(f"fetch_details failed for {site_name}: {e}")
                    detailed_items.extend(site_items)
            else:
                detailed_items.extend(site_items)

        screened = detailed_items

    # Layer 4: LLM structured extraction
    if screened:
        items_with_text = [(item, item._detail_text) for item in screened]
        extractor = LLMExtractor(llm_client)
        screened = await extractor.extract_batch(items_with_text)
        logger.info(f"After LLM extract: {len(screened)} items")

    # Layer 5: dedup + feishu
    unique = deduplicate(screened)
    logger.info(f"After dedup: {len(unique)}")

    if unique:
        records = format_for_feishu(unique)
        sheet_client = FeishuSpreadsheetClient()
        success = sheet_client.create_records(records, insert_at_top=True)
        if success:
            logger.info(f"Wrote {len(records)} records to Feishu Spreadsheet: {sheet_client.spreadsheet_url()}")
        else:
            logger.error("Failed to write records to Feishu Spreadsheet")
            send_feishu_alert(f"飞书Excel写入失败，本次共有 {len(records)} 条数据待写入")
    else:
        logger.info("No new items to write")

    save_last_run()
    logger.info("Scrape job completed")


def start_scheduler() -> None:
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

    is_first = not os.path.exists(LAST_RUN_FILE)
    if is_first:
        logger.info("First run detected, will scrape last 1 day")
        scheduler.add_job(run_scrape, args=[True], id="first_run", max_instances=1)

    scheduler.add_job(
        run_scrape,
        args=[False],
        trigger=CronTrigger(day_of_week="mon-fri", hour="10,18", minute=0, timezone="Asia/Shanghai"),
        id="scheduled_scrape",
        max_instances=1,
        misfire_grace_time=300,
    )

    scheduler.start()
    logger.info("Scheduler started (Beijing time Mon-Fri 10:00 and 18:00)")

    try:
        asyncio.get_event_loop().run_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        scheduler.shutdown()
