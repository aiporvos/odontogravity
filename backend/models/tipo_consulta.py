import uuid
from datetime import datetime

from sqlalchemy import String, Boolean, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, ARRAY

from backend.database import Base


class TipoConsulta(Base):
    """Los motivos por los que un paciente pide turno, y qué implica cada uno.

    Antes esto vivía repartido entre la base y el código: las especialidades de
    cada profesional se cargaban desde el panel, pero la duración de cada tipo
    de turno y las formas en que la gente lo nombra estaban escritas a mano en
    appointment_service.py. La clínica podía dar de alta un profesional nuevo,
    pero no podía decir cuánto dura una endodoncia sin tocar el código.

    Cada fila junta las tres cosas que el bot necesita para agendar bien:
    cuánto dura, qué especialidad lo atiende (y por lo tanto quién), y cómo lo
    dicen los pacientes en WhatsApp.
    """

    __tablename__ = "tipos_consulta"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Nombre canónico, el que se guarda en el turno. Ej: "Extracción".
    nombre: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    duracion_minutos: Mapped[int] = mapped_column(Integer, nullable=False, default=15)

    # Con qué especialidad de la ficha del profesional se corresponde. Es el
    # puente entre lo que pide el paciente y quién puede atenderlo: si dice
    # "sacar una muela", esto lleva a "Extracción" y de ahí a quien la tenga
    # cargada como especialidad.
    especialidad: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Cómo lo dice la gente: "sacar", "muela", "cordal". Nadie escribe
    # "Extracción" en WhatsApp. Se amplía desde el panel, sin tocar código.
    sinonimos: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=[])

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
