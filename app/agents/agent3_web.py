"""Agent 3: Web quality analyzer — PageSpeed Insights + mobile screenshot."""
import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from app.config import settings
from app.utils.url import normalize_url

logger = logging.getLogger(__name__)

PAGESPEED_API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
SCREENSHOTS_DIR = Path("screenshots")


async def _scrape_web_content(url: str) -> str:
    """Fetch webpage and extract readable text content for AI analysis."""
    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Prospector/1.0)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
    except Exception as e:
        logger.warning(f"Could not fetch {url} for content scraping: {e}")
        return ""

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    # Remove noise
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()

    parts: list[str] = []

    title = soup.find("title")
    if title:
        parts.append(f"TÍTULO: {title.get_text(strip=True)}")

    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        parts.append(f"META DESCRIPCIÓN: {meta_desc['content'].strip()}")

    for heading in soup.find_all(["h1", "h2", "h3"], limit=10):
        text = heading.get_text(strip=True)
        if text:
            parts.append(f"{heading.name.upper()}: {text}")

    for p in soup.find_all("p", limit=20):
        text = p.get_text(strip=True)
        if len(text) > 40:
            parts.append(text)

    content = "\n".join(parts)
    return content[:3000]  # cap to avoid huge prompts


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

    website = normalize_url(website)

    # --- PageSpeed Insights ---
    pagespeed_score = None
    try:
        params: dict = {"url": website, "strategy": "mobile"}
        api_key = settings.pagespeed_api_key
        if api_key and api_key not in ("your-key-here", ""):
            params["key"] = api_key
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(PAGESPEED_API_URL, params=params)
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

    result["web_score"] = _score_from_performance(pagespeed_score)

    # Scrape webpage text for AI analysis
    web_contenido = ""
    if website:
        web_contenido = await _scrape_web_content(website)
        if web_contenido:
            logger.info(f"Scraped {len(web_contenido)} chars from {website}")
        else:
            logger.warning(f"No content scraped from {website}")
    result["web_contenido"] = web_contenido

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
                # Dismiss cookie banners
                for label in ("Aceptar", "Accept", "Rechazar todo", "Reject all", "OK", "Agree"):
                    try:
                        btn = await page.query_selector(f'button:has-text("{label}")')
                        if btn:
                            await btn.click()
                            await asyncio.sleep(0.5)
                            break
                    except Exception:
                        pass
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
