"""Mobile scraper - 中国移动采购与招标网, optimized: search all types, filter before detail fetch."""
from datetime import datetime
from typing import Optional
import ssl
import httpx
import re

from src.scraper.scrapling_base import ScraplingScraper, TenderItem

VALID_PUB_ONE_TYPES = {"PROCUREMENT", "CANDIDATE_PUBLICITY", "ONE_SOURCE_PROCUREMENT", "PURCHASE_OPINION"}
SEARCH_PUB_TYPES = ["PROCUREMENT", "PURCHASE_SERVICE"]


class MobileScraper(ScraplingScraper):
    _ssl_ctx = None

    def _get_ssl_ctx(self):
        if self._ssl_ctx is None:
            ctx = ssl.create_default_context()
            ctx.options |= 0x4
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            self._ssl_ctx = ctx
        return self._ssl_ctx

    @staticmethod
    def _extract_bidder_from_title(title: str) -> str:
        t = title.strip()
        # Skip leading year/date prefix like "2026年-2027年" or "2026-2027年"
        t = re.sub(r'^\d{4}\s*年?\s*[-~至]\s*\d{4}\s*年?\s*', '', t)
        t = re.sub(r'^\d{4}\s*年\s*', '', t)

        # Try full organization name with common suffixes (including parenthesis)
        m = re.match(r'^([\u4e00-\u9fa5（）()]+(?:公司|集团|分局|中心|研究院|研究所|局|院|处|部|厅|委|办|站|所|学校|医院|协会|基金会|分公司|信息|科技|大学))', t)
        if m:
            name = m.group(1)
            if len(name) >= 4:
                return name
        # Fallback: match until year/date
        m = re.match(r'^(.{2,30}?)(?:\d{4}年|\d{4}[-/])', t)
        if m:
            name = m.group(1).rstrip('的')
            if len(name) >= 2:
                return name
        return ""

    @staticmethod
    def _keyword_matches(title: str, keyword: str) -> bool:
        parts = [p.strip() for p in keyword.split("/") if len(p.strip()) >= 2]
        if not parts:
            parts = [keyword]
        return any(p in title for p in parts)

    def _do_search(self, fetcher, keyword: str, category: str) -> list[TenderItem]:
        items: list[TenderItem] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36",
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://b2b.10086.cn/b2b/main/buyer/listVendorNotice.html",
            "Origin": "https://b2b.10086.cn",
        }

        try:
            with httpx.Client(verify=self._get_ssl_ctx(), headers=headers, timeout=30) as client:
                seen_ids = set()

                for pub_type in SEARCH_PUB_TYPES:
                    page = 1
                    max_pages = 5

                    while page <= max_pages:
                        body = {
                            "current": page,
                            "size": 20,
                            "name": keyword,
                            "publishType": pub_type,
                            "publishOneType": "",
                            "companyOneType": "",
                            "creationDateStart": "",
                            "creationDateEnd": "",
                            "sfactApplColumn5": "PC",
                        }
                        r = client.post(
                            "https://b2b.10086.cn/api-b2b/api-sync-es/white_list_api/b2b/publish/queryList",
                            json=body,
                        )
                        r.raise_for_status()
                        data = r.json()
                        if data.get("code") != 0:
                            break

                        page_data = data.get("data", {})
                        content = page_data.get("content", [])
                        total_pages = page_data.get("totalPages", 1)

                        if not content:
                            break

                        for record in content:
                            notice_id = str(record.get("id", ""))
                            if notice_id in seen_ids:
                                continue
                            seen_ids.add(notice_id)

                            rec_pub_one_type = record.get("publishOneType", "")
                            if rec_pub_one_type not in VALID_PUB_ONE_TYPES:
                                continue

                            name = record.get("name", "").strip()
                            project_name_list = record.get("projectName", "").strip() if record.get("projectName") else ""
                            display_name_list = project_name_list or name

                            if not self._keyword_matches(display_name_list, keyword):
                                continue

                            pub_date = record.get("publishDate", "")[:10]
                            notice_uuid = record.get("uuid", "")
                            rec_pub_type = record.get("publishType", pub_type)

                            bidder = self._extract_bidder_from_title(display_name_list)

                            detail_deadline = ""
                            detail_bid_time = ""
                            detail_project_name = ""
                            detail_bidder = ""
                            try:
                                detail_body = {
                                    "publishId": record.get("id"),
                                    "publishUuid": notice_uuid,
                                    "publishType": rec_pub_type,
                                    "publishOneType": rec_pub_one_type,
                                }
                                dr = client.post(
                                    "https://b2b.10086.cn/api-b2b/api-sync-es/white_list_api/b2b/publish/queryDetail",
                                    json=detail_body, timeout=15,
                                )
                                if dr.status_code == 200:
                                    ddata = dr.json()
                                    if ddata.get("code") == 0:
                                        d = ddata.get("data", {})
                                        detail_project_name = d.get("projectName", "")
                                        if d.get("tenderSaleDeadline"):
                                            raw = d["tenderSaleDeadline"][:19]
                                            if not raw.startswith("1900"):
                                                detail_deadline = raw
                                        if d.get("backDate"):
                                            raw = d["backDate"][:19]
                                            if not raw.startswith("1900"):
                                                detail_bid_time = raw
                                        if d.get("publicityEndTime") and not detail_deadline:
                                            raw = d["publicityEndTime"][:19]
                                            if not raw.startswith("1900"):
                                                detail_deadline = raw
                                        if d.get("publicityStartTime") and not detail_bid_time:
                                            raw = d["publicityStartTime"][:19]
                                            if not raw.startswith("1900"):
                                                detail_bid_time = raw
                                        if d.get("companyName"):
                                            detail_bidder = d.get("companyName")
                                        elif d.get("tenantName"):
                                            detail_bidder = d.get("tenantName", "")
                            except Exception:
                                pass

                            final_name = detail_project_name or display_name_list
                            # Prefer bidder extracted from title/projectName; only use API companyName/tenantName as fallback
                            fallback_bidder = self._extract_bidder_from_title(final_name)
                            final_bidder = fallback_bidder or detail_bidder or bidder

                            items.append(TenderItem(
                                date=pub_date or datetime.now().strftime("%Y-%m-%d"),
                                category=category,
                                project_name=final_name,
                                link=f"https://b2b.10086.cn/#/noticeDetail?publishId={notice_id}&publishUuid={notice_uuid}&publishType={rec_pub_type}&publishOneType={rec_pub_one_type}",
                                source_site=self.site_name,
                                bidder=final_bidder,
                                deadline=detail_deadline,
                                bid_time=detail_bid_time,
                                bid_count=self._extract_bid_count(name),
                            ))

                        if page >= total_pages:
                            break
                        page += 1

                self.logger.info(f"Mobile: keyword=[{keyword}] found {len(items)} items after filter")
        except Exception as e:
            self.logger.error(f"Mobile API failed: {e}")
        return items
