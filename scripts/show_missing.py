import json, sys
sys.stdout.reconfigure(encoding='utf-8')
with open('coverage_report.json','r',encoding='utf-8') as f:
    r = json.load(f)
print('Missing by platform:')
for p,c in sorted(r['missing_by_platform'].items(), key=lambda x:-x[1]):
    print(f'  {p}: {c}')
print()
print('Missing items (first 30):')
for i,m in enumerate(r['missing_items'][:30],1):
    plat = m['platform']
    name = m['name'][:60]
    org = m.get('org','')
    print(f'  {i:2d}. [{plat}] {name}')
    if org:
        print(f'      org: {org}')
