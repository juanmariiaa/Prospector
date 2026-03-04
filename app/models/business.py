from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict

class BusinessCreate(BaseModel):
    nombre: str
    categoria: str | None = None
    direccion: str | None = None
    telefono: str | None = None
    email: str | None = None
    website: str | None = None
    rating_google: float | None = None
    num_reseñas: int | None = None
    tiene_web: bool | None = None
    web_score: int | None = None
    oportunidad_score: int | None = None
    oportunidad_razon: str | None = None
    web_es_mobile: bool | None = None
    web_velocidad_ms: int | None = None
    maps_url: str | None = None
    zona_busqueda: str | None = None
    estado: str | None = None

class BusinessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    categoria: str | None = None
    direccion: str | None = None
    telefono: str | None = None
    email: str | None = None
    website: str | None = None
    rating_google: float | None = None
    num_reseñas: int | None = None
    tiene_web: bool
    web_score: int | None = None
    oportunidad_score: int | None = None
    oportunidad_razon: str | None = None
    web_es_mobile: bool | None = None
    web_velocidad_ms: int | None = None
    maps_url: str | None = None
    zona_busqueda: str | None = None
    fecha_scraping: datetime
    estado: str

class SearchRequest(BaseModel):
    query: str
    max_results: int = 30

class JobStatus(BaseModel):
    job_id: str
    status: Literal["running", "completed", "failed"]
    count: int = 0
    error: str | None = None
