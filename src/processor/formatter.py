from datetime import datetime
from src.scraper.base import TenderItem

PLATFORM_MAP = {
    "中国采购与招标网": "中国采购与招标网",
    "元博网": "元博网",
    "中国移动采购与招标网": "中国移动采购与招标网",
    "中国联通合作方门户": "中国联通合作方门户",
    "中国铁塔电子采购平台": "中国铁塔电子采购平台",
    "中国电信电子采购系统": "中国电信电子采购系统",
    "中国电信阳光采购网": "中国电信电子采购系统",
    "中国南方电网电子采购交易平台": "中国南方电网",
    "国家电网电子商务平台": "国家电网",
    "中核集团电子商务平台": "中核集团",
    "四川招投标网": "四川招投标网",
}


def _now_timestamp() -> int:
    return int(datetime.now().timestamp() * 1000)


def _to_number(val) -> float:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def format_for_feishu(items: list[TenderItem]) -> list[dict]:
    total = len(items)
    records = []
    for idx, item in enumerate(items):
        seq = total - idx

        if item.link and item.project_name:
            project_field = {"link": item.link, "text": item.project_name}
        elif item.project_name:
            project_field = item.project_name
        else:
            project_field = ""

        platform = PLATFORM_MAP.get(item.source_site, item.source_site) if item.source_site else None

        record = {
            "项目名称": project_field,
            "添加时间": _now_timestamp(),
            "序号": seq,
            "项目类目": item.category,
            "招标单位": item.bidder if item.bidder else "",
            "投标平台": platform,
            "招标次数": item.bid_count if item.bid_count else "第一次",
            "报名截止时间": item.deadline if item.deadline else "",
            "投标时间": item.bid_time if item.bid_time else "",
            "预算(万)": _to_number(item.budget),
            "标书价格": item.doc_price if item.doc_price else "",
        }
        records.append(record)
    return records
