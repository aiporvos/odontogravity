import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Text, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from backend.database import Base
import enum


class ToothFace(str, enum.Enum):
    mesial = "mesial"
    distal = "distal"
    vestibular = "vestibular"
    palatina = "palatina"       # lingual para inferiores
    oclusal = "oclusal"
    full = "full"               # diente completo


class EntryCategory(str, enum.Enum):
    preexisting = "preexisting"     # Rojo - hallazgo preexistente
    treatment = "treatment"         # Azul - prestación nueva/realizada


class ToothSymbol(str, enum.Enum):
    filling = "filling"             # Relleno (cara)
    extraction = "extraction"       # X - extracción
    missing = "missing"             # ausente
    crown = "crown"                 # corona
    fixed_prosthesis = "fixed_prosthesis"      # prótesis fija
    removable_prosthesis = "removable_prosthesis"  # prótesis removible
    cavity = "cavity"               # caries O
    root_canal = "root_canal"       # tratamiento de conducto
    implant = "implant"             # implante


class OdontogramEntry(Base):
    __tablename__ = "odontogram_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    tooth_number: Mapped[int] = mapped_column(nullable=False, comment="FDI notation 11-48, 51-85")
    face: Mapped[ToothFace] = mapped_column(SAEnum(ToothFace), nullable=False)
    symbol: Mapped[ToothSymbol] = mapped_column(SAEnum(ToothSymbol), nullable=False)
    category: Mapped[EntryCategory] = mapped_column(SAEnum(EntryCategory), nullable=False)
    procedure_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    professional_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("professionals.id"), nullable=True)
    patient_consent: Mapped[bool] = mapped_column(Boolean, default=False, comment="Conformidad del paciente")
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    patient = relationship("Patient", back_populates="odontogram_entries")
