"""Ctbpsp scraper - 中招联合招标采购网 (ctbpsp.com).

Uses Scrapling StealthyFetcher browser with interactive search.
The site is a Vue SPA where navigating to hash URLs doesn't trigger search.
Instead, we must: load homepage → fill search box → click search → extract DOM.

API responses are encrypted; DOM extraction is the only viable approach.

DOM search results structure (after search renders):
  <div cursor=pointer> (each result row)
    <p> Title text (keyword highlighted in <em>) </p>
    <div> Region + BulletinType + 接收时间:YYYY-MM-DD </div>
  </div>

Detail URL pattern:
  https://ctbpsp.com/#/bulletinDetail?uuid=XXX&inpvalue=关键词&dataSource=0&tenderAgency=
"""
import re
from datetime import datetime
from typing import Optional

from src.scraper.scrapling_base import ScraplingScraper, TenderItem

BASE = "https://ctbpsp.com"


class CtbpspScraper(ScraplingScraper):
    MAX_PAGES = 3

    @property
    def supports_keyword_search(self) -> bool:
        return True

    def _do_search(self, fetcher, keyword: str, category: str) -> list[TenderItem]:
        items: list[TenderItem] = []
        seen_titles: set[str] = set()

        def do_search(page):
            nonlocal items
            page.goto(f"{BASE}/#/", timeout=30000)
            page.wait_for_timeout(3000)

            search_input = page.locator('input[type="text"], input[placeholder]').first
            search_input.fill(keyword)
            page.wait_for_timeout(500)

            search_btn = page.locator('button:has-text("搜索")').first
            search_btn.click()
            page.wait_for_timeout(5000)

            for page_num in range(1, self.MAX_PAGES + 1):
                if page_num > 1:
                    next_btn = page.locator('button:has-text("下一页"), .ant-pagination-next, [class*="next"]')
                    if next_btn.count() > 0:
                        try:
                            next_btn.first.click()
                            page.wait_for_timeout(3000)
                        except Exception:
                            break
                    else:
                        break

                raw = page.evaluate(r"""() => {
                    const results = [];
                    const resultDivs = document.querySelectorAll('[cursor=pointer], [class*="result"], [class*="item"]');
                    resultDivs.forEach(div => {
                        const pEl = div.querySelector('p');
                        if (!pEl) return;
                        const title = (pEl.textContent || '').trim();
                        if (!title || title.length < 5) return;
                        const metaDiv = pEl.nextElementSibling || div.querySelector('div:not(:first-child)');
                        let date = '', region = '', bulletinType = '';
                        if (metaDiv) {
                            const meta = (metaDiv.textContent || '').trim();
                            const dm = meta.match(/(\d{4}-\d{2}-\d{2})/);
                            if (dm) date = dm[1];
                            const parts = meta.split(/\s+/);
                            parts.forEach(p => {
                                p = p.trim();
                                if (/省|市|区|县/.test(p) && p.length <= 6) region = p;
                                if (/公告|公示|结果/.test(p) && p.length <= 12) bulletinType = p;
                            });
                        }
                        let href = '';
                        const aEl = div.querySelector('a[href*="bulletinDetail"]');
                        if (aEl) href = aEl.getAttribute('href') || '';
                        results.push({title, date, href, region, bulletinType});
                    });
                    return results;
                }""")

                if not raw:
                    if page_num == 1:
                        self.logger.info(f"ctbpsp: no results for keyword '{keyword}'")
                    break

                page_new = 0
                for row in raw:
                    title = row.get("title", "").strip()
                    if not title or title in seen_titles:
                        continue
                    seen_titles.add(title)

                    bulletin_type = row.get("bulletinType", "")
                    skip_types = ["中标结果公示", "成交结果公示", "中标公告", "成交公告",
                                  "候选人公示", "结果公告", "中标候选人", "流标公告", "终止公告",
                                  "采购预告", "事前公示", "意向公示", "需求公示", "前期公示",
                                  "计划公示", "采购意向"]
                    if any(t in (bulletin_type + title) for t in skip_types):
                        continue

                    href = row.get("href", "")
                    if href and href.startswith("/"):
                        href = BASE + href
                    elif href and href.startswith("#"):
                        href = BASE + "/" + href
                    elif not href:
                        href = f"{BASE}/#/bulletinList?keyword={keyword}"

                    date_str = row.get("date", "")
                    bidder = self._extract_bidder_from_title(title)

                    items.append(TenderItem(
                        date=date_str,
                        category=category,
                        project_name=title,
                        link=href,
                        source_site=self.site_name,
                        bidder=bidder,
                        deadline="",
                        bid_time="",
                        bid_count=self._extract_bid_count(title),
                    ))
                    page_new += 1

                self.logger.info(f"ctbpsp page {page_num}: {len(raw)} raw, {page_new} new items")

                if page_new == 0:
                    break

        fetcher.fetch(
            f"{BASE}/#/",
            headless=True,
            block_images=True,
            timeout=90000,
            page_action=do_search,
        )
        return items

    @staticmethod
    def _extract_bidder_from_title(title: str) -> str:
        m = re.match(
            r"^([\u4e00-\u9fa5]+(?:公司|集团|分局|中心|研究院|研究所|局|院|处|部|厅|委|办|站|所|学校|医院|协会|基金会))",
            title,
        )
        if m:
            return m.group(1)
        m = re.match(r"^(.{4,25}?)(?:\d{4}年|\d{4}[-/])", title)
        if m:
            return m.group(1).rstrip('的')
        return ""
