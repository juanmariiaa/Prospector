"""Pipeline orchestrator: runs agents 1→2→3→4 for a search query."""
import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

_JOB_TTL = 3600  # seconds — evict jobs older than 1 hour

from app.agents.agent1_maps import scrape_google_maps
from app.agents.agent2_contact import extract_contact
from app.agents.agent3_web import analyze_web
from app.agents.agent4_scoring import score_business
from app.db.database import AsyncSessionLocal as async_session
from app.models.orm import Business

logger = logging.getLogger(__name__)

# In-memory job store { job_id: {"status": str, "count": int, "error": str|None} }
JOBS: dict[str, dict[str, Any]] = {}


def create_job() -> str:
    _evict_old_jobs()
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"status": "running", "count": 0, "error": None, "created_at": time.time()}
    return job_id


def get_job(job_id: str) -> dict[str, Any] | None:
    return JOBS.get(job_id)


def _evict_old_jobs() -> None:
    now = time.time()
    stale = [k for k, v in JOBS.items() if now - v.get("created_at", 0) > _JOB_TTL]
    for k in stale:
        del JOBS[k]


async def run_pipeline(query: str, max_results: int, job_id: str) -> None:
    """
    Full pipeline: Maps scrape → contact extract → web analyze → AI score → persist.
    Updates JOBS[job_id] throughout. Safe to run as a FastAPI BackgroundTask.
    """
    logger.info(f"[{job_id}] Pipeline started: query='{query}' max={max_results}")

    try:
        # Agent 1 — scrape Google Maps
        businesses_raw = await scrape_google_maps(query, max_results)
        logger.info(f"[{job_id}] Agent 1 found {len(businesses_raw)} businesses")

        async with async_session() as session:
            for raw in businesses_raw:
                try:
                    business_data = dict(raw)
                    business_data["zona_busqueda"] = query

                    # Agents 2 & 3 are independent — run in parallel
                    contact, web_info = await asyncio.gather(
                        extract_contact(business_data),
                        analyze_web(business_data),
                    )
                    business_data.update(contact)
                    business_data.update(web_info)

                    # Serialize web_analisis dict → JSON string for persistence
                    web_analisis = business_data.get("web_analisis")
                    business_data["web_datos_extra"] = (
                        json.dumps(web_analisis, ensure_ascii=False)
                        if web_analisis is not None
                        else None
                    )

                    # Agent 4 — AI scoring
                    scoring = await score_business(business_data)
                    business_data.update(scoring)

                    # Persist
                    business_data["fecha_scraping"] = datetime.now(timezone.utc)
                    business_data["estado"] = "analizado"

                    # Keep only ORM-mapped columns
                    orm_fields = {c.name for c in Business.__table__.columns}
                    filtered = {k: v for k, v in business_data.items() if k in orm_fields}

                    db_business = Business(**filtered)
                    session.add(db_business)
                    await session.commit()

                    JOBS[job_id]["count"] += 1
                    logger.info(
                        f"[{job_id}] Saved {business_data.get('nombre', '?')} "
                        f"(score={business_data.get('oportunidad_score')})"
                    )

                except Exception as e:
                    logger.error(
                        f"[{job_id}] Error processing {raw.get('nombre', '?')}: {e}",
                        exc_info=True,
                    )
                    await session.rollback()
                    continue

        JOBS[job_id]["status"] = "completed"
        logger.info(
            f"[{job_id}] Pipeline completed: {JOBS[job_id]['count']} businesses saved"
        )

    except Exception as e:
        logger.error(f"[{job_id}] Pipeline failed: {e}", exc_info=True)
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["error"] = str(e)
