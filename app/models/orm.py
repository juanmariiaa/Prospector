from datetime import datetime
from sqlalchemy import (
    Integer, String, Float, Boolean, Text, DateTime, Enum
)
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base

class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(255))
    categoria: Mapped[str | None] = mapped_column(String(255), nullable=True)
    direccion: Mapped[str | None] = mapped_column(String(500), nullable=True)
    telefono: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rating_google: Mapped[float | None] = mapped_column(Float, nullable=True)
    num_reseñas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tiene_web: Mapped[bool] = mapped_column(Boolean, default=False)
    web_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    oportunidad_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    oportunidad_razon: Mapped[str | None] = mapped_column(Text, nullable=True)
    web_es_mobile: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    web_velocidad_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    maps_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    zona_busqueda: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fecha_scraping: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    estado: Mapped[str] = mapped_column(
        Enum("pendiente", "analizado", "contactado", "vendido", name="estado_enum"),
        default="pendiente",
    )
