"""Pipeline orchestrator: runs agents 1→2→3→4 for a search query."""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.agents.agent1_maps import scrape_google_maps
from app.agents.agent2_contact import extract_contact
from app.agents.agent3_web import analyze_web
from app.agents.agent4_scoring import score_business
from app.db.database import async_session
from app.models.orm import Business

logger = logging.getLogger(__name__)

# In-memory job store { job_id: {"status": str, "count": int, "error": str|None} }
JOBS: dict[str, dict[str, Any]] = {}


def create_job() -> str:
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"status": "running", "count": 0, "error": None}
    return job_id


def get_job(job_id: str) -> dict[str, Any] | None:
    return JOBS.get(job_id)


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

                    # Agent 2 — contact info
                    contact = await extract_contact(business_data)
                    business_data.update(contact)

                    # Agent 3 — web analysis
                    web_info = await analyze_web(business_data)
                    business_data.update(web_info)

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
