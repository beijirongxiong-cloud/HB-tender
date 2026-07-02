"""Feishu Cloud Spreadsheet (云文档Excel) client: create, set public edit permission, and append/insert rows."""
import os
import json
import time
from datetime import datetime
from typing import Optional

import httpx
from src.utils.logger import setup_logger
from src.utils.notify import send_feishu_alert

logger = setup_logger("feishu_sheet")

BASE_URL = "https://open.feishu.cn/open-apis"

SPREADSHEET_TOKEN_ENV = "FEISHU_SPREADSHEET_TOKEN"
SPREADSHEET_TITLE = "招标信息汇总"
SHEET_TITLE = "招标数据"

COLUMNS = [
    "序号",
    "添加时间",
    "项目类目",
    "项目名称",
    "招标单位",
    "投标平台",
    "招标次数",
    "报名截止时间",
    "投标时间",
    "预算(万)",
    "标书价格",
]


class FeishuSpreadsheetClient:
    def __init__(self):
        self.app_id = os.getenv("FEISHU_APP_ID", "")
        self.app_secret = os.getenv("FEISHU_APP_SECRET", "")
        self.spreadsheet_token = os.getenv(SPREADSHEET_TOKEN_ENV, "")
        self.sheet_id: Optional[str] = None
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

    def _ensure_spreadsheet(self) -> bool:
        """Create spreadsheet if token not set; always set public edit permission."""
        if not self.spreadsheet_token:
            url = f"{BASE_URL}/sheets/v3/spreadsheets"
            resp = httpx.post(
                url,
                headers=self._headers(),
                json={"title": SPREADSHEET_TITLE},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                logger.error(f"Failed to create spreadsheet: {data}")
                return False
            self.spreadsheet_token = data["data"]["spreadsheet"]["spreadsheet_token"]
            logger.info(f"Created spreadsheet: {self.spreadsheet_token}")
            # Persist token to .env file for reuse
            self._save_spreadsheet_token(self.spreadsheet_token)
        else:
            # Verify it exists
            url = f"{BASE_URL}/sheets/v3/spreadsheets/{self.spreadsheet_token}/sheets/query"
            resp = httpx.get(url, headers=self._headers(), timeout=15)
            if resp.status_code != 200 or resp.json().get("code") != 0:
                logger.warning("Existing spreadsheet invalid, will create new one")
                self.spreadsheet_token = ""
                return self._ensure_spreadsheet()

        # Ensure default sheet title
        self._ensure_sheet_title()
        # Set public edit permission
        self._set_public_edit_permission()
        return True

    def _save_spreadsheet_token(self, token: str) -> None:
        env_path = ".env"
        try:
            lines = []
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()

            found = False
            for i, line in enumerate(lines):
                if line.strip().startswith(f"{SPREADSHEET_TOKEN_ENV}="):
                    lines[i] = f"{SPREADSHEET_TOKEN_ENV}={token}\n"
                    found = True
                    break

            if not found:
                lines.append(f"\n{SPREADSHEET_TOKEN_ENV}={token}\n")

            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
        except Exception as e:
            logger.warning(f"Could not save spreadsheet token to .env: {e}")

    def _ensure_sheet_title(self) -> None:
        url = f"{BASE_URL}/sheets/v3/spreadsheets/{self.spreadsheet_token}/sheets/query"
        resp = httpx.get(url, headers=self._headers(), timeout=15)
        data = resp.json()
        if data.get("code") != 0:
            return
        sheets = data.get("data", {}).get("sheets", [])
        if not sheets:
            return
        sheet = sheets[0]
        self.sheet_id = sheet["sheet_id"]
        if sheet.get("title") != SHEET_TITLE:
            update_url = f"{BASE_URL}/sheets/v3/spreadsheets/{self.spreadsheet_token}/sheets/{self.sheet_id}"
            httpx.patch(update_url, headers=self._headers(), json={"title": SHEET_TITLE}, timeout=10)

    def _set_public_edit_permission(self) -> None:
        url = f"{BASE_URL}/drive/v1/permissions/{self.spreadsheet_token}/public?type=sheet"
        resp = httpx.patch(
            url,
            headers=self._headers(),
            json={
                "security_entity": "anyone_can_edit",
                "link_share_entity": "anyone_editable",
                "external_access": True,
            },
            timeout=15,
        )
        if resp.status_code == 200 and resp.json().get("code") == 0:
            logger.info("Spreadsheet public edit permission set")
        else:
            logger.warning(f"Failed to set public permission: {resp.text[:300]}")

    def _write_header(self) -> None:
        if not self.sheet_id:
            return
        url = f"{BASE_URL}/sheets/v2/spreadsheets/{self.spreadsheet_token}/values"
        body = {
            "valueRange": {
                "range": f"{self.sheet_id}!A1:K1",
                "values": [COLUMNS],
            }
        }
        resp = httpx.put(url, headers=self._headers(), json=body, timeout=20)
        if resp.status_code != 200 or resp.json().get("code") != 0:
            logger.warning(f"Failed to write header: {resp.text[:300]}")

    def _read_header(self) -> bool:
        """Check if header exists; if not, write it."""
        if not self.sheet_id:
            return False
        url = f"{BASE_URL}/sheets/v2/spreadsheets/{self.spreadsheet_token}/values/{self.sheet_id}!A1:K1"
        resp = httpx.get(url, headers=self._headers(), timeout=15)
        if resp.status_code == 200 and resp.json().get("code") == 0:
            values = resp.json().get("data", {}).get("valueRange", {}).get("values", [])
            if values and values[0] == COLUMNS:
                return True
        self._write_header()
        return True

    def _insert_rows(self, row_count: int) -> bool:
        """Insert rows at index 1 (after header) so new data appears at row 2."""
        if not self.sheet_id or row_count <= 0:
            return True
        url = f"{BASE_URL}/sheets/v2/spreadsheets/{self.spreadsheet_token}/insert_dimension_range"
        body = {
            "dimension": {
                "sheetId": self.sheet_id,
                "majorDimension": "ROWS",
                "startIndex": 1,
                "endIndex": 1 + row_count,
            },
            "inheritStyle": False,
        }
        resp = httpx.post(url, headers=self._headers(), json=body, timeout=20)
        if resp.status_code == 200 and resp.json().get("code") == 0:
            logger.info(f"Inserted {row_count} rows at position 2")
            return True
        logger.warning(f"Failed to insert rows: {resp.text[:300]}")
        return False

    @staticmethod
    def _format_record(item: dict) -> list:
        """Convert formatted Feishu record dict to row values."""
        project_field = item.get("项目名称", "")
        if isinstance(project_field, dict):
            project_text = project_field.get("text", "")
            project_link = project_field.get("link", "")
            # Use rich-text dict so Feishu renders it as a real hyperlink
            if project_link and project_text:
                project_value = {
                    "text": project_text,
                    "link": project_link,
                    "type": "url",
                }
            else:
                project_value = project_text
        else:
            project_value = project_field or ""

        add_time = item.get("添加时间", "")
        if isinstance(add_time, (int, float)):
            add_time = datetime.fromtimestamp(add_time / 1000).strftime("%Y-%m-%d %H:%M")

        return [
            item.get("序号", ""),
            add_time,
            item.get("项目类目", ""),
            project_value,
            item.get("招标单位", ""),
            item.get("投标平台", ""),
            item.get("招标次数", ""),
            item.get("报名截止时间", ""),
            item.get("投标时间", ""),
            item.get("预算(万)", "") if item.get("预算(万)") is not None else "",
            item.get("标书价格", ""),
        ]

    def create_records(self, records: list[dict], insert_at_top: bool = True) -> bool:
        if not records:
            logger.info("No records to write")
            return True

        # Deduplicate by project URL before writing
        seen_urls: set[str] = set()
        seen_title_keys: set[str] = set()
        unique_records: list[dict] = []
        dup_count = 0
        for r in records:
            name_field = r.get("项目名称", "")
            url = ""
            if isinstance(name_field, dict):
                url = name_field.get("link", "")
            if url and url in seen_urls:
                dup_count += 1
                continue
            if url:
                seen_urls.add(url)

            title_text = name_field.get("text", name_field) if isinstance(name_field, dict) else str(name_field)
            org = str(r.get("招标单位", ""))
            title_key = (title_text[:20], org[:10])
            if title_key in seen_title_keys:
                dup_count += 1
                continue
            seen_title_keys.add(title_key)

            unique_records.append(r)

        if dup_count > 0:
            logger.info(f"Dedup: {len(records)} -> {len(unique_records)} (removed {dup_count} duplicates)")
        records = unique_records

        if not records:
            logger.info("No unique records to write after dedup")
            return True

        if not self._ensure_spreadsheet():
            return False
        self._read_header()

        # Format rows
        rows = [self._format_record(r) for r in records]

        if insert_at_top:
            self._insert_rows(len(rows))
            start_row = 2
        else:
            start_row = 2  # header at row 1

        end_row = start_row + len(rows) - 1
        range_str = f"{self.sheet_id}!A{start_row}:K{end_row}"

        url = f"{BASE_URL}/sheets/v2/spreadsheets/{self.spreadsheet_token}/values"
        body = {
            "valueRange": {
                "range": range_str,
                "values": rows,
            }
        }

        for attempt in range(3):
            try:
                resp = httpx.put(url, headers=self._headers(), json=body, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("code") == 0:
                        logger.info(f"Wrote {len(rows)} rows to {range_str}")
                        return True
                    else:
                        logger.warning(f"Feishu sheet API error: {data.get('msg')}")
                else:
                    logger.warning(f"Feishu sheet HTTP {resp.status_code}")
            except Exception as e:
                logger.error(f"Feishu sheet write attempt {attempt + 1} failed: {e}")
                if attempt == 2:
                    send_feishu_alert(f"飞书Excel写入失败: {str(e)[:200]}")
                time.sleep(2)

        return False

    def spreadsheet_url(self) -> str:
        if not self.spreadsheet_token:
            self._ensure_spreadsheet()
        url = f"{BASE_URL}/sheets/v3/spreadsheets/{self.spreadsheet_token}"
        try:
            resp = httpx.get(url, headers=self._headers(), timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                real_url = data.get("data", {}).get("spreadsheet", {}).get("url", "")
                if real_url:
                    return real_url
        except Exception:
            pass
        return f"https://www.feishu.cn/sheets/{self.spreadsheet_token}"
