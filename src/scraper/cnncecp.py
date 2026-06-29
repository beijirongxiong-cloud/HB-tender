"""CNNCECP (中核集团电子商务平台) scraper.

Architecture (efficiency-first):
  1. List phase  — Scrapling StealthyFetcher loads list pages (bypasses anti-bot
     JS challenge that returns HTTP 412 to plain HTTP clients). No login needed;
     the tender announcement list is public.
  2. Filter phase — Keyword/date filtering happens in Python BEFORE any detail
     page is fetched, so we only solve the captcha for items that matter.
  3. Detail phase — The old CMS (www.cnncecp.com) gates detail pages behind an
     anji-plus blockPuzzle slider captcha.  We solve it via the /captcha/get +
     /captcha/check JSON API (gap detection via edge analysis on the background
     image, AES-ECB encrypted pointJson).  The verification is session-scoped,
     so after one solve we fetch ALL detail pages via in-browser fetch() — no
     page.goto() (which triggers a separate anti-bot JS challenge that resets the
     captcha session).

Site map:
  List : https://www.cnncecp.com/xzbgg/index.jhtml  (招标公告, paginated index_N.jhtml)
  Detail: https://www.cnncecp.com/xzbgg/{noticeId}.jhtml  (redirects to /captcha.html)
"""
import os
import re
import io
import json
import time
import base64
import asyncio
from datetime import datetime
from typing import Optional

from PIL import Image
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from src.scraper.base import BaseScraper, TenderItem
from src.utils.logger import setup_logger


class CnncecpScraper(BaseScraper):
    LIST_URL = "https://www.cnncecp.com/xzbgg/index.jhtml"
    BASE_URL = "https://www.cnncecp.com"
    MAX_LIST_PAGES = 4
    CAPTCHA_MAX_RETRIES = 15

    def __init__(self, site_config: dict):
        super().__init__(site_config)

    async def login(self, page) -> bool:
        return True

    async def parse_detail(self, page, url: str) -> Optional[TenderItem]:
        return None

    async def search(self, page, keyword: str, category: str) -> list[TenderItem]:
        return []

    # ── public API (called by scheduler) ──────────────────────────────

    async def run(self, keywords_by_category: dict[str, list[str]], since: Optional[datetime] = None) -> list[TenderItem]:
        """Phase 1: fetch list pages via Scrapling, return basic TenderItems."""
        import concurrent.futures
        if not hasattr(CnncecpScraper, "_pool"):
            CnncecpScraper._pool = concurrent.futures.ThreadPoolExecutor(max_workers=3)

        loop = asyncio.get_event_loop()
        list_items = await loop.run_in_executor(CnncecpScraper._pool, self._fetch_list_sync, since)

        items: list[TenderItem] = []
        for r in list_items:
            title = r.get("title", "")
            items.append(TenderItem(
                date=r.get("date", ""),
                category="",
                project_name=title,
                link=r.get("link", ""),
                source_site=self.site_name,
                bidder=self._extract_bidder_from_title(title),
                deadline=r.get("deadline", ""),
                bid_count=self._extract_bid_count(title),
            ))
        return items

    async def fetch_details(self, items: list[TenderItem]) -> list[TenderItem]:
        """Phase 3: solve captcha + fetch detail pages for filtered items only."""
        if not items:
            return items

        import concurrent.futures
        if not hasattr(CnncecpScraper, "_pool"):
            CnncecpScraper._pool = concurrent.futures.ThreadPoolExecutor(max_workers=3)

        loop = asyncio.get_event_loop()
        detail_map = await loop.run_in_executor(
            CnncecpScraper._pool,
            self._fetch_details_sync,
            [it.link for it in items],
        )

        for item in items:
            data = detail_map.get(item.link, {})
            if data.get("bidder"):
                item.bidder = data["bidder"]
            if data.get("deadline"):
                item.deadline = data["deadline"]
            if data.get("bid_time"):
                item.bid_time = data["bid_time"]
            if data.get("budget"):
                item.budget = data["budget"]
            if data.get("doc_price"):
                item.doc_price = data["doc_price"]

        return items

    # ── Phase 1: list fetch ───────────────────────────────────────────

    def _fetch_list_sync(self, since: Optional[datetime] = None) -> list[dict]:
        from scrapling.fetchers import StealthyFetcher

        all_items: list[dict] = []

        def page_action(page):
            for page_num in range(1, self.MAX_LIST_PAGES + 1):
                url = self.LIST_URL if page_num == 1 else f"{self.BASE_URL}/xzbgg/index_{page_num}.jhtml"
                try:
                    page.goto(url, timeout=30000)
                    page.wait_for_timeout(2000)
                except Exception as e:
                    self.logger.warning(f"List page {page_num} navigation failed: {e}")
                    continue

                rows = page.evaluate(r"""() => {
                    const out = [];
                    document.querySelectorAll('a[href*="/xzbgg/"]').forEach(a => {
                        const href = a.getAttribute('href') || '';
                        if (!/\/xzbgg\/\d+\.jhtml/.test(href)) return;
                        const title = (a.textContent || '').trim();
                        if (!title || title.length < 5) return;
                        const li = a.closest('li');
                        let date = '', deadline = '', status = '';
                        if (li) {
                            const t = li.textContent || '';
                            const dm = t.match(/(\d{4}-\d{2}-\d{2})/);
                            if (dm) date = dm[1];
                            const em = li.querySelector('em');
                            if (em) {
                                const et = em.textContent || '';
                                const dlm = et.match(/[：:]\s*([\d\-: ]+)/);
                                if (dlm) deadline = dlm[1].trim();
                            }
                            if (t.includes('正在报名')) status = '正在报名';
                            else if (t.includes('变更公告')) status = '变更公告';
                        }
                        const full = href.startsWith('http') ? href : 'https://www.cnncecp.com' + href;
                        out.push({title, link: full, date, deadline, status});
                    });
                    return out;
                }""")

                if not rows:
                    break

                all_items.extend(rows)
                self.logger.info(f"List page {page_num}: {len(rows)} items")

                if since and rows:
                    last_date = rows[-1].get("date", "")
                    if last_date:
                        try:
                            if datetime.strptime(last_date, "%Y-%m-%d") < since:
                                break
                        except ValueError:
                            pass

        try:
            fetcher = StealthyFetcher()
            fetcher.fetch(self.LIST_URL, headless=True, block_images=True, timeout=90000, page_action=page_action)
        except Exception as e:
            self.logger.error(f"List fetch session failed: {e}")

        if since:
            kept = []
            for r in all_items:
                ds = r.get("date", "")
                if not ds:
                    continue
                try:
                    if datetime.strptime(ds, "%Y-%m-%d") >= since:
                        kept.append(r)
                except ValueError:
                    kept.append(r)
            all_items = kept

        seen: set[str] = set()
        unique: list[dict] = []
        for r in all_items:
            if r["link"] not in seen:
                seen.add(r["link"])
                unique.append(r)

        self.logger.info(f"List fetch complete: {len(unique)} unique items (since={since})")
        return unique

    # ── Phase 3: detail fetch with captcha ────────────────────────────

    def _fetch_details_sync(self, urls: list[str]) -> dict:
        """Solve captcha once via API, then fetch all detail pages via fetch()."""
        from scrapling.fetchers import StealthyFetcher

        results: dict[str, dict] = {}
        if not urls:
            return results

        first_id = urls[0].rstrip("/").split("/")[-1].replace(".jhtml", "")

        def page_action(page):
            try:
                if "cnncecp.com" not in (page.url or ""):
                    page.goto(f"{self.BASE_URL}/captcha.html?noticeId={first_id}", timeout=30000)
            except Exception:
                page.goto(f"{self.BASE_URL}/captcha.html?noticeId={first_id}", timeout=30000)
            page.wait_for_timeout(2000)

            # ── For each URL: solve per-notice captcha → fetch detail via fetch() ──
            for i, url in enumerate(urls):
                if i > 0:
                    time.sleep(1)  # inter-notice delay
                notice_id = url.rstrip("/").split("/")[-1].replace(".jhtml", "")
                detail_fetched = False

                for attempt in range(1, self.CAPTCHA_MAX_RETRIES + 1):
                    ok = self._try_solve_captcha(page, notice_id)
                    if not ok:
                        time.sleep(0.3)
                        continue

                    test = self._fetch_detail_html(page, url)
                    if test and not test.get("isCaptcha") and test.get("len", 0) > 3000:
                        # Try to get PDF content for richer fields
                        pdf_text = ""
                        if test.get("pdfUrl"):
                            pdf_url = test["pdfUrl"].replace("&amp;", "&")
                            if not pdf_url.startswith("http"):
                                pdf_url = f"{self.BASE_URL}{pdf_url}"
                            pdf_text = self._fetch_pdf_text(page, pdf_url)

                        results[url] = self._parse_detail_html(test["text"], pdf_text)
                        d = results[url]
                        # Debug: save first successful HTML for analysis
                        if i == 0:
                            try:
                                with open("data/cnncecp_detail_sample.html", "w", encoding="utf-8") as f:
                                    f.write(test["text"])
                            except Exception:
                                pass
                        self.logger.info(
                            f"Detail {i+1}/{len(urls)}: solved attempt {attempt} "
                            f"bidder={d.get('bidder','')[:20]} budget={d.get('budget','')} "
                            f"bid_time={d.get('bid_time','')} doc_price={d.get('doc_price','')}"
                        )
                        detail_fetched = True
                        break

                if not detail_fetched:
                    self.logger.warning(f"Detail {i+1}/{len(urls)}: failed after all captcha attempts")
                    results[url] = {}

        try:
            fetcher = StealthyFetcher()
            fetcher.fetch(
                f"{self.BASE_URL}/captcha.html?noticeId={urls[0].rstrip('/').split('/')[-1].replace('.jhtml', '')}",
                headless=True,
                block_images=False,
                timeout=120000 + len(urls) * 8000,
                page_action=page_action,
            )
        except Exception as e:
            self.logger.error(f"Detail fetch session failed: {e}")

        return results

    def _try_solve_captcha(self, page, notice_id: str) -> bool:
        """One captcha attempt: get → detect gap → check.  Returns True if check completed."""
        client_uid = "slider-" + "a" * 50

        # Step 1: GET captcha
        get_result = page.evaluate("""async (params) => {
            try {
                const r = await fetch('/captcha/get', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(params)
                });
                return await r.json();
            } catch(e) { return {error: e.message}; }
        }""", {
            "captchaType": "blockPuzzle",
            "captchaId": notice_id,
            "clientUid": client_uid,
            "ts": int(time.time() * 1000),
        })

        if not get_result or get_result.get("error") or get_result.get("repCode") != "0000":
            self.logger.warning(f"Captcha GET failed: {get_result}")
            return False

        rep = get_result["repData"]
        secret_key = rep["secretKey"]
        token = rep["token"]
        bg_b64 = rep["originalImageBase64"]

        # Step 2: detect gap
        gap_x = self._detect_gap_x(bg_b64, rep.get("jigsawImageBase64", ""))

        # Step 3: AES encrypt + check
        point_json = json.dumps({"x": gap_x, "y": 5.0})
        encrypted_point = self._aes_encrypt(point_json, secret_key)

        # Step 4: POST /captcha/check (response is opaque redirect — we ignore it)
        page.evaluate("""async (params) => {
            try {
                const formData = new URLSearchParams();
                for (const [k, v] of Object.entries(params)) {
                    formData.append(k, v);
                }
                await fetch('/captcha/check', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    body: formData.toString(),
                    redirect: 'follow'
                });
            } catch(e) { /* redirect causes opaque response, ignore */ }
        }""", {
            "captchaType": "blockPuzzle",
            "pointJson": encrypted_point,
            "token": token,
            "captchaId": notice_id,
            "clientUid": client_uid,
            "ts": int(time.time() * 1000),
        })

        self.logger.info(f"Captcha check sent (gap_x={gap_x})")
        return True

    def _fetch_detail_html(self, page, url: str) -> dict:
        """Fetch a detail page via in-browser fetch(). Returns {isCaptcha, len, text, pdfUrl}."""
        return page.evaluate(r"""async (url) => {
            try {
                const r = await fetch(url, {redirect: 'follow'});
                const text = await r.text();
                let pdfUrl = '';
                const m = text.match(/<iframe[^>]+src="([^"]*download\.svc[^"]*)"/);
                if (m) pdfUrl = m[1];
                return {
                    status: r.status,
                    url: r.url,
                    len: text.length,
                    isCaptcha: text.includes('captcha.html') || text.includes('安全验证'),
                    hasTender: text.includes('招标') || text.includes('采购'),
                    text: text.substring(0, 80000),
                    pdfUrl: pdfUrl,
                };
            } catch(e) {
                return {error: e.message, len: 0, isCaptcha: true};
            }
        }""", url)

    def _fetch_pdf_text(self, page, pdf_url: str) -> str:
        """Download PDF via fetch() and return extracted text (parsed in Python)."""
        if not pdf_url:
            return ""
        # Fetch PDF as base64 in the browser
        b64_result = page.evaluate(r"""async (url) => {
            try {
                const r = await fetch(url, {redirect: 'follow'});
                const blob = await r.blob();
                return new Promise((resolve) => {
                    const reader = new FileReader();
                    reader.onloadend = () => resolve({b64: reader.result.split(',')[1], ok: r.ok});
                    reader.readAsDataURL(blob);
                });
            } catch(e) { return {error: e.message}; }
        }""", pdf_url)
        if not b64_result or not b64_result.get("b64"):
            return ""

        try:
            from pypdf import PdfReader
            pdf_bytes = base64.b64decode(b64_result["b64"])
            reader = PdfReader(io.BytesIO(pdf_bytes))
            text = ""
            for pg in reader.pages:
                text += pg.extract_text() + "\n"
            return text
        except Exception as e:
            self.logger.warning(f"PDF parse failed: {e}")
            return ""

    # ── HTML parsing ──────────────────────────────────────────────────

    @staticmethod
    def _parse_detail_html(html: str, pdf_text: str = "") -> dict:
        """Parse detail page HTML + PDF text using regex."""
        R = {}
        # Combine HTML text and PDF text for regex search
        html_text = re.sub(r"<[^>]+>", " ", html)
        html_text = re.sub(r"\s+", " ", html_text)
        search_text = (pdf_text + "\n" + html_text).strip() if pdf_text else html_text

        m = re.search(r"(?:招标人|采购人|招标单位|采购单位)[：:]\s*([^\s<,，。]{4,40}?)(?:\s|,|，|。|<|$)", search_text)
        if m:
            R["bidder"] = m.group(1).strip()
        m = re.search(r"(?:报名|获取|递交)[^]{0,30}(?:截止|期限)[^]{0,30}[：:]?\s*(\d{4}[\-年/]\d{1,2}[\-月/]\d{1,2}[日]?\s*\d{1,2}[：:时]\d{1,2})", search_text)
        if m:
            R["deadline"] = m.group(1)
        m = re.search(r"开标[^]{0,20}时间[：:]?\s*(\d{4}[\-年/]\d{1,2}[\-月/]\d{1,2}[日]?\s*\d{1,2}[：:时]\d{1,2})", search_text)
        if m:
            R["bid_time"] = m.group(1)
        m = re.search(r"(?:预算|采购金额|最高限价|控制价|项目金额)[：:（(]?\s*[¥￥]?\s*(\d+\.?\d*)\s*万?元", search_text)
        if m:
            R["budget"] = m.group(1)
        m = re.search(r"标书[售价价格费]*[：:]\s*[¥￥]?\s*(\d+\.?\d*)\s*元", search_text)
        if m:
            R["doc_price"] = m.group(0)
        return R

    # ── Captcha helpers ───────────────────────────────────────────────

    @staticmethod
    def _aes_encrypt(text: str, key: str) -> str:
        """AES-ECB PKCS7, matching crypto-js used by anji-plus verify.js."""
        key_bytes = key.encode("utf-8")
        if len(key_bytes) not in (16, 24, 32):
            key_bytes = key_bytes.ljust(16, b"\0")[:16]
        cipher = AES.new(key_bytes, AES.MODE_ECB)
        ct = cipher.encrypt(pad(text.encode("utf-8"), AES.block_size))
        return base64.b64encode(ct).decode("utf-8")

    @staticmethod
    def _detect_gap_x(bg_b64: str, puzzle_b64: str = "") -> int:
        """Detect gap X position in anji-plus blockPuzzle background (310px ref).

        Computes per-column horizontal gradient and finds the first strong,
        sustained vertical edge after x≈55 — the gap's left boundary.
        """
        raw = base64.b64decode(bg_b64)
        img = Image.open(io.BytesIO(raw)).convert("L")
        w, h = img.size
        px = img.load()

        col_edge = []
        for x in range(w - 1):
            s = 0
            for y in range(h):
                s += abs(px[x, y] - px[x + 1, y])
            col_edge.append(s)

        region = col_edge[55:w - 20]
        if not region:
            return 120
        median = sorted(region)[len(region) // 2]
        threshold = max(median * 2.0, 600)

        for x in range(55, w - 20):
            if col_edge[x] > threshold and x + 2 < w and col_edge[x + 1] > threshold * 0.3:
                return round(x * 310 / w)

        mx, mi = 0, 80
        for x in range(55, w - 20):
            if col_edge[x] > mx:
                mx = col_edge[x]
                mi = x
        return round(mi * 310 / w)

    # ── title helpers ─────────────────────────────────────────────────

    @staticmethod
    def _extract_bidder_from_title(title: str) -> str:
        m = re.match(
            r"^([\u4e00-\u9fa5]+(?:公司|集团|分局|中心|研究院|研究所|局|院|处|部|厅|委|办|站|所|学校|医院|协会|基金会|联合会))",
            title,
        )
        if m:
            return m.group(1)
        m = re.match(r"^(.{4,25}?)(?:\d{4}年|\d{4}[-/])", title)
        if m:
            return m.group(1).rstrip("的")
        return ""

    @staticmethod
    def _extract_bid_count(title: str) -> str:
        for pat, val in [
            (r"第[四4]次", "第四次"),
            (r"第[三3]次", "第三次"),
            (r"第[二2]次", "第二次"),
            (r"第[一1]次", "第一次"),
            (r"[（(]\s*[二2]\s*[)）]", "第二次"),
            (r"[（(]\s*[三3]\s*[)）]", "第三次"),
            (r"[（(]\s*[四4]\s*[)）]", "第四次"),
            (r"二次", "第二次"),
            (r"三次", "第三次"),
            (r"四次", "第四次"),
        ]:
            if re.search(pat, title):
                return val
        return "第一次"
