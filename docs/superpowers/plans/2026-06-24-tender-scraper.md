# 招标信息抓取系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建自动从10个招标网站抓取招标信息、过滤去重后写入飞书多维表格的系统，北京时间9:00-17:00每2小时执行一次。

**Architecture:** Python + Playwright无头浏览器自动化登录搜索，2Captcha解验证码，APScheduler定时调度，飞书Bitable API写入多维表格，Docker部署到阿里云。

**Tech Stack:** Python 3.11, Playwright, 2Captcha, APScheduler, Feishu Open API, Docker

---

## File Structure

```
HB-tender/
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── .gitignore
├── requirements.txt
├── config/
│   ├── sites.yaml
│   └── keywords.yaml
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── scheduler.py
│   ├── scraper/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── captcha.py
│   │   ├── chinabidding.py
│   │   ├── yuanbo.py
│   │   ├── mobile.py
│   │   ├── unicom.py
│   │   ├── tower.py
│   │   ├── telecom.py
│   │   ├── csg.py
│   │   ├── sgcc.py
│   │   ├── cnncecp.py
│   │   └── scbid.py
│   ├── processor/
│   │   ├── __init__.py
│   │   ├── filter.py
│   │   ├── dedup.py
│   │   └── formatter.py
│   ├── output/
│   │   ├── __init__.py
│   │   └── feishu.py
│   └── utils/
│       ├── __init__.py
│       ├── logger.py
│       └── notify.py
├── data/
│   └── .gitkeep
└── tests/
    ├── __init__.py
    ├── test_filter.py
    ├── test_dedup.py
    └── test_formatter.py
```

---

### Task 1: 项目基础设施搭建

**Files:**
- Create: `requirements.txt`
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `src/__init__.py`
- Create: `data/.gitkeep`

- [ ] **Step 1: 创建 requirements.txt**

```txt
playwright==1.49.1
2captcha-python==1.5.0
apscheduler==3.10.4
pyyaml==6.0.2
httpx==0.28.1
python-dotenv==1.0.1
lxml==5.3.0
beautifulsoup4==4.12.3
pytest==8.3.4
pytest-asyncio==0.24.0
```

- [ ] **Step 2: 创建 Dockerfile**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium \
    && playwright install-deps chromium

COPY . .

RUN mkdir -p /app/data

CMD ["python", "-m", "src.main"]
```

- [ ] **Step 3: 创建 docker-compose.yml**

```yaml
version: "3.8"
services:
  tender-scraper:
    build: .
    env_file: .env
    volumes:
      - ./data:/app/data
    restart: unless-stopped
```

- [ ] **Step 4: 更新 .gitignore**

```
__pycache__/
*.pyc
.env
data/*.json
data/cache/
*.log
```

- [ ] **Step 5: 创建 .env.example**

```
# 2Captcha
TWOCAPTCHA_API_KEY=

# 飞书
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_BITABLE_APP_TOKEN=
FEISHU_BITABLE_TABLE_ID=
FEISHU_WEBHOOK_URL=

# 招标网站凭证
CHINABIDDING_USERNAME=
CHINABIDDING_PASSWORD=
YUANBO_USERNAME=
YUANBO_PASSWORD=
MOBILE_USERNAME=
MOBILE_PASSWORD=
UNICOM_USERNAME=
UNICOM_PASSWORD=
TOWER_USERNAME=
TOWER_PASSWORD=
TELECOM_USERNAME=
TELECOM_PASSWORD=
CSG_USERNAME=
CSG_PASSWORD=
SGCC_USERNAME=
SGCC_PASSWORD=
CNNCECP_USERNAME=
CNNCECP_PASSWORD=
SCBID_USERNAME=
SCBID_PASSWORD=
```

- [ ] **Step 6: 创建 src/__init__.py 和 data/.gitkeep**

空文件。

- [ ] **Step 7: Commit**

```bash
git add .
git commit -m "feat: project scaffolding with Docker setup"
```

---

### Task 2: 配置文件

**Files:**
- Create: `config/keywords.yaml`
- Create: `config/sites.yaml`

- [ ] **Step 1: 创建 config/keywords.yaml**

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

- [ ] **Step 2: 创建 config/sites.yaml**

```yaml
sites:
  - id: chinabidding
    name: 中国采购与招标网
    url: https://www.chinabidding.cn/
    env_username: CHINABIDDING_USERNAME
    env_password: CHINABIDDING_PASSWORD
    has_captcha: true
    captcha_type: image
    search_url: https://www.chinabidding.cn/search/searchzbgg
    login_required: true

  - id: yuanbo
    name: 元博网
    url: https://www.sbiao360.com
    env_username: YUANBO_USERNAME
    env_password: YUANBO_PASSWORD
    has_captcha: true
    captcha_type: image
    login_required: true

  - id: mobile
    name: 中国移动采购与招标网
    url: https://b2b.10086.cn/b2b/main/preIndex.html
    env_username: MOBILE_USERNAME
    env_password: MOBILE_PASSWORD
    has_captcha: true
    captcha_type: image
    login_required: true

  - id: unicom
    name: 中国联通合作方门户
    url: https://www.cuecp.cn/portal/index.jhtml
    env_username: UNICOM_USERNAME
    env_password: UNICOM_PASSWORD
    has_captcha: true
    captcha_type: image
    login_required: true

  - id: tower
    name: 中国铁塔电子采购平台
    url: https://ebid.chinatowercom.cn/
    env_username: TOWER_USERNAME
    env_password: TOWER_PASSWORD
    has_captcha: true
    captcha_type: image
    login_required: true

  - id: telecom
    name: 中国电信电子采购系统
    url: https://trade.chinatelecom.com.cn/TPFrameDX/customframe4bid/login_TP
    env_username: TELECOM_USERNAME
    env_password: TELECOM_PASSWORD
    has_captcha: true
    captcha_type: image
    login_required: true

  - id: csg
    name: 中国南方电网电子采购交易平台
    url: https://ecsg.com.cn/
    env_username: CSG_USERNAME
    env_password: CSG_PASSWORD
    has_captcha: true
    captcha_type: image
    login_required: true

  - id: sgcc
    name: 国家电网电子商务平台
    url: https://ecp.sgcc.com.cn/
    env_username: SGCC_USERNAME
    env_password: SGCC_PASSWORD
    has_captcha: true
    captcha_type: image
    login_required: true

  - id: cnncecp
    name: 中核集团电子商务平台
    url: https://one.cnncecp.com/cnnc-pm-web/#/portal
    env_username: CNNCECP_USERNAME
    env_password: CNNCECP_PASSWORD
    has_captcha: true
    captcha_type: image
    login_required: true

  - id: scbid
    name: 四川招投标网
    url: http://www.scbid.com/zh/news/web_zbxx_6.shtml
    env_username: SCBID_USERNAME
    env_password: SCBID_PASSWORD
    has_captcha: false
    captcha_type: none
    login_required: false
```

- [ ] **Step 3: Commit**

```bash
git add config/
git commit -m "feat: add site and keyword configuration files"
```

---

### Task 3: 工具模块（Logger + Notify）

**Files:**
- Create: `src/utils/__init__.py`
- Create: `src/utils/logger.py`
- Create: `src/utils/notify.py`

- [ ] **Step 1: 创建 src/utils/logger.py**

```python
import logging
import os
from datetime import datetime


def setup_logger(name: str = "tender") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    log_dir = os.getenv("LOG_DIR", "/app/data")
    os.makedirs(log_dir, exist_ok=True)
    fh = logging.FileHandler(
        os.path.join(log_dir, f"tender_{datetime.now():%Y%m%d}.log"),
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger
```

- [ ] **Step 2: 创建 src/utils/notify.py**

```python
import os
import httpx
from src.utils.logger import setup_logger

logger = setup_logger("notify")


def send_feishu_alert(message: str) -> None:
    webhook_url = os.getenv("FEISHU_WEBHOOK_URL")
    if not webhook_url:
        logger.warning("FEISHU_WEBHOOK_URL not set, skip alert")
        return

    try:
        resp = httpx.post(
            webhook_url,
            json={
                "msg_type": "interactive",
                "card": {
                    "header": {
                        "title": {"tag": "plain_text", "content": "招标抓取异常告警"},
                        "template": "red",
                    },
                    "elements": [
                        {"tag": "markdown", "content": message},
                    ],
                },
            },
            timeout=10,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to send feishu alert: {e}")
```

- [ ] **Step 3: 创建 src/utils/__init__.py**

空文件。

- [ ] **Step 4: Commit**

```bash
git add src/utils/
git commit -m "feat: add logger and feishu notification utilities"
```

---

### Task 4: 验证码处理模块

**Files:**
- Create: `src/scraper/__init__.py`
- Create: `src/scraper/captcha.py`

- [ ] **Step 1: 创建 src/scraper/captcha.py**

```python
import os
import time
import base64
from twocaptcha import TwoCaptcha
from src.utils.logger import setup_logger

logger = setup_logger("captcha")

MAX_RETRIES = 3


def solve_captcha(image_base64: str) -> str:
    solver = TwoCaptcha(os.getenv("TWOCAPTCHA_API_KEY"))

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = solver.normal(image_base64)
            code = result["code"]
            logger.info(f"Captcha solved on attempt {attempt}: {code}")
            return code
        except Exception as e:
            logger.warning(f"Captcha solve attempt {attempt} failed: {e}")
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"Captcha solving failed after {MAX_RETRIES} attempts") from e
            time.sleep(2)


async def solve_captcha_from_element(page, selector: str) -> str:
    element = page.locator(selector)
    screenshot_bytes = await element.screenshot()
    image_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
    return solve_captcha(image_b64)
```

- [ ] **Step 2: 创建 src/scraper/__init__.py**

空文件。

- [ ] **Step 3: Commit**

```bash
git add src/scraper/
git commit -m "feat: add 2captcha integration for captcha solving"
```

---

### Task 5: BaseScraper 抽象基类

**Files:**
- Create: `src/scraper/base.py`

- [ ] **Step 1: 创建 src/scraper/base.py**

```python
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from playwright.async_api import async_playwright, Page, BrowserContext

from src.utils.logger import setup_logger

logger = setup_logger("scraper")


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


class BaseScraper(ABC):
    def __init__(self, site_config: dict):
        self.site_id = site_config["id"]
        self.site_name = site_config["name"]
        self.url = site_config["url"]
        self.has_captcha = site_config.get("has_captcha", False)
        self.captcha_type = site_config.get("captcha_type", "none")
        self.login_required = site_config.get("login_required", True)
        self.username = os.getenv(site_config.get("env_username", ""), "")
        self.password = os.getenv(site_config.get("env_password", ""), "")
        self.logger = setup_logger(f"scraper.{self.site_id}")

    @abstractmethod
    async def login(self, page: Page) -> bool:
        pass

    @abstractmethod
    async def search(self, page: Page, keyword: str, category: str) -> list[TenderItem]:
        pass

    @abstractmethod
    async def parse_detail(self, page: Page, url: str) -> Optional[TenderItem]:
        pass

    async def run(self, keywords_by_category: dict[str, list[str]], since: Optional[datetime] = None) -> list[TenderItem]:
        results: list[TenderItem] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = await context.new_page()

            try:
                if self.login_required:
                    self.logger.info(f"Logging in to {self.site_name}")
                    success = await self.login(page)
                    if not success:
                        self.logger.error(f"Login failed for {self.site_name}")
                        return results

                for category, keywords in keywords_by_category.items():
                    for keyword in keywords:
                        self.logger.info(f"Searching {self.site_name}: [{category}] {keyword}")
                        try:
                            items = await self.search(page, keyword, category)
                            results.extend(items)
                            self.logger.info(f"Found {len(items)} items for [{category}] {keyword}")
                        except Exception as e:
                            self.logger.error(f"Search failed for [{category}] {keyword}: {e}")
            finally:
                await browser.close()

        return results
```

- [ ] **Step 2: Commit**

```bash
git add src/scraper/base.py
git commit -m "feat: add BaseScraper abstract class with TenderItem dataclass"
```

---

### Task 6: 中国采购与招标网爬虫

**Files:**
- Create: `src/scraper/chinabidding.py`

- [ ] **Step 1: 创建 src/scraper/chinabidding.py**

```python
from datetime import datetime
from typing import Optional

from playwright.async_api import Page

from src.scraper.base import BaseScraper, TenderItem
from src.scraper.captcha import solve_captcha_from_element


class ChinaBiddingScraper(BaseScraper):
    async def login(self, page: Page) -> bool:
        await page.goto("https://www.chinabidding.cn/")
        await page.wait_for_load_state("networkidle")

        try:
            login_btn = page.locator("text=登录")
            if await login_btn.count() > 0:
                await login_btn.first.click()
                await page.wait_for_timeout(1000)
        except Exception:
            pass

        try:
            await page.fill('input[name="username"], input[name="loginName"], input[placeholder*="用户名"]', self.username)
            await page.fill('input[name="password"], input[type="password"]', self.password)
        except Exception as e:
            self.logger.error(f"Fill credentials failed: {e}")
            return False

        if self.has_captcha:
            try:
                captcha_selector = "img[src*='captcha'], img[src*='verify'], img[src*='code'], #captchaImg, .captcha-img"
                captcha_img = page.locator(captcha_selector)
                if await captcha_img.count() > 0:
                    code = await solve_captcha_from_element(page, captcha_selector)
                    captcha_input = page.locator('input[name*="captcha"], input[name*="verify"], input[placeholder*="验证码"]')
                    if await captcha_input.count() > 0:
                        await captcha_input.first.fill(code)
            except Exception as e:
                self.logger.warning(f"Captcha handling failed: {e}")

        submit = page.locator('button[type="submit"], input[type="submit"], .login-btn, text=登 录, text=登录')
        if await submit.count() > 0:
            await submit.first.click()

        await page.wait_for_timeout(2000)
        return "登录" not in await page.title() or await page.locator("text=退出").count() > 0

    async def search(self, page: Page, keyword: str, category: str) -> list[TenderItem]:
        items: list[TenderItem] = []
        search_url = f"https://www.chinabidding.cn/search/searchzbgg?keyword={keyword}"
        await page.goto(search_url)
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(1500)

        rows = page.locator("table tbody tr, .list-item, .result-item, .bid-list li")
        count = await rows.count()

        for i in range(min(count, 50)):
            try:
                row = rows.nth(i)
                link_el = row.locator("a[href*='zbgg'], a[href*='zbgs'], a[href*='detail'], a")
                if await link_el.count() == 0:
                    continue

                href = await link_el.first.get_attribute("href") or ""
                title = await link_el.first.inner_text() or ""

                if not href.startswith("http"):
                    href = "https://www.chinabidding.cn" + href

                item = TenderItem(
                    date=datetime.now().strftime("%Y-%m-%d"),
                    category=category,
                    project_name=title.strip(),
                    link=href,
                    source_site=self.site_name,
                )

                try:
                    detail = await self.parse_detail(page, href)
                    if detail:
                        item.bidder = detail.bidder or item.bidder
                        item.budget = detail.budget or item.budget
                        item.deadline = detail.deadline or item.deadline
                        item.bid_time = detail.bid_time or item.bid_time
                        item.doc_price = detail.doc_price or item.doc_price
                        item.bid_count = detail.bid_count or item.bid_count
                except Exception:
                    pass

                items.append(item)
            except Exception as e:
                self.logger.warning(f"Parse row {i} failed: {e}")

        return items

    async def parse_detail(self, page: Page, url: str) -> Optional[TenderItem]:
        new_page = await page.context.new_page()
        try:
            await new_page.goto(url, timeout=15000)
            await new_page.wait_for_load_state("networkidle")
            await new_page.wait_for_timeout(1000)

            text = await new_page.inner_text("body")

            item = TenderItem()

            import re
            budget_match = re.search(r"预算[：:]\s*([\d.]+)\s*万?", text)
            if budget_match:
                item.budget = budget_match.group(1)

            deadline_match = re.search(r"报名截止[：:]\s*(\d{4}[-年]\d{1,2}[-月]\d{1,2}[^日时分]*日?\s*\d{0,2}[时:]?\d{0,2}[分:]?\d{0,2})", text)
            if deadline_match:
                item.deadline = deadline_match.group(1)

            bid_time_match = re.search(r"开标时间[：:]\s*(\d{4}[-年]\d{1,2}[-月]\d{1,2}[^日时分]*日?\s*\d{0,2}[时:]?\d{0,2}[分:]?\d{0,2})", text)
            if bid_time_match:
                item.bid_time = bid_time_match.group(1)

            bidder_match = re.search(r"招标人[：:]\s*(.+?)[\n,，。；;]", text)
            if bidder_match:
                item.bidder = bidder_match.group(1).strip()

            price_match = re.search(r"标书[售价价格费][：:]\s*(.+?)[\n,，。；;]", text)
            if price_match:
                item.doc_price = price_match.group(1).strip()

            return item
        except Exception as e:
            self.logger.warning(f"Parse detail failed for {url}: {e}")
            return None
        finally:
            await new_page.close()
```

- [ ] **Step 2: Commit**

```bash
git add src/scraper/chinabidding.py
git commit -m "feat: add ChinaBidding scraper implementation"
```

---

### Task 7: 其余9个网站爬虫（骨架实现）

**Files:**
- Create: `src/scraper/yuanbo.py`
- Create: `src/scraper/mobile.py`
- Create: `src/scraper/unicom.py`
- Create: `src/scraper/tower.py`
- Create: `src/scraper/telecom.py`
- Create: `src/scraper/csg.py`
- Create: `src/scraper/sgcc.py`
- Create: `src/scraper/cnncecp.py`
- Create: `src/scraper/scbid.py`

每个爬虫遵循相同模式：继承BaseScraper，实现login/search/parse_detail。由于每个网站结构不同，先创建骨架，后续根据实际页面调试完善选择器。

- [ ] **Step 1: 创建 src/scraper/mobile.py**

```python
from datetime import datetime
from typing import Optional

from playwright.async_api import Page

from src.scraper.base import BaseScraper, TenderItem
from src.scraper.captcha import solve_captcha_from_element


class MobileScraper(BaseScraper):
    async def login(self, page: Page) -> bool:
        await page.goto(self.url)
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(2000)

        try:
            await page.fill('input[name*="user"], input[name*="login"], input[placeholder*="用户名"]', self.username)
            await page.fill('input[type="password"]', self.password)
        except Exception as e:
            self.logger.error(f"Fill credentials failed: {e}")
            return False

        if self.has_captcha:
            try:
                captcha_selector = "img[src*='captcha'], img[src*='verify'], img[src*='code'], #captchaImg"
                captcha_img = page.locator(captcha_selector)
                if await captcha_img.count() > 0:
                    code = await solve_captcha_from_element(page, captcha_selector)
                    captcha_input = page.locator('input[name*="captcha"], input[name*="verify"], input[placeholder*="验证码"]')
                    if await captcha_input.count() > 0:
                        await captcha_input.first.fill(code)
            except Exception as e:
                self.logger.warning(f"Captcha handling failed: {e}")

        submit = page.locator('button[type="submit"], input[type="submit"], .login-btn, text=登录')
        if await submit.count() > 0:
            await submit.first.click()

        await page.wait_for_timeout(3000)
        return True

    async def search(self, page: Page, keyword: str, category: str) -> list[TenderItem]:
        items: list[TenderItem] = []
        try:
            search_input = page.locator('input[name*="keyword"], input[name*="search"], input[placeholder*="搜索"], input[placeholder*="关键字"]')
            if await search_input.count() > 0:
                await search_input.first.fill(keyword)
                search_btn = page.locator('button:has-text("搜索"), button:has-text("查询"), .search-btn')
                if await search_btn.count() > 0:
                    await search_btn.first.click()
                else:
                    await search_input.first.press("Enter")
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(2000)

            rows = page.locator("table tbody tr, .list-item, .result-item, .bid-list li, .search-result li")
            count = await rows.count()

            for i in range(min(count, 50)):
                try:
                    row = rows.nth(i)
                    link_el = row.locator("a")
                    if await link_el.count() == 0:
                        continue
                    href = await link_el.first.get_attribute("href") or ""
                    title = await link_el.first.inner_text() or ""
                    if not href.startswith("http"):
                        href = self.url.rstrip("/") + "/" + href.lstrip("/")

                    items.append(TenderItem(
                        date=datetime.now().strftime("%Y-%m-%d"),
                        category=category,
                        project_name=title.strip(),
                        link=href,
                        source_site=self.site_name,
                    ))
                except Exception:
                    continue
        except Exception as e:
            self.logger.error(f"Search failed: {e}")

        return items

    async def parse_detail(self, page: Page, url: str) -> Optional[TenderItem]:
        new_page = await page.context.new_page()
        try:
            await new_page.goto(url, timeout=15000)
            await new_page.wait_for_load_state("networkidle")
            text = await new_page.inner_text("body")

            item = TenderItem()
            import re
            budget_match = re.search(r"预算[：:]\s*([\d.]+)\s*万?", text)
            if budget_match:
                item.budget = budget_match.group(1)
            deadline_match = re.search(r"报名截止[：:]\s*(\d{4}[-年]\d{1,2}[-月]\d{1,2}[^日时分]*日?\s*\d{0,2}[时:]?\d{0,2}[分:]?\d{0,2})", text)
            if deadline_match:
                item.deadline = deadline_match.group(1)
            bid_time_match = re.search(r"开标时间[：:]\s*(\d{4}[-年]\d{1,2}[-月]\d{1,2}[^日时分]*日?\s*\d{0,2}[时:]?\d{0,2}[分:]?\d{0,2})", text)
            if bid_time_match:
                item.bid_time = bid_time_match.group(1)
            bidder_match = re.search(r"招标人[：:]\s*(.+?)[\n,，。；;]", text)
            if bidder_match:
                item.bidder = bidder_match.group(1).strip()
            price_match = re.search(r"标书[售价价格费][：:]\s*(.+?)[\n,，。；;]", text)
            if price_match:
                item.doc_price = price_match.group(1).strip()
            return item
        except Exception:
            return None
        finally:
            await new_page.close()
```

- [ ] **Step 2: 创建其余8个爬虫文件**

每个文件结构相同，类名和site_id不同。创建 `yuanbo.py` (YuanboScraper), `unicom.py` (UnicomScraper), `tower.py` (TowerScraper), `telecom.py` (TelecomScraper), `csg.py` (CsgScraper), `sgcc.py` (SgccScraper), `cnncecp.py` (CnncecpScraper), `scbid.py` (ScbidScraper)。

每个文件复制mobile.py的结构，修改：
- 类名
- `self.url` 已由BaseScraper从config设置
- scbid.py 的 `login_required=False`，login方法直接返回True

- [ ] **Step 3: Commit**

```bash
git add src/scraper/
git commit -m "feat: add all 10 site scraper implementations"
```

---

### Task 8: 数据处理模块（过滤 + 去重 + 格式化）

**Files:**
- Create: `src/processor/__init__.py`
- Create: `src/processor/filter.py`
- Create: `src/processor/dedup.py`
- Create: `src/processor/formatter.py`
- Create: `tests/__init__.py`
- Create: `tests/test_filter.py`
- Create: `tests/test_dedup.py`
- Create: `tests/test_formatter.py`

- [ ] **Step 1: 创建 src/processor/filter.py**

```python
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
            if any(kw.lower() in combined_text for kw in keywords):
                logger.info(f"Blacklisted: [{item.category}] {item.project_name} (matched in {item.bidder})")
                continue
        filtered.append(item)
    return filtered
```

- [ ] **Step 2: 创建 src/processor/dedup.py**

```python
import json
import os
from src.scraper.base import TenderItem
from src.utils.logger import setup_logger

logger = setup_logger("dedup")


def deduplicate(items: list[TenderItem], seen_file: str = "data/seen.json") -> list[TenderItem]:
    seen = set()
    if os.path.exists(seen_file):
        with open(seen_file, "r", encoding="utf-8") as f:
            seen = set(json.load(f))

    unique = []
    for item in items:
        key = item.link or (item.project_name + item.bidder)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    os.makedirs(os.path.dirname(seen_file), exist_ok=True)
    with open(seen_file, "w", encoding="utf-8") as f:
        json.dump(list(seen), f, ensure_ascii=False)

    logger.info(f"Dedup: {len(items)} -> {len(unique)} (removed {len(items) - len(unique)})")
    return unique
```

- [ ] **Step 3: 创建 src/processor/formatter.py**

```python
from src.scraper.base import TenderItem


def format_for_feishu(items: list[TenderItem]) -> list[dict]:
    records = []
    for idx, item in enumerate(items, 1):
        record = {
            "日期": item.date,
            "编号": idx,
            "项目类别": item.category,
            "招标单位": item.bidder,
            "项目名称": item.project_name,
            "预算(万)": item.budget,
            "招标次数": item.bid_count or "第一次",
            "报名截止时间": item.deadline,
            "投标时间": item.bid_time,
            "链接": {"link": item.link, "text": item.project_name[:30]} if item.link else "",
            "标书价格": item.doc_price,
        }
        records.append(record)
    return records
```

- [ ] **Step 4: 创建 src/processor/__init__.py 和 tests/__init__.py**

空文件。

- [ ] **Step 5: 创建 tests/test_filter.py**

```python
from src.scraper.base import TenderItem
from src.processor.filter import apply_blacklist


def test_blacklist_filters_bank_in_performance_category():
    blacklist = {"绩效系统": ["银行", "医院"]}
    items = [
        TenderItem(category="绩效系统", bidder="招商银行", project_name="绩效管理系统采购"),
        TenderItem(category="绩效系统", bidder="某科技公司", project_name="绩效管理系统采购"),
        TenderItem(category="咨询", bidder="招商银行", project_name="管理咨询项目"),
    ]
    result = apply_blacklist(items, blacklist)
    assert len(result) == 2
    assert result[0].bidder == "某科技公司"
    assert result[1].bidder == "招商银行"


def test_blacklist_filters_hospital_in_performance_category():
    blacklist = {"绩效系统": ["银行", "医院"]}
    items = [
        TenderItem(category="绩效系统", bidder="某医院", project_name="绩效系统建设"),
    ]
    result = apply_blacklist(items, blacklist)
    assert len(result) == 0


def test_no_blacklist_for_consulting():
    blacklist = {"绩效系统": ["银行", "医院"]}
    items = [
        TenderItem(category="咨询", bidder="招商银行", project_name="管理咨询"),
    ]
    result = apply_blacklist(items, blacklist)
    assert len(result) == 1
```

- [ ] **Step 6: 创建 tests/test_dedup.py**

```python
from src.scraper.base import TenderItem
from src.processor.dedup import deduplicate
import json
import os
import tempfile


def test_dedup_removes_duplicate_links():
    with tempfile.TemporaryDirectory() as tmpdir:
        seen_file = os.path.join(tmpdir, "seen.json")
        items = [
            TenderItem(link="https://example.com/1", project_name="项目A", bidder="单位A"),
            TenderItem(link="https://example.com/1", project_name="项目A", bidder="单位A"),
            TenderItem(link="https://example.com/2", project_name="项目B", bidder="单位B"),
        ]
        result = deduplicate(items, seen_file)
        assert len(result) == 2


def test_dedup_persists_seen():
    with tempfile.TemporaryDirectory() as tmpdir:
        seen_file = os.path.join(tmpdir, "seen.json")
        items1 = [TenderItem(link="https://example.com/1", project_name="项目A", bidder="单位A")]
        deduplicate(items1, seen_file)

        items2 = [TenderItem(link="https://example.com/1", project_name="项目A", bidder="单位A")]
        result = deduplicate(items2, seen_file)
        assert len(result) == 0
```

- [ ] **Step 7: 创建 tests/test_formatter.py**

```python
from src.scraper.base import TenderItem
from src.processor.formatter import format_for_feishu


def test_format_produces_correct_keys():
    items = [TenderItem(date="2026-06-24", category="咨询", bidder="测试单位", project_name="测试项目", link="https://example.com")]
    result = format_for_feishu(items)
    assert len(result) == 1
    assert result[0]["日期"] == "2026-06-24"
    assert result[0]["项目类别"] == "咨询"
    assert result[0]["招标单位"] == "测试单位"
    assert result[0]["项目名称"] == "测试项目"
    assert result[0]["编号"] == 1
```

- [ ] **Step 8: 运行测试**

```bash
cd E:\Opencode\HB-tender && python -m pytest tests/ -v
```

Expected: All tests pass

- [ ] **Step 9: Commit**

```bash
git add src/processor/ tests/
git commit -m "feat: add data processing modules with tests"
```

---

### Task 9: 飞书多维表格输出模块

**Files:**
- Create: `src/output/__init__.py`
- Create: `src/output/feishu.py`

- [ ] **Step 1: 创建 src/output/feishu.py**

```python
import os
import json
import time
from typing import Optional

import httpx
from src.utils.logger import setup_logger
from src.utils.notify import send_feishu_alert

logger = setup_logger("feishu")

BASE_URL = "https://open.feishu.cn/open-apis"


class FeishuClient:
    def __init__(self):
        self.app_id = os.getenv("FEISHU_APP_ID", "")
        self.app_secret = os.getenv("FEISHU_APP_SECRET", "")
        self.app_token = os.getenv("FEISHU_BITABLE_APP_TOKEN", "")
        self.table_id = os.getenv("FEISHU_BITABLE_TABLE_ID", "")
        self._token: Optional[str] = None
        self._token_expires: float = 0

    def _get_tenant_token(self) -> str:
        if self._token and time.time() < self._token_expires:
            return self._token

        resp = httpx.post(
            f"{BASE_URL}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["tenant_access_token"]
        self._token_expires = time.time() + data.get("expire", 7200) - 300
        logger.info("Feishu tenant token refreshed")
        return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_tenant_token()}",
            "Content-Type": "application/json",
        }

    def create_records(self, records: list[dict]) -> bool:
        if not records:
            logger.info("No records to write")
            return True

        url = f"{BASE_URL}/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records/batch_create"

        batch_size = 10
        for i in range(0, len(records), batch_size):
            batch = records[i : i + batch_size]
            payload = {"records": [{"fields": r} for r in batch]}

            for attempt in range(3):
                try:
                    resp = httpx.post(url, headers=self._headers(), json=payload, timeout=30)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("code") == 0:
                            logger.info(f"Wrote batch {i // batch_size + 1}: {len(batch)} records")
                            break
                        else:
                            logger.warning(f"Feishu API error: {data.get('msg')}")
                    else:
                        logger.warning(f"Feishu HTTP {resp.status_code}")
                except Exception as e:
                    logger.error(f"Feishu write attempt {attempt + 1} failed: {e}")
                    if attempt == 2:
                        self._cache_failed_batch(batch)
                        send_feishu_alert(f"飞书写入失败: {str(e)[:200]}")
                    time.sleep(2)

        return True

    def _cache_failed_batch(self, batch: list[dict]) -> None:
        cache_dir = "data/cache"
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, f"failed_{int(time.time())}.json")
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(batch, f, ensure_ascii=False)
        logger.info(f"Cached failed batch to {cache_file}")

    def retry_cached(self) -> None:
        cache_dir = "data/cache"
        if not os.path.exists(cache_dir):
            return

        for filename in os.listdir(cache_dir):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(cache_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                batch = json.load(f)

            success = self.create_records(batch)
            if success:
                os.remove(filepath)
                logger.info(f"Retried and removed cache file: {filename}")
```

- [ ] **Step 2: 创建 src/output/__init__.py**

空文件。

- [ ] **Step 3: Commit**

```bash
git add src/output/
git commit -m "feat: add Feishu Bitable client with retry and cache"
```

---

### Task 10: 调度器 + 主入口

**Files:**
- Create: `src/scheduler.py`
- Create: `src/main.py`

- [ ] **Step 1: 创建 src/scheduler.py**

```python
import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Optional

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.scraper.base import BaseScraper, TenderItem
from src.scraper.chinabidding import ChinaBiddingScraper
from src.scraper.yuanbo import YuanboScraper
from src.scraper.mobile import MobileScraper
from src.scraper.unicom import UnicomScraper
from src.scraper.tower import TowerScraper
from src.scraper.telecom import TelecomScraper
from src.scraper.csg import CsgScraper
from src.scraper.sgcc import SgccScraper
from src.scraper.cnncecp import CnncecpScraper
from src.scraper.scbid import ScbidScraper
from src.processor.filter import apply_blacklist, load_blacklist
from src.processor.dedup import deduplicate
from src.processor.formatter import format_for_feishu
from src.output.feishu import FeishuClient
from src.utils.logger import setup_logger
from src.utils.notify import send_feishu_alert

logger = setup_logger("scheduler")

SCRAPER_MAP: dict[str, type[BaseScraper]] = {
    "chinabidding": ChinaBiddingScraper,
    "yuanbo": YuanboScraper,
    "mobile": MobileScraper,
    "unicom": UnicomScraper,
    "tower": TowerScraper,
    "telecom": TelecomScraper,
    "csg": CsgScraper,
    "sgcc": SgccScraper,
    "cnncecp": CnncecpScraper,
    "scbid": ScbidScraper,
}

LAST_RUN_FILE = "data/last_run.json"


def get_last_run() -> Optional[datetime]:
    if os.path.exists(LAST_RUN_FILE):
        with open(LAST_RUN_FILE, "r") as f:
            ts = json.load(f).get("last_run")
            if ts:
                return datetime.fromisoformat(ts)
    return None


def save_last_run() -> None:
    os.makedirs(os.path.dirname(LAST_RUN_FILE), exist_ok=True)
    with open(LAST_RUN_FILE, "w") as f:
        json.dump({"last_run": datetime.now().isoformat()}, f)


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

    semaphore = asyncio.Semaphore(3)

    async def scrape_site(site_config: dict) -> list[TenderItem]:
        async with semaphore:
            scraper_cls = SCRAPER_MAP.get(site_config["id"])
            if not scraper_cls:
                logger.warning(f"Unknown site: {site_config['id']}")
                return []
            scraper = scraper_cls(site_config)
            try:
                return await scraper.run(keywords_by_category, since)
            except Exception as e:
                logger.error(f"Scraper {site_config['id']} failed: {e}")
                send_feishu_alert(f"爬虫 **{site_config['name']}** 执行失败: {str(e)[:200]}")
                return []

    tasks = [scrape_site(cfg) for cfg in sites_config]
    results = await asyncio.gather(*tasks)
    for r in results:
        all_items.extend(r)

    logger.info(f"Total raw items: {len(all_items)}")

    filtered = apply_blacklist(all_items, blacklist)
    logger.info(f"After blacklist filter: {len(filtered)}")

    unique = deduplicate(filtered)
    logger.info(f"After dedup: {len(unique)}")

    if unique:
        records = format_for_feishu(unique)
        client = FeishuClient()
        client.retry_cached()
        client.create_records(records)
        logger.info(f"Wrote {len(records)} records to Feishu")
    else:
        logger.info("No new items to write")

    save_last_run()
    logger.info("Scrape job completed")


def start_scheduler() -> None:
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

    is_first = not os.path.exists(LAST_RUN_FILE)
    if is_first:
        logger.info("First run detected, will scrape last 3 days")
        scheduler.add_job(run_scrape, args=[True], id="first_run", max_instances=1)

    scheduler.add_job(
        run_scrape,
        args=[False],
        trigger=CronTrigger(hour="9-17/2", minute=0, timezone="Asia/Shanghai"),
        id="scheduled_scrape",
        max_instances=1,
        misfire_grace_time=300,
    )

    scheduler.start()
    logger.info("Scheduler started (Beijing time 9:00-17:00 every 2 hours: 9,11,13,15,17)")

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
```

- [ ] **Step 2: 创建 src/main.py**

```python
from dotenv import load_dotenv

load_dotenv()

from src.scheduler import start_scheduler

if __name__ == "__main__":
    start_scheduler()
```

- [ ] **Step 3: Commit**

```bash
git add src/scheduler.py src/main.py
git commit -m "feat: add scheduler and main entry point"
```

---

### Task 11: 部署脚本

**Files:**
- Create: `sync-to-server.ps1`

- [ ] **Step 1: 创建 sync-to-server.ps1**

```powershell
param(
    [switch]$Deploy
)

$Server = "root@47.250.95.61"
$Key = "$env:USERPROFILE\.ssh\aliyun_server"
$RemoteDir = "~/hb-tender"
$LocalDir = $PSScriptRoot

Write-Host "Syncing to server..." -ForegroundColor Cyan

# rsync via WSL or scp
$exclude = @(".env", "__pycache__", "*.pyc", "data/", ".git")

$excludeArgs = $exclude | ForEach-Object { "-e '$_'" }

# Use scp for Windows compatibility
ssh -i $Key $Server "mkdir -p $RemoteDir"

# Copy files using scp (exclude .env and data)
Get-ChildItem -Path $LocalDir -Recurse -File |
    Where-Object {
        $_.FullName -notlike "*\.env" -and
        $_.FullName -notlike "*__pycache__*" -and
        $_.FullName -notlike "*\data\*" -and
        $_.FullName -notlike "*\.git\*"
    } | ForEach-Object {
        $relativePath = $_.FullName.Substring($LocalDir.Length + 1).Replace("\", "/")
        $remotePath = "$RemoteDir/$relativePath"
        $remoteDir = Split-Path -Parent $remotePath
        ssh -i $Key $Server "mkdir -p $remoteDir"
        scp -i $Key $_.FullName "${Server}:${remotePath}"
    }

Write-Host "Sync complete!" -ForegroundColor Green

if ($Deploy) {
    Write-Host "Deploying on server..." -ForegroundColor Cyan
    ssh -i $Key $Server @"
        cd $RemoteDir
        docker compose down 2>/dev/null || true
        docker compose build --no-cache
        docker compose up -d
        docker compose ps
"@
    Write-Host "Deploy complete!" -ForegroundColor Green
}
```

- [ ] **Step 2: Commit**

```bash
git add sync-to-server.ps1
git commit -m "feat: add deployment sync script"
```

---

### Task 12: 端到端测试与调试

**Files:**
- Modify: 各爬虫文件的选择器（根据实际页面调试）

- [ ] **Step 1: 本地构建Docker镜像**

```bash
cd E:\Opencode\HB-tender
docker build -t hb-tender .
```

- [ ] **Step 2: 配置 .env 文件**

填入实际的2Captcha API Key、飞书凭证、网站凭证。

- [ ] **Step 3: 本地运行单次抓取测试**

```bash
docker run --rm --env-file .env hb-tender python -c "
from dotenv import load_dotenv; load_dotenv()
import asyncio
from src.scheduler import run_scrape
asyncio.run(run_scrape(is_first_run=True))
"
```

- [ ] **Step 4: 检查飞书多维表格是否写入成功**

- [ ] **Step 5: 根据实际页面调整各爬虫的CSS选择器**

逐个网站调试，修正login/search/parse_detail中的选择器。

- [ ] **Step 6: 部署到阿里云**

```powershell
.\sync-to-server.ps1 -Deploy
```

- [ ] **Step 7: 验证服务器运行**

```bash
ssh -i ~/.ssh/aliyun_server root@47.250.95.61 "docker logs hb-tender-tender-scraper-1 --tail 50"
```

- [ ] **Step 8: Commit 最终调整**

```bash
git add .
git commit -m "fix: adjust selectors based on live testing"
```
