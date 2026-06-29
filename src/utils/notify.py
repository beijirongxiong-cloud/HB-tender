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
