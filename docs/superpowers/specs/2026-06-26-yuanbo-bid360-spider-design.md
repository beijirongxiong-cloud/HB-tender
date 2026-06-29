# 元博网（bid360.com.cn）招标公告爬虫设计

**日期**: 2026-06-26
**目标**: 单独调试元博网爬虫，抓取招标公告并写入飞书 Excel 云文档

---

## 1. 背景与现状

### 1.1 元博网入口分析

元博网与中国招标网（chinabidding.cn）共享会员体系、CDN 静态资源（`cdn.chinabidding.cn`）和账号系统，但反爬强度不同：

| 入口 | 实际指向 | WAF JS Challenge | 列表抓取难度 |
|------|----------|------------------|--------------|
| `www.bid360.com.cn` | 元博网主页 | ❌ 无 | 低（普通 GET 可拿完整 HTML） |
| `www.sbiao360.com` | 302 → `gxq.chinabidding.cn` | ✅ 有阿里云 WAF | 高 |
| `www.chinabidding.cn` | 中国招标网主页 | ✅ 有阿里云 WAF | 高 |

**结论**：以 `bid360.com.cn` 作为主入口，反爬最弱，稳定性最高。

### 1.2 现有代码基础

项目已有 scraper 框架：
- `src/scraper/base.py` — `BaseScraper` 抽象基类 + `TenderItem` dataclass
- `src/scraper/scrapling_base.py` — `ScraplingScraper` 基于 Scrapling 的实现基类
- `src/scraper/chinabidding.py` — 中国招标网 scraper（含登录、搜索、详情解析逻辑可复用）
- `src/scraper/yuanbo.py` — 现有 yuanbo.py 实际通过 chinabidding 搜索，非真正 bid360 入口
- `src/processor/filter.py` — 黑名单 + 关键词筛选
- `src/processor/formatter.py` — 飞书字段格式化
- `src/output/feishu_sheet.py` — 飞书 Excel 云文档写入（11 列标准字段）
- `config/keywords.yaml` — 关键词分类 + 黑名单配置
- `config/sites.yaml` — 站点配置（yuanbo 站 url 需更新为 bid360.com.cn）

### 1.3 验证过的事实

1. `bid360.com.cn` 普通 GET 直接返回完整 HTML，无 `acw_sc__v2` / `aliyun_waf_aa` challenge
2. `bid360.com.cn/public/2020/html/login.html` 有独立登录页，含用户名、密码、验证码输入框
3. 首页登录按钮 `onclick="loginTo()"`，登录链接 `https://www.bid360.com.cn/public/2020/html/login.html?source=2&url=/yuan/login/loginnew/tobussroom`
4. 招标列表通过 `javascript:ajaxlink(...)` 动态加载
5. 详情页部分在 bid360 域名内（如 `/zbgs/U-vz22BFB.html`），部分跳转 chinabidding.cn
6. `bid360.com.cn/public/2020/html/channel.html?channel_id={id}` 是行业频道入口，包含招标列表

---

## 2. 目标与非目标

### 2.1 目标
- 抓取元博网**招标公告**类目
- 按**关键词**匹配项目
- 只保留**最近 1 天**发布的项目
- 用**黑名单**排除不需要的标题/单位
- 登录会员后从**详情页**提取完整字段
- 结果写入**飞书 Excel 云文档**
- **先手动跑通**，暂不接入定时任务

### 2.2 非目标
- 不抓中标公告、变更公告等其他类目
- 不做增量去重（后续接入 scheduler 再做）
- 不做代理轮换（调试阶段用单 IP）
- 不重构现有 chinabidding.py

---

## 3. 抓取流程

```
1. 登录 bid360.com.cn（获取会员 cookie）
        ↓
2. 访问招标公告频道页 / 列表接口
        ↓
3. 加载招标列表（处理 ajaxlink 动态加载）
        ↓
4. 列表阶段粗筛：
   - 只保留"招标公告"标签
   - 标题命中关键词
   - 发布日期 >= 今天 - 1 天
   - 标题/单位不在黑名单
        ↓
5. 并发进入详情页（bid360 域名内 + 跳转 chinabidding 的）
        ↓
6. 详情页解析：预算、截止时间、投标时间、标书价格、招标单位等
        ↓
7. 格式化 → 写入飞书 Excel 云文档
```

---

## 4. 组件设计

### 4.1 YuanboBid360Scraper 类

新建 `src/scraper/yuanbo_bid360.py`，继承 `ScraplingScraper`。

**职责**：
- `login(page)` — 在 bid360.com.cn 登录页填表单、解验证码、提交
- `_do_search(fetcher, keyword, category)` — 抓取招标公告列表
- `_do_fetch_details(items)` — 并发抓取详情页
- `_parse_bid360_detail(page, url)` — 解析 bid360 域名详情页
- `_parse_chinabidding_detail(page, url)` — 解析 chinabidding 域名详情页（复用现有逻辑）

**关键方法签名**：
```python
class YuanboBid360Scraper(ScraplingScraper):
    LOGIN_URL = "https://www.bid360.com.cn/public/2020/html/login.html"
    CHANNEL_URL = "https://www.bid360.com.cn/public/2020/html/channel.html?channel_id={id}"
    
    async def login(self, page) -> bool: ...
    def _do_search(self, fetcher, keyword: str, category: str) -> list[TenderItem]: ...
    def _do_fetch_details(self, items: list[TenderItem]) -> list[TenderItem]: ...
```

### 4.2 登录策略

- 环境变量：`YUANBO_USERNAME` / `YUANBO_PASSWORD`（已在 .env 中）
- 登录 URL：`https://www.bid360.com.cn/public/2020/html/login.html`
- 表单字段：用户名输入框、密码输入框、验证码输入框（需确认实际 id/name）
- 验证码：复用 `src/scraper/captcha.py` 的 `solve_captcha()`（2captcha）
- 登录成功判定：页面出现"我的商务室"或 URL 跳离登录页
- 登录态持久化：保存 cookie，后续请求复用

### 4.3 列表抓取策略

**优先方案**：分析 `ajaxlink(...)` 调用的实际 AJAX 接口，直接请求 JSON 数据接口（最快）。

**备选方案**：用 Scrapling `DynamicFetcher` / `StealthyFetcher` 渲染页面，等待列表 DOM 加载完成后用 CSS 选择器提取。

**列表字段提取**：
- 标题（`<a>` 文本）
- 详情链接（`<a href>`，可能是 `/zbgs/xxx.html` 或 `javascript:ajaxlink(...)`）
- 发布日期（列表项中的日期文本）
- 地区/行业标签（如有）

**频道 ID 映射**：需要实测 `channel.html?channel_id={id}` 各 id 对应的行业，找到"招标公告"总入口或按行业遍历。

### 4.4 筛选器（列表阶段）

复用 `src/processor/filter.py`，按顺序应用：

1. **类目过滤**：只保留标题/标签含"招标公告"的项目（排除"中标公告""变更公告"）
2. **关键词过滤**：`apply_keyword_strict_filter()` — 标题命中 `keywords.yaml` 中任一关键词
3. **时间过滤**：`item.date >= today - 1 day`
4. **黑名单过滤**：`apply_blacklist()` — 标题/招标单位命中黑名单则丢弃

**效率优化**：列表阶段就完成全部筛选，只对通过筛选的项目请求详情页，减少 80%+ 的详情请求。

### 4.5 详情页解析

详情页有两种域名，分别解析：

**bid360.com.cn/zbgs/xxx.html**：
- 用 `.info_table` 表格提取结构化字段
- 用 `.xq_nr` 正文区域做正则 fallback
- 字段映射：招标人/采购人 → bidder，开标时间 → bid_time，报名截止 → deadline，预算 → budget，标书售价 → doc_price

**chinabidding.cn 详情页**：
- 复用 `chinabidding.py` 中已有的 JS evaluate 解析逻辑（`_scrapling_fetch_details` 中的 `page.evaluate`）
- 用同一套 cookie 访问（元博网登录态共享）

**正则 fallback 模式**（复用现有）：
- 预算：`(预算|预算金额|项目预算|采购金额)[：:(]\s*[¥￥]?\s*(\d+\.?\d*)\s*万元?`
- 截止时间：`(报名|获取)[^<]{0,20}(截止|期限)[^<]{0,20}[：:]?\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}...)`
- 开标时间：`开标[^<]{0,20}时间[：:]?\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}...)`
- 标书售价：`标书[售价格]*[：:]\s*[¥￥]?\s*(\d+\.?\d*)\s*元`

### 4.6 输出

复用 `src/output/feishu_sheet.py` 的 `FeishuSpreadsheetClient.create_records()`。

字段映射（`src/processor/formatter.py` 的 `format_for_feishu`）：

| 飞书列 | TenderItem 字段 | 来源 |
|--------|-----------------|------|
| 序号 | 自动编号 | 程序生成 |
| 添加时间 | 当前时间戳 | 程序生成 |
| 项目类目 | category | 关键词分类 |
| 项目名称 | project_name + link | 列表页 |
| 招标单位 | bidder | 详情页 / 标题正则 |
| 投标平台 | source_site | "元博网" |
| 招标次数 | bid_count | 标题正则 |
| 报名截止时间 | deadline | 详情页 |
| 投标时间 | bid_time | 详情页 |
| 预算(万) | budget | 详情页 |
| 标书价格 | doc_price | 详情页 |

### 4.7 调试入口脚本

新建 `debug_yuanbo_bid360.py`（项目根目录），用于手动运行：

```python
"""手动调试元博网爬虫：登录 → 搜索 → 筛选 → 详情 → 飞书"""
import asyncio
from src.scraper.yuanbo_bid360 import YuanboBid360Scraper
from src.processor.filter import apply_blacklist, apply_keyword_strict_filter, load_blacklist
from src.processor.formatter import format_for_feishu
from src.output.feishu_sheet import FeishuSpreadsheetClient
from config.keywords_config import load_keywords  # 或直接读 yaml

async def main():
    site_config = {
        "id": "yuanbo",
        "name": "元博网",
        "url": "https://www.bid360.com.cn",
        "env_username": "YUANBO_USERNAME",
        "env_password": "YUANBO_PASSWORD",
        "has_captcha": True,
        "captcha_type": "image",
        "login_required": True,
    }
    scraper = YuanboBid360Scraper(site_config)
    keywords_by_category = load_keywords("config/keywords.yaml")
    blacklist = load_blacklist("config/keywords.yaml")
    
    # 1. 搜索
    items = await scraper.run(keywords_by_category, since=<today-1day>)
    # 2. 筛选
    items = apply_keyword_strict_filter(items, keywords_by_category)
    items = apply_blacklist(items, blacklist)
    # 3. 详情
    items = await scraper.run_with_details(keywords_by_category, since, filtered_items=items)
    # 4. 输出
    records = format_for_feishu(items)
    FeishuSpreadsheetClient().create_records(records)
    
    print(f"完成：抓取 {len(items)} 条，已写入飞书")

asyncio.run(main())
```

---

## 5. 配置变更

### 5.1 config/sites.yaml

更新 yuanbo 站点 url：
```yaml
- id: yuanbo
  name: 元博网
  url: https://www.bid360.com.cn    # 从 sbiao360.com 改为 bid360.com.cn
  env_username: YUANBO_USERNAME
  env_password: YUANBO_PASSWORD
  has_captcha: true
  captcha_type: image
  login_required: true
```

### 5.2 config/keywords.yaml

现有配置已满足需求（咨询/培训/绩效系统三类关键词 + 绩效系统黑名单），暂不改动。

---

## 6. 效率优化措施

| 措施 | 预期提效 |
|------|----------|
| 列表阶段完成全部筛选，只请求通过项的详情页 | 减少 80%+ 详情请求 |
| 优先分析 AJAX 接口直接拿 JSON，避免浏览器渲染 | 列表抓取快 10x |
| 详情页并发（线程池 max_workers=5） | 详情抓取快 5x |
| 复用登录 cookie，不重复登录 | 减少登录开销 |
| bid360 入口无 WAF，普通 HTTP 即可 | 无需浏览器执行 JS challenge |

---

## 7. 错误处理

- **登录失败**：重试 1 次，仍失败则记录日志并退出
- **验证码识别失败**：刷新验证码重试，最多 3 次
- **详情页超时**：跳过该条，记录日志，继续下一条
- **飞书写入失败**：复用现有 `_cache_failed_batch` 缓存机制，后续可重试
- **网络超时**：单页超时 30s，整体超时按 item 数量动态计算

---

## 8. 验证标准

1. 能成功登录 bid360.com.cn（页面出现"我的商务室"或跳离登录页）
2. 能抓到招标公告列表（至少 10 条/页）
3. 筛选后只剩关键词匹配 + 最近 1 天 + 非黑名单的项目
4. 详情页能提取到 bidder / deadline / bid_time / budget / doc_price 中至少 2 个字段
5. 结果成功写入飞书 Excel 云文档，字段对齐 11 列

---

## 9. 待实现时确认的事项

以下需在实现阶段实测确认，不影响设计批准：

1. bid360 登录表单的实际 input id/name（需 inspect 登录页 DOM）
2. `ajaxlink(...)` 的实际 AJAX 接口 URL 和参数
3. `channel.html?channel_id={id}` 各 id 对应行业，哪个是"招标公告"总入口
4. bid360 详情页 `/zbgs/xxx.html` 的 DOM 结构（.info_table 是否存在）
5. 登录 bid360 后访问 chinabidding 详情页是否免登录（cookie 域共享情况）
