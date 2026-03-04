"""Agent 3: Web quality analyzer — PageSpeed Insights + mobile screenshot."""
import logging
import os
from pathlib import Path
from typing import Any

import httpx
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from app.config import settings

logger = logging.getLogger(__name__)

PAGESPEED_API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
SCREENSHOTS_DIR = Path("screenshots")


def _score_from_performance(perf_score: float | None) -> int:
    """Convert PageSpeed performance score (0-1) to opportunity score (1-5)."""
    if perf_score is None:
        return 3  # unknown
    if perf_score >= 0.9:
        return 1  # excellent — low opportunity
    if perf_score >= 0.7:
        return 2
    if perf_score >= 0.5:
        return 3
    if perf_score >= 0.3:
        return 4
    return 5  # terrible — high opportunity


async def analyze_web(business: dict[str, Any]) -> dict[str, Any]:
    """
    Analyze website quality using PageSpeed Insights and Playwright screenshot.

    Args:
        business: dict with 'website' and 'nombre' keys

    Returns:
        dict with keys:
          web_score (int 1-5), web_es_mobile (bool | None),
          web_velocidad_ms (int | None), screenshot_path (str | None)
    """
    result: dict[str, Any] = {
        "web_score": None,
        "web_es_mobile": None,
        "web_velocidad_ms": None,
        "screenshot_path": None,
    }

    website = business.get("website", "")
    if not website:
        logger.info(f"No website for {business.get('nombre', 'unknown')}, skipping")
        return result

    if not website.startswith("http"):
        website = "https://" + website

    # --- PageSpeed Insights ---
    pagespeed_score = None
    if settings.pagespeed_api_key:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    PAGESPEED_API_URL,
                    params={
                        "url": website,
                        "strategy": "mobile",
                        "key": settings.pagespeed_api_key,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            categories = data.get("lighthouseResult", {}).get("categories", {})
            perf = categories.get("performance", {})
            pagespeed_score = perf.get("score")  # 0.0 – 1.0

            # Load time from FCP audit
            audits = data.get("lighthouseResult", {}).get("audits", {})
            fcp = audits.get("first-contentful-paint", {})
            fcp_ms = fcp.get("numericValue")
            if fcp_ms:
                result["web_velocidad_ms"] = int(fcp_ms)

            # Mobile-friendly check
            viewport_audit = audits.get("viewport", {})
            result["web_es_mobile"] = viewport_audit.get("score", 0) == 1

            logger.info(
                f"PageSpeed for {website}: score={pagespeed_score}, "
                f"fcp={result['web_velocidad_ms']}ms"
            )

        except httpx.TimeoutException:
            logger.warning(f"PageSpeed timeout for {website}")
        except Exception as e:
            logger.error(f"PageSpeed error for {website}: {e}")
    else:
        logger.info("No PAGESPEED_API_KEY set, skipping PageSpeed analysis")

    result["web_score"] = _score_from_performance(pagespeed_score)

    # --- Screenshot ---
    try:
        SCREENSHOTS_DIR.mkdir(exist_ok=True)
        nombre_safe = "".join(
            c if c.isalnum() or c in "-_" else "_"
            for c in business.get("nombre", "business")[:50]
        )
        screenshot_path = SCREENSHOTS_DIR / f"{nombre_safe}.png"

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 375, "height": 812},
                device_scale_factor=2,
                is_mobile=True,
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
                    "Mobile/15E148 Safari/604.1"
                ),
            )
            page = await context.new_page()

            try:
                await page.goto(website, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(2000)
                await page.screenshot(path=str(screenshot_path), full_page=False)
                result["screenshot_path"] = str(screenshot_path)
                logger.info(f"Screenshot saved: {screenshot_path}")

            except PlaywrightTimeoutError:
                logger.warning(f"Timeout taking screenshot of {website}")
            except Exception as e:
                logger.warning(f"Screenshot error for {website}: {e}")
            finally:
                await browser.close()

    except Exception as e:
        logger.error(f"Error in screenshot flow for {website}: {e}", exc_info=True)

    return result
