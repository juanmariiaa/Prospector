from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.db.database import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="Prospector Local", lifespan=lifespan)
