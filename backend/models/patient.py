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
    # Opcional a proposito: para agendar alcanza el numero de WhatsApp, que es
    # una credencial mas fuerte (Meta lo verifica; un DNI lo sabe cualquiera).
    # Pedirselo al paciente por chat era la mayor friccion del alta, y recepcion
    # lo completa cuando llega. Una ficha sin DNI queda marcada como incompleta.
    dni: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True, index=True)
    # Opcional, igual que el DNI. Recepcion carga fichas desde la agenda de
    # papel donde muchas veces no figura el telefono; exigirlo obligaba a
    # inventar uno. Sin telefono la ficha existe, pero no recibe recordatorios.
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
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
