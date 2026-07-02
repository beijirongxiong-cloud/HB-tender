"""Iccec scraper - 中交招采网 (iccec.cn).

Uses the public searchSupNoticeNew API for search (returns JSON with
full notice data: title, bidder, scheme info, dates, etc.)
No login required.

API endpoint: POST https://sp.iccec.cn/apis/sp/bidc/users/signup/searchSupNoticeNew
Request body: {
    "pageNo": 1,
    "pageSize": 10,
    "noticeTitle": "",
    "schemeName": "培训",
    "sortName": "1",
    "sortOrder": "0",
    "supCodeList": [],
    "purchaseCategory": "",
    "purchaseType": [],
    "purchaseClassList": [],
    "matBigClasses": [],
    "schemeClass": "",
    "agentId": 100123,
    "languageType": "zh-cn"
}

Detail URL pattern:
  https://sp.iccec.cn/viewNoticeDetail?schemeId={schemeId}&schemeCode={schemeCode}
"""
import re
from datetime import datetime
from typing import Optional

import httpx

from src.scraper.scrapling_base import ScraplingScraper, TenderItem

BASE = "https://sp.iccec.cn"
SEARCH_URL = f"{BASE}/apis/sp/bidc/users/signup/searchSupNoticeNew"
PAGE_SIZE = 10
MAX_PAGES = 5

SKIP_NOTICE_STATUSES = {"4", "5", "6"}


class IccecScraper(ScraplingScraper):

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
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": f"{BASE}/",
        }

        try:
            with httpx.Client(headers=headers, timeout=25, verify=False) as client:
                for page_no in range(1, MAX_PAGES + 1):
                    body = {
                        "pageNo": page_no,
                        "pageSize": PAGE_SIZE,
                        "noticeTitle": "",
                        "schemeName": keyword,
                        "sortName": "1",
                        "sortOrder": "0",
                        "supCodeList": [],
                        "purchaseCategory": "",
                        "purchaseType": [],
                        "purchaseClassList": [],
                        "matBigClasses": [],
                        "schemeClass": "",
                        "agentId": 100123,
                        "languageType": "zh-cn",
                    }
                    r = client.post(SEARCH_URL, json=body)
                    if r.status_code != 200:
                        break
                    data = r.json()
                    if data.get("code") != "0":
                        break
                    rows = data.get("data", {}).get("rows", [])
                    if not rows:
                        break

                    page_new = 0
                    for row in rows:
                        notice_id = str(row.get("noticeId", ""))
                        if notice_id in seen_ids:
                            continue
                        seen_ids.add(notice_id)

                        notice_status = str(row.get("noticeStatus", ""))
                        if notice_status in SKIP_NOTICE_STATUSES:
                            continue

                        title = (row.get("noticeTitle") or "").strip()
                        if not title:
                            continue

                        notice_title_lower = title
                        skip_words = ["中标", "成交结果", "候选人公示", "结果公示", "流标",
                                      "废标", "终止公告", "评标结果", "采购预告", "事前公示",
                                      "意向公示", "需求公示", "前期公示", "计划公示", "采购意向"]
                        if any(w in notice_title_lower for w in skip_words):
                            continue

                        scheme_id = str(row.get("schemeId", ""))
                        scheme_code = row.get("schemeCode", "")
                        link = f"{BASE}/viewNoticeDetail?schemeId={scheme_id}&schemeCode={scheme_code}" if scheme_id else ""

                        bidder = (row.get("opUnitName") or "").strip()
                        if not bidder:
                            bidder = self._extract_bidder_from_title(title)

                        notice_start = row.get("noticeStartTime", "")
                        date_str = notice_start[:10] if notice_start else ""

                        first_round_end = row.get("firstRoundEndTime") or ""
                        deadline = first_round_end[:16].replace("T", " ") if first_round_end and first_round_end not in ("null", "") else ""

                        purchase_type_name = row.get("purchaseTypeName", "")

                        items.append(TenderItem(
                            date=date_str,
                            category=category,
                            project_name=title,
                            link=link,
                            source_site=self.site_name,
                            bidder=bidder,
                            deadline=deadline,
                            bid_time="",
                            bid_count=self._extract_bid_count(title),
                            _obj_id=notice_id,
                        ))
                        page_new += 1

                    self.logger.info(f"iccec page {page_no}: {len(rows)} raw, {page_new} new items")

                    total = data.get("data", {}).get("recordsTotal", 0)
                    if page_no * PAGE_SIZE >= total:
                        break

                    if page_new == 0:
                        break

        except Exception as e:
            self.logger.error(f"iccec search API failed: {e}")
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
