"""Agent 2: Extract contact info (email, social media) from a business website."""
import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.utils.url import normalize_url

logger = logging.getLogger(__name__)

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
SOCIAL_PATTERNS = {
    "facebook": re.compile(r"facebook\.com/[a-zA-Z0-9._/\-]+"),
    "instagram": re.compile(r"instagram\.com/[a-zA-Z0-9._/\-]+"),
    "twitter": re.compile(r"(?:twitter|x)\.com/[a-zA-Z0-9._/\-]+"),
    "linkedin": re.compile(r"linkedin\.com/(?:in|company)/[a-zA-Z0-9._/\-]+"),
    "youtube": re.compile(r"youtube\.com/(?:channel|c|user|@)[a-zA-Z0-9._/\-]+"),
}
PRIORITY_PREFIXES = ("contact", "info", "hola", "hello", "web", "admin", "correo")


async def extract_contact(business: dict[str, Any]) -> dict[str, Any]:
    """
    Extract contact info from a business website.

    Args:
        business: dict with at least 'website' key

    Returns:
        dict with keys: email, redes_sociales (dict), contacto_extra (str | None)
    """
    result: dict[str, Any] = {
        "email": None,
        "redes_sociales": {},
        "contacto_extra": None,
    }

    website = business.get("website", "")
    if not website:
        logger.info(f"No website for {business.get('nombre', 'unknown')}, skipping")
        return result

    website = normalize_url(website)

    try:
        async with httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ProspectorBot/1.0)"},
        ) as client:
            response = await client.get(website)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type and "application/xhtml" not in content_type:
                logger.warning(f"Non-HTML response from {website}: {content_type}")
                return result

            html = response.text

    except httpx.TimeoutException:
        logger.warning(f"Timeout fetching {website}")
        return result
    except httpx.HTTPStatusError as e:
        logger.warning(f"HTTP {e.response.status_code} fetching {website}")
        return result
    except Exception as e:
        logger.error(f"Error fetching {website}: {e}")
        return result

    try:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator=" ")

        # Single pass over all anchor tags
        all_links = soup.find_all("a", href=True)

        # --- Emails ---
        emails_found: set[str] = set()

        # From mailto links (highest quality)
        for a in all_links:
            href = a["href"]
            if href.startswith("mailto:"):
                email = href[7:].split("?")[0].strip().lower()
                if email and EMAIL_REGEX.match(email):
                    emails_found.add(email)

        # From visible text
        for email in EMAIL_REGEX.findall(text):
            if "." in email.split("@")[1] and len(email) < 100:
                emails_found.add(email.lower())

        if emails_found:
            email_list = sorted(emails_found)
            chosen = next(
                (e for pref in PRIORITY_PREFIXES for e in email_list if e.startswith(pref)),
                email_list[0],
            )
            result["email"] = chosen

        # --- Social media ---
        all_links_text = " ".join(str(a.get("href", "")) for a in all_links)
        searchable = all_links_text + " " + text  # use parsed text, not raw HTML

        for platform, pattern in SOCIAL_PATTERNS.items():
            match = pattern.search(searchable)
            if match:
                url = match.group(0).split('"')[0].split("'")[0].rstrip("/")
                result["redes_sociales"][platform] = f"https://{url}"

        # --- Extra phone (Spanish format) ---
        phone_pattern = re.compile(
            r"(?:\+34|0034)?[\s\-]?[6789]\d{2}[\s\-]?\d{3}[\s\-]?\d{3}"
        )
        phone_match = phone_pattern.search(text)
        if phone_match:
            result["contacto_extra"] = phone_match.group(0).strip()

    except Exception as e:
        logger.error(f"Error parsing {website}: {e}", exc_info=True)

    return result
