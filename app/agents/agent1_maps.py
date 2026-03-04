"""Agent 1: Google Maps scraper using Playwright async."""
import asyncio
import logging
import re
from typing import Any

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)


async def scrape_google_maps(query: str, max_results: int = 30) -> list[dict[str, Any]]:
    """
    Search Google Maps for businesses matching query.

    Returns list of dicts with keys:
      nombre, categoria, direccion, telefono, maps_url,
      rating_google, num_reseñas, website, tiene_web
    """
    results: list[dict[str, Any]] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        try:
            url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
            logger.info(f"Navigating to {url}")
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            # Accept cookie consent if present
            try:
                accept_btn = await page.query_selector('button[aria-label*="Aceptar"]')
                if not accept_btn:
                    accept_btn = await page.query_selector('button[aria-label*="Accept"]')
                if accept_btn:
                    await accept_btn.click()
                    await asyncio.sleep(1)
            except Exception:
                pass

            # Wait for results feed
            try:
                await page.wait_for_selector('[role="feed"]', timeout=15000)
            except PlaywrightTimeoutError:
                logger.warning("Results feed not found, trying alternative selectors")
                try:
                    await page.wait_for_selector('[data-item-id]', timeout=10000)
                except PlaywrightTimeoutError:
                    logger.error("Could not find results on page")
                    return results

            await asyncio.sleep(1)

            seen_ids: set[str] = set()
            scroll_attempts = 0
            max_scrolls = 25
            no_new_results_count = 0

            while len(results) < max_results and scroll_attempts < max_scrolls:
                cards = await page.query_selector_all('.Nv2PK')
                new_found = False

                for card in cards:
                    if len(results) >= max_results:
                        break

                    try:
                        item_id = await card.get_attribute("aria-label") or ""
                        if not item_id or item_id in seen_ids:
                            continue

                        seen_ids.add(item_id)
                        new_found = True

                        # Click to open detail panel
                        await card.click()
                        await asyncio.sleep(1.5)

                        business = await _extract_business_details(page)
                        if business:
                            business["maps_url"] = page.url
                            results.append(business)
                            logger.info(
                                f"[{len(results)}/{max_results}] Extracted: "
                                f"{business.get('nombre', 'unknown')}"
                            )

                        # Navigate back to results list (locale-agnostic)
                        back_btn = None
                        for label in ("Atrás", "Back", "Voltar", "Retour", "Zurück"):
                            back_btn = await page.query_selector(
                                f'button[aria-label="{label}"]'
                            )
                            if back_btn:
                                break
                        if back_btn:
                            await back_btn.click()
                        else:
                            # Fallback: Escape closes the detail panel
                            await page.keyboard.press("Escape")
                        await asyncio.sleep(1)

                    except Exception as e:
                        logger.warning(f"Error processing card {item_id}: {e}")
                        continue

                # Scroll the results feed
                try:
                    feed = await page.query_selector('[role="feed"]')
                    if feed:
                        await feed.evaluate("el => el.scrollBy(0, 600)")
                    else:
                        await page.keyboard.press("End")
                except Exception:
                    await page.evaluate("window.scrollBy(0, 600)")

                await asyncio.sleep(1)
                scroll_attempts += 1

                if not new_found:
                    no_new_results_count += 1
                    if no_new_results_count >= 3:
                        logger.info("No new results after 3 scrolls, ending")
                        break
                else:
                    no_new_results_count = 0

                # Check for end-of-results marker
                try:
                    end_markers = [
                        'span.HlvSq',
                        '[class*="end"]',
                        'p.fontBodyMedium span',
                    ]
                    for selector in end_markers:
                        el = await page.query_selector(selector)
                        if el:
                            text = (await el.inner_text()).lower()
                            if "fin" in text or "end" in text or "todo" in text:
                                logger.info("End of results marker found")
                                return results
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Fatal error in scrape_google_maps: {e}", exc_info=True)

        finally:
            await browser.close()

    logger.info(f"Scraped {len(results)} businesses for query: '{query}'")
    return results


async def _extract_business_details(page) -> dict[str, Any] | None:
    """Extract details from the currently open business side panel."""
    # Wait briefly for panel to settle
    try:
        await page.wait_for_selector('h1', timeout=5000)
    except PlaywrightTimeoutError:
        return None

    try:
        # Name
        nombre = ""
        for selector in ['h1.DUwDvf', 'h1[class*="fontHeadlineLarge"]', 'h1']:
            el = await page.query_selector(selector)
            if el:
                nombre = (await el.inner_text()).strip()
                if nombre:
                    break

        if not nombre:
            return None

        # Category — first button-like element after the name
        categoria = ""
        cat_selectors = [
            'button[jsaction*="category"]',
            '[data-section-id="ap"] button.DkEaL',
            '.skqShb button',
        ]
        for sel in cat_selectors:
            el = await page.query_selector(sel)
            if el:
                categoria = (await el.inner_text()).strip()
                if categoria:
                    break

        # Address
        direccion = ""
        addr_selectors = [
            'button[data-tooltip*="irección"] .Io6YTe',
            'button[data-tooltip*="ddress"] .Io6YTe',
            '[data-item-id*="address"] .Io6YTe',
            '[aria-label*="irección"]',
        ]
        for sel in addr_selectors:
            el = await page.query_selector(sel)
            if el:
                direccion = (await el.inner_text()).strip()
                if direccion:
                    break

        # Phone
        telefono = ""
        phone_selectors = [
            'button[data-tooltip*="eléfono"] .Io6YTe',
            'button[data-tooltip*="hone"] .Io6YTe',
            '[data-item-id*="phone"] .Io6YTe',
            'a[href^="tel:"]',
        ]
        for sel in phone_selectors:
            el = await page.query_selector(sel)
            if el:
                if sel == 'a[href^="tel:"]':
                    href = await el.get_attribute("href") or ""
                    telefono = href.replace("tel:", "").strip()
                else:
                    telefono = (await el.inner_text()).strip()
                if telefono:
                    break

        # Website
        website = ""
        web_selectors = [
            'a[data-item-id="authority"]',
            'a[href*="http"][data-tooltip*="itio web"]',
            'a[href*="http"][data-tooltip*="ebsite"]',
        ]
        for sel in web_selectors:
            el = await page.query_selector(sel)
            if el:
                website = (await el.get_attribute("href") or "").strip()
                if website and "google.com" not in website:
                    break
                else:
                    website = ""

        # Rating
        rating_google = None
        rating_selectors = [
            'span.ceNzKf[aria-hidden="true"]',
            '[data-section-id="overview"] .F7nice span[aria-hidden="true"]',
        ]
        for sel in rating_selectors:
            el = await page.query_selector(sel)
            if el:
                try:
                    text = (await el.inner_text()).strip().replace(",", ".")
                    rating_google = float(text)
                    break
                except ValueError:
                    pass

        # Review count
        num_reseñas = None
        review_selectors = [
            'button.HHrUdb span',
            '[aria-label*="reseña"] span',
            'span[aria-label*="reseña"]',
        ]
        for sel in review_selectors:
            el = await page.query_selector(sel)
            if el:
                try:
                    text = (await el.inner_text()).strip()
                    num_str = re.sub(r"[^\d]", "", text)
                    if num_str:
                        num_reseñas = int(num_str)
                        break
                except (ValueError, TypeError):
                    pass

        return {
            "nombre": nombre,
            "categoria": categoria,
            "direccion": direccion,
            "telefono": telefono,
            "website": website,
            "tiene_web": bool(website),
            "rating_google": rating_google,
            "num_reseñas": num_reseñas,
            "maps_url": "",  # will be set by caller
        }

    except Exception as e:
        logger.error(f"Error extracting business details: {e}", exc_info=True)
        return None
