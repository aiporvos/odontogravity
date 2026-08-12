import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Integer, Text, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from backend.database import Base
import enum


class AppointmentStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    cancelled = "cancelled"
    completed = "completed"
    no_show = "no_show"


class AppointmentChannel(str, enum.Enum):
    web = "web"
    bot_whatsapp = "bot_whatsapp"
    bot_telegram = "bot_telegram"
    phone = "phone"


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    professional_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("professionals.id"), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Cobertura (obra social o "Particular") usada para ESTE turno. Es un
    # snapshot: el paciente puede cambiar de obra social entre turnos, así que
    # se guarda por turno además de en la ficha del paciente.
    insurance_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[AppointmentStatus] = mapped_column(
        SAEnum(AppointmentStatus), default=AppointmentStatus.confirmed, nullable=False
    )
    channel: Mapped[AppointmentChannel] = mapped_column(
        SAEnum(AppointmentChannel), default=AppointmentChannel.web, nullable=False
    )
    location: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    patient = relationship("Patient", back_populates="appointments", lazy="selectin")
    professional = relationship("Professional", back_populates="appointments", lazy="selectin")

    @property
    def treatment_priority(self) -> str | None:
        if not self.patient:
            return None
        # get all active treatment entries
        treatments = [e for e in self.patient.odontogram_entries if e.category == "treatment" and not e.is_deleted]
        if not treatments:
            return None
        # prioritize: alta > media > baja
        priority_map = {"alta": 3, "media": 2, "baja": 1}
        max_val = 0
        max_pri = None
        for t in treatments:
            pri = t.priority
            if pri:
                val = priority_map.get(pri.lower(), 0)
                if val > max_val:
                    max_val = val
                    max_pri = pri
        return max_pri
