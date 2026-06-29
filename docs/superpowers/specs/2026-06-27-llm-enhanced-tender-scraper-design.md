# LLM 增强招标爬虫 — 设计文档

**日期**: 2026-06-27
**目标**: 引入 LLM（Volcano Engine deepseek-v4-flash）双层介入，提升招标信息抓取的准确率与成功率，解决漏抓、抓错、详情字段提取脆弱、抓取失败四大痛点。

---

## 1. 背景与痛点

### 1.1 现有系统

10 个招标网站爬虫（Scrapling/Playwright）→ 正则粗筛（黑名单 + 关键词子串）→ 中标结果过滤 → 去重 → 详情正则提取 → 飞书 Excel 输出。每 2 小时执行一次。

### 1.2 痛点优先级（用户确认）

1. **D. 整体抓取失败**（最痛）：网站登录不上、反爬被拦、页面结构变化导致根本抓不到数据
2. **A. 漏抓**：相关咨询/培训/绩效招标项目被漏掉（关键词匹配太死板，假阴性）
3. **C. 详情字段缺失**：项目抓到了，但预算/截止时间/招标单位等字段提取不出来或提错（正则脆弱）
4. **B. 抓错**：抓回一堆无关项目，人工筛选费劲（假阳性，如"绩效"匹配到绩效工资）

### 1.3 现有代码 Bug

- **Bug 1**（`src/processor/filter.py:59`）：`_BID_RESULT_URL_PATHS = ['/zbgs/']` 把 `/zbgs/`（招标公告）当中标结果 URL 删除，误删目标数据。各站 URL 结构不同，路径判断不可靠。
- **Bug 2**（`config/keywords.yaml`）：关键词配置与 V1.0 需求 xlsx 附表二不同步，缺少"胜任力"等词，且部分关键词被简化。

### 1.4 LLM 资源

Volcano Engine（OpenAI 兼容），配置见本机 `E:\Opencode\opencode.jsonc:45-72`：
- Endpoint: `https://ark.cn-beijing.volces.com/api/coding/v3`
- 模型: `deepseek-v4-flash`（速度快）
- API Key: 已有

⚠️ `/coding/` endpoint 可能仅限编码场景，实现时需先发测试 prompt 验证普通文本任务可用性。若不可用，改用标准 ARK endpoint `https://ark.cn-beijing.volces.com/api/v3`（同 API key 通常通用）。

### 1.5 业务约束（用户确认）

- 元博网账号异常，与 chinabidding 共享会员体系，统一用 chinabidding 抓取（实际抓取站 10 → 9）
- 黑名单按类别作用域：仅"绩效系统"类排除银行/医院/医疗/诊所/卫生院；培训类、咨询类即使招标单位是医院/银行也保留
- V1.0 需求 xlsx 附表三为输出格式权威源（11 列）

---

## 2. 总体架构

### 2.1 方案选型

采用**方案 A：LLM 双层介入**（用户确认）。保留现有爬虫基础设施，在筛选和提取两个环节引入 LLM。

### 2.2 五层数据流

```
┌─ 第0层：现有爬虫抓列表（9站，Scrapling/Playwright）─┐
│  产出：TenderItem 列表（仅 title/link/date）       │
└──────────────────┬─────────────────────────────────┘
                   ▼
┌─ 第1层：正则粗筛（现有 filter.py，修复 bug）─────┐
│  - 修 filter.py:59 的 /zbgs/ 误删 bug            │
│  - 关键词子串粗筛（快，去明显无关）               │
│  - 黑名单子串过滤（医疗/医院，仅绩效系统类）       │
│  产出：候选项（约 20-80 条/轮）                   │
└──────────────────┬─────────────────────────────────┘
                   ▼
┌─ 第2层：LLM 语义精筛（新增，deepseek-v4-flash）──┐
│  批量 50 条/批 → LLM 判断：                       │
│  - 归类：咨询 / 培训 / 绩效系统 / 无关             │
│  - 相关性：是海博目标项目吗                       │
│  - 医疗/银行语义排除（仅绩效系统类）              │
│  产出：通过项 + 正确 category（约 5-30 条）       │
└──────────────────┬─────────────────────────────────┘
                   ▼
┌─ 第3层：详情抓取（现有 fetch_details，限幸存项）──┐
│  只对 LLM 通过的项请求详情页（减少 80% 请求）      │
│  抓取正文文本（不再在浏览器里做正则提取）          │
└──────────────────┬─────────────────────────────────┘
                   ▼
┌─ 第4层：LLM 结构化提取（新增，deepseek-v4-flash）─┐
│  正文 → LLM → JSON：                              │
│  {招标单位, 预算(万), 截止时间, 投标时间,          │
│   标书价格, 招标次数}                              │
│  正则作为 fallback（LLM 失败时兜底）               │
└──────────────────┬─────────────────────────────────┘
                   ▼
┌─ 第5层：去重 + 飞书写入（现有）───────────────────┐
│  URL+项目名称去重 → 飞书 Excel 11 列              │
└──────────────────────────────────────────────────┘
```

**关键设计**：精筛（第2层）先于详情抓取（第3层），只对 LLM 通过的项请求详情页，省 80% 详情请求。

---

## 3. 模块结构

```
src/
├── llm/                    # 新增
│   ├── __init__.py
│   ├── client.py           # Volcano Engine OpenAI-compatible 客户端
│   ├── screener.py         # 第2层：LLM 语义精筛
│   └── extractor.py        # 第4层：LLM 详情字段提取
├── scraper/                # 现有，保持（fetch_details 改造为只抓文本）
│   ├── base.py             # TenderItem 新增 _detail_text 字段
│   ├── chinabidding.py     # JS_EXTRACT → JS_GRAB_TEXT，正则提取为 fallback
│   └── ...                 # 其他 scraper 同样改造
├── processor/
│   ├── filter.py           # 修复 bug + 作为第1层粗筛
│   ├── dedup.py            # 现有
│   └── formatter.py        # 现有
├── output/
│   └── feishu_sheet.py     # 现有
└── scheduler.py            # 改造 run_scrape，插入第2、4层
```

---

## 4. LLM 客户端（`src/llm/client.py`）

### 4.1 凭证管理

API key 从本机 `opencode.jsonc` 迁入项目 `.env`（不入 Git），使爬虫项目可独立部署到阿里云：

```env
# .env 新增
VOLC_API_KEY=ark-4918777f-1c65-4c35-88c6-9080797d0bc7-0f2f7
VOLC_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
VOLC_SCREEN_MODEL=deepseek-v4-flash
VOLC_EXTRACT_MODEL=deepseek-v4-flash
```

同步更新 `.env.example` 占位。

### 4.2 LLMClient 类

通用传输层，用 `httpx.AsyncClient`（与现有 `feishu_sheet.py` 一致，不加新依赖）。

```python
class LLMClient:
    """Volcano Engine (OpenAI-compatible) 异步客户端"""

    def __init__(self):
        self.api_key = os.getenv("VOLC_API_KEY", "")
        self.base_url = os.getenv("VOLC_BASE_URL", "...")
        self.timeout = 60

    async def chat_json(self, messages: list[dict], model: str = None) -> dict:
        """调用 chat/completions，强制 JSON 输出，返回解析后的 dict。
        - response_format: {"type": "json_object"}
        - 重试 3 次，指数退避 (2s/4s/8s)
        - 失败抛 LLMError，由上层 fallback 正则
        """
```

**关键设计点**：
- **强制 JSON**：`response_format={"type":"json_object"}`，prompt 要求返回 JSON，避免解析字符串
- **重试**：网络/限流时指数退避，3 次后放弃并抛 `LLMError`
- **超时**：单次 60s（flash 模型快，正常 2-5s）
- **并发**：用 `httpx.AsyncClient`，筛选/提取可 `asyncio.gather` 并发多个批次

### 4.3 两层 LLM 任务分工

| 层 | 文件 | 输入 | 输出 | 模型 | 调用方式 |
|----|------|------|------|------|----------|
| 精筛 | `src/llm/screener.py` | 50条标题/批 | 每条 `{分类, 相关, 原因}` | flash | 1次/批 |
| 提取 | `src/llm/extractor.py` | 1条正文 | `{招标单位,预算,截止,投标时间,标书价,招标次数}` | flash | 1次/条并发 |

**效率预算**（每轮约 80 候选）：
- 精筛：80条 ÷ 50/批 = 2 次 LLM 调用，约 3-4 秒
- 提取：筛后约 20 条 × 并发 5 ≈ 4 批，约 15-20 秒
- 总计 LLM 开销 < 30 秒/轮

### 4.4 容错策略

```
LLM 调用失败
   ├─ 精筛层失败 → 退化为正则筛选结果（不丢数据）
   └─ 提取层失败 → 退化为现有正则提取（JS_EXTRACT 逻辑迁移为独立函数）
```

LLM 是"增强"不是"单点"。任何 LLM 故障都 fallback 到现有正则，保证可用性。

---

## 5. LLM 精筛层（`src/llm/screener.py`）

### 5.1 设计目标

替代现有 `apply_keyword_strict_filter`（纯子串匹配，痛点 A 漏抓 + B 抓错）。输入一批标题，输出"哪些是海博目标项目 + 正确分类"。

### 5.2 Prompt 设计

**System Prompt**（固定角色 + 规则，关键词从 `config/keywords.yaml` 动态读取）：
```
你是招标项目筛选助手。海博智业是一家企业管理咨询公司，业务聚焦三类：
1. 咨询类：管理咨询、流程优化、企业文化、人力资源、薪酬绩效体系设计、组织管控等
2. 培训类：员工培训、内训师、管理能力提升、团队拓展、AI赋能培训等  
3. 绩效系统类：绩效管理系统/软件/平台的采购与开发

筛选规则：
- 只保留招标单位或项目内容属于上述三类的"招标公告"（非中标结果）
- 排除明显无关（如工程建设、物资采购、医疗器械、IT硬件采购等）
- 标题含"绩效"但实为"绩效工资发放/考核发放"等行政事务的，排除

排除规则（仅限"绩效系统"类）：
- 当项目判定为"绩效系统"类时，若招标单位涉及银行/医院/医疗/诊所/卫生院，则排除
- 培训类、咨询类不受此限制（如医院内训师项目、银行管理咨询项目仍保留）
```

**User Prompt**（批量输入）：
```
请对以下招标项目逐条判断，返回JSON数组。每条包含：
- id: 序号
- category: "咨询" | "培训" | "绩效系统" | "无关"
- relevant: true/false（是否海博目标项目）
- reason: 一句话理由

项目列表：
[1] 标题：中国移动2026年管理咨询项目招标公告 | 招标单位：中国移动通信集团
[2] 标题：某医院绩效工资发放方案采购 | 招标单位：XX人民医院
...
```

**期望输出**：
```json
{"items":[
  {"id":1,"category":"咨询","relevant":true,"reason":"管理咨询招标公告"},
  {"id":2,"category":"绩效系统","relevant":false,"reason":"医院+绩效工资发放，绩效系统类排除医疗"}
]}
```

### 5.3 批量策略

```python
async def screen(self, items: list[TenderItem]) -> list[TenderItem]:
    """精筛：标题+招标单位(如有) → LLM 判断"""
    BATCH = 50
    tasks = [self._screen_batch(batch) for batch in _chunks(items, BATCH)]
    results = await asyncio.gather(*tasks)  # 批次并发
    # 合并，只保留 relevant=True 的项，写入正确 category
```

- **每批 50 条标题**：prompt < 2K tokens，flash 响应 < 3 秒
- **批次并发**：`asyncio.gather`，80 条候选 2 批并发约 3-4 秒
- **输入精简**：只送 `id + title + bidder`（不送正文，省 token + 省详情请求）

### 5.4 输入数据增强

精筛时把列表阶段已有的 `bidder`（招标单位）一并带上，有助于 LLM 判断是否医疗/银行（"XX人民医院"直接排除绩效系统类）。

### 5.5 Fallback

```python
async def _screen_batch(self, batch) -> list[dict]:
    try:
        data = await self.llm.chat_json(messages, model=self.model)
        return data["items"]
    except LLMError:
        # 退化为正则：保留现有 apply_keyword_strict_filter 逻辑
        return [{"id": i+1, "category": cat_guess, "relevant": kw_matched, "reason": "regex_fallback"} 
                for ...]
```

### 5.6 关键词配置动态化

精筛 prompt 里的"三类业务定义"从 `config/keywords.yaml` 动态读取（不硬编码），保持与 V1.0 xlsx 附表二一致。

---

## 6. LLM 详情提取层（`src/llm/extractor.py`）

### 6.1 设计目标

替代 `chinabidding.py:112-282` 那 170 行脆弱的 `JS_EXTRACT` 正则。输入详情页正文，输出结构化字段。

### 6.2 字段映射（对齐 V1.0 附表三 11 列）

| LLM 提取字段 | TenderItem 字段 | 飞书列 | 提取说明 |
|-------------|-----------------|--------|---------|
| 招标单位 | `bidder` | 招标单位 | 招标人/采购人/发布单位 |
| 项目预算(万元) | `budget` | 预算(万) | 金额+单位换算为万元 |
| 报名截止时间 | `deadline` | 报名截止时间 | 报名/报价/获取文件截止 |
| 投标时间 | `bid_time` | 投标时间 | 开标/递交/磋商时间 |
| 标书价格 | `doc_price` | 标书价格 | 标书售价（元） |
| 招标次数 | `bid_count` | 招标次数 | 第几次招标 |

### 6.3 Prompt 设计

**System Prompt**：
```
你是招标公告信息提取助手。从招标公告正文中提取以下字段，返回JSON。
字段说明：
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
```

**User Prompt**：
```
招标公告正文：
{详情页正文文本，截断至前4000字符}

请提取字段，返回JSON。
```

**期望输出**：
```json
{"bidder":"中国移动通信集团四川有限公司","budget":"50","deadline":"2026-07-15 17:00","bid_time":"2026-07-20 09:30","doc_price":"500元","bid_count":"第一次"}
```

### 6.4 正文获取策略

详情页正文由现有 `fetch_details` 抓取。抽取文本时复用现有 DOM 定位（这部分相对稳定）：
- 优先 `.info_table` 表格文本 + `.xq_nr` 正文文本
- fallback 到 `document.body.innerText`

```python
async def extract(self, item: TenderItem, page_text: str) -> TenderItem:
    """LLM 提取详情字段。page_text 由 fetch_details 提供。"""
    try:
        data = await self.llm.chat_json([
            {"role":"system","content": SYSTEM_PROMPT},
            {"role":"user","content": f"招标公告正文：\n{page_text[:4000]}\n\n请提取字段，返回JSON。"}
        ])
        item.bidder = data.get("bidder") or item.bidder
        item.budget = data.get("budget") or item.budget
        # ... 其余字段
        return item
    except LLMError:
        return self._regex_fallback(item, page_text)  # 复用现有正则
```

### 6.5 并发策略

```python
async def extract_batch(self, items_with_text: list[tuple[TenderItem, str]]) -> list[TenderItem]:
    SEM = asyncio.Semaphore(5)  # 限制 5 并发，避免限流
    async def one(item, text):
        async with SEM:
            return await self.extract(item, text)
    return await asyncio.gather(*[one(i,t) for i,t in items_with_text])
```

20 条详情 × 5 并发 ≈ 4 批 ≈ 15-20 秒。

### 6.6 Fallback（正则兜底）

LLM 失败时，调用从 `chinabidding.py:112-282` 抽取的正则逻辑（提取为独立函数 `_regex_extract(text) -> dict`），保证可用性。这个正则逻辑从现有代码迁移，不重写。

### 6.7 与现有 fetch_details 的衔接

现有 `fetch_details` 用 Scrapling `page_action` 在浏览器里跑 `JS_EXTRACT`。改造为：
1. `page_action` 只负责**抓取正文文本**（`.info_table` + `.xq_nr` + `innerText`）
2. 返回文本后，由 `extractor.extract()` 用 LLM 解析

这样把"抓取"和"解析"解耦——抓取层只管拿文本，解析层用 LLM。`chinabidding.py` 的 170 行 JS 正则提取逻辑保留为 fallback。

---

## 7. 管线改造 & scheduler 整合

### 7.1 scheduler.py run_scrape 改造

现有流程（`scheduler.py:62-152`）插入两层 LLM。改造后：

```python
async def run_scrape(is_first_run: bool = False) -> None:
    # 1. 加载配置（现有）
    sites_config, keywords_config = ...
    keywords_by_category = keywords_config["categories"]
    blacklist = keywords_config.get("blacklist", {})
    since = ...

    # 2. 抓列表（现有，9站并发，yuanbo 已移除）
    all_items = await _scrape_all_sites(sites_config, keywords_by_category, since)
    logger.info(f"Total raw items: {len(all_items)}")

    # 3. 第1层：正则粗筛（现有 filter.py，修 bug 后）
    filtered = apply_blacklist(all_items, blacklist)
    filtered = apply_keyword_strict_filter(filtered, keywords_by_category)
    filtered = apply_bid_result_filter(filtered)  # 修 bug：只按标题判
    logger.info(f"After regex filter: {len(filtered)}")

    # 4. 第2层：LLM 精筛（新增）
    screener = LLMScreener(keywords_by_category, blacklist)
    screened = await screener.screen(filtered)
    logger.info(f"After LLM screen: {len(screened)}")

    # 5. 第3层：详情抓取（现有 fetch_details，只对幸存项）
    detailed = await _fetch_details_for_survivors(scrapers, screened)
    logger.info(f"After detail fetch: {len(detailed)}")

    # 6. 第4层：LLM 提取（新增）
    extractor = LLMExtractor()
    final = await extractor.extract_batch(detailed)
    logger.info(f"After LLM extract: {len(final)}")

    # 7. 第5层：去重 + 飞书（现有）
    unique = deduplicate(final)
    records = format_for_feishu(unique)
    FeishuSpreadsheetClient().create_records(records)
```

**关键变化**：详情抓取从"对去重后的项"前移到"对 LLM 筛选后的项"——精筛先于详情，省 80% 详情请求。

### 7.2 yuanbo / chinabidding 合并

元博网账号异常，两者共享会员体系，统一用 chinabidding 抓取。

- `config/sites.yaml`：删除 yuanbo 站点条目（或标记 `enabled: false`）
- `src/scheduler.py`：从 `SCRAPER_MAP` 移除 yuanbo，import 移除
- `src/scraper/yuanbo.py` / `yuanbo_bid360.py`：保留文件但不再被调度（不删，留作以后账号恢复）

实际抓取站从 10 → 9 个。

### 7.3 fetch_details 改造（抓取/解析解耦）

现有 `chinabidding.py:_scrapling_fetch_details` 在浏览器里跑 170 行 `JS_EXTRACT`。改造为两步：

**Step A — page_action 只抓文本**：
```javascript
JS_GRAB_TEXT = () => {
    const result = {};
    const table = document.querySelector('.info_table');
    result.table_text = table ? table.innerText : '';
    const xq = document.querySelector('.xq_nr');
    result.body_text = xq ? xq.innerText : document.body.innerText;
    result.full_text = (result.table_text + '\n' + result.body_text).slice(0, 8000);
    return result;
}
```
`page_action` 调用 `JS_GRAB_TEXT`，把 `full_text` 存入 `collected[url]`。

**Step B — LLM 解析**：
拿到 `full_text` 后调 LLM 提取字段。`JS_EXTRACT` 正则逻辑提取为 `_regex_extract(text)` 作为 fallback。

**其他 scraper**（mobile/tower/csg 等）：各自 `_do_fetch_details` 同样改为只返回正文文本，统一交给 `extractor`。各站解析逻辑差异由 LLM 抹平。

### 7.4 TenderItem 扩展

新增临时字段承载详情页正文，供 extractor 使用：
```python
@dataclass
class TenderItem:
    # ... 现有字段
    _detail_text: str = ""   # 新增：详情页正文，供 LLM 提取，不写入飞书
```

### 7.5 配置同步（修 Bug 2）

`config/keywords.yaml` 以 V1.0 xlsx 附表二为权威源补全（见附录 A）。

### 7.6 容错与可观测

- 每层 LLM 失败有 fallback，不中断流程
- 每层都 logger.info 输出数量变化（raw → regex → llm_screen → detail → llm_extract → dedup），便于排查
- LLM 调用失败超 30% 时，`send_feishu_alert` 通知（复用现有通知机制）

---

## 8. Bug 修复明细

### 8.1 Bug 1 — 误删招标公告

**位置**：`src/processor/filter.py:59`

**现状（错）**：
```python
_BID_RESULT_URL_PATHS = ['/zbgs/']  # /zbgs/ 是招标公告，却被当中标结果删了
```

**修复**：删除 URL 路径判断，只按标题关键词判别中标结果。各站 URL 结构不同，路径判断不可靠。

```python
# 删除 _BID_RESULT_URL_PATHS
# apply_bid_result_filter 只保留标题关键词判断
_BID_RESULT_TITLE_KEYWORDS = [
    '中标', '成交结果', '结果公告', '候选人公示', '中标候选人',
    '中标公示', '成交公示', '结果公示', '中标通知',
]
```

### 8.2 Bug 2 — 关键词配置不同步

`config/keywords.yaml` 补全为 V1.0 xlsx 附表二完整内容（见附录 A）。

---

## 9. 验证标准

1. **Bug 1 修复**：招标公告（含 `/zbgs/` 路径）不再被误删
2. **LLM 精筛**：对 20 条混合标题测试，准确分类 ≥ 90%，医疗/银行绩效系统类正确排除，培训/咨询类医院/银行项目保留
3. **LLM 提取**：对 10 条详情页正文测试，6 个字段提取准确率 ≥ 85%（对比人工标注）
4. **Fallback**：模拟 LLM 故障，系统退化为正则，不中断
5. **效率**：单轮 LLM 开销 < 30 秒
6. **端到端**：完整跑一轮，飞书 Excel 11 列数据正确写入

---

## 10. 待实现时确认的事项

以下需在实现阶段实测确认，不影响设计批准：

1. Volcano Engine `/coding/` endpoint 是否支持普通文本任务（先发测试 prompt 验证）
2. `deepseek-v4-flash` 的 `response_format: json_object` 支持情况
3. 各站详情页 DOM 结构（`.info_table` / `.xq_nr` 是否普遍存在，需逐站确认选择器）
4. LLM 并发 5 是否触发限流（实测调整 Semaphore 值）

---

## 附录 A：config/keywords.yaml 完整内容

以 V1.0 xlsx 附表二为权威源：

```yaml
categories:
  咨询:
    - 管理咨询项目/服务
    - 优化管理咨询/体系/提升
    - 管理提升咨询
    - 管理诊断
    - 流程管理咨询
    - 制度流程管理
    - 流程梳理/优化/制度
    - 企业文化建设项目
    - 企业文化体系
    - 企业文化管理咨询
    - 人力资源管理咨询/体系/优化
    - 薪酬管理
    - 薪酬与绩效
    - 绩效管理咨询
    - 绩效考核管理咨询
    - 绩效体系咨询
    - 薪酬管理体系
    - 定岗定编
    - 岗位价值评估
    - 薪酬激励体系
    - 组织管控
    - 激励机制
  培训:
    - 入库/入围服务
    - 培训机构/供应商
    - 培训项目/服务
    - 员工培训/赋能
    - 管理能力
    - 胜任力
    - 管理提升
    - 政企业务
    - 新员工入职培训
    - 内训师
    - AI赋能
    - 团队拓展
    - 培训提升
    - 能力素质/提升
  绩效系统:
    - 绩效管理系统
    - 绩效考核系统
    - 绩效系统
    - 绩效管理平台
    - 绩效管理软件
    - 绩效考核管理系统
    - 绩效管理信息系统
    - 绩效软件

blacklist:
  绩效系统:
    - 银行
    - 医院
    - 医疗
    - 诊所
    - 卫生院
```
