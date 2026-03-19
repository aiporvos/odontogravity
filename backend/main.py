import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from backend.database import engine, Base, SessionLocal
from backend.models import *  # noqa - import all models so Base.metadata knows them
from backend.routers.auth import router as auth_router
from backend.routers.admin.admin_routes import router as admin_router
from backend.routers.clinic.clinic_routes import router as clinic_router
from backend.routers.bot_routes import router as bot_router
from backend.routers.evolution_router import router as evolution_router
from backend.seed import run_seed

# ── Logging Configuration ────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)
logger.info("🚀 Dental Studio Pro Backend Starting...")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup (in dev; Alembic for production)
    Base.metadata.create_all(bind=engine)
    
    # Ensure new enum values exist (PostgreSQL doesn't update them automatically)
    with engine.connect() as conn:
        try:
            # Check for PostgreSQL
            if "postgresql" in str(engine.url):
                new_symbols = ["sff", "fracture", "bridge"]
                for symbol in new_symbols:
                    # PostgreSQL requires ALTER TYPE outside of a transaction or with check
                    conn.execute(text(f"ALTER TYPE toothsymbol ADD VALUE IF NOT EXISTS '{symbol}'"))
                conn.commit()
        except Exception:
            pass # Swallow if already exists or not PG

    # Seed initial data
    db = SessionLocal()
    try:
        run_seed(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="Dental Studio Pro",
    description="Sistema de gestión integral para consultorios odontológicos",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ────────────────────────────────────────────────
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ─────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(clinic_router)
app.include_router(bot_router)
app.include_router(evolution_router)

@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "Dental Studio Pro"}

# ── Serve Frontend (SPA) ───────────────────────────────
frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
