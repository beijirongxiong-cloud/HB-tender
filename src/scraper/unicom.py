"""China Unicom Bidding - API-based scraper with list-first filtering."""
import re
import ssl
from datetime import datetime
from typing import Optional
from urllib.parse import quote

import httpx

from src.scraper.scrapling_base import ScraplingScraper, TenderItem


class UnicomScraper(ScraplingScraper):
    BASE = "https://www.chinaunicombidding.cn"
    LIST_API = "/api/v1/bizAnno/getAnnoList"
    DETAIL_API = "/api/v1/bizAnno/getAnnoDetailed"
    ANNO_TYPE_BID = "011002"
    VALID_ANNO_TYPES = {"011002", "011001"}  # 011002=采购公告, 011001=招标公告
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
            "Accept": "application/json",
            "Referer": f"{self.BASE}/bidInformation?wd={quote(keyword)}",
            "Origin": self.BASE,
        }

        try:
            with httpx.Client(verify=self._get_ssl_ctx(), headers=headers, timeout=30) as client:
                seen_ids = set()
                page = 1
                while page <= 10:
                    body = {
                        "pageNo": page,
                        "pageSize": 20,
                        "modeNo": "BizAnnoVoMtable",
                        "annoName": keyword,
                        "annoTypeId": "",
                    }
                    r = client.post(f"{self.BASE}{self.LIST_API}", json=body)
                    r.raise_for_status()
                    data = r.json()

                    if data.get("code") != 200:
                        break

                    records = data.get("data", {}).get("records", [])
                    if not records:
                        break

                    for rec in records:
                        rid = str(rec.get("id", ""))
                        if rid in seen_ids:
                            continue
                        seen_ids.add(rid)

                        anno_name = rec.get("annoName", "").strip()
                        anno_type_id = rec.get("annoTypeId", "")
                        anno_type = rec.get("annoType", "")
                        # Client-side filter: only keep 采购公告/招标公告 (skip 结果/变更/终止)
                        if anno_type_id not in self.VALID_ANNO_TYPES and anno_type not in ("采购公告", "招标公告"):
                            continue

                        bid_company = rec.get("bidCompany", "").strip()
                        create_date = rec.get("createDate", "")[:10]
                        tender_end = rec.get("tenderEndDate", "")
                        reply_end = rec.get("replyEndTime", "")
                        bid_no = rec.get("bidNo", "")
                        procurement_type = rec.get("procurementType", "")
                        province = rec.get("provinceName", "")

                        if keyword and keyword not in anno_name:
                            continue

                        bidder = bid_company or self._extract_bidder_from_title(anno_name)
                        deadline = self._format_datetime(tender_end) if tender_end else ""
                        bid_time = self._format_datetime(reply_end) if reply_end else ""

                        item = TenderItem(
                            date=create_date or datetime.now().strftime("%Y-%m-%d"),
                            category=category,
                            project_name=anno_name,
                            link=f"{self.BASE}/bidInformation/detail?id={rid}",
                            source_site=self.site_name,
                            bidder=bidder,
                            deadline=deadline,
                            bid_time=bid_time,
                            bid_count=self._extract_bid_count(anno_name),
                        )
                        items.append(item)

                    total_pages = data.get("data", {}).get("pages", 1)
                    if page >= total_pages:
                        break
                    page += 1

                    if len(items) >= 50:
                        break

                filtered_items = self._keyword_prefilter(items)
                if filtered_items:
                    self._fetch_details(client, filtered_items)

        except Exception as e:
            self.logger.error(f"Unicom API failed: {e}")
        return items

    def _keyword_prefilter(self, items: list[TenderItem]) -> list[TenderItem]:
        return [it for it in items if it.project_name and len(it.project_name) >= 5]

    def _fetch_details(self, client: httpx.Client, items: list[TenderItem]) -> None:
        for item in items:
            try:
                ann_id = item.link.split("id=")[-1] if "id=" in item.link else ""
                if not ann_id:
                    continue

                r = client.get(f"{self.BASE}{self.DETAIL_API}/{ann_id}")
                if r.status_code != 200:
                    continue

                data = r.json()
                if data.get("code") != 200:
                    continue

                detail = data.get("data", {})
                anno_text = detail.get("annoText", "")

                if anno_text:
                    if not item.bidder or len(item.bidder) < 4:
                        db = self._extract_bidder_from_html(anno_text)
                        if db:
                            item.bidder = db

                    if not item.deadline:
                        dl = self._extract_deadline(anno_text)
                        if dl:
                            item.deadline = dl

                    if not item.bid_time:
                        bt = self._extract_bid_time(anno_text)
                        if bt:
                            item.bid_time = bt

                    budget = self._extract_budget(anno_text)
                    if budget:
                        item.budget = budget

                    doc_price = self._extract_doc_price(anno_text)
                    if doc_price:
                        item.doc_price = doc_price
            except Exception:
                continue

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
            r'招\s*募\s*人[:：\s]*([^\s<,，。；;且与和]{4,30}?)(?:\s|<|，|,|；|;|及|和|与|$)',
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
            r'购买[^<]{0,6}截止[^<]{0,10}[:：\s]*(\d{4}[-年/]\d{1,2}[-月/]\d{1,2}[^<\d]{0,10}\d{0,2}[时:点]?\d{0,2}[分:]?\d{0,2})',
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
                val = val.strip('-.:')
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
                val = val.strip('-.:')
                return val
        return ""

    @staticmethod
    def _extract_budget(html: str) -> str:
        for pattern in [
            r'(?:预算|预算金额|项目预算|采购金额|最高投标限价)[：:（(]\s*[¥￥]?\s*(\d+\.?\d*)\s*万?元?',
            r'[¥￥]\s*(\d+\.?\d*)\s*万?元',
        ]:
            m = re.search(pattern, html)
            if m:
                return m.group(1)
        return ""

    @staticmethod
    def _extract_doc_price(html: str) -> str:
        m = re.search(r'(?:标书|招标文件|招募文件)[售价价格]*[：:]\s*[¥￥]?\s*(\d+\.?\d*)\s*元', html)
        if m:
            return m.group(0)
        return ""
