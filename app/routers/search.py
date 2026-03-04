"""FastAPI router: search, businesses, jobs endpoints."""
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.business import BusinessOut, JobStatus, SearchRequest
from app.models.orm import Business
from app.pipeline import JOBS, create_job, get_job, run_pipeline

router = APIRouter()


@router.post("/search", response_model=dict[str, str])
async def search(
    req: SearchRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    """Launch a prospecting pipeline job in the background."""
    job_id = create_job()
    background_tasks.add_task(run_pipeline, req.query, req.max_results, job_id)
    return {"job_id": job_id, "status": "running"}


@router.get("/businesses", response_model=list[BusinessOut])
async def list_businesses(
    score: int | None = None,
    zona: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[Any]:
    """Return all businesses. Filter by oportunidad_score and/or zona_busqueda."""
    stmt = select(Business)
    if score is not None:
        stmt = stmt.where(Business.oportunidad_score == score)
    if zona:
        stmt = stmt.where(Business.zona_busqueda.ilike(f"%{zona}%"))
    stmt = stmt.order_by(Business.oportunidad_score.desc().nulls_last(), Business.fecha_scraping.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/businesses/{business_id}", response_model=BusinessOut)
async def get_business(
    business_id: int,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Return a single business by ID."""
    business = await db.get(Business, business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


@router.get("/jobs/{job_id}", response_model=JobStatus)
async def job_status(job_id: str) -> JobStatus:
    """Return current status of a pipeline job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatus(
        job_id=job_id,
        status=job["status"],
        count=job["count"],
        error=job.get("error"),
    )
