"""Yuanbo (bid360.com.cn) scraper using Scrapling StealthyFetcher.

bid360.com.cn has no WAF JS challenge, but uses dynamic JS loading (ajaxlink).
We use Scrapling's StealthyFetcher with page_action callback to:
1. Login (fill form + solve captcha)
2. Navigate to channel.html and extract list
3. Navigate to detail pages and extract fields
All in one browser session to maintain login cookies.
"""
import os
import re
import base64
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin

from src.scraper.base import BaseScraper, TenderItem
from src.scraper.captcha import solve_captcha
from src.utils.logger import setup_logger


class YuanboBid360Scraper(BaseScraper):
    LOGIN_URL = "https://www.bid360.com.cn/public/2020/html/login.html"
    CHANNEL_URL = "https://www.bid360.com.cn/public/2020/html/channel.html?channel_id={cid}"
    BASE_URL = "https://www.bid360.com.cn"
    CHANNEL_IDS = [1, 2, 3]

    def __init__(self, site_config: dict):
        super().__init__(site_config)
        self._logged_in = False
        self._cached_list: Optional[list[dict]] = None

    async def login(self, page) -> bool:
        return True

    async def parse_detail(self, page, url: str) -> Optional[TenderItem]:
        return None

    def _do_login_and_scrape(self, page):
        """Page action: login then scrape all channels, then all details.
        Runs inside Scrapling's browser context. Stores result in self._scraped_list.
        """
        import time

        all_list_items = []

        # --- Step 1: Login ---
        self.logger.info("Navigating to login page")
        try:
            page.goto(self.LOGIN_URL, timeout=45000)
        except Exception as e:
            self.logger.warning(f"Login page goto timeout (may still work): {e}")

        try:
            page.wait_for_selector("#loginname-l", timeout=15000)
        except Exception:
            self.logger.error("Login form not found")
            self._scraped_list = []
            return

        page.wait_for_timeout(1500)

        page.fill("#loginname-l", self.username)
        page.fill("#logincode-l", self.password)

        captcha_img = page.locator("#yzmImageL")
        if captcha_img.count() > 0:
            for captcha_attempt in range(3):
                try:
                    screenshot_bytes = captcha_img.screenshot()
                    image_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
                    code = solve_captcha(image_b64)
                    self.logger.info(f"Captcha solved: {code}")
                    page.fill("#loginimage-l", code)
                    break
                except Exception as e:
                    self.logger.warning(f"Captcha attempt {captcha_attempt+1} failed: {e}")
                    try:
                        page.evaluate("changeYzmL()")
                        page.wait_for_timeout(1000)
                    except Exception:
                        pass

        page.locator("._log").click()
        page.wait_for_timeout(5000)

        content = page.content()
        current_url = page.url

        # Check for error messages first
        error_texts = page.evaluate(r"""() => {
            const els = document.querySelectorAll('.msg-error, .error, .tip-error');
            return Array.from(els).map(e => e.textContent.trim()).filter(t => t && t.length > 2);
        }""")

        if error_texts:
            self.logger.error(f"Login error: {error_texts}")
            self._scraped_list = []
            return

        # Check for actual login success: URL away from login page AND no error
        logged_in = "login" not in current_url.lower()

        if not logged_in:
            # Double check: try navigating to member area
            try:
                page.goto("https://www.bid360.com.cn/yuan/login/loginnew/tobussroom", timeout=15000)
                page.wait_for_timeout(2000)
                member_url = page.url
                member_content = page.evaluate("() => document.body.textContent.substring(0, 200)")
                if "40002" not in member_content and "login" not in member_url.lower():
                    logged_in = True
                    self.logger.info(f"Login verified via member area: {member_url}")
                else:
                    self.logger.error(f"Login verification failed: {member_content[:100]}")
            except Exception:
                pass

        if not logged_in:
            self.logger.error(f"Login failed, still at {current_url}")
            self._scraped_list = []
            return
        self._logged_in = True
        self.logger.info(f"Login successful, now at {page.url}")

        # --- Step 2: Scrape lists from all channels ---
        for cid in self.CHANNEL_IDS:
            url = self.CHANNEL_URL.format(cid=cid)
            self.logger.info(f"Fetching channel {cid}: {url}")
            try:
                page.goto(url, timeout=45000)
                page.wait_for_timeout(5000)

                rows = page.evaluate(r"""() => {
                    const results = [];
                    const anchors = document.querySelectorAll('a[href*="zbgs"], a[href*="zbgg"], a[onclick*="ajaxlink"]');
                    anchors.forEach(a => {
                        let href = '';
                        const hrefAttr = a.getAttribute('href') || '';
                        const onclickAttr = a.getAttribute('onclick') || '';
                        // href="javascript:ajaxlink('/zbgs/xxx.html',...)"
                        let m = hrefAttr.match(/ajaxlink\(['"]([^'"]+)['"]/);
                        if (m) {
                            href = m[1];
                        } else if (onclickAttr.match(/ajaxlink\(['"]([^'"]+)['"]/)) {
                            m = onclickAttr.match(/ajaxlink\(['"]([^'"]+)['"]/);
                            href = m[1];
                        } else if (hrefAttr.includes('/zbgs/') || hrefAttr.includes('/zbgg/')) {
                            href = hrefAttr;
                        }
                        if (!href) return;
                        if (!href.includes('/zbgs/') && !href.includes('/zbgg/')) return;

                        const title = (a.textContent || '').trim();
                        if (!title || title.length < 5) return;

                        let dateStr = '';
                        let parent = a.closest('li, tr, div');
                        if (parent) {
                            const text = parent.textContent || '';
                            const dm = text.match(/(\d{4}[-/]\d{1,2}[-/]\d{1,2})/);
                            if (dm) dateStr = dm[1];
                        }
                        results.push({title, href, date: dateStr});
                    });
                    return results;
                }""")

                if not rows:
                    html_len = page.evaluate("() => document.documentElement.outerHTML.length")
                    self.logger.warning(f"Channel {cid}: 0 rows, html_len={html_len}")
                    continue

                self.logger.info(f"Channel {cid}: {len(rows)} items")
                all_list_items.extend(rows)
            except Exception as e:
                self.logger.error(f"Channel {cid} fetch failed: {e}")

        # Dedupe by href
        seen = set()
        deduped = []
        for r in all_list_items:
            if r["href"] not in seen:
                seen.add(r["href"])
                deduped.append(r)
        self.logger.info(f"Total unique list items: {len(deduped)}")

        self._scraped_list = deduped

    def _do_login_and_details(self, urls: list[str]):
        """Page action: login then fetch details for given URLs."""
        collected = {}

        # Login first
        self.logger.info("Navigating to login page (for details)")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return collected

        # We're inside scrapling's page_action, page is a patchright Page
        try:
            page = self._current_page
        except AttributeError:
            return collected

        if not self._logged_in:
            try:
                page.goto(self.LOGIN_URL, timeout=45000)
            except Exception:
                pass
            try:
                page.wait_for_selector("#loginname-l", timeout=15000)
                page.wait_for_timeout(1500)
                page.fill("#loginname-l", self.username)
                page.fill("#logincode-l", self.password)

                captcha_img = page.locator("#yzmImageL")
                if captcha_img.count() > 0:
                    screenshot_bytes = captcha_img.screenshot()
                    image_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
                    code = solve_captcha(image_b64)
                    page.fill("#loginimage-l", code)

                page.locator("._log").click()
                page.wait_for_timeout(5000)
                content = page.content()
                current_url = page.url
                self._logged_in = ("\u767b\u5f55\u6210\u529f" in content or
                                   "\u6211\u7684\u5546\u52a1\u5ba4" in content or
                                   "login" not in current_url.lower())
                if self._logged_in:
                    self.logger.info("Login successful for detail fetch")
            except Exception as e:
                self.logger.error(f"Login for details failed: {e}")
                return collected

        # Fetch details
        for i, url in enumerate(urls):
            try:
                full_url = urljoin(self.BASE_URL, url) if not url.startswith("http") else url
                page.goto(full_url, timeout=30000)
                for _ in range(8):
                    page.wait_for_timeout(3000)
                    html_len = page.evaluate("() => document.documentElement.outerHTML.length")
                    if html_len > 5000:
                        break

                # Check if logged in (content visible) vs login wall
                nologin = page.evaluate("""() => {
                    const el = document.querySelector('.info_nologin_desc');
                    return el ? el.offsetParent !== null : false;
                }""")
                if nologin:
                    self.logger.warning(f"Detail {i+1}: login wall detected, re-logging in")
                    self._logged_in = False
                    try:
                        page.goto(self.LOGIN_URL, timeout=30000)
                        page.wait_for_selector("#loginname-l", timeout=10000)
                        page.wait_for_timeout(1000)
                        page.fill("#loginname-l", self.username)
                        page.fill("#logincode-l", self.password)
                        captcha_img = page.locator("#yzmImageL")
                        if captcha_img.count() > 0:
                            screenshot_bytes = captcha_img.screenshot()
                            image_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
                            code = solve_captcha(image_b64)
                            page.fill("#loginimage-l", code)
                        page.locator("._log").click()
                        page.wait_for_timeout(5000)
                        self._logged_in = True
                        page.goto(full_url, timeout=30000)
                        page.wait_for_timeout(4000)
                    except Exception as e:
                        self.logger.error(f"Re-login failed: {e}")

                data = page.evaluate(r'''() => {
                    const result = {};
                    const table = document.querySelector('.info_table');
                    if (table) {
                        const rows = table.querySelectorAll('tr');
                        for (const row of rows) {
                            const cells = row.querySelectorAll('td');
                            if (cells.length >= 4) {
                                const l1 = cells[0].textContent.trim();
                                const v1 = cells[1].textContent.trim();
                                const l2 = cells[2].textContent.trim();
                                const v2 = cells[3].textContent.trim();
                                if (!v1.includes('\u6ce8\u518c') && !v1.includes('\u767b\u5f55')) {
                                    if (l1.includes('\u62db\u6807\u4eba') || l1.includes('\u91c7\u8d2d\u4eba') || l1.includes('\u62db\u6807\u5355\u4f4d')) result.bidder = v1;
                                    if (l1.includes('\u5f00\u6807') && l1.includes('\u65f6\u95f4')) result.bid_time = v1;
                                    if (l1.includes('\u62a5\u540d') && l1.includes('\u622a\u6b62')) result.deadline = v1;
                                    if (l1.includes('\u9884\u7b97')) result.budget = v1;
                                    if (l1.includes('\u6807\u4e66') && l1.includes('\u4ef7')) result.doc_price = v1;
                                }
                                if (!v2.includes('\u6ce8\u518c') && !v2.includes('\u767b\u5f55')) {
                                    if (l2.includes('\u62db\u6807\u4eba') || l2.includes('\u91c7\u8d2d\u4eba') || l2.includes('\u62db\u6807\u5355\u4f4d')) result.bidder = v2;
                                    if (l2.includes('\u5f00\u6807') && l2.includes('\u65f6\u95f4')) result.bid_time = v2;
                                    if (l2.includes('\u62a5\u540d') && l2.includes('\u622a\u6b62')) result.deadline = v2;
                                    if (l2.includes('\u9884\u7b97')) result.budget = v2;
                                    if (l2.includes('\u6807\u4e66') && l2.includes('\u4ef7')) result.doc_price = v2;
                                }
                            }
                            if (cells.length >= 2) {
                                const l = cells[0].textContent.trim();
                                const v = cells[1].textContent.trim();
                                if (!v.includes('\u6ce8\u518c') && !v.includes('\u767b\u5f55')) {
                                    if (l.includes('\u62db\u6807\u4eba') || l.includes('\u91c7\u8d2d\u4eba') || l.includes('\u62db\u6807\u5355\u4f4d')) result.bidder = v;
                                    if (l.includes('\u5f00\u6807') && l.includes('\u65f6\u95f4')) result.bid_time = v;
                                    if (l.includes('\u62a5\u540d') && l.includes('\u622a\u6b62')) result.deadline = v;
                                    if (l.includes('\u9884\u7b97')) result.budget = v;
                                    if (l.includes('\u6807\u4e66') && l.includes('\u4ef7')) result.doc_price = v;
                                }
                            }
                        }
                    }

                    const xq = document.querySelector('.xq_nr');
                    const text = xq ? xq.textContent.replace(/\s+/g, ' ').trim() : '';

                    if (!result.bidder) {
                        const m = text.match(/(\u62db\u6807\u4eba|\u91c7\u8d2d\u4eba|\u62db\u6807\u5355\u4f4d|\u91c7\u8d2d\u5355\u4f4d)[\uff1a:]\s*([^\s,\uff0c\u3002]{4,30}?)(?:\s|,|\uff0c|\u3002|$)/);
                        if (m) result.bidder = m[2].trim();
                    }
                    if (!result.deadline) {
                        const dm = text.match(/(\u62a5\u540d|\u83b7\u53d6)[^]{0,30}(\u622a\u6b62|\u671f\u9650)[^]{0,30}[\uff1a:]?\s*(\d{4}[\u5e74\-\/]\d{1,2}[\u6708\-\/]\d{1,2})/);
                        if (dm) result.deadline = dm[3];
                    }
                    if (!result.bid_time) {
                        const bm = text.match(/\u5f00\u6807[^]{0,20}\u65f6\u95f4[\uff1a:]?\s*(\d{4}[\u5e74\-\/]\d{1,2}[\u6708\-\/]\d{1,2})/);
                        if (bm) result.bid_time = bm[1];
                    }
                    if (!result.budget) {
                        const bm = text.match(/(\u9884\u7b97|\u91c7\u8d2d\u91d1\u989d)[\uff1a:\uff08(]\s*[\u00a5\uffe5]?\s*(\d+\.?\d*)\s*\u4e07?\u5143?/);
                        if (bm) result.budget = bm[2];
                    }
                    if (!result.doc_price) {
                        const dm = text.match(/\u6807\u4e66[\u552e\u4ef7\u683c]*[\uff1a:]\s*[\u00a5\uffe5]?\s*(\d+\.?\d*)\s*\u5143/);
                        if (dm) result.doc_price = dm[0];
                    }
                    return result;
                }''')

                collected[url] = data or {}
                self.logger.info(f"Detail {i+1}/{len(urls)}: bidder={data.get('bidder','')[:20] if data else ''}, deadline={data.get('deadline','') if data else ''}")
            except Exception as e:
                self.logger.error(f"Detail {i+1}/{len(urls)} failed: {e}")
                collected[url] = {}

        return collected

    def fetch_all(self, keywords_by_category: dict[str, list[str]], since: Optional[datetime] = None) -> tuple[list[dict], dict]:
        """Fetch list and details in one Scrapling session.

        Returns (list_items, detail_data).
        """
        from scrapling.fetchers import StealthyFetcher

        fetcher = StealthyFetcher()
        self._scraped_list = []

        # Phase 1: Login + list
        self.logger.info("Phase 1: Login + list fetch")
        try:
            fetcher.fetch(
                self.LOGIN_URL,
                headless=True,
                block_images=True,
                timeout=120000,
                page_action=self._do_login_and_scrape,
            )
        except Exception as e:
            self.logger.error(f"List fetch failed: {e}")

        list_items = getattr(self, "_scraped_list", [])
        if not list_items:
            self.logger.warning("No list items, skipping details")
            return [], {}

        # Apply date filter
        if since:
            filtered = []
            for r in list_items:
                if not r.get("date"):
                    filtered.append(r)
                    continue
                try:
                    item_date = datetime.strptime(r["date"], "%Y-%m-%d")
                    if item_date >= since:
                        filtered.append(r)
                except (ValueError, TypeError):
                    filtered.append(r)
            self.logger.info(f"After date filter (since {since.strftime('%Y-%m-%d')}): {len(filtered)}/{len(list_items)}")
            list_items = filtered

        return list_items, {}

    def fetch_details_sync(self, urls: list[str]) -> dict:
        """Fetch details for a list of URLs in one Scrapling session."""
        from scrapling.fetchers import StealthyFetcher

        if not urls:
            return {}

        fetcher = StealthyFetcher()
        self.logger.info(f"Fetching {len(urls)} details via Scrapling")
        self._detail_results = {}

        def page_action(page):
            self._current_page = page
            self._detail_results = self._do_login_and_details(urls)

        try:
            fetcher.fetch(
                self.LOGIN_URL,
                headless=True,
                block_images=True,
                timeout=120000 + len(urls) * 20000,
                page_action=page_action,
            )
        except Exception as e:
            self.logger.error(f"Detail fetch session failed: {e}")

        return getattr(self, "_detail_results", {})

    async def search(self, page, keyword: str, category: str) -> list[TenderItem]:
        return []

    async def run(self, keywords_by_category: dict[str, list[str]], since: Optional[datetime] = None) -> list[TenderItem]:
        return []

    async def run_full(self, keywords_by_category: dict[str, list[str]], since: Optional[datetime] = None) -> list[TenderItem]:
        """Full pipeline: list -> filter -> detail -> TenderItem list."""
        import concurrent.futures
        if not hasattr(YuanboBid360Scraper, '_pool'):
            YuanboBid360Scraper._pool = concurrent.futures.ThreadPoolExecutor(max_workers=3)

        loop = asyncio.get_event_loop()

        # Phase 1: fetch list (sync, in thread)
        list_items, _ = await loop.run_in_executor(
            YuanboBid360Scraper._pool,
            self.fetch_all,
            keywords_by_category,
            since,
        )

        if not list_items:
            return []

        self.logger.info(f"Sample list items (first 5):")
        for r in list_items[:5]:
            self.logger.info(f"  title={r.get('title','')[:50]}, date={r.get('date','')}, href={r.get('href','')[:50]}")

        # Convert to TenderItem
        items = []
        for r in list_items:
            href = r.get("href", "")
            full_url = urljoin(self.BASE_URL, href) if not href.startswith("http") else href
            items.append(TenderItem(
                date=r.get("date", "") or datetime.now().strftime("%Y-%m-%d"),
                category="",
                project_name=r.get("title", ""),
                link=full_url,
                source_site=self.site_name,
                bidder=self._extract_bidder_from_title(r.get("title", "")),
                bid_count=self._extract_bid_count(r.get("title", "")),
            ))

        # Phase 2: filter
        from src.processor.filter import apply_blacklist, apply_keyword_strict_filter, load_blacklist
        blacklist = load_blacklist()

        items = apply_keyword_strict_filter(items, keywords_by_category)
        self.logger.info(f"After keyword filter: {len(items)}")
        items = apply_blacklist(items, blacklist)
        self.logger.info(f"After blacklist filter: {len(items)}")

        if not items:
            return []

        # Phase 3: fetch details (sync, in thread)
        urls = [item.link for item in items]
        detail_data = await loop.run_in_executor(
            YuanboBid360Scraper._pool,
            self.fetch_details_sync,
            urls,
        )

        # Merge detail data
        for item in items:
            data = detail_data.get(item.link, {}) or detail_data.get(item.link.replace(self.BASE_URL, ""), {})
            if data:
                if data.get("bidder"):
                    item.bidder = data["bidder"]
                else:
                    item.bidder = self._extract_bidder_from_title(item.project_name)
                if data.get("deadline"):
                    item.deadline = self._clean_date(data["deadline"])
                if data.get("bid_time"):
                    item.bid_time = self._clean_date(data["bid_time"])
                if data.get("budget"):
                    item.budget = data["budget"]
                if data.get("doc_price"):
                    item.doc_price = data["doc_price"]
            else:
                item.bidder = self._extract_bidder_from_title(item.project_name)

        return items

    async def cleanup(self):
        pass

    @staticmethod
    def _clean_date(s: str) -> str:
        if not s:
            return s
        s = s.replace("\u5e74", "-").replace("\u6708", "-").replace("\u65e5", "").replace("\u53f7", "")
        s = s.replace("\u65f6", ":").replace("\u70b9", ":").replace("\u5206", ":").replace("\u79d2", "")
        s = re.sub(r'-+', '-', s).strip('-:. ')
        return s

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
