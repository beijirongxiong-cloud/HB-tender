import os
import time
import base64
from twocaptcha import TwoCaptcha
from src.utils.logger import setup_logger

logger = setup_logger("captcha")

MAX_RETRIES = 3


def solve_captcha(image_base64: str) -> str:
    solver = TwoCaptcha(os.getenv("TWOCAPTCHA_API_KEY"))

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = solver.normal(image_base64)
            code = result["code"]
            logger.info(f"Captcha solved on attempt {attempt}: {code}")
            return code
        except Exception as e:
            logger.warning(f"Captcha solve attempt {attempt} failed: {e}")
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"Captcha solving failed after {MAX_RETRIES} attempts") from e
            time.sleep(2)


async def solve_captcha_from_element(page, selector: str) -> str:
    element = page.locator(selector)
    screenshot_bytes = await element.screenshot()
    image_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
    return solve_captcha(image_b64)
