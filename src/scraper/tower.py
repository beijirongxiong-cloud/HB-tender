"""Tower scraper - 中国铁塔电子采购平台, optimized: filter before detail fetch."""
from datetime import datetime, timedelta
from typing import Optional
import json
import httpx
import re

from src.scraper.scrapling_base import ScraplingScraper, TenderItem


class TowerScraper(ScraplingScraper):
    BASE = "https://ebid.chinatowercom.cn"
    PN = "/epointwebbuilder_zgtt"
    SITEGUID = "7eb5f7f1-9041-43ad-8e13-8fcb82ea831a"
    CLIENT_ID = "5223ad48-09b8-4839-8a6b-cb733d0d3468"
    SINCE_DAYS = 1

    # 003001=招标/比选公告, 003002=变更公告
    VALID_CATEGORIES = ["003001", "003002"]

    async def run(self, keywords_by_category: dict[str, list[str]], since=None) -> list[TenderItem]:
        since = datetime.now() - timedelta(days=self.SINCE_DAYS)
        return await super().run(keywords_by_category, since)

    def _get_token(self, client: httpx.Client) -> str:
        client.post(f"{self.PN}/rest/getOauthInfoAction/getAppInfo", data={"params": "{}"})
        r = client.post(
            f"{self.PN}/rest/getOauthInfoAction/getNoUserAccessToken",
            data={"params": json.dumps({"client_id": self.CLIENT_ID})},
        )
        return r.json()["custom"]["access_token"]

    @staticmethod
    def _extract_bidder_from_title(title: str) -> str:
        t = title.strip()
        t = re.sub(r'^\d{4}\s*年?\s*[-~至]\s*\d{4}\s*年?\s*', '', t)
        t = re.sub(r'^\d{4}\s*年\s*', '', t)
        t = re.sub(r'^\[.*?\]\s*', '', t)
        m = re.match(r'^([\u4e00-\u9fa5（）()]+(?:公司|集团|分局|中心|研究院|研究所|局|院|处|部|厅|委|办|站|所|学校|医院|协会|基金会|分公司|信息|科技|大学))', t)
        if m:
            name = m.group(1)
            if len(name) >= 4:
                return name
        m = re.match(r'^(.{2,30}?)(?:\d{4}年|\d{4}[-/])', t)
        if m:
            name = m.group(1).rstrip('的')
            if len(name) >= 2:
                return name
        return ""

    @staticmethod
    def _extract_bidder_from_html(text: str) -> str:
        for pattern in [
            r'采\s*购\s*人[:：\s]*(?:为\s*)?([\u4e00-\u9fa5（）()]{4,60}(?:公司|集团|局|院|中心|部|办))',
            r'招\s*标\s*人[:：\s]*(?:为\s*)?([\u4e00-\u9fa5（）()]{4,60}(?:公司|集团|局|院|中心|部|办))',
            r'采\s*购\s*单\s*位[:：\s]*(?:为\s*)?([\u4e00-\u9fa5（）()]{4,60}(?:公司|集团|局|院|中心|部|办))',
            r'招\s*标\s*单\s*位[:：\s]*(?:为\s*)?([\u4e00-\u9fa5（）()]{4,60}(?:公司|集团|局|院|中心|部|办))',
            r'采\s*购\s*人[:：\s]*(?:为\s*)?【\s*([\u4e00-\u9fa5（）()]{4,60}?)\s*】',
            r'招\s*标\s*人[:：\s]*(?:为\s*)?【\s*([\u4e00-\u9fa5（）()]{4,60}?)\s*】',
        ]:
            m = re.search(pattern, text)
            if m:
                val = m.group(1).strip()
                if val and val not in ('不具有独立法人资格的附属机构', '附属机构', '代理机构', '采购代理机构'):
                    if len(val) >= 4:
                        return val
        return ""

    @staticmethod
    def _clean_html_text(content: str) -> str:
        text = re.sub(r'<[^>]+>', ' ', content)
        text = re.sub(r'\s+', ' ', text).strip()
        # Merge digits/commas/dots split across HTML tags: "18 . 37" -> "18.37", "124, 399" -> "124,399"
        text = re.sub(r'([\d.,])\s+(?=[\d.])', r'\1', text)
        # Merge Chinese characters split across HTML tags: "预 估含税 金额" -> "预估含税金额"
        text = re.sub(r'([\u4e00-\u9fa5])\s+(?=[\u4e00-\u9fa5])', r'\1', text)
        return text

    @staticmethod
    def _normalize_datetime(val: str) -> str:
        val = re.sub(r'\s+', '', val)
        val = re.sub(r'[年月]', '-', val)
        val = re.sub(r'[日号]', ' ', val)
        val = re.sub(r'[时点]', ':', val)
        val = re.sub(r'分', '', val)
        val = re.sub(r'\s+', ' ', val)
        val = re.sub(r'-\s*-', '-', val)
        val = val.strip('-.: ')
        if val and not val.startswith('1900'):
            return val
        return ""

    @staticmethod
    def _extract_deadline(text: str) -> str:
        for pattern in [
            r'应答文件递交截止时间[^为]*?为[：:\s]*【?\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*\d{0,2}\s*[时:]\s*\d{0,2}\s*分?)',
            r'响应文件递交截止时间[^为]*?为[：:\s]*【?\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*\d{0,2}\s*[时:]\s*\d{0,2}\s*分?)',
            r'递交截止时间[^为]*?为[：:\s]*【?\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*\d{0,2}\s*[时:]\s*\d{0,2}\s*分?)',
            r'应答截止时间[^为]*?为[：:\s]*【?\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*\d{0,2}\s*[时:]\s*\d{0,2}\s*分?)',
            r'报名[^<]{0,10}截止[^<]{0,10}[:：\s]*(\d{4}\s*[-年/]\s*\d{1,2}\s*[-月/]\s*\d{1,2}[^<\d]{0,10}\d{0,2}\s*[时:点]?\s*\d{0,2})',
        ]:
            m = re.search(pattern, text)
            if m:
                val = TowerScraper._normalize_datetime(m.group(1).strip())
                if val:
                    return val
        return ""

    @staticmethod
    def _extract_bid_time(text: str) -> str:
        for pattern in [
            r'开标[^<]{0,10}时间[:：\s]*(\d{4}\s*[-年/]\s*\d{1,2}\s*[-月/]\s*\d{1,2}[^<\d]{0,10}\d{0,2}\s*[时:点]?\s*\d{0,2})',
            r'公开开标[^<]{0,10}[:：\s]*(\d{4}\s*[-年/]\s*\d{1,2}\s*[-月/]\s*\d{1,2}[^<\d]{0,10}\d{0,2}\s*[时:点]?\s*\d{0,2})',
        ]:
            m = re.search(pattern, text)
            if m:
                val = TowerScraper._normalize_datetime(m.group(1).strip())
                if val:
                    return val
        return ""

    @staticmethod
    def _extract_budget(text: str) -> str:
        patterns = [
            # 采购预算含税金额为 XXX万元
            (r'采购预算含税金额为\s*([\d,]+\.?\d*)\s*万元', 'wan'),
            # 采购预算含税总价为 XXX元 / 采购预算含税总价 XXX元
            (r'采购预算含税总价[为\s]*([\d,]+\.?\d*)\s*元', 'yuan'),
            # 采购预算金额: XXX万元
            (r'采购预算金额[：:\s]*[^万]*?([\d,]+\.?\d*)\s*万元', 'wan'),
            # 含税预算金额 XXX万元 / 含税预算金额约XXX万元
            (r'含税预算金额[约\s]*([\d,]+\.?\d*)\s*万元', 'wan'),
            # 不含税预算金额 XXX万元
            (r'不含税预算金额\s*([\d,]+\.?\d*)\s*万元', 'wan'),
            # 项目预算：含税预算金额约XXX万元
            (r'项目预算[：:]\s*含税预算金额约?([\d,]+\.?\d*)\s*万元', 'wan'),
            # 预估含税总金额 XXX元
            (r'预估含税总金额\s*([\d,]+\.?\d*)\s*元', 'yuan'),
            # 预估不含税总金额 XXX元
            (r'预估不含税总金额\s*([\d,]+\.?\d*)\s*元', 'yuan'),
            # 预估含税金额 XXX元
            (r'预估含税金额\s*([\d,]+\.?\d*)\s*元', 'yuan'),
            # 预估不含税金额 XXX元
            (r'预估不含税金额\s*([\d,]+\.?\d*)\s*元', 'yuan'),
            # 含税金额 XXX元
            (r'含税金额\s*([\d,]+\.?\d*)\s*元', 'yuan'),
            # 预估含税总价 XXX元
            (r'预估含税总价\s*([\d,]+\.?\d*)\s*元', 'yuan'),
            # 项目预估规模： XXX万元
            (r'项目预估规模[：:\s]*([\d,]+\.?\d*)\s*万元', 'wan'),
            # 项目预估规模 XXX万 (without 元)
            (r'项目预估规模[：:\s]*([\d,]+\.?\d*)\s*万', 'wan'),
            # 预估 XXX万元
            (r'预估[^<]{0,20}?([\d,]+\.?\d*)\s*万元', 'wan'),
            # 预算 XXX万元
            (r'预算[^<]{0,20}?([\d,]+\.?\d*)\s*万元', 'wan'),
            # 最高限价 XXX万元
            (r'最高限价[^<]{0,30}?([\d,]+\.?\d*)\s*万元', 'wan'),
            # 不含税总价 XXX元
            (r'不含税总价[：:\s]*([\d,]+\.?\d*)\s*元', 'yuan'),
            # 含税总价 XXX元
            (r'含税总价[：:\s]*([\d,]+\.?\d*)\s*元', 'yuan'),
        ]
        for pattern, unit in patterns:
            m = re.search(pattern, text)
            if m:
                val = m.group(1).replace(',', '')
                try:
                    num = float(val)
                except ValueError:
                    continue
                if unit == 'yuan':
                    return str(round(num / 10000, 4))
                return str(round(num, 4))
        return ""

    @staticmethod
    def _extract_doc_price(text: str) -> str:
        for pattern in [
            # 售价 XXX元 / 每套售价 XXX元 / 本项目售价 XXX元 (exclude CA证书售价 via lookbehind)
            r'(?<!证书)售价\s*【?\s*(\d+[\.\d]*)\s*】?\s*元',
            # 采购文件售价：XXX元 (simple format)
            r'采购文件售价[：:\s]*(\d+[\.\d]*)\s*元',
            r'招标文件售价[：:\s]*(\d+[\.\d]*)\s*元',
            r'比选文件售价[：:\s]*(\d+[\.\d]*)\s*元',
            r'询价文件售价[：:\s]*(\d+[\.\d]*)\s*元',
            # 文件售价人民币【叁佰元整】（￥ 300.00元）
            r'￥\s*(\d+[\.\d]*)\s*元',
        ]:
            m = re.search(pattern, text)
            if m:
                return m.group(1)
        return ""

    @staticmethod
    def _keyword_matches(title: str, keyword: str) -> bool:
        parts = [p.strip() for p in keyword.split("/") if len(p.strip()) >= 2]
        if not parts:
            parts = [keyword]
        return any(p in title for p in parts)

    @staticmethod
    def _simplify_keyword(keyword: str) -> str:
        parts = [p.strip() for p in keyword.split("/") if len(p.strip()) >= 2]
        if not parts:
            parts = [keyword]
        return parts[0][:2] if parts[0] and len(parts[0]) > 2 else parts[0]

    def _do_search(self, fetcher, keyword: str, category: str) -> list[TenderItem]:
        items: list[TenderItem] = []
        headers = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}
        api_keyword = self._simplify_keyword(keyword)
        try:
            with httpx.Client(verify=False, timeout=30, base_url=self.BASE, headers=headers) as client:
                token = self._get_token(client)
                auth_headers = {"Authorization": f"Bearer {token}"}
                seen_ids = set()

                for cat in self.VALID_CATEGORIES:
                    for page_idx in range(1, 11):
                        payload = {
                            "siteGuid": self.SITEGUID,
                            "title": api_keyword,
                            "categorynum": cat,
                            "beginDate": "",
                            "toDate": "",
                            "infostatuscode": "",
                            "pageIndex": str(page_idx),
                            "pageSize": "15",
                        }
                        r = client.post(
                            f"{self.PN}/rest/frontAppNotNeedLoginAction/getWebInfoList",
                            data={"params": json.dumps(payload)},
                            headers=auth_headers,
                        )
                        if r.status_code != 200:
                            break
                        data = r.json()
                        if data.get("status", {}).get("code") != 1:
                            break

                        page_items = data.get("custom", {}).get("data", [])
                        if not page_items:
                            break

                        for it in page_items:
                            info_id = it.get("infoid", "")
                            if info_id in seen_ids:
                                continue
                            seen_ids.add(info_id)

                            title = it.get("title", "").strip()
                            if not self._keyword_matches(title, api_keyword):
                                continue

                            date_str = it.get("infodate", "")[:10]
                            date_compact = date_str.replace("-", "")
                            bidder = self._extract_bidder_from_title(title)

                            deadline = ""
                            bid_time = ""
                            budget = ""
                            doc_price = ""
                            if cat == "003001":
                                try:
                                    detail_payload = {
                                        "siteGuid": self.SITEGUID,
                                        "infoid": info_id,
                                    }
                                    dr = client.post(
                                        f"{self.PN}/rest/frontAppNotNeedLoginAction/getOneInformation",
                                        data={"params": json.dumps(detail_payload)},
                                        headers=auth_headers,
                                    )
                                    if dr.status_code == 200:
                                        ddata = dr.json()
                                        if ddata.get("status", {}).get("code") == 1:
                                            info = ddata.get("custom", {}).get("info", {})
                                            content = info.get("infocontent", "")
                                            if content:
                                                text = self._clean_html_text(content)
                                                detail_bidder = self._extract_bidder_from_html(text)
                                                if detail_bidder and len(detail_bidder) > len(bidder):
                                                    bidder = detail_bidder
                                                deadline = self._extract_deadline(text)
                                                bid_time = self._extract_bid_time(text)
                                                budget = self._extract_budget(text)
                                                doc_price = self._extract_doc_price(text)
                                except Exception:
                                    pass

                            items.append(TenderItem(
                                date=date_str,
                                category=category,
                                project_name=title,
                                link=f"{self.BASE}/zgtt/gggs/{cat}/{date_compact}/{info_id}.html",
                                source_site=self.site_name,
                                bidder=bidder,
                                deadline=deadline,
                                bid_time=bid_time,
                                budget=budget,
                                doc_price=doc_price,
                                bid_count=self._extract_bid_count(title),
                            ))

                        total_pages = data.get("custom", {}).get("totalPages", 1)
                        if page_idx >= total_pages:
                            break

                    if len(items) >= 50:
                        break

                self.logger.info(f"Tower: keyword=[{keyword}] found {len(items)} items after filter")
        except Exception as e:
            self.logger.error(f"Tower API failed: {e}")
        return items[:50]
