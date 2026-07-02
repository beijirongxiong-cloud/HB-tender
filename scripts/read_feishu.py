import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from src.output.feishu_sheet import FeishuSpreadsheetClient
import httpx

client = FeishuSpreadsheetClient()
token = client.spreadsheet_token
print(f'Spreadsheet token: {token}')
print(f'URL: {client.spreadsheet_url()}')

headers = client._headers()
BASE_URL = 'https://open.feishu.cn/open-apis'

# First ensure the client is initialized
if not client._ensure_spreadsheet():
    print('Failed to ensure spreadsheet')
    sys.exit(1)

sheet_id = client.sheet_id
token = client.spreadsheet_token
print(f'Sheet ID: {sheet_id}')

url = f'{BASE_URL}/sheets/v2/spreadsheets/{token}/values/{sheet_id}'
r = httpx.get(url, headers=headers, timeout=30)
data = r.json()
if data.get('code') != 0:
    print(f'Error: {data}')
else:
    values = data.get('data', {}).get('valueRange', {}).get('values', [])
    print(f'Total rows: {len(values)}')
    if values:
        print(f'Headers: {values[0]}')
        # Count by platform
        platform_counts = {}
        for row in values[1:]:
            platform = row[5] if len(row) > 5 else ''
            platform_counts[platform] = platform_counts.get(platform, 0) + 1
        print('\nBy platform:')
        for p, c in sorted(platform_counts.items(), key=lambda x: -x[1]):
            print(f'  {p}: {c}')

        # Show unique project names
        def extract_text(cell):
            if cell is None:
                return ''
            if isinstance(cell, str):
                return cell
            if isinstance(cell, (int, float)):
                return str(cell)
            if isinstance(cell, dict):
                return cell.get('text', cell.get('link', cell.get('value', '')))
            if isinstance(cell, list):
                return extract_text(cell[0]) if cell else ''
            return str(cell)

        names = set()
        projects = []
        for row in values[1:]:
            name = extract_text(row[3]) if len(row) > 3 else ''
            platform = extract_text(row[5]) if len(row) > 5 else ''
            org = extract_text(row[4]) if len(row) > 4 else ''
            deadline = extract_text(row[7]) if len(row) > 7 else ''
            names.add(name[:40])
            projects.append({'name': name, 'platform': platform, 'org': org, 'deadline': deadline})
        print(f'\nUnique project names (first 40 chars): {len(names)}')

        # Save full project list as JSON for comparison
        import json
        out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'feishu_projects.json')
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(projects, f, ensure_ascii=False, indent=2)
        print(f'Saved {len(projects)} projects to feishu_projects.json')
