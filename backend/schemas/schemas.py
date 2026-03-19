from pydantic import BaseModel, EmailStr, Field
from uuid import UUID
from datetime import datetime, date
from typing import Optional
from backend.models.user import UserRole
from backend.models.appointment import AppointmentStatus, AppointmentChannel
from backend.models.odontogram import ToothFace, EntryCategory, ToothSymbol


# ═══════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════
class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserRead"


# ═══════════════════════════════════════════════════════
# USER
# ═══════════════════════════════════════════════════════
class UserCreate(BaseModel):
    email: str
    password: str = Field(min_length=6)
    full_name: str
    role: UserRole = UserRole.receptionist


class UserRead(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


# ═══════════════════════════════════════════════════════
# PATIENT
# ═══════════════════════════════════════════════════════
class PatientCreate(BaseModel):
    first_name: str
    last_name: str
    dni: str
    phone: str
    email: Optional[str] = None
    date_of_birth: Optional[date] = None
    address: Optional[str] = None
    city: Optional[str] = None
    insurance_name: Optional[str] = None
    insurance_number: Optional[str] = None
    medical_notes: Optional[str] = None


class PatientRead(BaseModel):
    id: UUID
    first_name: str
    last_name: str
    dni: str
    phone: str
    email: Optional[str] = None
    date_of_birth: Optional[date] = None
    address: Optional[str] = None
    city: Optional[str] = None
    insurance_name: Optional[str] = None
    insurance_number: Optional[str] = None
    medical_notes: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PatientUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    date_of_birth: Optional[date] = None
    address: Optional[str] = None
    city: Optional[str] = None
    insurance_name: Optional[str] = None
    insurance_number: Optional[str] = None
    medical_notes: Optional[str] = None


# ═══════════════════════════════════════════════════════
# PROFESSIONAL
# ═══════════════════════════════════════════════════════
class ProfessionalCreate(BaseModel):
    full_name: str
    license_number: str
    specialties: list[str] = []
    phone: Optional[str] = None
    email: Optional[str] = None
    locations: list[str] = []
    notes: Optional[str] = None


class ProfessionalRead(BaseModel):
    id: UUID
    full_name: str
    license_number: str
    specialties: list[str]
    phone: Optional[str] = None
    email: Optional[str] = None
    locations: list[str]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ProfessionalUpdate(BaseModel):
    full_name: Optional[str] = None
    specialties: Optional[list[str]] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    locations: Optional[list[str]] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


# ═══════════════════════════════════════════════════════
# APPOINTMENT
# ═══════════════════════════════════════════════════════
class AppointmentCreate(BaseModel):
    patient_id: UUID
    professional_id: UUID
    start_time: datetime
    duration_minutes: int = 30
    reason: Optional[str] = None
    status: AppointmentStatus = AppointmentStatus.pending
    channel: AppointmentChannel = AppointmentChannel.web
    location: Optional[str] = None
    notes: Optional[str] = None


class AppointmentRead(BaseModel):
    id: UUID
    patient_id: UUID
    professional_id: UUID
    start_time: datetime
    duration_minutes: int
    reason: Optional[str] = None
    status: AppointmentStatus
    channel: AppointmentChannel
    location: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    patient: Optional[PatientRead] = None
    professional: Optional[ProfessionalRead] = None

    model_config = {"from_attributes": True}


class AppointmentUpdate(BaseModel):
    start_time: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    reason: Optional[str] = None
    status: Optional[AppointmentStatus] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    professional_id: Optional[UUID] = None


# ═══════════════════════════════════════════════════════
# ODONTOGRAM
# ═══════════════════════════════════════════════════════
class OdontogramEntryCreate(BaseModel):
    patient_id: UUID
    tooth_number: int = Field(ge=11, le=85)
    face: ToothFace
    symbol: ToothSymbol
    category: EntryCategory
    procedure_code: Optional[str] = None
    description: Optional[str] = None
    professional_id: Optional[UUID] = None
    patient_consent: bool = False


class OdontogramEntryRead(BaseModel):
    id: UUID
    patient_id: UUID
    tooth_number: int
    face: ToothFace
    symbol: ToothSymbol
    category: EntryCategory
    procedure_code: Optional[str] = None
    description: Optional[str] = None
    professional_id: Optional[UUID] = None
    patient_consent: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════
# ADMIN CONFIG / LOCATIONS / INSURANCES
# ═══════════════════════════════════════════════════════
class ConfigCreate(BaseModel):
    key: str
    value: str
    description: Optional[str] = None

class ConfigRead(BaseModel):
    key: str
    value: str
    description: Optional[str]
    model_config = {"from_attributes": True}

class LocationCreate(BaseModel):
    name: str
    address: Optional[str] = None
    phone: Optional[str] = None

class LocationRead(BaseModel):
    id: UUID
    name: str
    address: Optional[str]
    phone: Optional[str]
    is_active: bool
    model_config = {"from_attributes": True}

class InsuranceCreate(BaseModel):
    name: str
    code: Optional[str] = None

class InsuranceRead(BaseModel):
    id: UUID
    name: str
    code: Optional[str]
    is_active: bool
    model_config = {"from_attributes": True}

# ═══════════════════════════════════════════════════════
# SEARCH / OMNIBOX
# ═══════════════════════════════════════════════════════
class SearchResult(BaseModel):
    type: str  # "patient" | "appointment" | "professional"
    id: UUID
    label: str
    detail: Optional[str] = None


# ═══════════════════════════════════════════════════════
# BOT SCHEMAS
# ═══════════════════════════════════════════════════════
class BotAppointmentRequest(BaseModel):
    patient_name: str
    patient_last_name: str
    dni: str
    phone: str
    insurance_name: Optional[str] = None
    reason: str
    location: str  # "San Rafael" | "Alvear"
    preferred_date: Optional[str] = None


class BotCancelRequest(BaseModel):
    dni: str
    appointment_id: Optional[UUID] = None


class BotRescheduleRequest(BaseModel):
    dni: str
    appointment_id: UUID
    new_start_time: datetime


class BotQueryRequest(BaseModel):
    dni: str
