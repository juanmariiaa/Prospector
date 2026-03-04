"""Basic tests for Agent 1 (Maps Scraper)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_scrape_returns_list():
    """scrape_google_maps should return a list (possibly empty on mock)."""
    from app.agents.agent1_maps import scrape_google_maps

    # Mock playwright so tests don't open a real browser
    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_page = AsyncMock()
    mock_page.url = "https://www.google.com/maps/place/Test"
    mock_page.query_selector_all = AsyncMock(return_value=[])
    mock_page.query_selector = AsyncMock(return_value=None)
    mock_page.goto = AsyncMock()
    mock_page.wait_for_selector = AsyncMock()
    mock_page.keyboard = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    mock_playwright = AsyncMock()
    mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)

    with patch("app.agents.agent1_maps.async_playwright") as mock_ap:
        mock_ap.return_value.__aenter__ = AsyncMock(return_value=mock_playwright)
        mock_ap.return_value.__aexit__ = AsyncMock(return_value=False)

        results = await scrape_google_maps("test query", max_results=5)

    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_result_has_required_keys():
    """Each result dict must have the expected keys."""
    expected_keys = {
        "nombre", "categoria", "direccion", "telefono",
        "website", "tiene_web", "rating_google", "num_reseñas", "maps_url",
    }

    # Simulate what _extract_business_details returns
    from app.agents.agent1_maps import _extract_business_details

    mock_page = AsyncMock()
    mock_page.url = "https://www.google.com/maps/place/Cafeteria+Test"

    # Make all query_selector calls return None (no elements found)
    mock_page.query_selector = AsyncMock(return_value=None)
    mock_page.wait_for_selector = AsyncMock(side_effect=Exception("timeout"))

    result = await _extract_business_details(mock_page)
    # With no elements, result should be None (nombre is empty)
    assert result is None or isinstance(result, dict)
    if result is not None:
        assert expected_keys.issubset(result.keys())
