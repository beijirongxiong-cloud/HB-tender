import os
import json
import time
from typing import Optional

import httpx
from src.utils.logger import setup_logger
from src.utils.notify import send_feishu_alert
from src.output.feishu_sheet import FeishuSpreadsheetClient

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

    def create_records(self, records: list[dict], insert_at_top: bool = True) -> bool:
        sheet_client = FeishuSpreadsheetClient()
        return sheet_client.create_records(records, insert_at_top=insert_at_top)

    def create_bitable_records(self, records: list[dict], insert_at_top: bool = True) -> bool:
        if not records:
            logger.info("No records to write")
            return True

        url = f"{BASE_URL}/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records/batch_create"

        all_success = True
        batch_size = 10
        total_batches = (len(records) + batch_size - 1) // batch_size

        for i in range(0, len(records), batch_size):
            batch = records[i : i + batch_size]
            payload = {"records": [{"fields": r} for r in batch]}

            batch_idx = i // batch_size
            params = {}
            if insert_at_top:
                params["offset"] = 0

            success = False
            for attempt in range(3):
                try:
                    resp = httpx.post(url, headers=self._headers(), json=payload, params=params, timeout=30)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("code") == 0:
                            logger.info(f"Wrote batch {batch_idx + 1}/{total_batches}: {len(batch)} records (insert_at_top={insert_at_top})")
                            success = True
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

            if not success:
                all_success = False

        return all_success

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

            success = self.create_bitable_records(batch)
            if success:
                os.remove(filepath)
                logger.info(f"Retried and removed cache file: {filename}")

    def create_sheet_records(self, records: list[dict], insert_at_top: bool = True) -> bool:
        """Write to Feishu cloud spreadsheet (Excel) with public edit permission."""
        sheet_client = FeishuSpreadsheetClient()
        return sheet_client.create_records(records, insert_at_top=insert_at_top)
