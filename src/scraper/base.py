import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from playwright.async_api import async_playwright, Page, BrowserContext

from src.utils.logger import setup_logger

logger = setup_logger("scraper")


@dataclass
class TenderItem:
    date: str = ""
    seq: int = 0
    category: str = ""
    bidder: str = ""
    project_name: str = ""
    budget: str = ""
    bid_count: str = ""
    deadline: str = ""
    bid_time: str = ""
    link: str = ""
    doc_price: str = ""
    source_site: str = ""
    platform: str = ""
    _obj_id: str = ""
    _obj_type: int = 0
    _detail_text: str = ""


class BaseScraper(ABC):
    def __init__(self, site_config: dict):
        self.site_id = site_config["id"]
        self.site_name = site_config["name"]
        self.url = site_config["url"]
        self.has_captcha = site_config.get("has_captcha", False)
        self.captcha_type = site_config.get("captcha_type", "none")
        self.login_required = site_config.get("login_required", True)
        self.username = os.getenv(site_config.get("env_username", ""), "")
        self.password = os.getenv(site_config.get("env_password", ""), "")
        self.logger = setup_logger(f"scraper.{self.site_id}")

    @abstractmethod
    async def login(self, page: Page) -> bool:
        pass

    @abstractmethod
    async def search(self, page: Page, keyword: str, category: str) -> list[TenderItem]:
        pass

    @abstractmethod
    async def parse_detail(self, page: Page, url: str) -> Optional[TenderItem]:
        pass

    async def run(self, keywords_by_category: dict[str, list[str]], since: Optional[datetime] = None) -> list[TenderItem]:
        results: list[TenderItem] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = await context.new_page()

            try:
                if self.login_required:
                    self.logger.info(f"Logging in to {self.site_name}")
                    success = await self.login(page)
                    if not success:
                        self.logger.error(f"Login failed for {self.site_name}")
                        return results

                for category, keywords in keywords_by_category.items():
                    for keyword in keywords:
                        self.logger.info(f"Searching {self.site_name}: [{category}] {keyword}")
                        try:
                            items = await self.search(page, keyword, category)
                            if since:
                                items = [item for item in items if self._is_after(item, since)]
                            results.extend(items)
                            self.logger.info(f"Found {len(items)} items for [{category}] {keyword}")
                        except Exception as e:
                            self.logger.error(f"Search failed for [{category}] {keyword}: {e}")
            finally:
                await browser.close()

        return results

    @staticmethod
    def _is_after(item: "TenderItem", since: datetime) -> bool:
        if not item.date:
            return True
        try:
            item_date = datetime.strptime(item.date, "%Y-%m-%d").date()
            return item_date >= since.date()
        except (ValueError, TypeError):
            return True

    async def fetch_details(self, items: list[TenderItem]) -> list[TenderItem]:
        return items
