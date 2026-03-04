"""Agent 3: Web quality analyzer — PageSpeed Insights + mobile detection."""
import asyncio
import logging
from typing import Any

import httpx

from app.config import settings
from app.utils.url import normalize_url

logger = logging.getLogger(__name__)

PAGESPEED_API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


async def _scrape_web_content(url: str) -> tuple[str, bool]:
    """Fetch webpage and extract readable text content for AI analysis.

    Returns:
        Tuple of (text_content, has_viewport) where has_viewport is True
        if a <meta name="viewport"> tag is present in the HTML.
    """
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
        return "", False

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    # Check for viewport meta BEFORE stripping tags
    has_viewport = bool(soup.find("meta", attrs={"name": "viewport"}))

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
    return content[:3000], has_viewport  # cap to avoid huge prompts


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
    Analyze website quality using PageSpeed Insights and HTML inspection.

    Args:
        business: dict with 'website' and 'nombre' keys

    Returns:
        dict with keys:
          web_score (int 1-5), web_es_mobile (bool | None),
          web_velocidad_ms (int | None)
    """
    result: dict[str, Any] = {
        "web_score": None,
        "web_es_mobile": None,
        "web_velocidad_ms": None,
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

        for attempt in range(2):  # try once, retry once on 429
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(PAGESPEED_API_URL, params=params)
            if resp.status_code == 429:
                if attempt == 0:
                    logger.warning(f"PageSpeed 429 for {website}, retrying in 3s...")
                    await asyncio.sleep(3)
                    continue
                else:
                    logger.warning(f"PageSpeed 429 persists for {website}, skipping")
                    break
            resp.raise_for_status()
            data = resp.json()

            categories = data.get("lighthouseResult", {}).get("categories", {})
            perf = categories.get("performance", {})
            pagespeed_score = perf.get("score")  # 0.0 – 1.0

            audits = data.get("lighthouseResult", {}).get("audits", {})
            fcp = audits.get("first-contentful-paint", {})
            fcp_ms = fcp.get("numericValue")
            if fcp_ms:
                result["web_velocidad_ms"] = int(fcp_ms)

            logger.info(
                f"PageSpeed for {website}: score={pagespeed_score}, "
                f"fcp={result['web_velocidad_ms']}ms"
            )
            break  # success

    except httpx.TimeoutException:
        logger.warning(f"PageSpeed timeout for {website}")
    except Exception as e:
        logger.error(f"PageSpeed error for {website}: {e}")

    result["web_score"] = _score_from_performance(pagespeed_score)

    # Scrape webpage text for AI analysis and detect mobile viewport
    web_contenido = ""
    has_viewport = False
    if website:
        web_contenido, has_viewport = await _scrape_web_content(website)
        if web_contenido:
            logger.info(f"Scraped {len(web_contenido)} chars from {website}")
        else:
            logger.warning(f"No content scraped from {website}")
    result["web_contenido"] = web_contenido
    result["web_es_mobile"] = has_viewport

    return result
