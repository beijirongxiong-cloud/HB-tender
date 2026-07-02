"""ChinaBidding scraper: Scrapling for search (WAF bypass) + Scrapling page_action for login/detail."""
import os
import re
import asyncio
from datetime import datetime
from typing import Optional
from urllib.parse import quote

from src.scraper.base import BaseScraper, TenderItem


def _extract_project_part(title: str) -> str:
    m = re.match(r'^([\u4e00-\u9fa5]+(?:公司|集团|分局|中心|研究院|研究所|局|院|处|部|厅|委|办|站|所|学校|医院|协会|基金会|联合会))', title)
    if m:
        return title[m.end():]
    m = re.match(r'^(.{2,25}?)(?:\d{4}年|\d{4}[-/])', title)
    if m:
        return title[m.end():]
    return title


class ChinaBiddingScraper(BaseScraper):
    def __init__(self, site_config: dict):
        super().__init__(site_config)
        self._logged_in = False

    async def login(self, page) -> bool:
        return True

    async def parse_detail(self, page, url: str) -> Optional[dict]:
        return None

    async def search(self, page, keyword: str, category: str) -> list[TenderItem]:
        import concurrent.futures
        if not hasattr(ChinaBiddingScraper, '_pool'):
            ChinaBiddingScraper._pool = concurrent.futures.ThreadPoolExecutor(max_workers=7)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            ChinaBiddingScraper._pool,
            self._scrapling_search,
            keyword,
            category,
            None,
        )

    def _scrapling_search(self, keyword: str, category: str, since: Optional[datetime] = None) -> list[TenderItem]:
        from scrapling import StealthyFetcher

        items: list[TenderItem] = []
        seen_hrefs: set[str] = set()
        MAX_PAGES = 50
        PAGE_SIZE = 30
        today = datetime.now().date()

        for page_num in range(1, MAX_PAGES + 1):
            url = f"https://www.chinabidding.cn/public/yjsc/html/zbcg_search.html?keywords={quote(keyword)}&page={page_num}"

            page_data: list[dict] = []

            def wait_and_extract(page):
                try:
                    page.wait_for_selector(".resitem", timeout=15000)
                except Exception:
                    pass
                page.wait_for_timeout(2000)
                raw = page.evaluate('''() => {
                    const results = [];
                    document.querySelectorAll('.resitem').forEach(el => {
                        const a = el.querySelector('a');
                        if (!a) return;
                        const title = (a.textContent || '').trim();
                        const href = a.getAttribute('href') || '';
                        let date = '';
                        const dateTip = el.querySelector('.tip.nobor');
                        if (dateTip) {
                            const m = dateTip.textContent.match(/(\\d{4}-\\d{2}-\\d{2})/);
                            if (m) date = m[1];
                        }
                        let docPrice = '';
                        el.querySelectorAll('.tip').forEach(t => {
                            const txt = (t.textContent || '').trim();
                            if (txt.includes('\\u6807\\u4e66') || txt.includes('\\u5143')) {
                                const pm = txt.match(/(\\d+\\.?\\d*)\\s*\\u5143/);
                                if (pm) docPrice = pm[0];
                            }
                        });
                        if (title.length >= 5) {
                            results.push({title, href, date, docPrice});
                        }
                    });
                    return results;
                }''')
                page_data.extend(raw or [])

            try:
                fetcher = StealthyFetcher()
                response = fetcher.fetch(
                    url,
                    headless=True,
                    block_images=True,
                    timeout=30000,
                    page_action=wait_and_extract,
                )
                if response.status != 200:
                    self.logger.warning(f"Search returned status {response.status} on page {page_num}")
                    break

                if not page_data:
                    break

                page_matched = 0
                page_new = 0
                page_raw_new = 0
                page_has_today = False
                for row in page_data:
                    date_str = row.get("date", "")
                    if date_str:
                        try:
                            item_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                            if item_date >= today:
                                page_has_today = True
                            if since and item_date < since.date():
                                continue
                        except ValueError:
                            pass

                    title = row["title"]
                    if not self._title_matches_keyword(title, keyword):
                        continue

                    href = row["href"]
                    if href and not href.startswith("http"):
                        href = "https://www.chinabidding.cn" + href

                    if href in seen_hrefs:
                        continue
                    seen_hrefs.add(href)
                    page_raw_new += 1

                    if "/zbgg/" not in href:
                        continue

                    page_new += 1
                    items.append(TenderItem(
                        date=date_str or datetime.now().strftime("%Y-%m-%d"),
                        category=category,
                        project_name=title,
                        link=href,
                        source_site=self.site_name,
                        bidder="",
                        deadline="",
                        bid_time="",
                        budget="",
                        doc_price=row.get("docPrice", ""),
                        bid_count=self._extract_bid_count(title),
                    ))
                    page_matched += 1

                self.logger.info(f"  Page {page_num}: {len(page_data)} raw, {page_matched} zbgg matched, {page_raw_new} raw new, today={page_has_today}")

                # Stop if last page is not full (no more results)
                if len(page_data) < PAGE_SIZE:
                    self.logger.info(f"  Last page {page_num} not full ({len(page_data)}/{PAGE_SIZE}), stopping")
                    break

                # Stop if all raw items are duplicates — chinabidding recycles content beyond real results
                if page_raw_new == 0:
                    self.logger.info(f"  All raw duplicates on page {page_num}, stopping")
                    break

                # Stop if this page has no items published today — all newer content exhausted
                if not page_has_today:
                    self.logger.info(f"  No today's items on page {page_num}, stopping")
                    break

            except Exception as e:
                self.logger.error(f"Scrapling search failed for '{keyword}' page {page_num}: {e}")
                break
        return items

    @staticmethod
    def _title_matches_keyword(title: str, keyword: str) -> bool:
        parts = [p.strip() for p in keyword.split("/") if len(p.strip()) >= 2]
        if not parts:
            parts = [keyword]
        project_part = _extract_project_part(title)
        if any(p in project_part for p in parts):
            return True
        if any(p in title for p in parts):
            return True
        return False

    def _scrapling_fetch_details(self, items: list[TenderItem]) -> list[TenderItem]:
        if not items:
            return items

        username = os.getenv("CHINABIDDING_USERNAME", "")
        password = os.getenv("CHINABIDDING_PASSWORD", "")

        from scrapling import StealthyFetcher
        fetcher = StealthyFetcher()

        urls = [item.link for item in items if item.link]
        if not urls:
            return items

        collected = {}

        JS_GRAB_TEXT = r'''() => {
        const result = {};
        const table = document.querySelector('.info_table');
        result.table_text = table ? table.innerText : '';
        const xq = document.querySelector('.xq_nr');
        result.body_text = xq ? xq.innerText : document.body.innerText;
        result.full_text = (result.table_text + '\\n' + result.body_text).slice(0, 8000);
        return result;
    }'''

        def login_and_fetch_details(page):
            page.wait_for_timeout(1000)

            if username and password:
                page.goto("https://www.chinabidding.cn/public/2020/html/login.html", timeout=30000)
                page.wait_for_selector("#loginname-l", timeout=15000)
                page.wait_for_timeout(2000)

                page.fill("#loginname-l", username)
                page.fill("#logincode-l", password)

                captcha_img = page.locator("#yzmImageL")
                if captcha_img.count() > 0:
                    try:
                        screenshot_bytes = captcha_img.screenshot()
                        import base64
                        image_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
                        from src.scraper.captcha import solve_captcha
                        code = solve_captcha(image_b64)
                        self.logger.info(f"Captcha solved: {code}")
                        page.fill("#loginimage-l", code)
                    except Exception as e:
                        self.logger.error(f"Captcha solve failed: {e}")

                page.locator("._log").click()
                page.wait_for_timeout(5000)

                content = page.content()
                logged_in = "\u767b\u5f55\u6210\u529f" in content or "\u6211\u7684\u5546\u52a1\u5ba4" in content
                if not logged_in and "login" not in page.url.lower():
                    logged_in = True
                self.logger.info(f"Login result: {logged_in}")
                self._logged_in = logged_in
            else:
                self.logger.warning("No credentials, skipping login")

            for i, url in enumerate(urls):
                try:
                    page.goto(url, timeout=30000)
                    page_loaded = False
                    for _ in range(10):
                        page.wait_for_timeout(2000)
                        html_len = page.evaluate("() => document.documentElement.outerHTML.length")
                        if html_len > 5000:
                            page_loaded = True
                            break

                    if not page_loaded:
                        self.logger.warning(f"Detail page never loaded: {url}")
                        collected[url] = {}
                        continue

                    data = page.evaluate(JS_GRAB_TEXT)
                    collected[url] = data.get("full_text", "") if data else ""
                    self.logger.info(
                        f"Detail {i+1}/{len(urls)}: grabbed text len={len(collected[url])}"
                    )
                except Exception as e:
                    self.logger.error(f"Detail fetch failed for {url}: {e}")
                    collected[url] = {}

        try:
            fetcher.fetch(
                "https://www.chinabidding.cn/",
                headless=True,
                block_images=True,
                timeout=max(60000, len(urls) * 20000 + 60000),
                page_action=login_and_fetch_details,
            )
        except Exception as e:
            self.logger.error(f"Scrapling detail fetch failed: {e}")

        for item in items:
            text = collected.get(item.link, "")
            item._detail_text = text
            if not item.bidder:
                item.bidder = self._extract_bidder_from_title(item.project_name)

        return items

    async def run(self, keywords_by_category: dict[str, list[str]], since: Optional[datetime] = None) -> list[TenderItem]:
        import concurrent.futures
        if not hasattr(ChinaBiddingScraper, '_pool'):
            ChinaBiddingScraper._pool = concurrent.futures.ThreadPoolExecutor(max_workers=7)

        results: list[TenderItem] = []
        loop = asyncio.get_event_loop()

        async def search_one(keyword: str, category: str):
            self.logger.info(f"Searching {self.site_name}: [{category}] {keyword}")
            try:
                items = await loop.run_in_executor(
                    ChinaBiddingScraper._pool,
                    self._scrapling_search,
                    keyword,
                    category,
                    since,
                )
                self.logger.info(f"Found {len(items)} items for [{category}] {keyword}")
                return items
            except Exception as e:
                self.logger.error(f"Search failed for [{category}] {keyword}: {e}")
                return []

        tasks = []
        for category, keywords in keywords_by_category.items():
            for keyword in keywords:
                tasks.append(search_one(keyword, category))

        all_results = await asyncio.gather(*tasks)
        for items in all_results:
            results.extend(items)

        return results

    async def fetch_details(self, items: list[TenderItem]) -> list[TenderItem]:
        if not items:
            return items

        self.logger.info(f"Fetching details for {len(items)} items via Scrapling (login + detail)")
        import concurrent.futures
        if not hasattr(ChinaBiddingScraper, '_pool'):
            ChinaBiddingScraper._pool = concurrent.futures.ThreadPoolExecutor(max_workers=7)

        NUM_BATCHES = min(4, len(items))
        batch_size = (len(items) + NUM_BATCHES - 1) // NUM_BATCHES
        batches = [items[i:i+batch_size] for i in range(0, len(items), batch_size)]
        self.logger.info(f"Split into {len(batches)} batches of ~{batch_size} items each")

        loop = asyncio.get_event_loop()
        futures = [
            loop.run_in_executor(ChinaBiddingScraper._pool, self._scrapling_fetch_details, batch)
            for batch in batches
        ]
        results = await asyncio.gather(*futures)

        items = []
        for batch in results:
            items.extend(batch)
        return items

    @staticmethod
    def _extract_bidder_from_title(title: str) -> str:
        m = re.match(r'^([\u4e00-\u9fa5]+(?:\u516c\u53f8|\u96c6\u56e2|\u5206\u5c40|\u4e2d\u5fc3|\u7814\u7a76\u9662|\u7814\u7a76\u6240|\u5c40|\u9662|\u5904|\u90e8|\u5385|\u59d4|\u529e|\u7ad9|\u6240|\u5b66\u6821|\u533b\u9662|\u534f\u4f1a|\u57fa\u91d1\u4f1a|\u8054\u5408\u4f1a))', title)
        if m:
            return m.group(1)
        m = re.match(r'^(.{4,25}?)(?:\d{4}\u5e74|\d{4}[-/])', title)
        if m:
            return m.group(1).rstrip('\u7684')
        return ""

    @staticmethod
    def _extract_bid_count(title: str) -> str:
        for pattern, val in [
            (r'\u7b2c[\u56db4]\u6b21', '\u7b2c\u56db\u6b21'),
            (r'\u7b2c[\u4e093]\u6b21', '\u7b2c\u4e09\u6b21'),
            (r'\u7b2c[\u4e8c2]\u6b21', '\u7b2c\u4e8c\u6b21'),
            (r'\u7b2c[\u4e001]\u6b21', '\u7b2c\u4e00\u6b21'),
            (r'[\uff08(]\s*[\u4e8c2]\s*[\uff09)]', '\u7b2c\u4e8c\u6b21'),
            (r'[\uff08(]\s*[\u4e093]\s*[\uff09)]', '\u7b2c\u4e09\u6b21'),
            (r'[\uff08(]\s*[\u56db4]\s*[\uff09)]', '\u7b2c\u56db\u6b21'),
            (r'\u4e8c\u6b21', '\u7b2c\u4e8c\u6b21'),
            (r'\u4e09\u6b21', '\u7b2c\u4e09\u6b21'),
            (r'\u56db\u6b21', '\u7b2c\u56db\u6b21'),
        ]:
            if re.search(pattern, title):
                return val
        return '\u7b2c\u4e00\u6b21'
