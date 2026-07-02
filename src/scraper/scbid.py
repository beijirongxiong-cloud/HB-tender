"""Revised scbid.py - Add bidder extraction from title."""
from datetime import datetime
from typing import Optional
import httpx
import re

from src.scraper.scrapling_base import ScraplingScraper, TenderItem


class ScbidScraper(ScraplingScraper):
    @property
    def supports_keyword_search(self) -> bool:
        return False

    def _do_search(self, fetcher, keyword: str, category: str) -> list[TenderItem]:
        items: list[TenderItem] = []
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            with httpx.Client(headers=headers, timeout=20, verify=False, follow_redirects=True) as client:
                seen_links = set()
                for page in range(1, 6):
                    r = client.get(f"https://www.scbid.com/zbxx/p{page}.html")
                    if r.status_code != 200:
                        break
                    html = r.text
                    pattern = r'<a[^>]*href="(https?://www\.scbid\.com/[^"]*detail[^"]*)"[^>]*>([^<]{8,})</a>'
                    matches = re.findall(pattern, html)
                    if not matches:
                        break
                    for href, title in matches:
                        title = title.strip()
                        if len(title) < 8 or href in seen_links:
                            continue
                        seen_links.add(href)
                        # Skip non-tender announcements
                        skip_words = ["成交公告", "结果公告", "中标公告", "废标公告", "终止公告",
                                      "采购预告", "事前公示", "意向公示", "需求公示", "前期公示",
                                      "计划公示", "采购意向"]
                        if any(w in title for w in skip_words):
                            continue

                        bidder = self._extract_bidder_from_title(title)
                        items.append(TenderItem(
                            date=datetime.now().strftime("%Y-%m-%d"),
                            category=category,
                            project_name=title,
                            link=href,
                            source_site=self.site_name,
                            bidder=bidder,
                            bid_count=self._extract_bid_count(title),
                        ))
                        if len(items) >= 200:
                            break
                    if len(items) >= 200:
                        break
        except Exception as e:
            self.logger.error(f"Scbid fetch failed: {e}")
        return items[:200]

    @staticmethod
    def _extract_bidder_from_title(title: str) -> str:
        m = re.match(r'^([\u4e00-\u9fa5]+(?:公司|集团|分局|中心|研究院|研究所|局|院|处|部|厅|委|办|站|所|学校|医院|协会|基金会))', title)
        if m:
            return m.group(1)
        m = re.match(r'^(.{4,25}?)(?:\d{4}年|\d{4}[-/])', title)
        if m:
            return m.group(1).rstrip('的')
        return ""
