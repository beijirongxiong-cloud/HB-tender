# LLM 增强招标爬虫实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有9站招标爬虫基础上引入 deepseek-v4-flash 实现双层语义管线（LLM精筛+LLM提取），修复两个已知 Bug，改造数据流为"先筛选再抓详情"。

**Architecture:** 五层数据流：爬虫抓列表→正则粗筛→LLM精筛(50条/批)→详情抓取(仅幸存项)→LLM提取(6字段JSON)→去重飞书。LLM 客户端用 httpx.AsyncClient 调用 Volcano Engine OpenAI-compatible API。每层 LLM 失败 fallback 到现有正则。

**Tech Stack:** Python 3.11, httpx (异步HTTP), deepseek-v4-flash (Volcano Engine), pytest (测试)

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `src/processor/filter.py` | 修 Bug1：删除 URL 路径判断 |
| Modify | `config/keywords.yaml` | 修 Bug2：补全关键词 |
| Modify | `config/sites.yaml` | 移除 yuanbo 站点 |
| Modify | `src/scheduler.py` | 移除 yuanbo，插入 LLM 层 |
| Modify | `src/scraper/base.py` | 新增 `_detail_text` 字段 |
| Modify | `src/scraper/chinabidding.py` | JS_GRAB_TEXT 替代 JS_EXTRACT |
| Modify | `.env.example` | 新增 VOLC 环境变量 |
| Create | `src/llm/__init__.py` | 模块初始化 |
| Create | `src/llm/client.py` | Volcano Engine 异步客户端 |
| Create | `src/llm/screener.py` | LLM 语义精筛 |
| Create | `src/llm/extractor.py` | LLM 详情字段提取 |
| Create | `tests/test_llm_client.py` | LLM 客户端测试 |
| Create | `tests/test_llm_screener.py` | 精筛测试 |
| Create | `tests/test_llm_extractor.py` | 提取测试 |

---

### Task 1: 修复 Bug1 — 删除 filter.py 中误删 /zbgs/ 的 URL 路径判断

**Files:**
- Modify: `src/processor/filter.py:59-78`
- Modify: `tests/test_filter.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_filter.py` 末尾添加：

```python
from src.processor.filter import apply_bid_result_filter


def test_zbgs_url_not_filtered_as_bid_result():
    items = [
        TenderItem(project_name="XX管理咨询项目招标公告", link="https://www.chinabidding.cn/zbgs/U-abc123.html"),
    ]
    result = apply_bid_result_filter(items)
    assert len(result) == 1, "含/zbgs/路径的招标公告不应被当中标结果过滤"


def test_real_bid_result_filtered_by_title():
    items = [
        TenderItem(project_name="XX管理咨询项目中标公告", link="https://example.com/detail/123"),
        TenderItem(project_name="XX管理咨询项目结果公示", link="https://example.com/detail/456"),
        TenderItem(project_name="XX管理咨询项目招标公告", link="https://example.com/detail/789"),
    ]
    result = apply_bid_result_filter(items)
    assert len(result) == 1
    assert result[0].project_name == "XX管理咨询项目招标公告"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd E:\Opencode\HB-tender && .venv\Scripts\python.exe -m pytest tests/test_filter.py::test_zbgs_url_not_filtered_as_bid_result -v`
Expected: FAIL（/zbgs/ 被误删）

- [ ] **Step 3: 修改 filter.py**

在 `src/processor/filter.py` 中，删除 `_BID_RESULT_URL_PATHS` 及其在 `apply_bid_result_filter` 中的 URL 检查分支。修改后：

```python
_BID_RESULT_TITLE_KEYWORDS = [
    '中标', '成交结果', '结果公告', '候选人公示', '中标候选人',
    '中标公示', '成交公示', '结果公示', '中标通知',
]


def apply_bid_result_filter(items: list[TenderItem]) -> list[TenderItem]:
    """筛除投标结果(中标公示)，只保留招标信息。"""
    filtered = []
    for item in items:
        title = item.project_name or ""
        if any(kw in title for kw in _BID_RESULT_TITLE_KEYWORDS):
            logger.info(f"Bid result filtered (title): {title[:60]}")
            continue
        filtered.append(item)
    return filtered
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd E:\Opencode\HB-tender && .venv\Scripts\python.exe -m pytest tests/test_filter.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/processor/filter.py tests/test_filter.py
git commit -m "fix: remove /zbgs/ URL path filter that误删招标公告"
```

---

### Task 2: 修复 Bug2 — 补全 keywords.yaml 与 V1.0 xlsx 同步

**Files:**
- Modify: `config/keywords.yaml`

- [ ] **Step 1: 替换 keywords.yaml 内容**

将 `config/keywords.yaml` 替换为 V1.0 xlsx 附表二的完整内容：

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

- [ ] **Step 2: 验证 YAML 可解析**

Run: `cd E:\Opencode\HB-tender && .venv\Scripts\python.exe -c "import yaml; d=yaml.safe_load(open('config/keywords.yaml','r',encoding='utf-8')); print('咨询:', len(d['categories']['咨询']), '培训:', len(d['categories']['培训']), '绩效系统:', len(d['categories']['绩效系统']))"`
Expected: `咨询: 22 培训: 14 绩效系统: 8`

- [ ] **Step 3: Commit**

```bash
git add config/keywords.yaml
git commit -m "fix: sync keywords.yaml with V1.0 xlsx (add 胜任力 etc, 22+14+8 keywords)"
```

---

### Task 3: 移除 yuanbo 站点 + 新增 VOLC 环境变量

**Files:**
- Modify: `config/sites.yaml`
- Modify: `src/scheduler.py`
- Modify: `.env.example`

- [ ] **Step 1: 修改 sites.yaml**

删除 `config/sites.yaml` 中 yuanbo 站点条目（第 12-19 行），同时删除重复的 cnncecp 条目（第 91-98 行）。保留 9 个站点：chinabidding, mobile, tower, csg, sgcc, scbid, unicom, telecom, cnncecp。

- [ ] **Step 2: 修改 scheduler.py**

在 `src/scheduler.py` 中：
- 删除 `from src.scraper.yuanbo import YuanboScraper` (第 13 行)
- 从 `SCRAPER_MAP` 删除 `"yuanbo": YuanboScraper` (第 33 行)

- [ ] **Step 3: 添加 VOLC 环境变量到 .env.example**

在 `.env.example` 末尾追加：

```env
# Volcano Engine LLM
VOLC_API_KEY=
VOLC_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
VOLC_SCREEN_MODEL=deepseek-v4-flash
VOLC_EXTRACT_MODEL=deepseek-v4-flash
```

- [ ] **Step 4: 验证导入无误**

Run: `cd E:\Opencode\HB-tender && .venv\Scripts\python.exe -c "from src.scheduler import SCRAPER_MAP; print(len(SCRAPER_MAP), list(SCRAPER_MAP.keys()))"`
Expected: `9 ['chinabidding', 'mobile', 'tower', 'csg', 'sgcc', 'scbid', 'unicom', 'telecom', 'cnncecp']`

- [ ] **Step 5: Commit**

```bash
git add config/sites.yaml src/scheduler.py .env.example
git commit -m "refactor: remove yuanbo site (10→9), add VOLC env vars"
```

---

### Task 4: TenderItem 新增 _detail_text 字段

**Files:**
- Modify: `src/scraper/base.py:15-30`

- [ ] **Step 1: 修改 TenderItem dataclass**

在 `src/scraper/base.py` 的 `TenderItem` dataclass 中，在 `_obj_type` 后新增：

```python
    _detail_text: str = ""
```

完整的 TenderItem：

```python
@dataclass
class TenderItem:
    date: str = ""
    seq: int = 0
    category: str = ""
    bidder: str = ""
    project_name: str = ""
    budget: str = ""
    bid_count: str = ""
    deadline: str = ""
    bid_time: str = ""
    link: str = ""
    doc_price: str = ""
    source_site: str = ""
    platform: str = ""
    _obj_id: str = ""
    _obj_type: int = 0
    _detail_text: str = ""
```

- [ ] **Step 2: 验证现有测试不破坏**

Run: `cd E:\Opencode\HB-tender && .venv\Scripts\python.exe -m pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 3: Commit**

```bash
git add src/scraper/base.py
git commit -m "feat: add _detail_text field to TenderItem for LLM extraction"
```

---

### Task 5: 实现 LLM 客户端（src/llm/client.py）

**Files:**
- Create: `src/llm/__init__.py`
- Create: `src/llm/client.py`
- Create: `tests/test_llm_client.py`

- [ ] **Step 1: 创建 src/llm/__init__.py**

```python
```

（空文件，仅标记为 Python 包）

- [ ] **Step 2: 写失败测试 tests/test_llm_client.py**

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.llm.client import LLMClient, LLMError


@pytest.fixture
def client():
    with patch.dict("os.environ", {
        "VOLC_API_KEY": "test-key",
        "VOLC_BASE_URL": "https://ark.test.com/api/v3",
        "VOLC_SCREEN_MODEL": "test-model",
    }):
        return LLMClient()


def test_client_reads_env(client):
    assert client.api_key == "test-key"
    assert client.base_url == "https://ark.test.com/api/v3"


@pytest.mark.asyncio
async def test_chat_json_success(client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": '{"result": "ok"}'}}]
    }

    with patch("httpx.AsyncClient") as MockClient:
        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await client.chat_json(
            [{"role": "user", "content": "test"}],
            model="test-model"
        )
        assert result == {"result": "ok"}


@pytest.mark.asyncio
async def test_chat_json_retries_on_failure(client):
    with patch("httpx.AsyncClient") as MockClient:
        mock_client_instance = AsyncMock()
        mock_client_instance.post.side_effect = Exception("network error")
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(LLMError):
            await client.chat_json(
                [{"role": "user", "content": "test"}],
                model="test-model"
            )


@pytest.mark.asyncio
async def test_chat_json_non_json_response_fallback(client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "not valid json"}}]
    }

    with patch("httpx.AsyncClient") as MockClient:
        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(LLMError):
            await client.chat_json(
                [{"role": "user", "content": "test"}],
                model="test-model"
            )
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd E:\Opencode\HB-tender && .venv\Scripts\python.exe -m pytest tests/test_llm_client.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 4: 实现 src/llm/client.py**

```python
import json
import os
import asyncio
from typing import Optional

import httpx

from src.utils.logger import setup_logger

logger = setup_logger("llm.client")


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self):
        self.api_key = os.getenv("VOLC_API_KEY", "")
        self.base_url = os.getenv("VOLC_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3")
        self.default_model = os.getenv("VOLC_SCREEN_MODEL", "deepseek-v4-flash")
        self.timeout = 60

    async def chat_json(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        max_retries: int = 3,
    ) -> dict:
        model = model or self.default_model
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_error = None
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()

                content = data["choices"][0]["message"]["content"]
                return json.loads(content)
            except json.JSONDecodeError as e:
                logger.error(f"LLM returned non-JSON (attempt {attempt+1}): {content[:200]}")
                last_error = LLMError(f"Non-JSON response: {e}")
            except (httpx.HTTPStatusError, httpx.RequestError, KeyError, IndexError) as e:
                logger.warning(f"LLM call failed (attempt {attempt+1}/{max_retries}): {e}")
                last_error = LLMError(str(e))

            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** (attempt + 1))

        raise last_error or LLMError("Unknown error")
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd E:\Opencode\HB-tender && .venv\Scripts\python.exe -m pytest tests/test_llm_client.py -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add src/llm/__init__.py src/llm/client.py tests/test_llm_client.py
git commit -m "feat: add LLM client with Volcano Engine OpenAI-compatible API"
```

---

### Task 6: 实现 LLM 精筛层（src/llm/screener.py）

**Files:**
- Create: `src/llm/screener.py`
- Create: `tests/test_llm_screener.py`

- [ ] **Step 1: 写失败测试 tests/test_llm_screener.py**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.scraper.base import TenderItem
from src.llm.screener import LLMScreener


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def screener(mock_llm):
    keywords = {
        "咨询": ["管理咨询", "流程优化"],
        "培训": ["员工培训", "内训师"],
        "绩效系统": ["绩效管理系统"],
    }
    blacklist = {"绩效系统": ["银行", "医院"]}
    return LLMScreener(mock_llm, keywords, blacklist)


@pytest.mark.asyncio
async def test_screen_keeps_relevant_items(screener, mock_llm):
    mock_llm.chat_json.return_value = {
        "items": [
            {"id": 1, "category": "咨询", "relevant": True, "reason": "管理咨询"},
            {"id": 2, "category": "无关", "relevant": False, "reason": "工程建设"},
        ]
    }
    items = [
        TenderItem(project_name="XX管理咨询项目招标公告", bidder="XX集团"),
        TenderItem(project_name="XX工程施工招标", bidder="XX建设"),
    ]
    result = await screener.screen(items)
    assert len(result) == 1
    assert result[0].project_name == "XX管理咨询项目招标公告"
    assert result[0].category == "咨询"


@pytest.mark.asyncio
async def test_screen_excludes_performance_system_in_hospital(screener, mock_llm):
    mock_llm.chat_json.return_value = {
        "items": [
            {"id": 1, "category": "绩效系统", "relevant": False, "reason": "医院绩效系统排除"},
            {"id": 2, "category": "培训", "relevant": True, "reason": "医院培训保留"},
        ]
    }
    items = [
        TenderItem(project_name="XX医院绩效管理系统采购", bidder="XX医院"),
        TenderItem(project_name="XX医院内训师培训项目", bidder="XX医院"),
    ]
    result = await screener.screen(items)
    assert len(result) == 1
    assert result[0].project_name == "XX医院内训师培训项目"
    assert result[0].category == "培训"


@pytest.mark.asyncio
async def test_screen_fallback_to_regex(screener, mock_llm):
    from src.llm.client import LLMError
    mock_llm.chat_json.side_effect = LLMError("API down")
    items = [
        TenderItem(project_name="XX管理咨询项目招标公告", bidder="XX集团"),
        TenderItem(project_name="XX工程施工招标", bidder="XX建设"),
    ]
    result = await screener.screen(items)
    assert len(result) == 1
    assert result[0].project_name == "XX管理咨询项目招标公告"


@pytest.mark.asyncio
async def test_screen_batch_size(screener, mock_llm):
    mock_llm.chat_json.return_value = {"items": []}
    items = [TenderItem(project_name=f"项目{i}") for i in range(120)]
    await screener.screen(items)
    assert mock_llm.chat_json.call_count == 3
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd E:\Opencode\HB-tender && .venv\Scripts\python.exe -m pytest tests/test_llm_screener.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 src/llm/screener.py**

```python
import asyncio
from typing import Optional

from src.scraper.base import TenderItem
from src.llm.client import LLMClient, LLMError
from src.processor.filter import apply_keyword_strict_filter, apply_blacklist
from src.utils.logger import setup_logger

logger = setup_logger("llm.screener")

SYSTEM_PROMPT = """你是招标项目筛选助手。海博智业是一家企业管理咨询公司，业务聚焦三类：
1. 咨询类：管理咨询、流程优化、企业文化、人力资源、薪酬绩效体系设计、组织管控等
2. 培训类：员工培训、内训师、管理能力提升、团队拓展、AI赋能培训等
3. 绩效系统类：绩效管理系统/软件/平台的采购与开发

筛选规则：
- 只保留招标单位或项目内容属于上述三类的"招标公告"（非中标结果）
- 排除明显无关（如工程建设、物资采购、医疗器械、IT硬件采购等）
- 标题含"绩效"但实为"绩效工资发放/考核发放"等行政事务的，排除

排除规则（仅限"绩效系统"类）：
- 当项目判定为"绩效系统"类时，若招标单位涉及银行/医院/医疗/诊所/卫生院，则排除
- 培训类、咨询类不受此限制（如医院内训师项目、银行管理咨询项目仍保留）"""


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

        logger.info(f"LLM screen: {len(items)} → {len(passed)} items passed")
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
            return self._merge_results(batch, data.get("items", []))
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd E:\Opencode\HB-tender && .venv\Scripts\python.exe -m pytest tests/test_llm_screener.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/llm/screener.py tests/test_llm_screener.py
git commit -m "feat: add LLM screener with batch semantic filtering + regex fallback"
```

---

### Task 7: 实现 LLM 提取层（src/llm/extractor.py）

**Files:**
- Create: `src/llm/extractor.py`
- Create: `tests/test_llm_extractor.py`

- [ ] **Step 1: 写失败测试 tests/test_llm_extractor.py**

```python
import pytest
from unittest.mock import AsyncMock
from src.scraper.base import TenderItem
from src.llm.extractor import LLMExtractor


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def extractor(mock_llm):
    return LLMExtractor(mock_llm)


@pytest.mark.asyncio
async def test_extract_fields_from_text(extractor, mock_llm):
    mock_llm.chat_json.return_value = {
        "bidder": "中国移动通信集团四川有限公司",
        "budget": "50",
        "deadline": "2026-07-15 17:00",
        "bid_time": "2026-07-20 09:30",
        "doc_price": "500元",
        "bid_count": "第一次",
    }
    item = TenderItem(project_name="XX管理咨询项目", link="https://example.com/1")
    text = "中国移动通信集团四川有限公司拟就管理咨询项目进行公开招标。项目预算50万元。报名截止时间2026年7月15日17:00。开标时间2026年7月20日09:30。标书售价500元。"

    result = await extractor.extract(item, text)
    assert result.bidder == "中国移动通信集团四川有限公司"
    assert result.budget == "50"
    assert result.deadline == "2026-07-15 17:00"
    assert result.bid_time == "2026-07-20 09:30"
    assert result.doc_price == "500元"
    assert result.bid_count == "第一次"


@pytest.mark.asyncio
async def test_extract_fallback_to_regex(extractor, mock_llm):
    from src.llm.client import LLMError
    mock_llm.chat_json.side_effect = LLMError("API down")

    item = TenderItem(project_name="XX管理咨询项目", link="https://example.com/1")
    text = "项目预算金额：100万元。开标时间：2026年8月1日09:00。"

    result = await extractor.extract(item, text)
    assert result.budget == "100"
    assert result.bid_time == "2026-08-01 09:00"


@pytest.mark.asyncio
async def test_extract_batch_concurrency(extractor, mock_llm):
    mock_llm.chat_json.return_value = {
        "bidder": "", "budget": "", "deadline": "", "bid_time": "", "doc_price": "", "bid_count": "第一次"
    }
    items_with_text = [
        (TenderItem(project_name=f"项目{i}"), f"正文{i}") for i in range(10)
    ]
    results = await extractor.extract_batch(items_with_text)
    assert len(results) == 10


@pytest.mark.asyncio
async def test_extract_preserves_existing_fields(extractor, mock_llm):
    mock_llm.chat_json.return_value = {
        "bidder": "新招标单位",
        "budget": "",
        "deadline": "",
        "bid_time": "",
        "doc_price": "",
        "bid_count": "",
    }
    item = TenderItem(project_name="XX项目", bidder="旧招标单位", source_site="测试站")
    text = "新招标单位发布招标公告"

    result = await extractor.extract(item, text)
    assert result.bidder == "新招标单位"
    assert result.source_site == "测试站"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd E:\Opencode\HB-tender && .venv\Scripts\python.exe -m pytest tests/test_llm_extractor.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 src/llm/extractor.py**

```python
import asyncio
import re
from typing import Optional

from src.scraper.base import TenderItem
from src.llm.client import LLMClient, LLMError
from src.utils.logger import setup_logger

logger = setup_logger("llm.extractor")

SYSTEM_PROMPT = """你是招标公告信息提取助手。从招标公告正文中提取以下字段，返回JSON。
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
- budget 必须是纯数字（万元），无预算信息填空"""


class LLMExtractor:
    MAX_CONCURRENT = 5
    MAX_TEXT_LENGTH = 4000

    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def extract(self, item: TenderItem, page_text: str) -> TenderItem:
        truncated = page_text[: self.MAX_TEXT_LENGTH]
        try:
            data = await self.llm.chat_json(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"招标公告正文：\n{truncated}\n\n请提取字段，返回JSON。"},
                ],
                model=os.getenv("VOLC_EXTRACT_MODEL", "deepseek-v4-flash"),
            )
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

        return await asyncio.gather(*[one(i, t) for i, t in items_with_text])

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
                r'(预算|预算金额|项目预算|采购金额)[\s\S]{0,20}[\uff1a:\uff08(]\s*[\u00a5\uffe5]?\s*([\d,]+\.?\d*)\s*万?\u5143?',
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
                r'(报名|获取)[\s\S]{0,30}(截止|期限)[\s\S]{0,30}[\uff1a:]?\s*(\d{4})[\u5e74\-](\d{1,2})[\u6708\-](\d{1,2})[\u65e5]?\s*(\d{1,2})[\u65f6:](\d{1,2})',
                text,
            )
            if dm:
                item.deadline = f"{dm.group(3)}-{dm.group(4).zfill(2)}-{dm.group(5).zfill(2)} {dm.group(6).zfill(2)}:{dm.group(7).zfill(2)}"

        if not item.bid_time:
            bm = re.search(
                r'开标[\s\S]{0,30}时间[\uff1a:]?\s*(\d{4})[\u5e74\-](\d{1,2})[\u6708\-](\d{1,2})[\u65e5]?\s*(\d{1,2})[\u65f6:](\d{1,2})',
                text,
            )
            if bm:
                item.bid_time = f"{bm.group(1)}-{bm.group(2).zfill(2)}-{bm.group(3).zfill(2)} {bm.group(4).zfill(2)}:{bm.group(5).zfill(2)}"

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
```

- [ ] **Step 4: 修复 import 缺失**

在 `src/llm/extractor.py` 顶部添加缺失的 `import os`：

```python
import asyncio
import os
import re
from typing import Optional
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd E:\Opencode\HB-tender && .venv\Scripts\python.exe -m pytest tests/test_llm_extractor.py -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add src/llm/extractor.py tests/test_llm_extractor.py
git commit -m "feat: add LLM extractor with structured field extraction + regex fallback"
```

---

### Task 8: 改造 chinabidding fetch_details 为抓文本模式

**Files:**
- Modify: `src/scraper/chinabidding.py`

- [ ] **Step 1: 替换 JS_EXTRACT 为 JS_GRAB_TEXT**

在 `src/scraper/chinabidding.py` 中：

1. 删除 `JS_EXTRACT` 变量（约第 112-282 行的巨大字符串）
2. 在其位置添加 `JS_GRAB_TEXT`：

```python
    JS_GRAB_TEXT = r'''() => {
        const result = {};
        const table = document.querySelector('.info_table');
        result.table_text = table ? table.innerText : '';
        const xq = document.querySelector('.xq_nr');
        result.body_text = xq ? xq.innerText : document.body.innerText;
        result.full_text = (result.table_text + '\\n' + result.body_text).slice(0, 8000);
        return result;
    }'''
```

3. 修改 `login_and_fetch_details` 函数中详情页处理部分。将原来的 `page.evaluate(JS_EXTRACT)` 改为 `page.evaluate(JS_GRAB_TEXT)`，并将存储方式改为存 `full_text`：

```python
                    data = page.evaluate(JS_GRAB_TEXT)
                    collected[url] = data.get("full_text", "") if data else ""
                    self.logger.info(
                        f"Detail {i+1}/{len(urls)}: grabbed text len={len(collected[url])}"
                    )
```

4. 修改函数末尾的合并逻辑，将 `collected[url]` 从 dict 改为 str：

```python
        for item in items:
            text = collected.get(item.link, "")
            item._detail_text = text
            if not item.bidder:
                item.bidder = self._extract_bidder_from_title(item.project_name)
```

- [ ] **Step 2: 验证导入无误**

Run: `cd E:\Opencode\HB-tender && .venv\Scripts\python.exe -c "from src.scraper.chinabidding import ChinaBiddingScraper; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/scraper/chinabidding.py
git commit -m "refactor: chinabidding fetch_details grabs text only (JS_GRAB_TEXT replaces JS_EXTRACT)"
```

---

### Task 9: 改造 scheduler.py 整合 LLM 层

**Files:**
- Modify: `src/scheduler.py`

- [ ] **Step 1: 添加 LLM 层 import**

在 `src/scheduler.py` 顶部 import 区追加：

```python
from src.llm.client import LLMClient
from src.llm.screener import LLMScreener
from src.llm.extractor import LLMExtractor
```

- [ ] **Step 2: 改造 run_scrape 函数**

替换整个 `run_scrape` 函数（约第 62-152 行）：

```python
async def run_scrape(is_first_run: bool = False) -> None:
    logger.info(f"Starting scrape job (first_run={is_first_run})")

    with open("config/sites.yaml", "r", encoding="utf-8") as f:
        sites_config = yaml.safe_load(f)["sites"]
    with open("config/keywords.yaml", "r", encoding="utf-8") as f:
        keywords_config = yaml.safe_load(f)

    keywords_by_category = keywords_config["categories"]
    blacklist = keywords_config.get("blacklist", {})

    since = None
    if is_first_run:
        since = datetime.now() - timedelta(days=3)
    else:
        since = get_last_run()

    all_items: list[TenderItem] = []

    scrapers: dict[str, BaseScraper] = {}
    tasks = []
    for cfg in sites_config:
        scraper_cls = SCRAPER_MAP.get(cfg["id"])
        if not scraper_cls:
            logger.warning(f"Unknown site: {cfg['id']}")
            continue
        scraper = scraper_cls(cfg)
        scrapers[scraper.site_name] = scraper
        async def _run(s):
            try:
                return await s.run(keywords_by_category, since)
            except Exception as e:
                logger.error(f"Scraper {s.site_id} failed: {e}")
                send_feishu_alert(f"爬虫 **{s.site_name}** 执行失败: {str(e)[:200]}")
                return []
        tasks.append(_run(scraper))

    results = await asyncio.gather(*tasks)
    for r in results:
        all_items.extend(r)

    logger.info(f"Total raw items: {len(all_items)}")

    # Layer 1: regex coarse filter
    filtered = apply_blacklist(all_items, blacklist)
    logger.info(f"After blacklist filter: {len(filtered)}")

    filtered = apply_keyword_strict_filter(filtered, keywords_by_category)
    logger.info(f"After keyword strict filter: {len(filtered)}")

    filtered = apply_bid_result_filter(filtered)
    logger.info(f"After bid result filter: {len(filtered)}")

    # Layer 2: LLM semantic screening
    llm_client = LLMClient()
    screener = LLMScreener(llm_client, keywords_by_category, blacklist)
    screened = await screener.screen(filtered)
    logger.info(f"After LLM screen: {len(screened)}")

    # Layer 3: fetch details only for screened items
    if screened:
        by_site: dict[str, list[TenderItem]] = {}
        for item in screened:
            by_site.setdefault(item.source_site, []).append(item)

        detailed_items: list[TenderItem] = []
        for site_name, site_items in by_site.items():
            scraper = scrapers.get(site_name)
            if scraper and len(site_items) > 0:
                try:
                    enriched = await scraper.fetch_details(site_items)
                    detailed_items.extend(enriched)
                    logger.info(f"Fetched details for {len(enriched)} items from {site_name}")
                except Exception as e:
                    logger.error(f"fetch_details failed for {site_name}: {e}")
                    detailed_items.extend(site_items)
            else:
                detailed_items.extend(site_items)

        screened = detailed_items

    # Layer 4: LLM structured extraction
    if screened:
        items_with_text = [(item, item._detail_text) for item in screened]
        extractor = LLMExtractor(llm_client)
        screened = await extractor.extract_batch(items_with_text)
        logger.info(f"After LLM extract: {len(screened)} items")

    # Layer 5: dedup + feishu
    unique = deduplicate(screened)
    logger.info(f"After dedup: {len(unique)}")

    if unique:
        records = format_for_feishu(unique)
        sheet_client = FeishuSpreadsheetClient()
        success = sheet_client.create_records(records, insert_at_top=True)
        if success:
            logger.info(f"Wrote {len(records)} records to Feishu Spreadsheet: {sheet_client.spreadsheet_url()}")
        else:
            logger.error("Failed to write records to Feishu Spreadsheet")
            send_feishu_alert(f"飞书Excel写入失败，本次共有 {len(records)} 条数据待写入")
    else:
        logger.info("No new items to write")

    save_last_run()
    logger.info("Scrape job completed")
```

- [ ] **Step 2: 验证导入无误**

Run: `cd E:\Opencode\HB-tender && .venv\Scripts\python.exe -c "from src.scheduler import run_scrape; print('OK')"`
Expected: `OK`

- [ ] **Step 3: 运行全部测试**

Run: `cd E:\Opencode\HB-tender && .venv\Scripts\python.exe -m pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
git add src/scheduler.py
git commit -m "feat: integrate LLM screener + extractor into scheduler pipeline"
```

---

### Task 10: 更新 .env 添加 VOLC 凭证

**Files:**
- Modify: `.env`

- [ ] **Step 1: 在 .env 末尾追加**

```env
# Volcano Engine LLM
VOLC_API_KEY=ark-4918777f-1c65-4c35-88c6-9080797d0bc7-0f2f7
VOLC_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
VOLC_SCREEN_MODEL=deepseek-v4-flash
VOLC_EXTRACT_MODEL=deepseek-v4-flash
```

- [ ] **Step 2: 验证环境变量可读**

Run: `cd E:\Opencode\HB-tender && .venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); import os; print('VOLC_API_KEY:', bool(os.getenv('VOLC_API_KEY')), 'MODEL:', os.getenv('VOLC_SCREEN_MODEL'))"`
Expected: `VOLC_API_KEY: True MODEL: deepseek-v4-flash`

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "chore: add VOLC env vars to .env.example"
```

（注意：.env 在 .gitignore 中，不会被提交）

---

### Task 11: 端到端集成测试

**Files:**
- Create: `tests/test_integration_llm.py`

- [ ] **Step 1: 写集成测试（mock LLM）**

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.scraper.base import TenderItem
from src.processor.filter import apply_blacklist, apply_keyword_strict_filter, apply_bid_result_filter
from src.llm.screener import LLMScreener
from src.llm.extractor import LLMExtractor


def _load_config():
    import yaml
    with open("config/keywords.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.mark.asyncio
async def test_full_pipeline_with_mock_llm():
    config = _load_config()
    keywords = config["categories"]
    blacklist = config.get("blacklist", {})

    raw_items = [
        TenderItem(project_name="中国移动2026年管理咨询项目招标公告", bidder="中国移动", category="咨询", link="https://example.com/1"),
        TenderItem(project_name="XX医院绩效工资发放方案采购", bidder="XX人民医院", category="绩效系统", link="https://example.com/2"),
        TenderItem(project_name="XX集团内训师培养体系建设项目", bidder="XX集团", category="培训", link="https://example.com/3"),
        TenderItem(project_name="XX道路工程施工招标", bidder="XX建设局", link="https://example.com/4"),
        TenderItem(project_name="XX银行绩效管理系统采购公告", bidder="中国工商银行", category="绩效系统", link="https://example.com/5"),
        TenderItem(project_name="XX银行员工培训服务招标", bidder="中国银行", category="培训", link="https://example.com/6"),
    ]

    # Layer 1: regex
    filtered = apply_blacklist(raw_items, blacklist)
    filtered = apply_keyword_strict_filter(filtered, keywords)
    filtered = apply_bid_result_filter(filtered)
    assert len(filtered) >= 3  # 至少咨询、培训、绩效系统类的被保留

    # Layer 2: LLM screen (mock)
    mock_llm = AsyncMock()
    mock_llm.default_model = "test-model"
    mock_llm.chat_json.return_value = {
        "items": [
            {"id": 1, "category": "咨询", "relevant": True, "reason": "管理咨询"},
            {"id": 2, "category": "绩效系统", "relevant": False, "reason": "医院绩效工资排除"},
            {"id": 3, "category": "培训", "relevant": True, "reason": "内训师"},
            {"id": 4, "category": "无关", "relevant": False, "reason": "工程施工"},
            {"id": 5, "category": "绩效系统", "relevant": False, "reason": "银行绩效系统排除"},
            {"id": 6, "category": "培训", "relevant": True, "reason": "银行培训保留"},
        ]
    }
    screener = LLMScreener(mock_llm, keywords, blacklist)
    screened = await screener.screen(filtered)
    assert len(screened) == 3
    categories = {item.category for item in screened}
    assert "咨询" in categories
    assert "培训" in categories

    # Layer 3+4: detail text + extract (mock)
    for item in screened:
        item._detail_text = "项目预算50万元。开标时间2026年8月1日09:30。报名截止2026年7月25日17:00。标书售价300元。"

    mock_llm.chat_json.return_value = {
        "bidder": "测试招标单位", "budget": "50", "deadline": "2026-07-25 17:00",
        "bid_time": "2026-08-01 09:30", "doc_price": "300元", "bid_count": "第一次",
    }
    extractor = LLMExtractor(mock_llm)
    items_with_text = [(item, item._detail_text) for item in screened]
    extracted = await extractor.extract_batch(items_with_text)
    assert len(extracted) == 3
    for item in extracted:
        assert item.budget == "50"
        assert item.bidder == "测试招标单位"
```

- [ ] **Step 2: 运行集成测试**

Run: `cd E:\Opencode\HB-tender && .venv\Scripts\python.exe -m pytest tests/test_integration_llm.py -v`
Expected: PASS

- [ ] **Step 3: 运行全部测试**

Run: `cd E:\Opencode\HB-tender && .venv\Scripts\python.exe -m pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_llm.py
git commit -m "test: add end-to-end integration test for LLM pipeline"
```

---

### Task 12: LLM 客户端端点可用性验证

**Files:** 无新文件，手动验证

- [ ] **Step 1: 测试 Volcano Engine 端点连通性**

Run: `cd E:\Opencode\HB-tender && .venv\Scripts\python.exe -c "
import asyncio, os
from dotenv import load_dotenv
load_dotenv()
from src.llm.client import LLMClient

async def test():
    client = LLMClient()
    print(f'Endpoint: {client.base_url}')
    print(f'Model: {client.default_model}')
    print(f'Key: {client.api_key[:20]}...')
    try:
        result = await client.chat_json([
            {'role': 'user', 'content': '返回JSON: {\"ok\": true}'}
        ])
        print(f'SUCCESS: {result}')
    except Exception as e:
        print(f'FAILED: {e}')
        print('尝试标准 ARK endpoint...')
        os.environ['VOLC_BASE_URL'] = 'https://ark.cn-beijing.volces.com/api/v3'
        client2 = LLMClient()
        try:
            result = await client2.chat_json([
                {'role': 'user', 'content': '返回JSON: {\"ok\": true}'}
            ])
            print(f'STANDARD ENDPOINT SUCCESS: {result}')
        except Exception as e2:
            print(f'STANDARD ENDPOINT ALSO FAILED: {e2}')

asyncio.run(test())
"`

如果 `/coding/` 端点不可用，修改 `.env` 中的 `VOLC_BASE_URL` 为 `https://ark.cn-beijing.volces.com/api/v3`。

- [ ] **Step 2: 确认端点可用后记录结果**

根据测试结果确认最终使用的 endpoint URL。

---

## Plan Self-Review

**1. Spec coverage:**
- Bug 1 修复 → Task 1 ✅
- Bug 2 修复 → Task 2 ✅
- yuanbo 移除 → Task 3 ✅
- TenderItem._detail_text → Task 4 ✅
- LLM 客户端 → Task 5 ✅
- LLM 精筛 → Task 6 ✅
- LLM 提取 → Task 7 ✅
- chinabidding 改造 → Task 8 ✅
- scheduler 整合 → Task 9 ✅
- .env 凭证 → Task 10 ✅
- 端到端测试 → Task 11 ✅
- 端点验证 → Task 12 ✅

**2. Placeholder scan:** No TBD/TODO/vague steps found.

**3. Type consistency:** 
- `LLMScreener.__init__(llm, keywords_by_category, blacklist)` matches usage in Task 9
- `LLMExtractor.__init__(llm)` matches usage in Task 9
- `LLMClient.chat_json(messages, model)` used consistently
- `_detail_text` field added in Task 4, used in Tasks 8, 9
