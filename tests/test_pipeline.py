"""FastAPI integration tests for search and business endpoints."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_post_search_returns_job_id():
    """POST /search should return a job_id and status=running."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/search", json={"query": "test", "max_results": 1})
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    assert data["status"] == "running"


@pytest.mark.asyncio
async def test_get_businesses_returns_list():
    """GET /businesses should return a list."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/businesses")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_get_job_not_found():
    """GET /jobs/<unknown_id> should return 404."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/jobs/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_business_not_found():
    """GET /businesses/99999 should return 404."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/businesses/99999")
    assert resp.status_code == 404
