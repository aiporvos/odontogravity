from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.sql import func
from backend.database import Base

class AppConfig(Base):
    __tablename__ = "app_configs"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)
    description = Column(String(255), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
