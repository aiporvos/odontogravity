import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://dentibot:dentibot_secure_2024@db:5432/dentibot")

# El pool por defecto es chico (5 + 10 de overflow) y cualquier pantalla que
# dispare varios requests a la vez lo agota: el request sobrante espera los 30s
# de pool_timeout y termina en 500. pool_pre_ping descarta las conexiones que
# quedaron muertas tras un reinicio de la base.
engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=1800,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
