"""China Telecom (中国电信阳光采购网) - API-based scraper."""
import re
import ssl
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

import httpx

from src.scraper.scrapling_base import ScraplingScraper, TenderItem


class TelecomScraper(ScraplingScraper):
    BASE = "https://caigou.chinatelecom.com.cn"
    LIST_API = "/portal/base/announcementJoin/queryListNew"
    DETAIL_API = "/portal/base/tenderannouncement/view"

    TYPE_BID = "e2no"
    TYPE_INQUIRY = "e3erht"
    TYPE_NEGOTIATION = "e8vif"

    DOC_TYPE_MAP = {
        "TenderAnnouncement": "TenderAnnouncement",
        "CompareSelect": "CompareSelect",
        "NegotiationAnnouncement": "NegotiationAnnouncement",
        "Prequalfication": "Prequalfication",
    }

    _ssl_ctx = None

    def _get_ssl_ctx(self):
        if self._ssl_ctx is None:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            self._ssl_ctx = ctx
        return self._ssl_ctx

    @property
    def supports_keyword_search(self) -> bool:
        return True

    def _do_search(self, fetcher, keyword: str, category: str) -> list[TenderItem]:
        items: list[TenderItem] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36",
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{self.BASE}/search?search={quote(keyword)}",
            "Origin": self.BASE,
        }

        search_types = [self.TYPE_BID, self.TYPE_INQUIRY, self.TYPE_NEGOTIATION, ""]

        try:
            with httpx.Client(verify=self._get_ssl_ctx(), headers=headers, timeout=30) as client:
                seen_ids = set()

                for search_type in search_types:
                    page = 1
                    while page <= 10:
                        body = {
                            "pageNum": page,
                            "pageSize": 20,
                            "type": search_type,
                            "title": keyword,
                            "provinceCode": "",
                            "noticeSummary": "",
                        }
                        r = client.post(f"{self.BASE}{self.LIST_API}", json=body)
                        r.raise_for_status()
                        data = r.json()

                        if data.get("code") != 200:
                            break

                        page_info = data.get("data", {}).get("pageInfo", {})
                        records = page_info.get("list", [])
                        if not records:
                            break

                        found_old_record = False
                        for rec in records:
                            rid = str(rec.get("id", ""))
                            if rid in seen_ids:
                                continue
                            seen_ids.add(rid)

                            doc_title = rec.get("docTitle", "").strip()
                            doc_type_code = rec.get("docTypeCode", "")
                            doc_type = rec.get("docType", "")
                            create_date_raw = rec.get("createDate", "") or ""

                            if create_date_raw and not self._is_recent_publish_date(create_date_raw):
                                found_old_record = True
                                continue

                            if doc_type_code == "ResultAnnounc" or "采购结果" in doc_type or "结果公示" in doc_type:
                                continue
                            if "失败" in doc_title or "终止" in doc_title:
                                continue

                            if keyword and keyword not in doc_title:
                                continue

                            province_name = rec.get("provinceName", "")
                            create_date = create_date_raw[:10]
                            p_start_date = rec.get("pStartDate", "")
                            p_end_date = rec.get("pEndDate", "")
                            security_view_code = rec.get("securityViewCode", "")
                            doc_id = str(rec.get("docId", ""))

                            bidder = self._extract_bidder_from_title(doc_title)
                            deadline = self._format_datetime(p_end_date) if p_end_date else ""

                            display_title = doc_title
                            if province_name and not doc_title.startswith(f"【{province_name}】"):
                                display_title = f"【{province_name}】{doc_title}"

                            detail_url = (
                                f"{self.BASE}/DeclareDetails"
                                f"?id={doc_id}&type=1"
                                f"&docTypeCode={doc_type_code}"
                                f"&securityViewCode={security_view_code}"
                            )

                            item = TenderItem(
                                date=create_date or datetime.now().strftime("%Y-%m-%d"),
                                category=category,
                                project_name=display_title,
                                link=detail_url,
                                source_site=self.site_name,
                                bidder=bidder,
                                deadline=deadline,
                                bid_count=self._extract_bid_count(doc_title),
                            )
                            items.append(item)

                        total_pages = page_info.get("pages", 1)
                        if found_old_record:
                            break
                        if page >= total_pages:
                            break
                        page += 1

                        if len(items) >= 50:
                            break

                    if len(items) >= 50:
                        break

                filtered_items = self._keyword_prefilter(items)
                if filtered_items:
                    self._fetch_details(client, filtered_items)

        except Exception as e:
            self.logger.error(f"Telecom API failed: {e}")
        return items

    def _keyword_prefilter(self, items: list[TenderItem]) -> list[TenderItem]:
        return [it for it in items if it.project_name and len(it.project_name) >= 5]

    def _fetch_details(self, client: httpx.Client, items: list[TenderItem]) -> None:
        for item in items:
            try:
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(item.link)
                qs = parse_qs(parsed.query)

                doc_id = qs.get("id", [""])[0]
                doc_type_code = qs.get("docTypeCode", [""])[0]
                security_view_code = qs.get("securityViewCode", [""])[0]

                if not doc_id or not doc_type_code:
                    continue

                api_type = self.DOC_TYPE_MAP.get(doc_type_code, doc_type_code)

                body = {
                    "type": api_type,
                    "id": doc_id,
                    "securityViewCode": security_view_code,
                }
                r = client.post(f"{self.BASE}{self.DETAIL_API}", json=body)
                if r.status_code != 200:
                    continue

                data = r.json()
                if data.get("code") != 200:
                    continue

                detail = data.get("data", {})
                context_html = detail.get("context", "")

                agent_name = detail.get("agentProviderName", "")

                if context_html:
                    if not item.bidder or len(item.bidder) < 4:
                        db = self._extract_bidder_from_html(context_html)
                        if db:
                            item.bidder = db

                    if not item.deadline:
                        dl = self._extract_deadline(context_html)
                        if dl:
                            item.deadline = dl

                    if not item.bid_time:
                        bt = self._extract_bid_time(context_html)
                        if bt:
                            item.bid_time = bt

                    budget = self._extract_budget(context_html)
                    if budget:
                        item.budget = budget

                    doc_price = self._extract_doc_price(context_html)
                    if doc_price:
                        item.doc_price = doc_price

            except Exception:
                continue

    @staticmethod
    def _is_recent_publish_date(date_str: str, now: Optional[datetime] = None) -> bool:
        if not date_str:
            return True
        now = now or datetime.now()
        try:
            publish_time = datetime.strptime(date_str[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                publish_time = datetime.strptime(date_str[:10], "%Y-%m-%d")
            except ValueError:
                return True
        return publish_time >= now - timedelta(days=3)

    @staticmethod
    def _format_datetime(dt_str: str) -> str:
        if not dt_str:
            return ""
        dt_str = dt_str[:19]
        dt_str = dt_str.replace("T", " ")
        return dt_str

    @staticmethod
    def _extract_bidder_from_html(html: str) -> str:
        for pattern in [
            r'招\s*标\s*人[:：\s]*([^\s<,，。；;且与和]{4,30}?)(?:\s|<|，|,|；|;|及|和|与|$)',
            r'采\s*购\s*人[:：\s]*([^\s<,，。；;且与和]{4,30}?)(?:\s|<|，|,|；|;|及|和|与|$)',
            r'招\s*标\s*单\s*位[:：\s]*([^\s<,，。；;且与和]{4,30}?)(?:\s|<|，|,|；|;|及|和|与|$)',
            r'采\s*购\s*单\s*位[:：\s]*([^\s<,，。；;且与和]{4,30}?)(?:\s|<|，|,|；|;|及|和|与|$)',
        ]:
            m = re.search(pattern, html)
            if m:
                val = m.group(1).strip().lstrip('为')
                if val and val not in ('不具有独立法人资格的附属机构', '附属机构', '代理机构', '采购代理机构'):
                    if len(val) >= 4 and ('公司' in val or '集团' in val or '局' in val or '院' in val or '中心' in val or '部' in val):
                        return val
        return ""

    @staticmethod
    def _extract_deadline(html: str) -> str:
        for pattern in [
            r'报名[^<]{0,10}截止[^<]{0,10}[:：\s]*(\d{4}[-年/]\d{1,2}[-月/]\d{1,2}[^<\d]{0,10}\d{0,2}[时:点]?\d{0,2}[分:]?\d{0,2})',
            r'投标[^<]{0,10}截止[^<]{0,10}[:：\s]*(\d{4}[-年/]\d{1,2}[-月/]\d{1,2}[^<\d]{0,10}\d{0,2}[时:点]?\d{0,2}[分:]?\d{0,2})',
            r'递交[^<]{0,10}截止[^<]{0,10}[:：\s]*(\d{4}[-年/]\d{1,2}[-月/]\d{1,2}[^<\d]{0,10}\d{0,2}[时:点]?\d{0,2}[分:]?\d{0,2})',
            r'文件[^<]{0,6}获取[^<]{0,6}截止[^<]{0,10}[:：\s]*(\d{4}[-年/]\d{1,2}[-月/]\d{1,2}[^<\d]{0,10}\d{0,2}[时:点]?\d{0,2}[分:]?\d{0,2})',
            r'截止时间[:：\s]*(\d{4}[-年/]\d{1,2}[-月/]\d{1,2}[^<\d]{0,10}\d{0,2}[时:点]?\d{0,2}[分:]?\d{0,2})',
        ]:
            m = re.search(pattern, html)
            if m:
                val = m.group(1).strip()
                val = re.sub(r'[年月]', '-', val)
                val = re.sub(r'[日号]', '', val)
                val = re.sub(r'[时点]', ':', val)
                val = re.sub(r'分', ':', val)
                val = re.sub(r'秒', '', val)
                val = re.sub(r'--+', '-', val)
                val = val.strip('-.')
                return val
        return ""

    @staticmethod
    def _extract_bid_time(html: str) -> str:
        for pattern in [
            r'开标[^<]{0,10}时间[:：\s]*(\d{4}[-年/]\d{1,2}[-月/]\d{1,2}[^<\d]{0,10}\d{0,2}[时:点]?\d{0,2}[分:]?\d{0,2})',
        ]:
            m = re.search(pattern, html)
            if m:
                val = m.group(1).strip()
                val = re.sub(r'[年月]', '-', val)
                val = re.sub(r'[日号]', '', val)
                val = re.sub(r'[时点]', ':', val)
                val = re.sub(r'分', ':', val)
                val = re.sub(r'秒', '', val)
                val = re.sub(r'--+', '-', val)
                val = val.strip('-.')
                return val
        return ""

    @staticmethod
    def _extract_budget(html: str) -> str:
        # Try "XX万元" first (already in 万元)
        m = re.search(r'(?:预算|预算金额|项目预算|采购金额|最高投标限价|最高限价)[^0-9¥￥]{0,10}[¥￥]?\s*(\d[\d,]*\.?\d*)\s*万元', html)
        if m:
            return m.group(1).replace(',', '')

        # Try "XX万元" standalone
        m = re.search(r'[¥￥]\s*(\d[\d,]*\.?\d*)\s*万元', html)
        if m:
            return m.group(1).replace(',', '')

        # Try "XX元" (convert to 万元 by dividing 10000)
        m = re.search(r'(?:预算|预算金额|项目预算|采购金额|最高投标限价|最高限价)[^0-9¥￥]{0,10}[¥￥]?\s*(\d[\d,]*\.?\d*)\s*元', html)
        if m:
            val = float(m.group(1).replace(',', ''))
            return f"{val / 10000:.4f}"

        # Try "¥XX元" or "￥XX元" standalone (convert to 万元)
        m = re.search(r'[¥￥]\s*(\d[\d,]*\.?\d*)\s*元', html)
        if m:
            val = float(m.group(1).replace(',', ''))
            return f"{val / 10000:.4f}"

        return ""

    @staticmethod
    def _extract_doc_price(html: str) -> str:
        m = re.search(r'(?:标书|招标文件|招募文件)[售价价格]*[：:]\s*[¥￥]?\s*(\d+\.?\d*)\s*元', html)
        if m:
            return m.group(0)
        return ""
