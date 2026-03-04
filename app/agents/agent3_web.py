"""Agent 3: Web quality analyzer — PageSpeed Insights + mobile detection."""
import asyncio
import json as _json
import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.utils.url import normalize_url

logger = logging.getLogger(__name__)

PAGESPEED_API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

# --- CMS detection patterns (checked against raw HTML) ---
_CMS_PATTERNS: list[tuple[str, str]] = [
    ("wordpress", r"wp-content|wp-json|wp-emoji"),
    ("wix", r"wix\.com"),
    ("squarespace", r"squarespace\.com"),
    ("webflow", r"webflow\.com"),
    ("shopify", r"cdn\.shopify\.com|shopify\.com"),
    ("blogger", r"blogger\.com"),
]

# Spanish phone patterns: +34 followed by 6xx/7xx/9xx, or bare 6xx/7xx/9xx
_PHONE_RE = re.compile(
    r"(?:\+34[\s\-]?)?(?:6\d{2}|7[0-9]\d|9\d{2})[\s\-]?\d{3}[\s\-]?\d{3}"
)

# Spanish address heuristics
_ADDRESS_RE = re.compile(
    r"\b(?:calle|c/|avda?\.?|avenida|plaza|pza\.?|paseo|po\.?|carretera|pol[íi]gono)\b",
    re.IGNORECASE,
)

# Copyright year: © 2019, Copyright 2020, 2021 ©
_COPYRIGHT_RE = re.compile(
    r"(?:©|copyright|cop\.?)\s*(\d{4})|(\d{4})\s*©",
    re.IGNORECASE,
)


def _detect_cms(html: str, response_headers: httpx.Headers) -> tuple[str | None, str | None]:
    """Return (cms_name, version_hint) detected from HTML and response headers."""
    html_lower = html.lower()

    # Check Wix via response headers first (X-Wix-* headers)
    for header_name in response_headers.keys():
        if header_name.lower().startswith("x-wix-"):
            return "wix", None

    # Meta generator tag → version hint and possible CMS
    generator_match = re.search(
        r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    generator_content: str | None = None
    if generator_match:
        generator_content = generator_match.group(1).strip()

    # Check HTML patterns
    for cms_name, pattern in _CMS_PATTERNS:
        if re.search(pattern, html_lower):
            return cms_name, generator_content

    # If generator tag matches a CMS keyword but no HTML pattern caught it
    if generator_content:
        gc_lower = generator_content.lower()
        for cms_name, _ in _CMS_PATTERNS:
            if cms_name in gc_lower:
                return cms_name, generator_content

    return None, generator_content


def _extract_copyright_year(soup: Any) -> int | None:
    """Search footer first, then full page text for a copyright year."""
    footer = soup.find("footer")
    search_text = footer.get_text(" ", strip=True) if footer else ""
    if not search_text:
        search_text = soup.get_text(" ", strip=True)

    for m in _COPYRIGHT_RE.finditer(search_text):
        year_str = m.group(1) or m.group(2)
        year = int(year_str)
        if 1990 <= year <= 2100:
            return year
    return None


def _has_contact_form(soup: Any) -> bool:
    """Return True if a form containing contact-related fields is present."""
    contact_field_names = re.compile(
        r"email|nombre|name|mensaje|message|asunto|subject|phone|tel[eé]fono",
        re.IGNORECASE,
    )
    for form in soup.find_all("form"):
        inputs = form.find_all(["input", "textarea", "select"])
        for inp in inputs:
            name_attr = inp.get("name", "") + inp.get("id", "") + inp.get("placeholder", "")
            if contact_field_names.search(name_attr):
                return True
    return False


def _count_internal_links(soup: Any, base_url: str) -> int:
    """Count <a href> links that point to the same domain or are relative."""
    parsed_base = urlparse(base_url)
    base_netloc = parsed_base.netloc.lower().lstrip("www.")
    count = 0
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        parsed = urlparse(href)
        if not parsed.scheme:
            # Relative URL → internal
            count += 1
        else:
            link_netloc = parsed.netloc.lower().lstrip("www.")
            if link_netloc == base_netloc:
                count += 1
    return count


async def _scrape_web_content(url: str) -> dict[str, Any]:
    """Fetch webpage and extract rich technical quality indicators.

    Returns a dict with keys:
        has_viewport (bool), contenido_texto (str, up to 10 000 chars),
        web_analisis (dict with tecnico/modernidad/seo/contenido sub-dicts).

    On any fetch/parse failure returns a minimal dict with has_viewport=False,
    empty contenido_texto, and web_analisis=None.
    """
    _empty: dict[str, Any] = {
        "has_viewport": False,
        "contenido_texto": "",
        "web_analisis": None,
    }

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Prospector/1.0)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
            response_headers = resp.headers
    except Exception as e:
        logger.warning(f"Could not fetch {url} for content scraping: {e}")
        return _empty

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    # ------------------------------------------------------------------ #
    # TECHNICAL — gathered BEFORE removing any tags                       #
    # ------------------------------------------------------------------ #

    # Viewport
    has_viewport = bool(soup.find("meta", attrs={"name": "viewport"}))

    # HTTPS
    is_https = url.startswith("https://")

    # HTTP headers
    server_header: str | None = response_headers.get("server") or None
    powered_by: str | None = response_headers.get("x-powered-by") or None
    last_modified_raw = response_headers.get("last-modified")
    last_modified_year: int | None = None
    if last_modified_raw:
        year_m = re.search(r"\b(19|20)\d{2}\b", last_modified_raw)
        if year_m:
            last_modified_year = int(year_m.group(0))

    # CMS detection
    cms_detectado, cms_version_hint = _detect_cms(html, response_headers)

    # Copyright year (needs soup with footer still intact)
    copyright_year = _extract_copyright_year(soup)

    # Analytics & tracking (scan raw html for script patterns)
    has_ga = bool(re.search(r"gtag\(|UA-\d|G-[A-Z0-9]+|google-analytics\.com", html))
    has_gtm = bool(re.search(r"googletagmanager\.com", html))
    has_pixel = bool(re.search(r"fbq\(|connect\.facebook\.net", html))

    # JSON-LD
    json_ld_tag = soup.find("script", attrs={"type": "application/ld+json"})
    has_json_ld = json_ld_tag is not None
    json_ld_type: str | None = None
    if json_ld_tag:
        try:
            ld_data = _json.loads(json_ld_tag.string or "")
            if isinstance(ld_data, list) and ld_data:
                json_ld_type = ld_data[0].get("@type")
            elif isinstance(ld_data, dict):
                json_ld_type = ld_data.get("@type")
        except Exception:
            pass

    # SEO — meta description
    meta_desc_tag = soup.find("meta", attrs={"name": "description"})
    meta_desc_content = ""
    if meta_desc_tag and meta_desc_tag.get("content"):
        meta_desc_content = meta_desc_tag["content"].strip()
    has_meta_description = bool(meta_desc_content)
    meta_description_length = len(meta_desc_content)

    # SEO — headings (before stripping)
    h1_count = len(soup.find_all("h1"))

    # SEO — images
    all_images = soup.find_all("img")
    imagenes_total = len(all_images)
    imagenes_con_alt = sum(
        1 for img in all_images
        if img.get("alt", "").strip()
    )
    imagenes_alt_pct = (imagenes_con_alt / imagenes_total) if imagenes_total else 1.0

    # SEO — internal links (before stripping)
    links_internos = _count_internal_links(soup, url)

    # SEO — sitemap link
    has_sitemap = bool(
        soup.find("link", attrs={"rel": "sitemap"})
        or re.search(r"sitemap\.xml", html, re.IGNORECASE)
    )

    # Content — contact form (before stripping scripts/forms)
    tiene_formulario_contacto = _has_contact_form(soup)

    # ------------------------------------------------------------------ #
    # Strip noise for text extraction                                      #
    # ------------------------------------------------------------------ #
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()

    # Content — phone & address in visible text
    visible_text = soup.get_text(" ", strip=True)
    tiene_telefono = bool(_PHONE_RE.search(visible_text))
    tiene_direccion = bool(_ADDRESS_RE.search(visible_text))

    # Word count
    palabras_visibles = len(visible_text.split())

    # ------------------------------------------------------------------ #
    # Build contenido_texto (for AI prompt, up to 10 000 chars)           #
    # ------------------------------------------------------------------ #
    parts: list[str] = []

    title_tag = soup.find("title")
    if title_tag:
        parts.append(f"TÍTULO: {title_tag.get_text(strip=True)}")

    if has_meta_description:
        parts.append(f"META DESCRIPCIÓN: {meta_desc_content}")

    for heading in soup.find_all(["h1", "h2", "h3"], limit=10):
        text = heading.get_text(strip=True)
        if text:
            parts.append(f"{heading.name.upper()}: {text}")

    for p in soup.find_all("p", limit=20):
        text = p.get_text(strip=True)
        if len(text) > 40:
            parts.append(text)

    contenido_texto = "\n".join(parts)[:10_000]

    # Modernidad heuristic: site is modern if copyright year >= 2022 or no year found
    es_moderna = (copyright_year is None) or (copyright_year >= 2022)

    # ------------------------------------------------------------------ #
    # Assemble result                                                      #
    # ------------------------------------------------------------------ #
    web_analisis: dict[str, Any] = {
        "tecnico": {
            "cms_detectado": cms_detectado,
            "cms_version_hint": cms_version_hint,
            "https": is_https,
            "server": server_header,
            "powered_by": powered_by,
            "last_modified_year": last_modified_year,
        },
        "modernidad": {
            "copyright_year": copyright_year,
            "es_moderna": es_moderna,
            "tiene_analytics": has_ga,
            "tiene_gtm": has_gtm,
            "tiene_pixel_facebook": has_pixel,
            "tiene_json_ld": has_json_ld,
            "json_ld_type": json_ld_type,
        },
        "seo": {
            "tiene_meta_description": has_meta_description,
            "meta_description_length": meta_description_length,
            "h1_count": h1_count,
            "imagenes_total": imagenes_total,
            "imagenes_con_alt": imagenes_con_alt,
            "imagenes_alt_pct": round(imagenes_alt_pct, 4),
            "links_internos": links_internos,
            "tiene_sitemap": has_sitemap,
        },
        "contenido": {
            "tiene_formulario_contacto": tiene_formulario_contacto,
            "tiene_telefono_en_texto": tiene_telefono,
            "tiene_direccion_en_texto": tiene_direccion,
            "palabras_visibles": palabras_visibles,
        },
    }

    return {
        "has_viewport": has_viewport,
        "contenido_texto": contenido_texto,
        "web_analisis": web_analisis,
    }


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
          web_velocidad_ms (int | None), web_contenido (str),
          web_analisis (dict | None)
    """
    result: dict[str, Any] = {
        "web_score": None,
        "web_es_mobile": None,
        "web_velocidad_ms": None,
        "web_contenido": "",
        "web_analisis": None,
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

    # Scrape webpage for rich analysis, AI content, and mobile viewport detection
    if website:
        scraped = await _scrape_web_content(website)
        result["web_contenido"] = scraped["contenido_texto"]
        result["web_es_mobile"] = scraped["has_viewport"]
        result["web_analisis"] = scraped["web_analisis"]

        if scraped["contenido_texto"]:
            logger.info(
                f"Scraped {len(scraped['contenido_texto'])} chars from {website}"
            )
        else:
            logger.warning(f"No content scraped from {website}")

    return result
