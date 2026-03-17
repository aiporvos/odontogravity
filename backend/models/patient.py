import uuid
from datetime import datetime, date
from sqlalchemy import String, Boolean, DateTime, Date, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from backend.database import Base


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    dni: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(30), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    insurance_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    insurance_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    medical_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    appointments = relationship("Appointment", back_populates="patient", lazy="selectin")
    odontogram_entries = relationship("OdontogramEntry", back_populates="patient", lazy="selectin")
    chat_sessions = relationship("ChatSession", back_populates="patient", lazy="selectin")
