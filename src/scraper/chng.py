"""CHNG scraper - 华能电子商务平台 (ec.chng.com.cn).

Uses Scrapling StealthyFetcher with page_action for search.
The site requires browser interaction to bypass WAF and execute search.

Search page: https://ec.chng.com.cn/channel/home/#/purchase?checked=3
Categories:
  - 招标公告 (checked=3)
  - 非招标公告 (checked=0)

Detail URL pattern:
  https://ec.chng.com.cn/channel/home/#/purchase/detail?id={announcementId}&system={announcementSystem}
"""
import re
from datetime import datetime
from typing import Optional

from src.scraper.scrapling_base import ScraplingScraper, TenderItem

BASE = "https://ec.chng.com.cn"
MAX_PAGES = 2

SKIP_WORDS = ["中标", "成交结果", "候选人公示", "结果公示", "流标",
              "废标", "终止公告", "评标结果", "采购预告", "事前公示",
              "意向公示", "需求公示", "前期公示", "计划公示", "采购意向"]


class ChngScraper(ScraplingScraper):

    @property
    def supports_keyword_search(self) -> bool:
        return True

    def _do_search(self, fetcher, keyword: str, category: str) -> list[TenderItem]:
        items: list[TenderItem] = []
        seen_titles: set[str] = set()

        for checked, label in [("3", "招标"), ("0", "非招标")]:
            try:
                type_items = self._search_section(fetcher, keyword, category, checked, label, seen_titles)
                items.extend(type_items)
            except Exception as e:
                self.logger.error(f"chng {label} search failed: {e}")
        return items

    def _search_section(self, fetcher, keyword: str, category: str,
                        checked: str, label: str, seen_titles: set[str]) -> list[TenderItem]:
        page_url = f"{BASE}/channel/home/#/purchase?checked={checked}"
        table_idx = 0 if checked == "3" else 1
        all_rows: list[dict] = []

        for page_num in range(MAX_PAGES):
            page_rows: list[dict] = []

            def make_action(kw, idx, rows_ref, pg):
                def action(page):
                    if pg == 0:
                        try:
                            page.wait_for_selector('input[placeholder="搜索"]', timeout=10000)
                        except Exception:
                            pass
                        page.wait_for_timeout(1000)
                        search_inputs = page.query_selector_all('input[placeholder="搜索"]')
                        if search_inputs:
                            search_inputs[0].fill(kw)
                        search_btns = page.query_selector_all('button')
                        for btn in search_btns:
                            text = (btn.inner_text() or '').strip()
                            if '搜标题' in text:
                                btn.click()
                                break
                        page.wait_for_timeout(3000)
                    else:
                        next_btn = page.query_selector('li:has-text("下一页")')
                        if next_btn:
                            try:
                                next_btn.click()
                            except Exception:
                                pass
                        page.wait_for_timeout(3000)

                    try:
                        page.wait_for_selector("table tbody tr", timeout=10000)
                    except Exception:
                        pass
                    page.wait_for_timeout(1000)

                    raw = page.evaluate(f'''() => {{
                        const rows = [];
                        const tables = document.querySelectorAll('table');
                        if (!tables.length) return rows;
                        const table = tables[{idx}];
                        if (!table) return rows;
                        table.querySelectorAll('tbody tr').forEach(tr => {{
                            const cells = tr.querySelectorAll('td');
                            if (cells.length >= 2) {{
                                const title = (cells[0]?.textContent || '').trim();
                                const date = (cells[cells.length - 1]?.textContent || '').trim();
                                rows.push({{title, date}});
                            }}
                        }});
                        return rows;
                    }}''')
                    rows_ref.extend(raw or [])
                return action

            try:
                action = make_action(keyword, table_idx, page_rows, page_num)
                response = fetcher.fetch(
                    page_url,
                    headless=True,
                    block_images=True,
                    timeout=30000,
                    page_action=action,
                )

                if not page_rows:
                    break

                all_rows.extend(page_rows)
                self.logger.info(f"chng {label} page {page_num+1}: {len(page_rows)} rows")

                if len(page_rows) < 10:
                    break

            except Exception as e:
                self.logger.error(f"chng {label} page {page_num+1} failed: {e}")
                break

        return self._rows_to_items(all_rows, keyword, category, seen_titles)

    def _rows_to_items(self, rows: list[dict], keyword: str,
                       category: str, seen_titles: set[str]) -> list[TenderItem]:
        items: list[TenderItem] = []
        for row in rows:
            title = (row.get('title') or '').strip()
            if not title or len(title) < 6:
                continue

            title_key = title[:30]
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)

            if any(w in title for w in SKIP_WORDS):
                continue

            date_str = row.get('date', '')
            m = re.search(r'(\d{4}-\d{2}-\d{2})', date_str)
            if m:
                date_str = m.group(1)
            else:
                date_str = ''

            bidder = self._extract_bidder_from_title(title)

            items.append(TenderItem(
                date=date_str,
                category=category,
                project_name=title,
                link=f"{BASE}/channel/home/#/purchase",
                source_site=self.site_name,
                bidder=bidder,
                deadline="",
                bid_time="",
                bid_count=self._extract_bid_count(title),
            ))

        return items
