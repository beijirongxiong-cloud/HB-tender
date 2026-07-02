import asyncio

from src.scraper.base import TenderItem
from src.llm.client import LLMClient, LLMError
from src.processor.filter import apply_keyword_strict_filter, apply_blacklist
from src.utils.logger import setup_logger

logger = setup_logger("llm.screener")

SYSTEM_PROMPT = """你是招标项目筛选助手。海博智业是一家企业管理咨询公司，业务聚焦三类：
1. 咨询类：管理咨询、流程优化、企业文化、人力资源、薪酬绩效体系设计、组织管控、
   内部控制、内控合规、合规管理、制度体系优化、人才盘点、战略解码、品牌形象、职级薪酬、
   改革深化、视觉识别、融媒体、宣传服务
2. 培训类：员工培训、内训师、管理能力提升、团队拓展、AI赋能培训、
   党建培训、党员培训、干部培训、储备干部培训、中层管理培训、班组长培训、
   销售技能培训、营销培训、新员工培训、校招培训、数字化转型培训、教育培训、
   后备人才培训、党性教育培训
3. 绩效系统类：绩效管理系统/软件/平台的采购与开发

筛选规则：
- 只保留招标单位或项目内容属于上述三类的"招标公告"（非中标结果）
- 排除明显无关（如工程建设、物资采购、医疗器械、IT硬件采购等）
- 标题含"绩效"但实为"绩效工资发放/考核发放"等行政事务的，排除
- 注意：标题含"改造""建设""采购"但实际内容为企业文化/培训/咨询的，应保留
  例如"企业文化中心改造项目""企业文化建设综合服务采购项目"属于咨询类

保留例外（即使含排除关键词也保留）：
- 标题含"改造""建设"但同时含"企业文化""培训""咨询"的，保留
- 标题含"采购"但同时含"咨询""培训""管理"的，保留
- 标题含"影像""宣传""物料"但同时含"企业文化"的，保留

排除规则（仅限"绩效系统"类）：
- 当项目判定为"绩效系统"类时，若招标单位涉及银行/医院/医疗/诊所/卫生院，则排除
- 培训类、咨询类不受此限制（如医院内训师项目、银行管理咨询项目仍保留）

排除规则（政府事业单位培训）：
- 当项目判定为"培训"类时，若招标单位是政府机关、事业单位、行政机关（如各级行政局、厅、委、办、
  人民政府、财政局、教育局、人社局、卫健委、应急管理局、消防救援局/大队/支队等），则排除
- 判断依据：招标单位名称含"局""厅""委""办""处""科""署""所""站""中心"且不属于企业（不含"公司""集团"），
  或含"人民政府""政府""事业单位""机关""行政"等关键词的，应排除
- 企业单位（含"公司""集团""分公司""子公司""研究院"等）的培训项目仍保留

排除规则（消防培训）：
- 项目内容涉及消防安全培训、消防演练、消防技能培训、防火培训、灭火培训的，排除
- 注意区分：消防设备采购属于物资采购（排除）；但消防系统安全管理咨询如含企业管理内容则可保留

排除规则（学校培训）：
- 招标单位是学校、院校、大学、学院、中小学、职业学校、技工学校等的，排除
- 判断依据：招标单位含"学校""学院""大学""中学""小学""幼儿园""职校""技校""师范""党校"等关键词的，排除
- 企业委托第三方为内部员工做的培训项目（招标单位是企业而非学校）不受此限制

排除规则（非正式招标公告）：
- 采购预告、事前公示、意向公示、需求公示、前期公示、计划公示等仅为预告性质的公告，排除
- 这些公告尚处于意向阶段，不是正式招标，无法投标
- 判断依据：标题含"预告""事前公示""意向公示""需求公示""前期公示""计划公示""采购意向"等关键词的，排除"""


class LLMScreener:
    BATCH_SIZE = 50

    def __init__(self, llm: LLMClient, keywords_by_category: dict, blacklist: dict):
        self.llm = llm
        self.keywords_by_category = keywords_by_category
        self.blacklist = blacklist

    async def screen(self, items: list[TenderItem]) -> list[TenderItem]:
        if not items:
            return items

        batches = [items[i:i + self.BATCH_SIZE] for i in range(0, len(items), self.BATCH_SIZE)]
        tasks = [self._screen_batch(batch) for batch in batches]
        results = await asyncio.gather(*tasks)

        passed = []
        for batch_result in results:
            passed.extend(batch_result)

        logger.info(f"LLM screen: {len(items)} -> {len(passed)} items passed")
        return passed

    async def _screen_batch(self, batch: list[TenderItem]) -> list[TenderItem]:
        lines = []
        for i, item in enumerate(batch):
            line = f"[{i+1}] 标题：{item.project_name}"
            if item.bidder:
                line += f" | 招标单位：{item.bidder}"
            lines.append(line)

        user_prompt = (
            "请对以下招标项目逐条判断，返回JSON。每条包含：\n"
            '- id: 序号\n'
            '- category: "咨询" | "培训" | "绩效系统" | "无关"\n'
            '- relevant: true/false（是否海博目标项目）\n'
            '- reason: 一句话理由\n\n'
            "项目列表：\n" + "\n".join(lines)
        )

        try:
            data = await self.llm.chat_json(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                model=self.llm.default_model,
            )
            if isinstance(data, list):
                llm_items = data
            elif isinstance(data, dict):
                llm_items = data.get("items", [])
            else:
                llm_items = []
            return self._merge_results(batch, llm_items)
        except LLMError as e:
            logger.error(f"LLM screen failed, falling back to regex: {e}")
            return self._regex_fallback(batch)

    def _merge_results(self, batch: list[TenderItem], llm_items: list[dict]) -> list[TenderItem]:
        id_to_result = {}
        for item in llm_items:
            id_to_result[int(item.get("id", 0))] = item

        passed = []
        for i, item in enumerate(batch):
            result = id_to_result.get(i + 1, {})
            if result.get("relevant", False):
                category = result.get("category", item.category)
                if category in ("咨询", "培训", "绩效系统"):
                    item.category = category
                passed.append(item)
            else:
                reason = result.get("reason", "LLM irrelevant")
                logger.info(f"LLM filtered: {item.project_name[:60]} ({reason})")

        return passed

    def _regex_fallback(self, batch: list[TenderItem]) -> list[TenderItem]:
        filtered = apply_keyword_strict_filter(batch, self.keywords_by_category)
        filtered = apply_blacklist(filtered, self.blacklist)
        return filtered
