import uuid
from datetime import datetime, date, time as py_time
from sqlalchemy import String, Boolean, DateTime, Date, Time, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from backend.database import Base


class ClinicSchedule(Base):
    """Horario de atención de la clínica (compartido por los profesionales).

    Cada fila es un bloque de un día de la semana. Ej: lunes 09:00-12:30.
    Un día puede tener varias filas (mañana y tarde).
    """
    __tablename__ = "clinic_schedule"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Lunes ... 6=Domingo
    start_time: Mapped[py_time] = mapped_column(Time, nullable=False)
    end_time: Mapped[py_time] = mapped_column(Time, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProfessionalTimeOff(Base):
    """Ausencia puntual de un profesional (día completo)."""
    __tablename__ = "professional_time_off"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    professional_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("professionals.id"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    professional = relationship("Professional", lazy="selectin")


class ClinicHoliday(Base):
    """Día feriado de la clínica (cierra todo el día para todos los profesionales)."""
    __tablename__ = "clinic_holidays"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
