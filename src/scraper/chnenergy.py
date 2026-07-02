"""Chnenergy scraper - 国能e招 (chnenergybidding.com.cn).

Static JSP site with no search API. Scrapes list pages and filters by keyword locally.

URL patterns:
  - /bidweb/001/{category}/moreinfo.html          (page 1)
  - /bidweb/001/{category}/{page}.html             (page N)
  - /bidweb/001/{category}/{subcategory}/moreinfo.html  (page 1 with subcategory)

Categories:
  - 001001 = 资格预审公告
  - 001002 = 招标公告
  - 001003 = 非招标公告
  - 001004 = 变更公告 (skip)
  - 001005 = 候选人公示 (skip)
  - 001006 = 中标公告 (skip)
  - 001007 = 终止公告 (skip)
  - 001009 = 招标计划
  - 001010 = 招标文件公示

Subcategories (for 招标公告 and 非招标公告):
  - xxx001 = 货物
  - xxx002 = 工程
  - xxx003 = 服务  <-- most relevant for 咨询/培训

List page HTML structure:
  <li>
    <div class="r-block l">
      <a href="/bidweb/001/001002/001002003/20260630/uuid.html" title="标题">
        <span class="author">编号</span>
      </a>
      <a href="..." title="标题">标题</a>
    </div>
    <span class="date">2026-06-30</span>
  </li>
"""
import re
from datetime import datetime
from typing import Optional

import httpx
from lxml import html as lxml_html

from src.scraper.scrapling_base import ScraplingScraper, TenderItem

BASE = "http://www.chnenergybidding.com.cn"
MAX_PAGES = 5

CATEGORIES = {
    "001002": "招标公告",
    "001003": "非招标公告",
}

SERVICE_SUBCATEGORIES = {
    "001002": "001002003",
    "001003": "001003003",
}

SKIP_WORDS = ["中标", "成交结果", "候选人公示", "结果公示", "流标",
              "废标", "终止公告", "评标结果", "采购预告", "事前公示",
              "意向公示", "需求公示", "前期公示", "计划公示", "采购意向"]


class ChnenergyScraper(ScraplingScraper):

    @property
    def supports_keyword_search(self) -> bool:
        return True

    def _do_search(self, fetcher, keyword: str, category: str) -> list[TenderItem]:
        items: list[TenderItem] = []
        seen_ids: set[str] = set()

        import os
        for _k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
            os.environ.pop(_k, None)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
        }

        try:
            with httpx.Client(headers=headers, timeout=25, verify=False, follow_redirects=True, proxy=None) as client:
                for cat_code, cat_name in CATEGORIES.items():
                    sub_code = SERVICE_SUBCATEGORIES.get(cat_code)
                    cat_items = self._scrape_category(client, keyword, category, cat_code, sub_code, seen_ids)
                    items.extend(cat_items)
        except Exception as e:
            self.logger.error(f"chnenergy scrape failed: {e}")
        return items

    def _scrape_category(self, client: httpx.Client, keyword: str,
                         category: str, cat_code: str, sub_code: Optional[str],
                         seen_ids: set[str]) -> list[TenderItem]:
        items: list[TenderItem] = []
        for page_num in range(1, MAX_PAGES + 1):
            if page_num == 1:
                if sub_code:
                    url = f"{BASE}/bidweb/001/{cat_code}/{sub_code}/moreinfo.html"
                else:
                    url = f"{BASE}/bidweb/001/{cat_code}/moreinfo.html"
            else:
                if sub_code:
                    url = f"{BASE}/bidweb/001/{cat_code}/{sub_code}/{page_num}.html"
                else:
                    url = f"{BASE}/bidweb/001/{cat_code}/{page_num}.html"

            try:
                r = client.get(url)
                if r.status_code != 200:
                    self.logger.warning(f"chnenergy page {page_num} returned {r.status_code}")
                    break

                page_items = self._parse_list_page(r.text, keyword, category, seen_ids)
                items.extend(page_items)

                self.logger.info(f"chnenergy cat={cat_code} page {page_num}: {len(page_items)} keyword-matched items")

                blocks = self._count_blocks(r.text)
                if blocks == 0:
                    break

            except Exception as e:
                self.logger.error(f"chnenergy scrape page {page_num} failed: {e}")
                break

        return items

    @staticmethod
    def _count_blocks(html_text: str) -> int:
        try:
            tree = lxml_html.fromstring(html_text)
            return len(tree.xpath('//div[@class="r-block l"]'))
        except Exception:
            return 0

    def _parse_list_page(self, html_text: str, keyword: str,
                         category: str, seen_ids: set[str]) -> list[TenderItem]:
        items: list[TenderItem] = []
        try:
            tree = lxml_html.fromstring(html_text)
        except Exception:
            return items

        blocks = tree.xpath('//div[@class="r-block l"]')
        for block in blocks:
            links = block.xpath('.//a[@title]')
            if not links:
                continue

            title = (links[0].get("title") or "").strip()
            if not title or len(title) < 6:
                continue

            href = links[0].get("href", "")
            if not href:
                continue

            if href.startswith("/"):
                link = f"{BASE}{href}"
            elif not href.startswith("http"):
                link = f"{BASE}/{href}"
            else:
                link = href

            obj_id = href.split("/")[-1].replace(".html", "")
            if obj_id in seen_ids:
                continue
            seen_ids.add(obj_id)

            if any(w in title for w in SKIP_WORDS):
                continue

            if not self._keyword_matches(title, keyword):
                continue

            date_str = self._extract_date_from_url(href)

            parent_li = block.getparent()
            while parent_li is not None and parent_li.tag != "li":
                parent_li = parent_li.getparent()
            if parent_li is not None:
                date_els = parent_li.xpath('.//span[contains(@class,"date")] | .//span[last()]')
                for date_el in date_els:
                    date_text = date_el.text_content().strip()
                    m = re.search(r'(\d{4}-\d{2}-\d{2})', date_text)
                    if m:
                        date_str = m.group(1)
                        break

            bidder = self._extract_bidder_from_title(title)

            items.append(TenderItem(
                date=date_str,
                category=category,
                project_name=title,
                link=link,
                source_site=self.site_name,
                bidder=bidder,
                deadline="",
                bid_time="",
                bid_count=self._extract_bid_count(title),
                _obj_id=obj_id,
            ))

        return items

    @staticmethod
    def _keyword_matches(title: str, keyword: str) -> bool:
        parts = [p.strip() for p in keyword.split("/") if len(p.strip()) >= 2]
        if not parts:
            parts = [keyword]
        return any(p in title for p in parts)

    @staticmethod
    def _extract_date_from_url(url: str) -> str:
        m = re.search(r'/(\d{8})/', url)
        if m:
            d = m.group(1)
            return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        return ""
