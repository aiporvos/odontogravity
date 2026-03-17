import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Text, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from backend.database import Base
import enum


class ChatPlatform(str, enum.Enum):
    whatsapp = "whatsapp"
    telegram = "telegram"


class MessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"
    system = "system"


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform: Mapped[ChatPlatform] = mapped_column(SAEnum(ChatPlatform), nullable=False)
    platform_user_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    context_data: Mapped[str | None] = mapped_column(Text, nullable=True, comment="JSON con datos recolectados")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    patient = relationship("Patient", back_populates="chat_sessions")
    messages = relationship("ChatMessage", back_populates="session", lazy="selectin", order_by="ChatMessage.created_at")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chat_sessions.id"), nullable=False)
    role: Mapped[MessageRole] = mapped_column(SAEnum(MessageRole), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    session = relationship("ChatSession", back_populates="messages")
