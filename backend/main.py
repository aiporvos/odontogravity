import os
import re
import hashlib
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from backend.database import engine, Base, SessionLocal
from backend.models import *  # noqa - import all models so Base.metadata knows them
from backend.routers.auth import router as auth_router
from backend.routers.admin.admin_routes import router as admin_router
from backend.routers.clinic.clinic_routes import router as clinic_router
from backend.routers.bot_routes import router as bot_router
from backend.routers.evolution_router import router as whatsapp_router
from backend.routers.public_routes import router as public_router
from backend.seed import run_seed
from backend.services.reminders_loop import start_reminders_loop

# ── Logging Configuration ────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)
logger.info("🚀 Silprodent Backend Starting...")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run Alembic migrations programmatically
    try:
        from alembic.config import Config
        from alembic import command
        logger.info("Running database migrations (Alembic upgrade head)...")
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        logger.info("✅ Database migrations applied successfully.")
    except Exception as e:
        logger.error(f"❌ Failed to run database migrations: {e}")

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

    # Columnas agregadas despues de que la tabla ya existia. create_all() crea
    # tablas nuevas pero NO agrega columnas a las que ya estan, y las
    # migraciones de Alembic vienen fallando en este deploy (la primera choca
    # con una columna que create_all ya habia creado). Sin esto habria que
    # correr el ALTER a mano en produccion despues de cada deploy.
    columnas_nuevas = [
        ("chat_sessions", "paused_until", "TIMESTAMP"),
    ]
    with engine.connect() as conn:
        for tabla, columna, tipo in columnas_nuevas:
            try:
                conn.execute(text(
                    f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS {columna} {tipo}"
                ))
                conn.commit()
            except Exception as e:
                logger.warning(f"No se pudo asegurar {tabla}.{columna}: {e}")

    # Seed initial data
    db = SessionLocal()
    try:
        run_seed(db)
    finally:
        db.close()
        
    start_reminders_loop()
    
    yield


app = FastAPI(
    title="Silprodent",
    description="Sistema de gestión integral para consultorios odontológicos",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ────────────────────────────────────────────────
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000").split(",")
    if o.strip()
]

# "*" con allow_credentials=True es inválido según el spec de CORS y
# expone la API a cualquier origen. Si se usa "*", desactivamos credenciales.
allow_credentials = "*" not in ALLOWED_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Evitar caché vieja del frontend ─────────────────────
# El navegador cacheaba el JS/CSS/HTML y no tomaba los cambios tras cada deploy.
# Con "no-cache" el navegador revalida siempre (y recibe 304 si no cambió, por
# el ETag/Last-Modified de StaticFiles), así que el frontend se actualiza solo.
@app.middleware("http")
async def no_cache_frontend(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.endswith((".js", ".css")):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    elif path == "/" or path.endswith(".html"):
        # El HTML nunca se guarda: es el que trae los ?v= nuevos de cada deploy.
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# ── Routers ─────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(clinic_router)
app.include_router(bot_router)
app.include_router(whatsapp_router)
app.include_router(public_router)

@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "Silprodent"}

# ── Serve Frontend (SPA) ───────────────────────────────
frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

# Cache-busting automático: en vez de acordarnos de subir el "?v=N" a mano en
# cada script del index.html, calculamos la versión de cada archivo a partir de
# su contenido. Si el archivo cambió, la URL cambia y el navegador está obligado
# a bajarlo de nuevo; si no cambió, sigue usando el que tiene en caché.
_ASSET_RE = re.compile(r'(src|href)="(?!https?://|//)([^"?]+\.(?:js|css))(?:\?[^"]*)?"')
_asset_versions: dict[str, tuple[float, str]] = {}


def _asset_version(rel_path: str) -> str:
    """Hash corto del contenido del archivo, cacheado por mtime."""
    full = os.path.join(frontend_path, rel_path.lstrip("/"))
    try:
        mtime = os.path.getmtime(full)
    except OSError:
        return "0"
    cached = _asset_versions.get(rel_path)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        with open(full, "rb") as f:
            digest = hashlib.sha1(f.read()).hexdigest()[:10]
    except OSError:
        return "0"
    _asset_versions[rel_path] = (mtime, digest)
    return digest


def _build_index_html() -> tuple[str, str]:
    """Devuelve (html con los assets versionados, versión global del build)."""
    with open(os.path.join(frontend_path, "index.html"), encoding="utf-8") as f:
        html = f.read()

    versions: list[str] = []

    def repl(m: re.Match) -> str:
        attr, path = m.group(1), m.group(2)
        version = _asset_version(path)
        versions.append(f"{path}:{version}")
        return f'{attr}="{path}?v={version}"'

    html = _ASSET_RE.sub(repl, html)

    # Versión global del build: si cambia cualquier asset, cambia este valor.
    build = hashlib.sha1("|".join(versions).encode()).hexdigest()[:10]
    html = html.replace(
        "</head>",
        f'    <script>window.APP_VERSION = "{build}";</script>\n</head>',
        1,
    )
    return html, build


@app.get("/api/version")
def app_version():
    """Lo consulta el frontend para detectar que salió una versión nueva."""
    if not os.path.exists(frontend_path):
        return {"version": "dev"}
    return {"version": _build_index_html()[1]}


if os.path.exists(frontend_path):

    @app.get("/", response_class=HTMLResponse)
    @app.get("/index.html", response_class=HTMLResponse)
    def serve_index():
        return HTMLResponse(_build_index_html()[0])

    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
