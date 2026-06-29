"""Revised yuanbo.py - Add bidder extraction from title."""
from datetime import datetime
from typing import Optional
from urllib.parse import quote
import re

from src.scraper.scrapling_base import ScraplingScraper, TenderItem


class YuanboScraper(ScraplingScraper):
    def _do_search(self, fetcher, keyword: str, category: str) -> list[TenderItem]:
        items: list[TenderItem] = []
        url = f"https://www.chinabidding.cn/public/yjsc/html/zbcg_search.html?keywords={quote(keyword)}&page=2"

        def wait_action(page):
            try:
                page.wait_for_selector(".resitem", timeout=15000)
            except:
                pass
            page.wait_for_timeout(2000)

        try:
            response = fetcher.fetch(
                url,
                headless=True,
                block_images=True,
                timeout=30000,
                page_action=wait_action,
            )
            if response.status != 200:
                return items

            for item in response.css(".resitem"):
                try:
                    links = item.css("a")
                    if not links:
                        continue
                    a = links[0]
                    title = a.text.strip() if a.text else ""
                    href = a.attrib.get("href", "")
                    if href and not href.startswith("http"):
                        href = "https://www.chinabidding.cn" + href

                    date_str = ""
                    for tip in item.css(".tip"):
                        if "nobor" in tip.attrib.get("class", ""):
                            date_str = tip.text.strip() if tip.text else ""
                            break

                    if len(title) < 5:
                        continue

                    bidder = self._extract_bidder_from_title(title)

                    items.append(TenderItem(
                        date=date_str or datetime.now().strftime("%Y-%m-%d"),
                        category=category,
                        project_name=title,
                        link=href,
                        source_site=self.site_name,
                        bidder=bidder,
                        deadline="",
                        bid_time="",
                        bid_count=self._extract_bid_count(title),
                    ))
                    if len(items) >= 10:
                        break
                except Exception:
                    continue
        except Exception as e:
            self.logger.error(f"Yuanbo fetch failed: {e}")
        return items

    @staticmethod
    def _extract_bidder_from_title(title: str) -> str:
        m = re.match(r'^([\u4e00-\u9fa5]+(?:公司|集团|分局|中心|研究院|研究所|局|院|处|部|厅|委|办|站|所|学校|医院|协会|基金会))', title)
        if m:
            return m.group(1)
        m = re.match(r'^(.{4,25}?)(?:\d{4}年|\d{4}[-/])', title)
        if m:
            return m.group(1).rstrip('的')
        return ""
