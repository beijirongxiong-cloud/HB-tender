"""Read Feishu sheet data including column L notes."""
import sys, os, json
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()
from src.output.feishu_sheet import FeishuSpreadsheetClient
import httpx

sheet = FeishuSpreadsheetClient()
headers = sheet._headers()

spreadsheet_token = sheet.spreadsheet_token
sheet_id = "1574a1"

# Read A1:L500 using V2 API (no params needed)
url = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/values/{sheet_id}!A1:L500"
resp = httpx.get(url, headers=headers, timeout=30)
data = resp.json()

print(f"Code: {data.get('code')}")
rows = data.get("data", {}).get("valueRange", {}).get("values", [])
print(f"Total rows: {len(rows)}")

if rows:
    print(f"\nHeader: {rows[0]}")
    
    # Find rows with L column (index 11) content
    print("\n=== Rows with L column notes ===")
    count = 0
    for i, row in enumerate(rows[1:], 2):
        while len(row) < 12:
            row.append("")
        note = str(row[11]).strip() if row[11] else ""
        if note:
            count += 1
            category = str(row[0]) if row[0] else ""
            title = str(row[1]) if row[1] else ""
            org = str(row[2]) if row[2] else ""
            platform = str(row[3]) if row[3] else ""
            deadline = str(row[4]) if row[4] else ""
            budget = str(row[5]) if row[5] else ""
            print(f"\n--- Row {i} ---")
            print(f"  Category: {category}")
            print(f"  Title: {title}")
            print(f"  Org: {org}")
            print(f"  Platform: {platform}")
            print(f"  Deadline: {deadline}")
            print(f"  Budget: {budget}")
            print(f"  L列备注: {note}")
    
    print(f"\n\nTotal rows with notes: {count}")
    print(f"Total rows: {len(rows)-1}")
else:
    print("No rows found.")
    print(json.dumps(data, ensure_ascii=False, indent=2)[:500])
