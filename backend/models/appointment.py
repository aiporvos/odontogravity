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
    status: Mapped[AppointmentStatus] = mapped_column(
        SAEnum(AppointmentStatus), default=AppointmentStatus.pending, nullable=False
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
