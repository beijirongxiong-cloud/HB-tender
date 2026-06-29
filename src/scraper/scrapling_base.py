import asyncio
import re
from datetime import datetime
from typing import Optional

from src.scraper.base import BaseScraper, TenderItem


class ScraplingScraper(BaseScraper):
    def __init__(self, site_config: dict):
        super().__init__(site_config)
        self._cached_items: Optional[list[TenderItem]] = None

    @property
    def supports_keyword_search(self) -> bool:
        return True

    async def login(self, page) -> bool:
        return True

    async def parse_detail(self, page, url: str) -> Optional[TenderItem]:
        return None

    def _do_fetch_details(self, items: list[TenderItem]) -> list[TenderItem]:
        return items

    async def run(self, keywords_by_category: dict[str, list[str]], since: Optional[datetime] = None) -> list[TenderItem]:
        results: list[TenderItem] = []
        for category, keywords in keywords_by_category.items():
            for keyword in keywords:
                self.logger.info(f"Searching {self.site_name}: [{category}] {keyword}")
                try:
                    items = await self.search(None, keyword, category)
                    if since:
                        items = [item for item in items if self._is_after(item, since)]
                    results.extend(items)
                    self.logger.info(f"Found {len(items)} items for [{category}] {keyword}")
                except Exception as e:
                    self.logger.error(f"Search failed for [{category}] {keyword}: {e}")

        return results

    async def run_with_details(self, keywords_by_category: dict[str, list[str]], since: Optional[datetime] = None, filtered_items: Optional[list[TenderItem]] = None) -> list[TenderItem]:
        if filtered_items is None:
            filtered_items = await self.run(keywords_by_category, since)

        if filtered_items and hasattr(self, '_do_fetch_details') and self.__class__._do_fetch_details is not ScraplingScraper._do_fetch_details:
            self.logger.info(f"Fetching details for {len(filtered_items)} items from {self.site_name}")
            import concurrent.futures
            if not hasattr(ScraplingScraper, '_pool'):
                ScraplingScraper._pool = concurrent.futures.ThreadPoolExecutor(max_workers=7)
            loop = asyncio.get_event_loop()
            filtered_items = await loop.run_in_executor(ScraplingScraper._pool, self._do_fetch_details, filtered_items)

        return filtered_items

    async def search(self, page, keyword: str, category: str) -> list[TenderItem]:
        import concurrent.futures
        if not hasattr(ScraplingScraper, '_pool'):
            ScraplingScraper._pool = concurrent.futures.ThreadPoolExecutor(max_workers=7)

        def sync_search():
            if self.supports_keyword_search:
                from scrapling import StealthyFetcher
                fetcher = StealthyFetcher()
                items = self._do_search(fetcher, keyword, category)
                for item in items:
                    item.category = category
                return items
            else:
                if self._cached_items is None:
                    from scrapling import StealthyFetcher
                    fetcher = StealthyFetcher()
                    self._cached_items = self._do_search(fetcher, "", "")
                return self._filter_keyword(self._cached_items, keyword, category)

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(ScraplingScraper._pool, sync_search)

    def _do_search(self, fetcher, keyword: str, category: str) -> list[TenderItem]:
        raise NotImplementedError("Subclasses must implement _do_search")

    @staticmethod
    def _extract_bid_count(title: str) -> str:
        import re
        for pattern, val in [
            (r'第[四4]次', '第四次'),
            (r'第[三3]次', '第三次'),
            (r'第[二2]次', '第二次'),
            (r'第[一1]次', '第一次'),
            (r'[（(]\s*[二2]\s*[)）]', '第二次'),
            (r'[（(]\s*[三3]\s*[)）]', '第三次'),
            (r'[（(]\s*[四4]\s*[)）]', '第四次'),
            (r'二次', '第二次'),
            (r'三次', '第三次'),
            (r'四次', '第四次'),
        ]:
            if re.search(pattern, title):
                return val
        return '第一次'

    @staticmethod
    def _filter_keyword(items: list[TenderItem], keyword: str, category: str) -> list[TenderItem]:
        if not keyword:
            return items
        parts = [p.strip() for p in keyword.split("/") if len(p.strip()) >= 2]
        if not parts:
            parts = [keyword]
        result = []
        for item in items:
            title = item.project_name or ""
            if any(p in title for p in parts):
                item.category = category
                result.append(item)
        return result

    @staticmethod
    def _filter_keyword_strict(items: list[TenderItem], keyword: str, category: str) -> list[TenderItem]:
        if not keyword:
            return items
        parts = [p.strip() for p in keyword.split("/") if len(p.strip()) >= 2]
        if not parts:
            parts = [keyword]
        result = []
        for item in items:
            title = item.project_name or ""
            if any(p in title for p in parts):
                item.category = category
                result.append(item)
        return result

    @staticmethod
    def _extract_bidder_from_title(title: str) -> str:
        m = re.match(r'^([\u4e00-\u9fa5]+(?:公司|集团|分局|中心|研究院|研究所|局|院|处|部|厅|委|办|站|所|学校|医院|协会|基金会))', title)
        if m:
            return m.group(1)
        m = re.match(r'^(.{2,25}?)(?:\d{4}年|\d{4}[-/])', title)
        if m:
            name = m.group(1).rstrip('的')
            if len(name) >= 2:
                return name
        return ""

    @staticmethod
    def _is_after(item: TenderItem, since: datetime) -> bool:
        if not item.date:
            return True
        try:
            item_date = datetime.strptime(item.date, "%Y-%m-%d")
            return item_date.date() >= since.date()
        except (ValueError, TypeError):
            return True
