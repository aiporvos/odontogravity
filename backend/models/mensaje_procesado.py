from sqlalchemy import Column, DateTime, String
from sqlalchemy.sql import func

from backend.database import Base


class MensajeProcesado(Base):
    """Ids de WhatsApp (wamid) ya procesados, para no responder dos veces.

    Antes vivia en un dict en memoria: un reinicio del backend lo vaciaba y con
    mas de un proceso cada uno tenia el suyo.
    """
    __tablename__ = "mensajes_procesados"

    wamid = Column(String(255), primary_key=True)
    recibido = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
