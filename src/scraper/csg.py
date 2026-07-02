"""CSG scraper - 南方电网电子采购交易平台 with keyword search via Scrapling browser."""
import re
from datetime import datetime
from typing import Optional

import httpx

from src.scraper.scrapling_base import ScraplingScraper, TenderItem

BASE = "https://ecsg.com.cn"


class CsgScraper(ScraplingScraper):

    @property
    def supports_keyword_search(self) -> bool:
        return True

    def _do_search(self, fetcher, keyword: str, category: str) -> list[TenderItem]:
        """Use Scrapling browser to search CSG website with keyword."""
        items: list[TenderItem] = []
        seen_ids: set[str] = set()
        current_year = datetime.now().year

        def search_page(page):
            nonlocal items
            page_num = 1
            while True:
                url = f"{BASE}/cms/NoticeList.html?id=159&typeid=4&word={keyword}&seacrhDate=&page={page_num}"
                try:
                    page.goto(url, timeout=30000)
                    page.wait_for_timeout(3000)
                except Exception as e:
                    self.logger.warning(f"CSG page {page_num} failed: {e}")
                    break

                raw = page.evaluate(r"""() => {
                    const results = [];
                    const tbody = document.getElementById('noticeListTBody');
                    if (!tbody) return results;
                    tbody.querySelectorAll('tr').forEach(tr => {
                        const a = tr.querySelector('a[href*="NoticeDetail"]');
                        if (!a) return;
                        const href = a.getAttribute('href') || '';
                        const text = (a.textContent || '').trim();
                        if (text.length < 5) return;
                        let date = '';
                        const tds = tr.querySelectorAll('td');
                        tds.forEach(td => {
                            const m = (td.textContent || '').trim().match(/(\d{4}-\d{2}-\d{2})/);
                            if (m) date = m[1];
                        });
                        results.push({title: text, href, date});
                    });
                    return results;
                }""")

                if not raw:
                    break

                page_matched = 0
                for row in raw:
                    href = row.get("href", "")
                    obj_id = ""
                    if "objectId=" in href:
                        obj_id = href.split("objectId=")[1].split("&")[0]
                    if obj_id and obj_id in seen_ids:
                        continue
                    if obj_id:
                        seen_ids.add(obj_id)

                    title = row.get("title", "").strip()
                    # Skip result/failure announcements
                    skip_words = ["成交结果", "中标公告", "失败公告", "流标公告", "终止公告",
                                  "成交公告", "候选人公示", "结果公告", "中标候选人",
                                  "采购预告", "事前公示", "意向公示", "需求公示", "前期公示",
                                  "计划公示", "采购意向"]
                    if any(w in title for w in skip_words):
                        continue

                    # Skip old projects (title year < current year - 1)
                    year_matches = re.findall(r'(\d{4})年', title)
                    if year_matches:
                        min_year = min(int(y) for y in year_matches)
                        if min_year < current_year - 1:
                            continue

                    if href.startswith("/"):
                        href = BASE + href

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
                        _obj_id=obj_id,
                        _obj_type=1,
                    ))
                    page_matched += 1

                self.logger.info(f"CSG page {page_num}: {len(raw)} raw, {page_matched} matched")

                # Check if there are more pages
                has_next = page.evaluate("""() => {
                    const links = document.querySelectorAll('a');
                    return Array.from(links).some(a => a.textContent.includes('下一页'));
                }""")
                if not has_next:
                    break
                page_num += 1

        fetcher.fetch(
            f"{BASE}/cms/NoticeList.html?id=159&typeid=4&word={keyword}&seacrhDate=&page=1",
            headless=True,
            block_images=True,
            timeout=60000,
            page_action=search_page,
        )
        return items

    def _do_fetch_details(self, items: list[TenderItem]) -> list[TenderItem]:
        """Fetch detail via API for budget, deadline, etc."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": f"{BASE}/",
        }

        try:
            with httpx.Client(verify=False, headers=headers, timeout=30, follow_redirects=True) as client:
                for item in items:
                    obj_id = getattr(item, "_obj_id", "")
                    obj_type = str(getattr(item, "_obj_type", 1))
                    if not obj_id:
                        continue
                    try:
                        body = {"objectId": obj_id, "objectType": obj_type, "cahSwitch": True}
                        r = client.post(
                            f"{BASE}/api/tender/tendermanage/gatewayNoticeQueryController/getNotice",
                            json=body,
                        )
                        if r.status_code != 200:
                            continue
                        detail = r.json()
                        if not detail or not detail.get("noticeTitle"):
                            continue

                        # Set detail text for LLM extractor
                        content = detail.get("noticeContent", "")
                        if content:
                            text = re.sub(r'<[^>]+>', ' ', content)
                            text = re.sub(r'\s+', ' ', text).strip()
                            item._detail_text = text[:4000]

                            if not item.budget:
                                m = re.search(r'(?:预算|预算金额|项目预算|采购预算|最高限价)[：:（(]?\s*[¥￥]?\s*([\d,.]+)\s*万?元', text)
                                if m:
                                    item.budget = m.group(1)
                            if not item.deadline:
                                m = re.search(r'(?:报名|获取|递交)[^]{0,30}(?:截止|期限)[^]{0,30}[：:]?\s*(\d{4}[\-年/]\d{1,2}[\-月/]\d{1,2}[日]?\s*\d{1,2}[：:时]\d{1,2})', text)
                                if m:
                                    item.deadline = m.group(1)
                            if not item.bid_time:
                                m = re.search(r'开标[^]{0,20}时间[：:]?\s*(\d{4}[\-年/]\d{1,2}[\-月/]\d{1,2}[日]?\s*\d{1,2}[：:时]\d{1,2})', text)
                                if m:
                                    item.bid_time = m.group(1)

                        enroll_end = detail.get("enrollEndTime")
                        if enroll_end and isinstance(enroll_end, (int, float)) and enroll_end > 0:
                            if not item.deadline:
                                item.deadline = datetime.fromtimestamp(enroll_end / 1000).strftime("%Y-%m-%d %H:%M")

                        # Use publishTime if item has no date
                        if not item.date:
                            pub_ts = detail.get("publishTime")
                            if pub_ts and isinstance(pub_ts, (int, float)) and pub_ts > 0:
                                item.date = datetime.fromtimestamp(pub_ts / 1000).strftime("%Y-%m-%d")
                    except Exception as e:
                        self.logger.warning(f"CSG detail fetch failed for {obj_id}: {e}")
        except Exception as e:
            self.logger.error(f"CSG detail fetch error: {e}")
        return items

    @staticmethod
    def _extract_bidder_from_title(title: str) -> str:
        m = re.match(r'^([\u4e00-\u9fa5]+(?:公司|集团|分局|中心|研究院|研究所|局|院|处|部|厅|委|办|站|所|学校|医院|协会|基金会))', title)
        if m:
            return m.group(1)
        m = re.match(r'^(.{4,25}?)(?:\d{4}年|\d{4}[-/])', title)
        if m:
            return m.group(1).rstrip('的')
        return ""
