import json
import os
import asyncio
from typing import Optional

import httpx

from src.utils.logger import setup_logger

logger = setup_logger("llm.client")


class LLMError(Exception):
    pass


def _extract_json(text: str) -> Optional[dict]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    import re
    m = re.search(r'\{[\s\S]*\}', text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


class LLMClient:
    def __init__(self):
        self.api_key = os.getenv("VOLC_API_KEY", "")
        self.base_url = os.getenv("VOLC_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3")
        self.default_model = os.getenv("VOLC_SCREEN_MODEL", "deepseek-v4-flash")
        self.timeout = 60

    async def chat_json(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        max_retries: int = 3,
    ) -> dict:
        model = model or self.default_model
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Try with JSON mode first, fallback to no response_format
        for use_json_mode in [True, False]:
            payload = {
                "model": model,
                "messages": messages,
            }
            if use_json_mode:
                payload["response_format"] = {"type": "json_object"}

            last_error = None
            for attempt in range(max_retries):
                try:
                    async with httpx.AsyncClient(timeout=self.timeout) as client:
                        resp = await client.post(url, json=payload, headers=headers)
                        resp.raise_for_status()
                        data = resp.json()

                    content = data["choices"][0]["message"]["content"]
                    parsed = _extract_json(content)
                    if parsed is not None:
                        return parsed
                    logger.warning(f"LLM response not valid JSON (attempt {attempt+1}), raw: {content[:200]}")
                    last_error = LLMError(f"Non-JSON response")
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 400 and use_json_mode:
                        logger.warning(f"400 error with json_object mode, retrying without response_format")
                        break
                    logger.warning(f"LLM call failed (attempt {attempt+1}/{max_retries}): {e}")
                    last_error = LLMError(str(e))
                except (httpx.RequestError, KeyError, IndexError) as e:
                    logger.warning(f"LLM call failed (attempt {attempt+1}/{max_retries}): {e}")
                    last_error = LLMError(str(e))

                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** (attempt + 1))

        raise last_error or LLMError("Unknown error")
