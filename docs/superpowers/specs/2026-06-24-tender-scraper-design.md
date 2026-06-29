# 招标信息抓取系统 — 设计文档

## 概述

自动从10个招标网站抓取招标信息，按关键词搜索、过滤、去重后写入飞书多维表格。北京时间9:00-17:00每2小时执行一次，首次抓取近3天数据。

## 技术栈

- **语言**: Python 3.11
- **浏览器自动化**: Playwright (headless Chromium)
- **验证码识别**: 2Captcha API
- **定时调度**: APScheduler
- **输出**: 飞书多维表格 (Bitable API)
- **部署**: Docker → 阿里云服务器 (47.250.95.61)
- **通知**: 飞书Webhook机器人

## 系统架构

```
阿里云 Docker 容器
├── Scheduler (APScheduler, 北京时间9:00-17:00每2小时)
├── Scraper Engine (Playwright, 并发3)
│   ├── 2Captcha (验证码识别, 重试3次)
│   └── 10个网站爬虫模块
├── Data Processor (过滤/去重/格式化)
├── Feishu Output (多维表格写入)
├── .env (加密凭证, 不入Git)
└── Feishu Notify (异常通知)
```

## 项目结构

```
HB-tender/
├── docker-compose.yml
├── Dockerfile
├── .env                    # 加密存储凭证（不入Git）
├── .env.example            # 模板文件
├── .gitignore
├── requirements.txt
├── config/
│   ├── sites.yaml          # 招标网站配置（URL、选择器）
│   └── keywords.yaml       # 搜索关键词 + 黑名单
├── src/
│   ├── main.py             # 入口：启动调度器
│   ├── scheduler.py        # APScheduler 定时任务
│   ├── scraper/
│   │   ├── base.py         # BaseScraper 抽象类
│   │   ├── captcha.py      # 2Captcha 验证码处理
│   │   ├── chinabidding.py # 中国采购与招标网
│   │   ├── yuanbo.py       # 元博网
│   │   ├── mobile.py       # 中国移动采购与招标网
│   │   ├── unicom.py       # 中国联通合作方门户
│   │   ├── tower.py        # 中国铁塔电子采购平台
│   │   ├── telecom.py      # 中国电信电子采购系统
│   │   ├── csg.py          # 中国南方电网
│   │   ├── sgcc.py         # 国家电网
│   │   ├── cnncecp.py      # 中核集团
│   │   └── scbid.py        # 四川招投标网
│   ├── processor/
│   │   ├── filter.py       # 黑名单过滤（银行/医院）
│   │   ├── dedup.py        # 去重（URL + 项目名称）
│   │   └── formatter.py    # 数据格式化
│   ├── output/
│   │   └── feishu.py       # 飞书多维表格写入
│   └── utils/
│       ├── logger.py       # 日志
│       └── notify.py       # 异常通知（飞书机器人）
└── tests/
```

## 目标网站（10个）

| 序号 | 平台名称 | 网址 |
|------|---------|------|
| 1 | 中国采购与招标网 | https://www.chinabidding.cn/ |
| 2 | 元博网 | https://www.sbiao360.com |
| 3 | 中国移动采购与招标网 | https://b2b.10086.cn/b2b/main/preIndex.html |
| 4 | 中国联通合作方门户 | https://www.cuecp.cn/portal/index.jhtml |
| 5 | 中国铁塔电子采购平台 | https://ebid.chinatowercom.cn/ |
| 6 | 中国电信电子采购系统 | https://trade.chinatelecom.com.cn/TPFrameDX/customframe4bid/login_TP |
| 7 | 中国南方电网电子采购交易平台 | https://ecsg.com.cn/ |
| 8 | 国家电网电子商务平台 | https://ecp.sgcc.com.cn/ (待验证) |
| 9 | 中核集团电子商务平台 | https://one.cnncecp.com/cnnc-pm-web/#/portal |
| 10 | 四川招投标网 | http://www.scbid.com/zh/news/web_zbxx_6.shtml |

## 搜索关键词

### 咨询类 (22个)
管理咨询项目/服务、优化管理咨询/体系/提升、管理提升咨询、管理诊断、流程管理咨询、制度流程管理、流程梳理/优化/制度、企业文化建设项目、企业文化体系、企业文化管理咨询、人力资源管理咨询/体系/优化、薪酬管理、薪酬与绩效、绩效管理咨询、绩效考核管理咨询、绩效体系咨询、薪酬管理体系、定岗定编、岗位价值评估、薪酬激励体系、组织管控、激励机制

### 培训类 (13个)
入库/入围服务、培训机构/供应商、培训项目/服务、员工培训/赋能、管理能力、管理提升、政企业务、新员工入职培训、内训师、AI赋能、团队拓展、培训提升、能力素质/提升

### 绩效系统类 (8个)
绩效管理系统、绩效考核系统、绩效系统、绩效管理平台、绩效管理软件、绩效考核管理系统、绩效管理信息系统、绩效软件

## 输出格式（飞书多维表格）

| 字段 | 飞书列名 | 类型 |
|------|---------|------|
| 日期 | 日期 | 日期 |
| 序号 | 编号 | 数字 |
| 项目类别 | 项目类别 | 单选（咨询/培训/绩效系统） |
| 招标单位 | 招标单位 | 文本 |
| 项目名称 | 项目名称 | 文本 |
| 项目预算(万) | 预算(万) | 数字 |
| 招标次数 | 招标次数 | 单选（第一次/第二次/...） |
| 报名截止时间 | 报名截止时间 | 文本 |
| 投标时间 | 投标时间 | 文本 |
| 链接 | 链接 | 超链接 |
| 标书价格 | 标书价格 | 文本 |

## 黑名单规则

- **适用类别**: 绩效系统
- **过滤关键词**: 银行、医院、医疗、诊所、卫生院
- **匹配范围**: 招标单位 + 项目名称
- **配置方式**: config/keywords.yaml 中的 blacklist 字段

## 核心流程

1. Scheduler在北京时间9:00、11:00、13:00、15:00、17:00触发
2. 并发3个网站同时抓取
3. Playwright打开网站 → 2Captcha解验证码 → 登录
4. 按3类关键词搜索
5. 解析搜索结果 → 进入详情页提取字段
6. 过滤：去重(URL+项目名称) + 黑名单
7. 写入飞书多维表格
8. 异常时飞书机器人通知

## 定时策略

- 执行时间：北京时间 9:00-17:00，每2小时一次（9:00、11:00、13:00、15:00、17:00）
- 时区：Asia/Shanghai（CronTrigger timezone参数）
- 首次运行：抓取近3天数据
- 后续运行：只抓取上次运行之后的新数据（记录 last_run 时间戳）
- 存储位置：data/last_run.json

## 凭证安全

- 所有敏感信息存 .env 文件
- .env 写入 .gitignore
- 提供 .env.example 模板
- Docker通过 env_file 加载

## 容错机制

- 单网站失败不影响其他网站
- 验证码识别失败重试3次
- 飞书写入失败本地缓存(data/cache/)，下次重试
- 所有异常飞书Webhook通知

## 部署

- Docker Compose部署到阿里云 (47.250.95.61)
- 同步脚本: sync-to-server.ps1
- 端口: 无需对外暴露（纯后台任务）
