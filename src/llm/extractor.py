import asyncio
import os
import re

from src.scraper.base import TenderItem
from src.llm.client import LLMClient, LLMError
from src.utils.logger import setup_logger

logger = setup_logger("llm.extractor")

SYSTEM_PROMPT = """你是招标公告信息提取助手。从招标公告正文中提取以下字段，返回JSON。
字段说明：
- is_bid_announcement: 该项目是否为"招标公告"（仅保留正在招标的项目）
  - true: 招标公告、采购公告、采购项目公告、竞争性磋商公告、竞争性谈判公告、询价公告、询比公告、比选公告、征集公告、征集意见公告、寻源公告、资格预审公告、入围公告、框架采购公告等（项目尚未开标，尚可投标或提出意见）
  - false: 中标公告、成交公告、中标候选人公示、评标结果公示、招标失败公告、废标公告、流标公告、终止公告、更正公告、合同公告、合同公示、履约验收等
  - false: 采购预告、事前公示、意向公示、需求公示、前期公示、计划公示、采购意向等仅为预告性质的公告（不是正式招标，无法投标）
- bidder: 招标单位/招标人/采购人/发布单位（机构全称）
- budget: 项目预算，统一换算为"万元"单位的纯数字（如"50万"→50，"100万元"→100，"500000元"→50）
- deadline: 报名截止时间（格式 YYYY-MM-DD HH:MM，无则空）
- bid_time: 投标/开标时间（格式 YYYY-MM-DD HH:MM，无则空）
- doc_price: 标书售价（格式"XXX元"，无则空）
- bid_count: 招标次数（第一次/第二次/第三次/第四次，无法判断则"第一次"）

规则：
- 只提取正文中明确出现的信息，找不到的字段填空字符串
- 不要编造或推测
- budget 必须是纯数字（万元），无预算信息填空
- is_bid_announcement 必须严格判断：只有项目尚在招标阶段（可投标）才为true，其余一律false
- 采购预告/事前公示/意向公示/需求公示/计划公示等预告性质的公告，is_bid_announcement应为false
- 注意：标题含"改造""建设"但内容为企业文化/培训/咨询的，is_bid_announcement应为true"""


class LLMExtractor:
    MAX_CONCURRENT = 5
    MAX_TEXT_LENGTH = 4000

    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def extract(self, item: TenderItem, page_text: str) -> TenderItem | None:
        # When no detail text is available, skip is_bid_announcement check
        # (the item already passed LLM screener, so it's relevant)
        if not page_text or len(page_text.strip()) < 20:
            return item

        truncated = page_text[: self.MAX_TEXT_LENGTH]
        model = os.getenv("GPT_EXTRACT_MODEL", "gpt-4o") if os.getenv("GPT_API_KEY") else os.getenv("VOLC_EXTRACT_MODEL", "deepseek-v4-flash")
        try:
            data = await self.llm.chat_json(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"招标公告正文：\n{truncated}\n\n请提取字段，返回JSON。"},
                ],
                model=model,
            )
            if data.get("is_bid_announcement") is False:
                logger.info(f"Non-bid announcement filtered: {item.project_name[:60]}")
                return None
            return self._apply_result(item, data)
        except LLMError as e:
            logger.error(f"LLM extract failed for {item.project_name[:40]}, fallback to regex: {e}")
            return self._regex_fallback(item, page_text)

    async def extract_batch(
        self, items_with_text: list[tuple[TenderItem, str]]
    ) -> list[TenderItem]:
        sem = asyncio.Semaphore(self.MAX_CONCURRENT)

        async def one(item, text):
            async with sem:
                return await self.extract(item, text)

        results = await asyncio.gather(*[one(i, t) for i, t in items_with_text])
        passed = [r for r in results if r is not None]
        filtered_count = len(results) - len(passed)
        if filtered_count:
            logger.info(f"LLM extract: filtered {filtered_count} non-bid announcements")
        return passed

    def _apply_result(self, item: TenderItem, data: dict) -> TenderItem:
        if data.get("bidder"):
            item.bidder = data["bidder"]
        if data.get("budget"):
            item.budget = data["budget"]
        if data.get("deadline"):
            item.deadline = data["deadline"]
        if data.get("bid_time"):
            item.bid_time = data["bid_time"]
        if data.get("doc_price"):
            item.doc_price = data["doc_price"]
        if data.get("bid_count"):
            item.bid_count = data["bid_count"]
        return item

    @staticmethod
    def _regex_fallback(item: TenderItem, text: str) -> TenderItem:
        if not item.bidder:
            m = re.match(
                r'^([\u4e00-\u9fa5]+(?:公司|集团|分局|中心|研究院|研究所|局|院|处|部|厅|委|办|站|所|学校|医院|协会|基金会))',
                item.project_name or "",
            )
            if m:
                item.bidder = m.group(1)

        if not item.budget:
            bm = re.search(
                r'(预算|预算金额|项目预算|采购金额)[\uff1a:\uff08(]\s*[\u00a5\uffe5]?\s*([\d,]+\.?\d*)\s*万?\u5143?',
                text,
            )
            if bm:
                val = bm.group(2).replace(",", "")
                if "万" in bm.group(0):
                    item.budget = val
                else:
                    try:
                        item.budget = str(float(val) / 10000)
                    except ValueError:
                        item.budget = val

        if not item.deadline:
            dm = re.search(
                r'(报名|获取)[\s\S]{0,30}(截止|期限)[\s\S]{0,30}[：:]?\s*(\d{4})[年\-](\d{1,2})[月\-](\d{1,2})日?\s*(\d{1,2})[时:](\d{1,2})',
                text,
            )
            if dm:
                item.deadline = f"{dm.group(3)}-{dm.group(4).zfill(2)}-{dm.group(5).zfill(2)} {dm.group(6).zfill(2)}:{dm.group(7).zfill(2)}"

        if not item.deadline:
            dm2 = re.search(
                r'截止时间[：:]\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*(\d{1,2}):(\d{2})',
                text,
            )
            if dm2:
                item.deadline = f"{dm2.group(1)}-{dm2.group(2).zfill(2)}-{dm2.group(3).zfill(2)} {dm2.group(4).zfill(2)}:{dm2.group(5)}"

        if not item.bid_time:
            bm = re.search(
                r'开标时间[：:]?\s*(\d{4})[年\-](\d{1,2})[月\-](\d{1,2})日?\s*(\d{1,2})[时:](\d{1,2})',
                text,
            )
            if bm:
                item.bid_time = f"{bm.group(1)}-{bm.group(2).zfill(2)}-{bm.group(3).zfill(2)} {bm.group(4).zfill(2)}:{bm.group(5).zfill(2)}"

        if not item.bid_time:
            bm2 = re.search(
                r'开标时间[：:]\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*(\d{1,2}):(\d{2})',
                text,
            )
            if bm2:
                item.bid_time = f"{bm2.group(1)}-{bm2.group(2).zfill(2)}-{bm2.group(3).zfill(2)} {bm2.group(4).zfill(2)}:{bm2.group(5)}"

        if not item.bid_count:
            for pattern, val in [
                (r'第[四4]次', '第四次'),
                (r'第[三3]次', '第三次'),
                (r'第[二2]次', '第二次'),
            ]:
                if re.search(pattern, item.project_name or ""):
                    item.bid_count = val
                    break
            if not item.bid_count:
                item.bid_count = '第一次'

        return item
