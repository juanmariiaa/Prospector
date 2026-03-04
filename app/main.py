import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.database import init_db
from app.routers.search import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="Prospector Local",
    description="Multi-agent pipeline for local business prospecting",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router)
