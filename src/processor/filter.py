import re
import yaml
from src.scraper.base import TenderItem
from src.utils.logger import setup_logger

logger = setup_logger("filter")


def load_blacklist(config_path: str = "config/keywords.yaml") -> dict[str, list[str]]:
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config.get("blacklist", {})


def apply_blacklist(items: list[TenderItem], blacklist: dict[str, list[str]]) -> list[TenderItem]:
    filtered = []
    for item in items:
        if item.category in blacklist:
            keywords = blacklist[item.category]
            combined_text = (item.bidder + item.project_name).lower()
            blacklisted = False
            for rule in keywords:
                words = [w.strip().lower() for w in rule.split() if w.strip()]
                if words and all(w in combined_text for w in words):
                    logger.info(f"Blacklisted: [{item.category}] {item.project_name} (rule: {rule})")
                    blacklisted = True
                    break
            if blacklisted:
                continue
        filtered.append(item)
    return filtered


_NEGATIVE_CONTEXT = [
    '工程造价', '造价咨询', '技术咨询服务', '环评', '环境影响评价',
    '勘察设计', '工程监理', '施工图审查', '招标代理', '工程检测',
    '工程质量', '安全评价', '节能评估', '水文监测', '气象监测',
    '污染防治', '污染治理', '污水处理', '供水管网', '排水管网',
    '道路工程', '公路工程', '桥梁工程', '隧道工程', '水利工程',
    '电力工程', '输变电', '配电工程', '发电厂', '变电站',
    '医院设备', '医疗器械', '诊疗能力提升', '医疗服务能力提升',
    '卫生服务能力', '公共卫生服务', '医疗设备采购',
    '实验室能力提升', '实验室仪器', '检测能力提升',
    '监测能力提升', '监管能力提升', '执法能力提升',
    '信息化能力提升', '系统研发', '软件开发', '平台建设',
    '通信工程', '基站建设', '网络建设', '信息化建设',
    '耕地保护', '土地整治', '农田建设', '高标准农田',
    '地质灾害', '防震减灾', '应急能力', '防灾减灾',
    '消防工程', '消防设施', '灭火器', '消防站',
    '学校建设', '教学楼', '校舍', '幼儿园建设',
    '养老机构', '养老院建设', '社会福利',
    '粮油仓储', '粮食储备', '储备库',
    '供电能力提升', '供电工程', '电网改造', '输电线路',
    '管道工程', '管网改造', '供水能力', '供热管网',
    '物业服务', '物业管理', '保洁服务', '保安服务',
    '打印复印', '办公用品', '办公家具', '服装采购',
    '车辆采购', '汽车租赁', '餐饮服务', '食堂服务',
    '绿化养护', '园林工程', '路灯', '照明工程',
    '房屋修缮', '装修工程', '防水工程', '保温工程',
    '钢材', '水泥', '混凝土', '管材', '电缆', '变压器',
    '档案整理', '档案数字化', '档案管理',
    '制作', '影像服务', '拍摄', '物料', '视频宣传',
    '广告制作', '策划及执行', '策划执行',
    '环保管理', '风电基建', '油气',
    '系统运营维护', '系统运维', '运维服务',
    '税务咨询', '税务风险', 'ISO体系', 'ISO认证',
    '证件培训', '操作员培训', '技能培训', '资格证',
    '教师素质提升', '教师培训', '校长培训',
    '单一来源', '直接采购公示', '预采购',
]

_POSITIVE_OVERRIDE = [
    '管理咨询', '企业管理咨询', '人力资源管理', '薪酬体系',
    '薪酬绩效', '绩效体系设计', '绩效管理咨询', '企业文化咨询',
    '企业文化体系', '企业文化建设', '企业文化宣传', '企业文化中心',
    '组织管控', '定岗定编', '人才盘点', '人才标准',
    '内训师', '培训服务采购', '培训服务项目', '培训供应商',
    '培训框架协议', '入职培训服务', '新员工入职培训服务',
    '党员培训服务', '党建培训服务', '干部培训服务',
    '中层管理培训', '班组长培训', '管理能力提升培训',
    '战略解码', '流程优化咨询', '制度体系优化', '内控合规咨询',
    '品牌形象设计', '视觉识别系统', '融媒体服务', '宣传策划服务',
    '管理提升咨询', '管理诊断咨询', '胜任力模型', '后备人才培养',
    '储备干部培训', '校招新员工培训', '营销培训服务', '销售技能培训',
    '数字化转型培训', '数字化转型咨询',     '绩效系统采购', '绩效平台开发',
    '绩效软件采购', '绩效管理系统', '组织绩效管理',
]


def apply_keyword_strict_filter(items: list[TenderItem], keywords_by_category: dict[str, list[str]]) -> list[TenderItem]:
    all_keywords = set()
    for cat, kws in keywords_by_category.items():
        for kw in kws:
            parts = [p.strip() for p in kw.split("/") if len(p.strip()) >= 2]
            if not parts:
                parts = [kw]
            all_keywords.update(parts)

    filtered = []
    for item in items:
        title = item.project_name or ""
        project_part = _extract_project_part(title)

        has_positive = any(kw in title for kw in _POSITIVE_OVERRIDE)
        if has_positive:
            filtered.append(item)
            continue

        has_keyword = any(kw in project_part for kw in all_keywords)
        if not has_keyword:
            logger.info(f"Keyword filtered: {title[:60]}")
            continue

        has_negative = any(neg in title for neg in _NEGATIVE_CONTEXT)
        if has_negative:
            logger.info(f"Negative context filtered: {title[:60]}")
            continue

        filtered.append(item)
    return filtered


def _extract_project_part(title: str) -> str:
    m = re.match(r'^([\u4e00-\u9fa5]+(?:公司|集团|分局|中心|研究院|研究所|局|院|处|部|厅|委|办|站|所|学校|医院|协会|基金会))', title)
    if m:
        return title[m.end():]
    m = re.match(r'^(.{2,25}?)(?:\d{4}年|\d{4}[-/])', title)
    if m:
        return title[m.end():]
    return title


_BID_RESULT_TITLE_KEYWORDS = [
    '中标', '成交结果', '结果公告', '候选人公示', '中标候选人',
    '中标公示', '成交公示', '结果公示', '中标通知', '废标',
    '流标', '终止招标', '招标终止', '撤销招标', '更正公告',
    '变更公告', '终止公告', '合同公告', '合同公示', '履约验收',
    '中标结果', '评标结果', '定标', '签约', '成交供应商',
    '预中标', '拟中标', '成交候选人',
]

_PRE_NOTICE_TITLE_KEYWORDS = [
    '采购预告', '事前公示', '意向公示', '需求公示',
    '前期公示', '计划公示', '采购意向', '招标预告',
]


def apply_bid_result_filter(items: list[TenderItem]) -> list[TenderItem]:
    """筛除投标结果(中标公示)和非招标公告，只保留正在招标的项目。"""
    filtered = []
    for item in items:
        title = item.project_name or ""

        if any(kw in title for kw in _BID_RESULT_TITLE_KEYWORDS):
            logger.info(f"Bid result filtered (title): {title[:60]}")
            continue

        if any(kw in title for kw in _PRE_NOTICE_TITLE_KEYWORDS):
            logger.info(f"Pre-notice filtered (title): {title[:60]}")
            continue

        filtered.append(item)
    return filtered
