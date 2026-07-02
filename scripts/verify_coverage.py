"""
Verify coverage: compare our Feishu sheet data vs competitor's Tencent Docs data.
Calculates coverage rate, identifies missing projects, and analyzes root causes.
"""
import sys, os, json, re
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def normalize(s):
    s = re.sub(r'[\s\u3000]+', '', s)
    s = re.sub(r'[（）\(\)【】\[\]{}]', '', s)
    s = s.lower()
    return s

SUFFIXES = r'(招标公告|采购公告|竞争性谈判公告|磋商公告|询比采购公告|公开招标公告|谈判采购公告|单一来源采购公告|询价采购公告|竞标公告|邀请招标公告|公开竞争性谈判公告|成交公告|中标公告|结果公示|候选人公示|事前公示|预公告|预告|寻源公告|征集公告|公告|公示|延期公告|变更公告|更正公告)$'

def title_core(s):
    n = normalize(s)
    n = re.sub(SUFFIXES, '', n)
    n = re.sub(r'(第[一二三四五六七八九十\d]+次?|二次|三次|重新|第\d+次)', '', n)
    return n

def title_key(s):
    return title_core(s)[:30]

def is_substring_match(competitor_name, our_names_normalized):
    cn = title_core(competitor_name)
    for on in our_names_normalized:
        if len(cn) >= 6 and (cn in on or on in cn):
            return True
        # Check if core content overlaps (at least 8 continuous chars match)
        if len(cn) >= 8:
            for i in range(len(cn) - 7):
                sub = cn[i:i+8]
                if sub in on:
                    return True
    return False

# Load our Feishu data
with open(os.path.join(BASE_DIR, 'feishu_projects.json'), 'r', encoding='utf-8') as f:
    our_projects = json.load(f)

# Load competitor data (from analyze_tencent.py)
sys.path.insert(0, BASE_DIR)
from analyze_tencent import tencent_data

competitor_projects = []
for name, org, platform in tencent_data:
    competitor_projects.append({'name': name, 'org': org, 'platform': platform})

print("=" * 70)
print("HB-Tender Coverage Verification Report")
print("=" * 70)

print(f"\nOur Feishu sheet: {len(our_projects)} items")
print(f"Competitor Tencent Docs: {len(competitor_projects)} items")

# Build title-key index for our projects
our_keys = {}
for p in our_projects:
    key = title_key(p['name'])
    our_keys[key] = our_keys.get(key, 0) + 1

our_key_set = set(our_keys.keys())
our_unique = len(our_key_set)

print(f"\nOur unique project keys: {our_unique}")
print(f"Competitor unique projects: {len(competitor_projects)}")

# Build normalized name list for substring matching
our_names_normalized = [title_core(p['name']) for p in our_projects]

# Match competitor projects against our data
matched = []
missing = []
blacklisted = []

# Also check org-based matching for very short names
our_org_index = {}
for p in our_projects:
    org_norm = normalize(p['org'])
    if org_norm:
        our_org_index.setdefault(org_norm[:10], []).append(title_core(p['name']))

BLACKLIST_ORG_PATTERNS = [
    r'局$', r'厅$', r'委$', r'办$', r'人民政府', r'海事局', r'交通局', r'教育局',
    r'消防', r'安全局', r'公安局', r'应急管',
]
BLACKLIST_TITLE_PATTERNS = [
    r'消防安全', r'消防演练', r'消防技能', r'灭火',
    r'学校', r'学院', r'大学', r'中学', r'小学', r'幼儿园',
    r'政府培训', r'干部远程教育',
]

# Platform mapping: competitor platform -> our scraper
PLATFORM_MAP = {
    'ctbpsp.com': '中招联合(ctbpsp)',
    'chinabidding.cn': '中国采购与招标网',
    'zjzcw.iccec.cn': '中交招采网(iccec)',
    'sp.iccec.cn': '中交招采网(iccec)',
}

# Infer platform from org name
def infer_platform(org, name):
    if '中国移动' in org or '移动' in org and '通信' in org:
        return '中国移动采购与招标网'
    if '中国联通' in org or '联通' in org:
        return '中国联通合作方门户'
    if '中国电信' in org:
        return '中国电信电子采购系统'
    if '中国铁塔' in org:
        return '中国铁塔电子采购平台'
    if '华能' in org:
        return '华能电子商务平台'
    if '华电' in org:
        return '华电(不可达)'
    if '国家能源' in org or '国能' in org:
        return '国能e招'
    if '国电投' in org or '国家电投' in org:
        return '国电投(不可达)'
    if '中交' in org:
        return '中交招采网(iccec)'
    if '南方电网' in org or '南网' in org:
        return '中国南方电网'
    if '国家电网' in org or '国网' in org:
        return '国家电网(sgcc)'
    return None

def is_blacklisted(name, org):
    for pat in BLACKLIST_ORG_PATTERNS:
        if re.search(pat, org):
            if '公司' not in org and '集团' not in org and '银行' not in org:
                return True
    for pat in BLACKLIST_TITLE_PATTERNS:
        if re.search(pat, name) or re.search(pat, org):
            return True
    return False

for cp in competitor_projects:
    name = cp['name']
    org = cp['org']
    platform = cp['platform']

    key = title_key(name)

    if is_blacklisted(name, org):
        blacklisted.append(cp)
        continue

    if key in our_key_set:
        matched.append(cp)
    elif is_substring_match(name, our_names_normalized):
        matched.append(cp)
    else:
            # Determine which platform it should come from
            source = PLATFORM_MAP.get(platform, '')
            if not source:
                source = infer_platform(org, name) or 'chinabidding或其他'
            cp['source_platform'] = source
            missing.append(cp)

print(f"\n{'='*70}")
print("Coverage Summary")
print(f"{'='*70}")
total_relevant = len(matched) + len(missing)
coverage_rate = len(matched) / total_relevant * 100 if total_relevant > 0 else 0
print(f"Blacklisted (gov/fire/school): {len(blacklisted)} items (excluded from coverage)")
print(f"Relevant competitor items: {total_relevant}")
print(f"Matched (in our sheet): {len(matched)}")
print(f"Missing (NOT in our sheet): {len(missing)}")
print(f"Coverage rate: {coverage_rate:.1f}%")

# Missing items by platform
print(f"\n{'='*70}")
print("Missing Items by Source Platform")
print(f"{'='*70}")
platform_missing = {}
for m in missing:
    src = m.get('source_platform', 'unknown')
    platform_missing[src] = platform_missing.get(src, 0) + 1
for p, c in sorted(platform_missing.items(), key=lambda x: -x[1]):
    print(f"  {p}: {c}")

# List all missing items
print(f"\n{'='*70}")
print("All Missing Items (detail)")
print(f"{'='*70}")
for i, m in enumerate(missing, 1):
    src = m.get('source_platform', 'unknown')
    print(f"  {i:3d}. [{src}] {m['name'][:65]}")
    if m['org']:
        print(f"       org: {m['org']}")

# Root cause analysis
print(f"\n{'='*70}")
print("Root Cause Analysis")
print(f"{'='*70}")

causes = {
    'scraper_not_registered': 0,
    'scraper_blocked': 0,
    'platform_unreachable': 0,
    'keyword_mismatch': 0,
    'llm_filter_too_aggressive': 0,
    'pagination_or_date_limit': 0,
    'unknown': 0,
}

for m in missing:
    src = m.get('source_platform', 'unknown')
    if '不可达' in src:
        causes['platform_unreachable'] += 1
    elif 'ctbpsp' in src:
        causes['scraper_blocked'] += 1
    elif 'chinabidding' in src:
        causes['keyword_mismatch'] += 1
    elif 'iccec' in src:
        causes['keyword_mismatch'] += 1
    elif '华能' in src or '国能' in src:
        causes['scraper_not_registered'] += 1
    else:
        causes['unknown'] += 1

for cause, count in sorted(causes.items(), key=lambda x: -x[1]):
    if count > 0:
        print(f"  {cause}: {count}")

# Our platform coverage
print(f"\n{'='*70}")
print("Our Feishu Data by Platform")
print(f"{'='*70}")
our_platform_counts = {}
for p in our_projects:
    plat = p['platform']
    our_platform_counts[plat] = our_platform_counts.get(plat, 0) + 1
for p, c in sorted(our_platform_counts.items(), key=lambda x: -x[1]):
    print(f"  {p}: {c}")

# Save results
result = {
    'coverage_rate': round(coverage_rate, 1),
    'total_competitor': len(competitor_projects),
    'total_ours': len(our_projects),
    'matched': len(matched),
    'missing': len(missing),
    'blacklisted': len(blacklisted),
    'missing_by_platform': platform_missing,
    'missing_items': [{'name': m['name'], 'org': m['org'], 'platform': m.get('source_platform', '')} for m in missing],
}
out_path = os.path.join(BASE_DIR, 'coverage_report.json')
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(f"\nSaved coverage report to {out_path}")
