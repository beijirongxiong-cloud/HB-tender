"""SGCC scraper - 国家电网电子商务平台.

Uses sgcc.com.cn noteList API for search (returns doci-bid tender announcements)
and getNoticeBid API for detail enrichment (deadline, bid_time, bidder).

Efficiency strategy:
1. List-page keyword filter: only fetch details for items whose title matches keywords.
2. Skip doc-spec type (no detail API available) — keep them with list-page data only.
3. Batch detail fetch with persistent httpx connection.
4. Cap results per keyword/menu to avoid excessive API calls.
"""
import os
import re
from datetime import datetime
from typing import Optional

import httpx

from src.scraper.scrapling_base import ScraplingScraper, TenderItem


class SgccScraper(ScraplingScraper):
    # Menu IDs on sgcc.com.cn for tender announcements (not bid results)
    # 2018032700291334 = 招标公告及投标邀请书
    # 2018032900295987 = 采购公告
    NOTICE_MENU_IDS = [
        "2018032700291334",
        "2018032900295987",
    ]

    SEARCH_URL = "https://ecp.sgcc.com.cn/ecp2.0/ecpwcmcore//index/noteList"
    DETAIL_URL = "https://ecp.sgcc.com.cn/ecp2.0/ecpwcmcore//index/getNoticeBid"
    PORTAL_URL = "https://ecp.sgcc.com.cn/ecp2.0/portal/#/doc/"
    REFERER = "https://ecp.sgcc.com.cn/ecp2.0/portal/"

    def _do_search(self, fetcher, keyword: str, category: str) -> list[TenderItem]:
        items: list[TenderItem] = []
        headers = {
            "Content-Type": "application/json",
            "Referer": self.REFERER,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        seen_ids: set[str] = set()

        try:
            with httpx.Client(headers=headers, timeout=25, verify=False) as client:
                for menu_id in self.NOTICE_MENU_IDS:
                    for page_idx in range(1, 6):
                        body = {
                            "index": page_idx,
                            "size": 50,
                            "firstPageMenuId": menu_id,
                            "purOrgStatus": "",
                            "purOrgCode": "",
                            "noticeType": "",
                            "orgId": "",
                            "key": keyword,
                            "orgName": "",
                        }
                        r = client.post(self.SEARCH_URL, json=body)
                        if r.status_code != 200:
                            break
                        data = r.json()
                        if not data.get("successful"):
                            break
                        rv = data.get("resultValue", {})
                        if not isinstance(rv, dict):
                            break
                        note_list = rv.get("noteList", [])
                        if not note_list:
                            break
                        for n in note_list:
                            notice_id = str(n.get("noticeId") or "")
                            doc_id = str(n.get("firstPageDocId") or "")
                            # Dedupe by noticeId (or doc_id fallback)
                            dedup_key = notice_id or doc_id
                            if not dedup_key or dedup_key in seen_ids:
                                continue
                            seen_ids.add(dedup_key)

                            title = n.get("title", "").strip()
                            if not title:
                                continue
                            # List-page keyword pre-filter (efficiency: avoid detail fetch for non-matches)
                            if keyword and not self._keyword_matches(title, keyword):
                                continue

                            org_name = n.get("publishOrgName", "") or ""
                            bidder = org_name if org_name else self._extract_bidder_from_title(title)
                            pub_date = n.get("noticePublishTime", "")
                            doctype = n.get("doctype", "")
                            menu = str(n.get("firstPageMenuId") or menu_id)

                            # Build detail link: #/doc/{doctype}/{doc_id}_{menu}_{notice_id}
                            link = self._build_link(doctype, doc_id, menu, notice_id)

                            items.append(TenderItem(
                                date=pub_date,
                                category=category,
                                project_name=title,
                                link=link,
                                source_site=self.site_name,
                                bidder=bidder,
                                deadline="",
                                bid_time="",
                                bid_count=self._extract_bid_count(title),
                            ))
                            if len(items) >= 50:
                                break
                        if len(items) >= 50:
                            break
                    if len(items) >= 50:
                        break
        except Exception as e:
            self.logger.error(f"SGCC search API failed: {e}")
        return items[:50]

    def _do_fetch_details(self, items: list[TenderItem]) -> list[TenderItem]:
        """Batch-fetch detail for items that have a noticeId in their link.

        Skip doc-spec items (no detail API) — keep their list-page data.
        """
        if not items:
            return items

        headers = {
            "Content-Type": "application/json",
            "Referer": self.REFERER,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

        enriched = 0
        try:
            with httpx.Client(headers=headers, timeout=20, verify=False) as client:
                for item in items:
                    notice_id = self._extract_notice_id_from_link(item.link)
                    if not notice_id:
                        # doc-spec or missing noticeId — keep list-page data
                        if not item.bidder:
                            item.bidder = self._extract_bidder_from_title(item.project_name)
                        continue
                    try:
                        r = client.post(self.DETAIL_URL, content=notice_id)
                        if r.status_code != 200:
                            continue
                        data = r.json()
                        rv = data.get("resultValue", {})
                        if not isinstance(rv, dict):
                            continue
                        notice = rv.get("notice", {})
                        if not notice:
                            continue

                        # Enrich fields
                        name = notice.get("PURPRJ_NAME", "")
                        if name and len(name) > len(item.project_name):
                            item.project_name = name.strip()
                        bid_org = notice.get("BID_ORG", "") or notice.get("PUBLISH_ORG_NAME", "")
                        if bid_org:
                            item.bidder = bid_org
                        elif not item.bidder:
                            item.bidder = self._extract_bidder_from_title(item.project_name)

                        deadline = notice.get("BIDBOOK_BUY_END_TIME", "")
                        if deadline and not deadline.startswith("1900"):
                            item.deadline = deadline
                        bid_time = notice.get("OPENBID_TIME", "")
                        if bid_time and not bid_time.startswith("1900"):
                            item.bid_time = bid_time

                        enriched += 1
                    except Exception as e:
                        self.logger.warning(f"SGCC detail fetch failed for {notice_id}: {e}")
        except Exception as e:
            self.logger.error(f"SGCC detail batch failed: {e}")

        self.logger.info(f"SGCC: enriched {enriched}/{len(items)} items with details")
        return items

    async def fetch_details(self, items: list[TenderItem]) -> list[TenderItem]:
        """Override to use sync httpx batch fetch instead of Scrapling browser."""
        if not items:
            return items
        import concurrent.futures
        if not hasattr(ScraplingScraper, "_pool"):
            ScraplingScraper._pool = concurrent.futures.ThreadPoolExecutor(max_workers=7)
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            ScraplingScraper._pool, self._do_fetch_details, items
        )

    @staticmethod
    def _keyword_matches(title: str, keyword: str) -> bool:
        """Match keyword parts (split by /) against title."""
        if not keyword:
            return True
        parts = [p.strip() for p in keyword.split("/") if len(p.strip()) >= 2]
        if not parts:
            parts = [keyword]
        return any(p in title for p in parts)

    @staticmethod
    def _build_link(doctype: str, doc_id: str, menu_id: str, notice_id: str) -> str:
        """Build detail page URL.

        For doci-bid/doci-win: #/doc/{doctype}/{doc_id}_{menu_id}_{notice_id}
        For doc-spec (no noticeId): #/doc/{doctype}/{doc_id}_{menu_id}
        """
        if not doc_id:
            return ""
        base = SgccScraper.PORTAL_URL + doctype + "/"
        if notice_id:
            return f"{base}{doc_id}_{menu_id}_{notice_id}"
        return f"{base}{doc_id}_{menu_id}"

    @staticmethod
    def _extract_notice_id_from_link(link: str) -> Optional[str]:
        """Extract noticeId (last segment) from a SGCC detail link.

        Link format: .../#/doc/doci-bid/{doc_id}_{menu_id}_{notice_id}
        Returns notice_id only for doci-bid/doci-win types (doc-spec has no noticeId).
        """
        if not link:
            return None
        # Only doci-bid and doci-win have 3-part IDs with noticeId
        if "doci-bid" not in link and "doci-win" not in link:
            return None
        # Extract last path segment after final /
        segments = link.rstrip("/").split("/")
        last = segments[-1] if segments else ""
        parts = last.split("_")
        if len(parts) >= 3:
            return parts[-1]
        return None

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
            return m.group(1).rstrip("的")
        return ""
